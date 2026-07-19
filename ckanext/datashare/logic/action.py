# encoding: utf-8
"""API actions for ckanext-datashare.

Grant management (org/group-level sharing) plus a read-only access probe.
Actions own the transaction boundary (db helpers never commit) and reindex
the affected package so permission labels stay in sync with Solr.
"""
import logging

import sqlalchemy as sa

import ckan.plugins.toolkit as tk

from ckanext.datashare import core, db

log = logging.getLogger(__name__)


def _reindex(package_id):
    """Refresh the package's Solr document (labels/level changed)."""
    try:
        import ckan.lib.search as search
        search.rebuild(package_id)
    except Exception:
        log.exception("datashare: could not reindex package %s", package_id)


def _validate_grantee(context, grantee_type, grantee_id):
    """Resolve + validate the grantee org/group; returns the Group object."""
    model = context['model']
    if grantee_type not in db.GRANTEE_TYPES:
        raise tk.ValidationError(
            {'grantee_type': ["Must be one of: %s" % ', '.join(
                db.GRANTEE_TYPES)]})
    group = model.Group.get(grantee_id)
    if group is None or group.state != 'active':
        raise tk.ObjectNotFound('Grantee organization/group not found')
    if grantee_type == db.GRANTEE_ORG and not group.is_organization:
        raise tk.ValidationError(
            {'grantee_id': ['Not an organization: %s' % grantee_id]})
    if grantee_type == db.GRANTEE_GROUP and group.is_organization:
        raise tk.ValidationError(
            {'grantee_id': ['Not a group/initiative: %s' % grantee_id]})
    return group


def _resolve_package(context, data_dict):
    model = context['model']
    pkg_id = data_dict.get('package_id') or data_dict.get('id')
    if not pkg_id:
        raise tk.ValidationError({'package_id': ['Missing value']})
    pkg = model.Package.get(pkg_id)
    if pkg is None:
        raise tk.ObjectNotFound('Dataset not found')
    return pkg


def datashare_grant_create(context, data_dict):
    """Grant an organization or initiative read/edit access to a dataset.

    :param package_id: dataset id or name
    :param grantee_type: 'org' | 'group'
    :param grantee_id: id or name of the organization/group
    :param capacity: 'read' (default) | 'edit'
    """
    tk.check_access('datashare_grant_manage', context, data_dict)
    pkg = _resolve_package(context, data_dict)

    capacity = data_dict.get('capacity', db.CAPACITY_READ)
    if capacity not in db.CAPACITIES:
        raise tk.ValidationError(
            {'capacity': ["Must be one of: %s" % ', '.join(db.CAPACITIES)]})

    grantee_type = data_dict.get('grantee_type', db.GRANTEE_ORG)
    group = _validate_grantee(context, grantee_type,
                              data_dict.get('grantee_id'))

    user = context.get('user')
    grant = db.upsert_grant(pkg.id, grantee_type, group.id, capacity, user)
    db.Session.commit()
    _reindex(pkg.id)

    result = db.grant_dictize(grant)
    result['grantee_title'] = group.title or group.name
    result['grantee_name'] = group.name
    return result


def datashare_grant_delete(context, data_dict):
    """Revoke a grant. Same parameters as datashare_grant_create."""
    tk.check_access('datashare_grant_manage', context, data_dict)
    pkg = _resolve_package(context, data_dict)

    grantee_type = data_dict.get('grantee_type', db.GRANTEE_ORG)
    group = _validate_grantee(context, grantee_type,
                              data_dict.get('grantee_id'))

    deleted = db.delete_grant(pkg.id, grantee_type, group.id)
    if not deleted:
        raise tk.ObjectNotFound('Grant not found')
    db.Session.commit()
    _reindex(pkg.id)
    return {'deleted': True}


@tk.side_effect_free
def datashare_grant_list(context, data_dict):
    """List grants on a dataset (managers only - grants are not public)."""
    tk.check_access('datashare_grant_manage', context, data_dict)
    pkg = _resolve_package(context, data_dict)
    model = context['model']

    results = []
    for grant in db.package_grants(pkg.id):
        item = db.grant_dictize(grant)
        group = model.Group.get(grant.grantee_id)
        item['grantee_title'] = (group.title or group.name) if group \
            else grant.grantee_id
        item['grantee_name'] = group.name if group else grant.grantee_id
        results.append(item)
    return results


