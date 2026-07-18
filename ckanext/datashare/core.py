# encoding: utf-8
"""CKAN glue for the datashare access engine.

``get_access()`` is the single entry point every layer uses (permission
labels, auth functions, template helpers, API actions, download views):
it resolves WHO the user is relative to the dataset (sysadmin / owner-org
member / native collaborator / entity grantee) and hands the verdict to the
pure policy matrix in ``policy.py``.
"""
import logging

import ckan.plugins.toolkit as tk

from ckanext.datashare import policy
from ckanext.datashare.policy import (  # noqa: F401  (re-exported)
    AccessResult,
    FIELD_NAME,
    LEVEL_PUBLIC,
    LEVEL_CONFIDENTIAL,
    LEVEL_FINDABLE,
    LEVEL_VIEWABLE,
    LEVEL_RESTRICTED,
)

log = logging.getLogger(__name__)

CONFIG_LEVELS = 'ckanext.datashare.levels'
CONFIG_RESTRICTED_BEHAVIOR = \
    'ckanext.datashare.restricted_unauthorized_behavior'
CONFIG_VIEWABLE_VIEW_TYPES = 'ckanext.datashare.viewable_allowed_view_types'

DEFAULT_VIEWABLE_VIEW_TYPES = [
    'pdf_view', 'image_view', 'text_view', 'video_view',
]


def configured_levels():
    levels = tk.aslist(tk.config.get(CONFIG_LEVELS, ''))
    return levels or list(policy.DEFAULT_LEVELS)


def restricted_behavior():
    value = tk.config.get(CONFIG_RESTRICTED_BEHAVIOR,
                          policy.BEHAVIOR_FINDABLE)
    return (value if value in (policy.BEHAVIOR_FINDABLE,
                               policy.BEHAVIOR_HIDDEN)
            else policy.BEHAVIOR_FINDABLE)


def viewable_view_types():
    return (tk.aslist(tk.config.get(CONFIG_VIEWABLE_VIEW_TYPES, ''))
            or list(DEFAULT_VIEWABLE_VIEW_TYPES))


# ---------------------------------------------------------------------------
# Dataset-side lookups (accept both package dicts and model objects)
# ---------------------------------------------------------------------------

def raw_level(pkg):
    """Extract the raw ``access_level`` value from a package dict or model."""
    if pkg is None:
        return None
    if isinstance(pkg, dict):
        value = pkg.get(FIELD_NAME)
        if value is None:
            for extra in pkg.get('extras') or []:
                if extra.get('key') == FIELD_NAME:
                    value = extra.get('value')
                    break
        return value
    try:
        return pkg.extras.get(FIELD_NAME)
    except Exception:
        return None


def dataset_level(pkg):
    level = policy.normalize_level(raw_level(pkg))
    if level != LEVEL_PUBLIC and level not in configured_levels():
        # A category that config no longer knows: policy treats it as
        # findable (fail closed for data); keep the raw value for display.
        log.debug("datashare: unknown access_level %r on package", level)
    return level


def _pkg_attr(pkg, dict_key, model_attr=None):
    if isinstance(pkg, dict):
        return pkg.get(dict_key)
    return getattr(pkg, model_attr or dict_key, None)


# ---------------------------------------------------------------------------
# User-side authorization
# ---------------------------------------------------------------------------

def _resolve_user_obj(user=None, context=None):
    """Best-effort resolution of a User object from what callers have."""
    if user is not None and not isinstance(user, str):
        return user
    if context is not None:
        user_obj = context.get('auth_user_obj')
        if user_obj is not None:
            return user_obj
        user = user or context.get('user')
    if isinstance(user, str) and user:
        import ckan.model as model
        return model.User.get(user)
    return None


def is_authorized(pkg, user_obj):
    """Does this user pass the dataset's authorization test at all?

    True for: sysadmins, members of the owner org (any capacity), native
    dataset collaborators (any capacity), and members of an org/group that
    holds a datashare grant on the dataset.
    """
    if user_obj is None:
        return False
    if getattr(user_obj, 'sysadmin', False):
        return True

    import ckan.authz as authz
    from ckanext.datashare import db

    pkg_id = _pkg_attr(pkg, 'id')
    owner_org = _pkg_attr(pkg, 'owner_org')

    if owner_org:
        role = authz.users_role_for_group_or_org(owner_org, user_obj.name)
        if role:
            return True
    else:
        creator = _pkg_attr(pkg, 'creator_user_id')
        if creator and creator == user_obj.id:
            return True

    if pkg_id:
        try:
            if authz.check_config_permission('allow_dataset_collaborators') \
                    and authz.user_is_collaborator_on_dataset(
                        user_obj.id, pkg_id):
                return True
        except Exception:
            log.exception("datashare: collaborator check failed")
        if db.user_has_read_grant(user_obj.id, pkg_id):
            return True
    return False


def can_edit(pkg, user_obj):
    """May this user edit the dataset (beyond what core auth already says)?

    Mirrors CKAN semantics: admin/editor of the owner org, admin/editor
    collaborator, or admin/editor of an entity holding an 'edit' grant.
    """
    if user_obj is None:
        return False
    if getattr(user_obj, 'sysadmin', False):
        return True

    import ckan.authz as authz
    from ckanext.datashare import db

    pkg_id = _pkg_attr(pkg, 'id')
    owner_org = _pkg_attr(pkg, 'owner_org')

    if owner_org:
        role = authz.users_role_for_group_or_org(owner_org, user_obj.name)
        if role in db.EDITOR_ROLES:
            return True

    if pkg_id:
        try:
            if authz.check_config_permission('allow_dataset_collaborators') \
                    and authz.user_is_collaborator_on_dataset(
                        user_obj.id, pkg_id, capacity=list(db.EDITOR_ROLES)):
                return True
        except Exception:
            log.exception("datashare: collaborator check failed")
        if db.user_has_edit_grant(user_obj.id, pkg_id):
            return True
    return False


def get_access(pkg, user=None, context=None):
    """The AccessResult for ``user`` (obj, name, or via context) on ``pkg``."""
    user_obj = _resolve_user_obj(user, context)
    level = dataset_level(pkg)
    if level == LEVEL_PUBLIC and user_obj is None:
        # Fast path: anonymous + public needs no DB lookups at all.
        return policy.access_for(level, False)
    authorized = is_authorized(pkg, user_obj)
    return policy.access_for(
        level,
        authorized,
        can_edit=can_edit(pkg, user_obj) if authorized else False,
        restricted_behavior=restricted_behavior(),
    )
