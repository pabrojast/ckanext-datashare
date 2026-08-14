# encoding: utf-8
"""The dataset form has no Public/Private select: `private` follows the level.

These exercise the chained package_create/package_update wrappers directly -
they are plain functions, so a stub `original_action` is enough and no CKAN
app is needed. Only the import of the module requires CKAN.
"""
import pytest

try:
    from ckanext.datashare.logic import action
    HAVE_CKAN = True
except Exception:  # pragma: no cover - environment without CKAN
    HAVE_CKAN = False

pytestmark = pytest.mark.skipif(not HAVE_CKAN, reason="requires CKAN")

ORG = 'e2a1c0de-0000-0000-0000-000000000001'


def _call(wrapper, data_dict):
    """Run a chained wrapper with a stub inner action; return the dict seen."""
    seen = {}

    def original_action(context, data):
        seen['data'] = data
        return {'ok': True}

    result = wrapper(original_action, {}, data_dict)
    assert result == {'ok': True}, "the inner action's return must pass through"
    assert seen['data'] is data_dict, "the same dict must reach the inner action"
    return data_dict


@pytest.mark.parametrize('wrapper_name', ['package_create', 'package_update'])
@pytest.mark.parametrize('level,expected', [
    ('confidential', True),
    ('public', False),
    ('findable', False),
    ('viewable', False),
    ('restricted', False),
    ('', False),
])
def test_level_drives_private(wrapper_name, level, expected):
    wrapper = getattr(action, wrapper_name)
    data = _call(wrapper, {'name': 'ds', 'owner_org': ORG,
                           'access_level': level})
    assert data['private'] is expected


@pytest.mark.parametrize('wrapper_name', ['package_create', 'package_update'])
def test_missing_level_leaves_private_alone(wrapper_name):
    """Harvesters and partial patches must keep CKAN's own behaviour."""
    wrapper = getattr(action, wrapper_name)
    data = _call(wrapper, {'name': 'ds', 'owner_org': ORG, 'private': True})
    assert data['private'] is True, "an explicit private must survive"

    data = _call(wrapper, {'name': 'ds', 'owner_org': ORG})
    assert 'private' not in data


def test_level_inside_extras_is_honoured():
    """The wrapper can run before schemingdcat promotes extras to top level."""
    data = _call(action.package_update, {
        'name': 'ds', 'owner_org': ORG,
        'extras': [{'key': 'access_level', 'value': 'confidential'}],
    })
    assert data['private'] is True


def test_confidential_without_organization_is_left_alone():
    """`datasets_with_no_organization_cannot_be_private` would 500 the form."""
    data = _call(action.package_create,
                 {'name': 'ds', 'access_level': 'confidential'})
    assert 'private' not in data


def test_group_id_counts_as_an_organization():
    data = _call(action.package_create,
                 {'name': 'ds', 'group_id': ORG,
                  'access_level': 'confidential'})
    assert data['private'] is True


def test_non_dict_payload_does_not_explode():
    """Some callers pass flattened/tuple-keyed dicts; never raise on them."""
    for payload in (None, [], 'nope'):
        seen = {}

        def original_action(context, data):
            seen['data'] = data
            return 'passthrough'

        assert action.package_update(original_action, {}, payload) \
            == 'passthrough'
        assert seen['data'] is payload


def test_derivation_is_idempotent():
    """A re-entrant patch (schemingdcat autofills after create) must agree."""
    data = {'name': 'ds', 'owner_org': ORG, 'access_level': 'confidential'}
    _call(action.package_update, data)
    first = data['private']
    _call(action.package_update, data)
    assert data['private'] is first is True