@tk.chained_action
@tk.side_effect_free
def resource_view_list(original_action, context, data_dict):
    """Filter resource views for 'viewable' datasets.

    Users who may preview but not download only get the configured whitelist
    of view types (views that proxy or dump the raw file are excluded).
    """
    views = original_action(context, data_dict)
    if not views:
        return views
    model = context['model']
    resource = model.Resource.get((data_dict or {}).get('id', ''))
    pkg = model.Package.get(resource.package_id) if resource else None
    if pkg is None:
        return views
    access = core.get_access(pkg, context=context)
    if access.can_download:
        return views
    if not access.can_view_resources:
        return []
    allowed = core.viewable_view_types()
    return [v for v in views if v.get('view_type') in allowed]


@tk.side_effect_free
def datashare_access_check(context, data_dict):
    """What can the current user do with this dataset?

    Read auth is enforced by the inner package_show (labels), so a
    confidential dataset 404s here exactly as it does everywhere else.
    """
    tk.check_access('datashare_access_check', context, data_dict)
    pkg_id = tk.get_or_bust(data_dict, 'id')
    pkg = tk.get_action('package_show')(context, {'id': pkg_id})
    access = core.get_access(pkg, context=context)
    result = dict(access._asdict())
    result['restricted_behavior'] = core.restricted_behavior()
    return result


# ---------------------------------------------------------------------------
# Access requests (request-access button -> owner-org review queue)
# ---------------------------------------------------------------------------

def _notify(user_obj, subject, body):
    """Best-effort email; never lets mail problems break the action."""
    try:
        from ckan.lib import mailer
        mailer.mail_user(user_obj, subject, body)
    except Exception:
        log.warning("datashare: could not send notification email")


def _org_managers(context, owner_org):
    import ckan.model as model
    rows = db.Session.execute(
        sa.text(
            "SELECT m.table_id FROM member m "
            "WHERE m.group_id = :org AND m.table_name = 'user' "
            "AND m.state = 'active' AND m.capacity IN ('admin', 'editor')"),
        {'org': owner_org}).fetchall()
    users = [model.User.get(r[0]) for r in rows]
    return [u for u in users if u is not None and u.email]


def datashare_access_request_create(context, data_dict):
    """Ask the data provider for access to a gated dataset.

    :param package_id: dataset id or name
    :param message: optional message for the provider
    """
    tk.check_access('datashare_access_request_create', context, data_dict)
    model = context['model']
    user_obj = context.get('auth_user_obj') or \
        model.User.get(context.get('user', ''))
    if user_obj is None:
        raise tk.NotAuthorized(tk._('You must be logged in'))

    pkg_id = data_dict.get('package_id') or data_dict.get('id')
    # package_show enforces read auth (confidential datasets 404 here too)
    pkg = tk.get_action('package_show')(context, {'id': pkg_id})

    access = core.get_access(pkg, user=user_obj)
    if access.can_download:
        raise tk.ValidationError(
            {'package_id': [tk._('You already have access to this dataset')]})
    if db.pending_request_for(pkg['id'], user_obj.id):
        raise tk.ValidationError(
            {'package_id': [tk._('You already have a pending request '
                                 'for this dataset')]})

    req = db.create_access_request(
        pkg['id'], user_obj.id, data_dict.get('message', ''))
    db.Session.commit()

    site_url = tk.config.get('ckan.site_url', '').rstrip('/')
    for manager in _org_managers(context, pkg.get('owner_org')):
        _notify(
            manager,
            tk._('IHP-WINS: data access request for "%s"') % pkg.get('title'),
            tk._('User %s requested access to the dataset "%s".\n\n'
                 'Message: %s\n\nReview it here: %s/datashare/requests\n')
            % (user_obj.display_name or user_obj.name, pkg.get('title'),
               data_dict.get('message', '') or '-', site_url))
    return db.request_dictize(req)


