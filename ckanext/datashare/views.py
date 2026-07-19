# encoding: utf-8
"""Download chokepoint for ckanext-datashare.

Registers the SAME two url rules that serve resource downloads on IHP-WINS
(core CKAN's ``/dataset/<id>/resource/<rid>/download`` and cloudstorage's
``.../download/<filename>``), checks ``datashare_resource_download`` and only
then delegates to the real download implementation (cloudstorage when
installed, else core).

PLUGIN ORDER MATTERS: PluginImplementations iterates plugins LIFO, so for
identical rules the blueprint of the plugin listed LAST in ``ckan.plugins``
wins the tie (verified empirically on dev 2026-07-19: with datashare before
cloudstorage, cloudstorage served the /download/<filename> rule). Therefore
``datashare`` must appear AFTER ``cloudstorage``. Verify after deploy with
an anonymous curl against both URL shapes on a 'viewable' dataset - both
must return 403.
"""
import logging

from flask import Blueprint

import ckan.model as model
import ckan.plugins.toolkit as tk

log = logging.getLogger(__name__)

datashare_bp = Blueprint('datashare', __name__)


def download(id, resource_id, filename=None):
    context = {
        'model': model,
        'session': model.Session,
        'user': tk.g.user,
        'auth_user_obj': tk.g.userobj,
    }
    try:
        tk.check_access('datashare_resource_download', context,
                        {'id': resource_id})
    except tk.ObjectNotFound:
        return tk.abort(404, tk._('Resource not found'))
    except tk.NotAuthorized:
        return tk.abort(
            403,
            tk._('Downloading this resource is not permitted by its '
                 'data sharing level. Contact the data provider to '
                 'request access.'))

    try:
        from ckanext.cloudstorage.views.resource_download import (
            resource_download as cloudstorage_download,
        )
        return cloudstorage_download(id, resource_id, filename)
    except ImportError:
        from ckan.views.resource import download as core_download
        return core_download(package_type='dataset', id=id,
                             resource_id=resource_id, filename=filename)


def shared(id):
    """Manage org/group grants for a dataset ("Shared with" tab)."""
    context = {
        'model': model,
        'session': model.Session,
        'user': tk.g.user,
        'auth_user_obj': tk.g.userobj,
    }
    try:
        pkg_dict = tk.get_action('package_show')(context, {'id': id})
        tk.check_access('datashare_grant_manage', context,
                        {'package_id': pkg_dict['id']})
    except (tk.ObjectNotFound, tk.NotAuthorized):
        return tk.abort(404, tk._('Dataset not found'))

    if tk.request.method == 'POST':
        form = tk.request.form
        form_action = form.get('action')
        # The grantee <select> encodes both facts as "org|<id>" / "group|<id>"
        grantee = form.get('grantee', '')
        grantee_type, _sep, grantee_id = grantee.partition('|')
        params = {
            'package_id': pkg_dict['id'],
            'grantee_type': grantee_type,
            'grantee_id': grantee_id,
        }
        try:
            if form_action == 'add':
                params['capacity'] = form.get('capacity', 'read')
                grant = tk.get_action('datashare_grant_create')(
                    context, params)
                tk.h.flash_success(
                    tk._('Dataset shared with %s') % grant['grantee_title'])
            elif form_action == 'remove':
                tk.get_action('datashare_grant_delete')(context, params)
                tk.h.flash_success(tk._('Sharing removed'))
        except tk.ValidationError as e:
            tk.h.flash_error(e.error_summary or tk._('Invalid request'))
        except tk.ObjectNotFound:
            tk.h.flash_error(tk._('Organization or initiative not found'))
        return tk.h.redirect_to('datashare.shared', id=pkg_dict['name'])

    grants = tk.get_action('datashare_grant_list')(
        context, {'package_id': pkg_dict['id']})
    orgs = tk.get_action('organization_list')(
        context, {'all_fields': True})
    groups = tk.get_action('group_list')(
        context, {'all_fields': True})
    return tk.render('datashare/shared.html', extra_vars={
        'pkg_dict': pkg_dict,
        'pkg': pkg_dict,
        'dataset_type': pkg_dict.get('type', 'dataset'),
        'grants': grants,
        'orgs': orgs,
        'groups': groups,
    })


