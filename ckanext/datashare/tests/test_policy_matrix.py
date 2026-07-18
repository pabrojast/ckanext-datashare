# encoding: utf-8
"""Exhaustive tests of the pure policy matrix (no CKAN required).

This is the contract the whole plugin hangs off: if these expectations ever
change, the UNESCO-facing access matrix document must change with them.
"""
import pytest

from ckanext.datashare import policy
from ckanext.datashare.policy import (
    access_for,
    normalize_level,
    is_hidden_from_public,
    LEVEL_PUBLIC,
    LEVEL_CONFIDENTIAL,
    LEVEL_FINDABLE,
    LEVEL_VIEWABLE,
    LEVEL_RESTRICTED,
    BEHAVIOR_FINDABLE,
    BEHAVIOR_HIDDEN,
)


# (level, behavior) -> expected caps for an UNAUTHORIZED user:
#   (can_discover, can_read_metadata, can_view_resources, can_download)
UNAUTHORIZED_MATRIX = [
    (LEVEL_PUBLIC, BEHAVIOR_FINDABLE, (True, True, True, True)),
    (LEVEL_CONFIDENTIAL, BEHAVIOR_FINDABLE, (False, False, False, False)),
    (LEVEL_FINDABLE, BEHAVIOR_FINDABLE, (True, True, False, False)),
    (LEVEL_VIEWABLE, BEHAVIOR_FINDABLE, (True, True, True, False)),
    (LEVEL_RESTRICTED, BEHAVIOR_FINDABLE, (True, True, False, False)),
    (LEVEL_RESTRICTED, BEHAVIOR_HIDDEN, (False, False, False, False)),
]


@pytest.mark.parametrize('level,behavior,expected', UNAUTHORIZED_MATRIX)
def test_unauthorized_matrix(level, behavior, expected):
    access = access_for(level, False, restricted_behavior=behavior)
    assert access.level == level
    assert not access.is_authorized
    assert not access.can_edit, 'unauthorized users can never edit'
    assert (access.can_discover, access.can_read_metadata,
            access.can_view_resources, access.can_download) == expected


@pytest.mark.parametrize('level', policy.DEFAULT_LEVELS)
@pytest.mark.parametrize('behavior', [BEHAVIOR_FINDABLE, BEHAVIOR_HIDDEN])
def test_authorized_users_get_full_read_access(level, behavior):
    access = access_for(level, True, restricted_behavior=behavior)
    assert access.is_authorized
    assert access.can_discover
    assert access.can_read_metadata
    assert access.can_view_resources
    assert access.can_download


@pytest.mark.parametrize('can_edit', [True, False])
def test_can_edit_passes_through_only_when_authorized(can_edit):
    assert access_for(LEVEL_RESTRICTED, True,
                      can_edit=can_edit).can_edit is can_edit
    assert access_for(LEVEL_RESTRICTED, False,
                      can_edit=can_edit).can_edit is False


def test_unknown_level_fails_closed_for_data_open_for_metadata():
    access = access_for('embargoed', False)
    assert access.can_discover and access.can_read_metadata
    assert not access.can_view_resources
    assert not access.can_download


def test_capability_ladder_is_monotonic():
    """Each capability implies the previous one (no weird combinations)."""
    for level in policy.DEFAULT_LEVELS + ['unknown-custom-level']:
        for behavior in (BEHAVIOR_FINDABLE, BEHAVIOR_HIDDEN):
            for authorized in (True, False):
                a = access_for(level, authorized,
                               restricted_behavior=behavior)
                if a.can_download:
                    assert a.can_view_resources
                if a.can_view_resources:
                    assert a.can_read_metadata
                if a.can_read_metadata:
                    assert a.can_discover


@pytest.mark.parametrize('raw,expected', [
    (None, LEVEL_PUBLIC),
    ('', LEVEL_PUBLIC),
    ('   ', LEVEL_PUBLIC),
    ('public', LEVEL_PUBLIC),
    (' viewable ', LEVEL_VIEWABLE),
    ('confidential', LEVEL_CONFIDENTIAL),
])
def test_normalize_level(raw, expected):
    assert normalize_level(raw) == expected


def test_hidden_from_public():
    assert is_hidden_from_public(LEVEL_CONFIDENTIAL)
    assert not is_hidden_from_public(LEVEL_FINDABLE)
    assert not is_hidden_from_public(LEVEL_VIEWABLE)
    assert not is_hidden_from_public(LEVEL_PUBLIC)
    assert not is_hidden_from_public(LEVEL_RESTRICTED,
                                     restricted_behavior=BEHAVIOR_FINDABLE)
    assert is_hidden_from_public(LEVEL_RESTRICTED,
                                 restricted_behavior=BEHAVIOR_HIDDEN)
