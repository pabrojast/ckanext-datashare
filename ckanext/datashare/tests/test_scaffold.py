# encoding: utf-8
"""Scaffold smoke tests: the plugin loads and registers everything.

Runs inside the ckan-dev container (skips without CKAN). The pure policy
tests in test_policy_matrix.py run anywhere.
"""
import pytest

try:
    from ckanext.datashare.plugin import DatasharePlugin
    HAVE_CKAN = True
except Exception:  # pragma: no cover - environment without CKAN
    HAVE_CKAN = False

pytestmark = pytest.mark.skipif(
    not HAVE_CKAN, reason="requires CKAN")


@pytest.fixture(scope='module')
def plugin():
    return DatasharePlugin()


def test_registries_non_empty(plugin):
    assert plugin.get_actions()
    assert plugin.get_auth_functions()
    assert plugin.get_validators()
    assert plugin.get_helpers()
    assert plugin.get_commands()


def test_expected_actions_registered(plugin):
    actions = plugin.get_actions()
    for name in ('datashare_grant_create', 'datashare_grant_delete',
                 'datashare_grant_list', 'datashare_access_check',
                 'resource_view_list', 'datashare_access_request_create',
                 'datashare_access_request_list',
                 'datashare_access_request_count',
                 'datashare_access_request_process'):
        assert name in actions
    # resource_view_list wraps core, it must be chained
    assert getattr(actions['resource_view_list'], 'chained_action', False)


def test_download_blueprint_rules(plugin):
    blueprints = plugin.get_blueprint()
    assert blueprints
    # Register on a throwaway app to enumerate the resulting url map.
    import flask
    app = flask.Flask(__name__)
    for bp in blueprints:
        app.register_blueprint(bp)
    rules = sorted(str(r) for r in app.url_map.iter_rules()
                   if r.endpoint != 'static')
    assert '/dataset/<id>/resource/<resource_id>/download' in rules
    assert '/dataset/<id>/resource/<resource_id>/download/<filename>' in rules
    assert '/dataset/<id>/shared' in rules


def test_expected_auth_functions_registered(plugin):
    auth = plugin.get_auth_functions()
    for name in ('resource_show', 'package_update',
                 'datashare_resource_download', 'datashare_grant_manage'):
        assert name in auth
    # The core overrides MUST be chained (schemingdcat registers plain
    # overrides; a second plain override would abort CKAN startup).
    assert getattr(auth['resource_show'], 'chained_auth_function', False)
    assert getattr(auth['package_update'], 'chained_auth_function', False)


def test_permission_labels_hooks_exist(plugin):
    assert callable(plugin.get_dataset_labels)
    assert callable(plugin.get_user_dataset_labels)