@tk.side_effect_free
def datashare_access_request_list(context, data_dict):
    """Pending access requests the current user may review.

    Sysadmins see everything; org admins/editors see requests on their
    organizations' datasets. Decorated with dataset title and requester.
    """
    tk.check_access('datashare_access_request_list', context, data_dict)
    model = context['model']
    user_obj = context.get('auth_user_obj') or \
        model.User.get(context.get('user', ''))
    if user_obj is None:
        return []

    scope = None if user_obj.sysadmin else db.managed_org_ids(user_obj.id)
    results = []
    for item in db.pending_requests(scope):
        requester = model.User.get(item['user_id'])
        item['user_name'] = requester.name if requester \
            else item['user_id']
        item['user_display_name'] = \
            (requester.display_name or requester.name) if requester \
            else item['user_id']
        results.append(item)
    return results


@tk.side_effect_free
def datashare_access_request_count(context, data_dict):
    """Pending-request count in the current user's review scope."""
    tk.check_access('datashare_access_request_count', context, data_dict)
    model = context['model']
    user_obj = context.get('auth_user_obj') or \
        model.User.get(context.get('user', ''))
    if user_obj is None:
        return 0
    scope = None if user_obj.sysadmin else db.managed_org_ids(user_obj.id)
    return db.count_pending_requests(scope)


def datashare_access_request_process(context, data_dict):
    """Approve or reject an access request.

    :param id: request id
    :param decision: 'approve' | 'reject'
    :param note: optional note sent to the requester

    Approval adds the requester as a native dataset collaborator
    (capacity 'member'), reusing all of CKAN's collaborator machinery.
    """
    model = context['model']
    request_id = tk.get_or_bust(data_dict, 'id')
    decision = data_dict.get('decision')
    if decision not in ('approve', 'reject'):
        raise tk.ValidationError(
            {'decision': [tk._("Must be 'approve' or 'reject'")]})

    req = db.get_request(request_id)
    if req is None or req.status != db.REQUEST_PENDING:
        raise tk.ObjectNotFound(tk._('Pending request not found'))

    # Reviewing = being allowed to update the dataset.
    tk.check_access('datashare_grant_manage', context,
                    {'package_id': req.package_id})

    pkg = model.Package.get(req.package_id)
    requester = model.User.get(req.user_id)
    import datetime
    req.decided_by = context.get('user')
    req.decided_at = datetime.datetime.utcnow()
    req.decision_note = data_dict.get('note', '') or ''

    if decision == 'approve':
        # The reviewer passed package_update; collaborator_create's own auth
        # is stricter (org admins only), so run it as the site.
        tk.get_action('package_collaborator_create')(
            {'ignore_auth': True, 'user': context.get('user')},
            {'id': req.package_id, 'user_id': req.user_id,
             'capacity': 'member'})
        req.status = db.REQUEST_APPROVED
    else:
        req.status = db.REQUEST_REJECTED
    db.Session.commit()

    if requester is not None and pkg is not None:
        site_url = tk.config.get('ckan.site_url', '').rstrip('/')
        if decision == 'approve':
            body = tk._('Your access request for "%s" was approved.\n'
                        'You can now access the data: %s/dataset/%s\n') % (
                pkg.title, site_url, pkg.name)
        else:
            body = tk._('Your access request for "%s" was declined.\n'
                        'Note: %s\n') % (pkg.title, req.decision_note or '-')
        _notify(requester,
                tk._('IHP-WINS: your data access request'), body)
    return db.request_dictize(req)


def get_actions():
    return {
        'datashare_access_request_create': datashare_access_request_create,
        'datashare_access_request_list': datashare_access_request_list,
        'datashare_access_request_count': datashare_access_request_count,
        'datashare_access_request_process': datashare_access_request_process,
        'datashare_grant_create': datashare_grant_create,
        'datashare_grant_delete': datashare_grant_delete,
        'datashare_grant_list': datashare_grant_list,
        'datashare_access_check': datashare_access_check,
        'resource_view_list': resource_view_list,
    }
