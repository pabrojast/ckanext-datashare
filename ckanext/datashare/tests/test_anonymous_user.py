# encoding: utf-8
"""Regression tests for flask-login AnonymousUser handling.

CKAN 2.10 passes a TRUTHY AnonymousUser object (``is_anonymous == True``)
as ``auth_user_obj``/label user for anonymous requests. Treating it as a
real user broke anonymous package_search in dev (its fake id reached
``package_collaborator_list_for_user``, which raises NotAuthorized for
unknown ids). These tests pin the guard in both entry points.
"""
import pytest

try:
    import ckan  # noqa: F401
    from ckanext.datashare import core, labels
    HAVE_CKAN = True
except Exception:  # pragma: no cover - environment without CKAN
    HAVE_CKAN = False

pytestmark = pytest.mark.skipif(not HAVE_CKAN, reason="requires CKAN")


class FakeAnonymousUser(object):
    """Mimics flask_login.AnonymousUserMixin: truthy, is_anonymous=True."""
    is_anonymous = True
    name = ''

    @property
    def id(self):  # pragma: no cover - must never be touched
        raise AssertionError('anonymous id must never be read')


def test_user_labels_for_anonymous_object_is_public_only():
    assert labels.get_user_dataset_labels(FakeAnonymousUser()) == ['public']


def test_user_labels_for_none_is_public_only():
    assert labels.get_user_dataset_labels(None) == ['public']


def test_resolve_user_obj_normalizes_anonymous_to_none():
    anon = FakeAnonymousUser()
    assert core._resolve_user_obj(user=anon) is None
    assert core._resolve_user_obj(context={'auth_user_obj': anon}) is None
    assert core._resolve_user_obj(user=None, context={}) is None
