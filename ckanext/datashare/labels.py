# encoding: utf-8
"""IPermissionLabels implementation for ckanext-datashare.

In CKAN 2.10 both ``package_search`` visibility AND ``package_show`` auth are
entirely label-based, so this one mechanism enforces 'confidential' (and
'restricted' in hidden mode) for search and read at once.

IMPORTANT: CKAN uses exactly ONE IPermissionLabels implementation (the first
plugin that provides it, else the default). This module therefore REPLICATES
``ckan.lib.plugins.DefaultPermissionLabels`` behaviour for every normal
dataset and only diverges for datashare-hidden levels:

  * dataset labels: hidden datasets never get the ``public`` label; they get
    the same labels a private dataset would (``member-<org>`` +
    ``collaborator-<id>``), plus ``datashare-grant-<id>`` when grantee
    entities should still see them (restricted-hidden, NOT confidential -
    confidential is exclusive to the data provider by definition).
  * user labels: default labels plus one ``datashare-grant-<pkg>`` label per
    dataset shared with any org/group the user is an active member of.

No other plugin in the IHP-WINS stack implements IPermissionLabels (verified
2026-07-18); if one ever does, only one of the two will win - see README.
"""
import logging

import ckan.authz as authz
from ckan.logic import get_action

from ckanext.datashare import core, policy

log = logging.getLogger(__name__)

GRANT_LABEL = u'datashare-grant-%s'


def _default_private_style_labels(dataset_obj):
    """The labels DefaultPermissionLabels gives a non-public dataset."""
    if authz.check_config_permission('allow_dataset_collaborators'):
        labels = [u'collaborator-%s' % dataset_obj.id]
    else:
        labels = []
    if dataset_obj.owner_org:
        labels.append(u'member-%s' % dataset_obj.owner_org)
    else:
        labels.append(u'creator-%s' % dataset_obj.creator_user_id)
    return labels


def get_dataset_labels(dataset_obj):
    level = core.dataset_level(dataset_obj)
    hidden = policy.is_hidden_from_public(
        level, restricted_behavior=core.restricted_behavior())

    if dataset_obj.state == u'active' and not dataset_obj.private \
            and not hidden:
        return [u'public']

    labels = _default_private_style_labels(dataset_obj)

    # Grantee orgs/groups keep seeing restricted-hidden datasets. Confidential
    # deliberately gets NO grant label: it is exclusive to the data provider.
    if hidden and level != core.LEVEL_CONFIDENTIAL:
        labels.append(GRANT_LABEL % dataset_obj.id)
    return labels


def get_user_dataset_labels(user_obj):
    labels = [u'public']
    if not user_obj:
        return labels

    labels.append(u'creator-%s' % user_obj.id)

    orgs = get_action(u'organization_list_for_user')(
        {u'user': user_obj.id}, {u'permission': u'read'})
    labels.extend(u'member-%s' % o[u'id'] for o in orgs)

    if authz.check_config_permission('allow_dataset_collaborators'):
        datasets = get_action('package_collaborator_list_for_user')(
            {'ignore_auth': True}, {'id': user_obj.id})
        labels.extend(u'collaborator-%s' % d['package_id'] for d in datasets)

    try:
        from ckanext.datashare import db
        labels.extend(GRANT_LABEL % pid
                      for pid in db.granted_package_ids_for_user(user_obj.id))
    except Exception:
        # Never break search/auth for everyone because of a grants hiccup.
        log.exception("datashare: could not resolve grant labels")
    return labels
