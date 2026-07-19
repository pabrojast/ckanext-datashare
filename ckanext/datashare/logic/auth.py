# encoding: utf-8
"""Auth functions for ckanext-datashare.

Chained functions ONLY for core overrides: schemingdcat registers PLAIN
overrides of ``package_create``/``package_update``, and CKAN applies chained
auth on top of whatever plain override won - a second plain override would
abort startup. ``resource_show`` has no other override in the IHP-WINS stack
but chaining keeps us compatible if one appears.

Note on bypasses that are correct and intended:
  * sysadmins never reach these functions (check_access short-circuits),
  * harvest/indexing run with ``ignore_auth=True`` and are equally exempt,
    so gating never breaks harvesting or the Solr indexer.
"""
import logging

import ckan.plugins.toolkit as tk

from ckanext.datashare import core

log = logging.getLogger(__name__)


def _resource_package(context, data_dict):
    """The package a resource_show-style data_dict points at."""
    model = context['model']
    resource_id = (data_dict or {}).get('id')
    resource = context.get('resource') or model.Resource.get(resource_id)
    if resource is None:
        return None
    return model.Package.get(resource.package_id)


@tk.chained_auth_function
@tk.auth_allow_anonymous_access
def resource_show(next_auth, context, data_dict):
    result = next_auth(context, data_dict)
    if not result.get('success'):
        return result
    pkg = _resource_package(context, data_dict)
    if pkg is None:
        return result
    access = core.get_access(pkg, context=context)
    if access.can_view_resources:
        return result
    return {
        'success': False,
        'msg': tk._('Resources of this dataset are not accessible '
                    '(access level: %s)') % access.level,
    }


@tk.chained_auth_function
def package_update(next_auth, context, data_dict):
    result = next_auth(context, data_dict)
    if result.get('success'):
        return result

    # Entity-level edit grants: admins/editors of an org or initiative that
    # holds an 'edit' grant on this dataset may update it (requirement ii).
    model = context['model']
    pkg = context.get('package')
    if pkg is None:
        pkg_id = (data_dict or {}).get('id')
        pkg = model.Package.get(pkg_id) if pkg_id else None
    if pkg is None:
        return result

    user_obj = core._resolve_user_obj(context=context)
    if user_obj is None:
        return result

    from ckanext.datashare import db
    if db.user_has_edit_grant(user_obj.id, pkg.id):
        return {'success': True}
    return result


@tk.auth_allow_anonymous_access
def datashare_resource_download(context, data_dict):
    """May the user download the actual file? (viewable = no)

    Separates "can see metadata/preview" (resource_show) from "can fetch the
    file", which core CKAN does not distinguish. Used by the download views.
    """
    import ckan.authz as authz
    result = authz.is_authorized('resource_show', context, data_dict)
    if not result.get('success'):
        return result
    pkg = _resource_package(context, data_dict)
    if pkg is None:
        return {'success': True}
    access = core.get_access(pkg, context=context)
    if access.can_download:
        return {'success': True}
    return {
        'success': False,
        'msg': tk._('Downloading this resource is not permitted '
                    '(access level: %s)') % access.level,
    }


def datashare_grant_manage(context, data_dict):
    """Managing grants == being allowed to update the dataset."""
    pkg_id = (data_dict or {}).get('package_id') or \
        (data_dict or {}).get('id')
    if not pkg_id:
        return {'success': False, 'msg': tk._('No dataset specified')}
    import ckan.authz as authz
    result = authz.is_authorized('package_update', context, {'id': pkg_id})
    if result.get('success'):
        return {'success': True}
    return {'success': False,
            'msg': tk._('Not authorized to manage sharing '
                        'for this dataset')}


@tk.auth_allow_anonymous_access
def datashare_access_check(context, data_dict):
    # The action itself calls package_show, which enforces read auth.
    return {'success': True}


def _logged_in(context):
    if context.get('auth_user_obj') or context.get('user'):
        return {'success': True}
    return {'success': False, 'msg': tk._('You must be logged in')}


def datashare_access_request_create(context, data_dict):
    return _logged_in(context)


def datashare_access_request_list(context, data_dict):
    # The action scopes results to orgs the user manages (empty otherwise).
    return _logged_in(context)


def datashare_access_request_count(context, data_dict):
    return _logged_in(context)


def datashare_access_request_process(context, data_dict):
    # Fine-grained check happens in the action (package_update on the
    # request's dataset); this gate just requires authentication.
    return _logged_in(context)


def get_auth_functions():
    return {
        'resource_show': resource_show,
        'package_update': package_update,
        'datashare_resource_download': datashare_resource_download,
        'datashare_grant_manage': datashare_grant_manage,
        'datashare_access_check': datashare_access_check,
        'datashare_access_request_create': datashare_access_request_create,
        'datashare_access_request_list': datashare_access_request_list,
        'datashare_access_request_count': datashare_access_request_count,
        'datashare_access_request_process': datashare_access_request_process,
    }
