# encoding: utf-8
"""API actions for ckanext-datashare.

Grant management (org/group-level sharing) plus a read-only access probe.
Actions own the transaction boundary (db helpers never commit) and reindex
the affected package so permission labels stay in sync with Solr.
"""
import logging

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


def get_actions():
    return {
        'datashare_grant_create': datashare_grant_create,
        'datashare_grant_delete': datashare_grant_delete,
        'datashare_grant_list': datashare_grant_list,
        'datashare_access_check': datashare_access_check,
    }
