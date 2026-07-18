# encoding: utf-8
"""Pure access-policy matrix for ckanext-datashare.

This module has NO CKAN imports on purpose: it is the single place that
encodes "what does each access level allow for an unauthorized user", and it
is unit-testable without a CKAN installation. All CKAN-dependent lookups
(who is the user, is she a member/collaborator/grantee) live in ``core.py``,
which composes those answers with this matrix.

Levels (dataset-level flag ``access_level``; categories are configurable via
``ckanext.datashare.levels`` until UNESCO finalizes them):

  public        - default; behaves exactly like today (no gating at all).
  confidential  - exclusively manageable by the data provider: invisible in
                  search and unreadable for everyone outside the owner org
                  (enforced via permission labels, see labels.py).
  findable      - appears in search with full metadata, but resources are
                  neither viewable nor downloadable.
  viewable      - metadata + resource previews are available, but the file
                  itself cannot be downloaded.
  restricted    - full access for selected organizations/initiatives (grants);
                  everyone else gets the configured fallback behaviour
                  ('findable' by default, or 'hidden').

An UNKNOWN level (e.g. a category renamed in config while old values linger
in datasets) is deliberately treated as ``findable``: metadata stays visible
but data access is closed. Failing open would silently publish gated data.
"""
from collections import namedtuple

LEVEL_PUBLIC = 'public'
LEVEL_CONFIDENTIAL = 'confidential'
LEVEL_FINDABLE = 'findable'
LEVEL_VIEWABLE = 'viewable'
LEVEL_RESTRICTED = 'restricted'

DEFAULT_LEVELS = [
    LEVEL_PUBLIC,
    LEVEL_CONFIDENTIAL,
    LEVEL_FINDABLE,
    LEVEL_VIEWABLE,
    LEVEL_RESTRICTED,
]

BEHAVIOR_FINDABLE = 'findable'
BEHAVIOR_HIDDEN = 'hidden'

FIELD_NAME = 'access_level'

AccessResult = namedtuple('AccessResult', [
    'level',              # normalized access level of the dataset
    'is_authorized',      # user passes the authorization test (org/collab/grant)
    'can_discover',       # may appear in search results for this user
    'can_read_metadata',  # may open the dataset page / package_show
    'can_view_resources', # may see the resource list + previews
    'can_download',       # may download the actual file
    'can_edit',           # may update the dataset
])


def normalize_level(value):
    """Map a raw ``access_level`` value to the effective level string.

    Empty/missing means ``public`` (backwards compatible: every pre-existing
    dataset keeps behaving exactly as today).
    """
    value = (value or '').strip()
    return value or LEVEL_PUBLIC


def access_for(level, authorized, can_edit=False,
               restricted_behavior=BEHAVIOR_FINDABLE):
    """Return the :class:`AccessResult` for a dataset at ``level``.

    ``authorized`` is the caller-resolved authorization verdict (sysadmin,
    owner-org member, dataset collaborator, or entity grant - see
    ``core.is_authorized``). ``can_edit`` only matters when authorized.
    """
    if authorized:
        return AccessResult(level, True, True, True, True, True,
                            bool(can_edit))

    if level == LEVEL_PUBLIC:
        return AccessResult(level, False, True, True, True, True, False)

    if level == LEVEL_CONFIDENTIAL:
        return AccessResult(level, False, False, False, False, False, False)

    if level == LEVEL_FINDABLE:
        return AccessResult(level, False, True, True, False, False, False)

    if level == LEVEL_VIEWABLE:
        return AccessResult(level, False, True, True, True, False, False)

    if level == LEVEL_RESTRICTED:
        if restricted_behavior == BEHAVIOR_HIDDEN:
            return AccessResult(level, False, False, False, False, False,
                                False)
        return AccessResult(level, False, True, True, False, False, False)

    # Unknown/custom level: fail closed for data, open for metadata.
    return AccessResult(level, False, True, True, False, False, False)


def is_hidden_from_public(level, restricted_behavior=BEHAVIOR_FINDABLE):
    """True when datasets at ``level`` must NOT carry the ``public`` search
    label for unauthorized users (drives labels.py)."""
    return not access_for(level, False,
                          restricted_behavior=restricted_behavior).can_discover