# Endpoints that hand out the FULL file/table and must honor can_download.
# Gated via before_app_request (below) instead of duplicate url rules:
# identical-rule ties between extension blueprints depend on the (fragile,
# non-config-order) PluginImplementations iteration - e.g. datastore always
# registers first and would always win a tie on /datastore/dump.
_GATED_ENDPOINTS = {
    'datastore.dump',                    # DataStore bulk export
    'cloudresource.resource_download',   # cloudstorage download view
    'dataset_resource.download',         # core download view
    'resource.download',                 # core download (legacy name)
}


@datashare_bp.before_app_request
def _gate_bulk_download_endpoints():
    """App-wide belt-and-braces gate for bulk-download endpoints.

    Runs after CKAN's identify_user (app-level before_request hooks are
    registered earlier), so g.user/g.userobj are populated. Returning None
    lets the real view continue; previews are unaffected (they use
    datastore_search, not these endpoints).
    """
    from flask import request
    if request.endpoint not in _GATED_ENDPOINTS:
        return None
    resource_id = (request.view_args or {}).get('resource_id')
    if not resource_id:
        return None
    context = {
        'model': model,
        'session': model.Session,
        'user': tk.g.user,
        'auth_user_obj': tk.g.userobj,
    }
    try:
        tk.check_access('datashare_resource_download', context,
                        {'id': resource_id})
    except tk.NotAuthorized:
        return tk.abort(
            403, tk._('Downloading this resource is not permitted by its '
                      'data sharing level.'))
    except tk.ObjectNotFound:
        return None  # let the real view produce its own 404
    return None


def request_access(id):
    """POST target for the 'Request access' button on gated datasets."""
    context = {
        'model': model,
        'session': model.Session,
        'user': tk.g.user,
        'auth_user_obj': tk.g.userobj,
    }
    try:
        result = tk.get_action('datashare_access_request_create')(
            context, {'package_id': id,
                      'message': tk.request.form.get('message', '')})
        tk.h.flash_success(
            tk._('Access request sent. The data provider will review it.'))
    except tk.NotAuthorized:
        tk.h.flash_error(tk._('You must be logged in to request access'))
    except tk.ValidationError as e:
        tk.h.flash_error(e.error_summary or tk._('Invalid request'))
    except tk.ObjectNotFound:
        return tk.abort(404, tk._('Dataset not found'))
    return tk.h.redirect_to('dataset.read', id=id)


def access_requests():
    """Review queue for data-access requests (GET list / POST decision)."""
    context = {
        'model': model,
        'session': model.Session,
        'user': tk.g.user,
        'auth_user_obj': tk.g.userobj,
    }
    if not tk.g.userobj:
        return tk.abort(404, tk._('Not found'))

    if tk.request.method == 'POST':
        form = tk.request.form
        try:
            result = tk.get_action('datashare_access_request_process')(
                context, {'id': form.get('request_id'),
                          'decision': form.get('decision'),
                          'note': form.get('note', '')})
            tk.h.flash_success(
                tk._('Request approved') if result['status'] == 'approved'
                else tk._('Request rejected'))
        except (tk.ValidationError, tk.ObjectNotFound) as e:
            tk.h.flash_error(getattr(e, 'error_summary', None)
                             or tk._('Invalid request'))
        except tk.NotAuthorized:
            tk.h.flash_error(
                tk._('Not authorized to process this request'))
        return tk.h.redirect_to('datashare.access_requests')

    requests = tk.get_action('datashare_access_request_list')(context, {})
    return tk.render('datashare/requests.html',
                     extra_vars={'requests': requests})


datashare_bp.add_url_rule(
    '/dataset/<id>/resource/<resource_id>/download',
    view_func=download, methods=['GET'])
datashare_bp.add_url_rule(
    '/dataset/<id>/resource/<resource_id>/download/<filename>',
    view_func=download, methods=['GET'])
datashare_bp.add_url_rule(
    '/dataset/<id>/shared', view_func=shared, methods=['GET', 'POST'])
datashare_bp.add_url_rule(
    '/dataset/<id>/request-access', view_func=request_access,
    methods=['POST'])
datashare_bp.add_url_rule(
    '/datashare/requests', view_func=access_requests,
    methods=['GET', 'POST'], endpoint='access_requests')


def get_blueprints():
    return [datashare_bp]
