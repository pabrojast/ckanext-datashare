# encoding: utf-8
"""Behavioral tests for the datashare_grant table + membership joins.

Fresh in-memory SQLite per test (no Postgres/Solr): creates the plugin table
plus CKAN's core ``group``/``member`` tables on the shared metadata so the
raw-SQL membership joins in db.py run against the real member schema.
Skips cleanly when CKAN is absent, but MUST pass inside ckan-dev:2.10.
"""
import pytest

try:
    import sqlalchemy as sa
    import ckan.model as ckan_model  # noqa: F401
    from ckan.model.group import group_table, member_table
    from ckanext.datashare import db
    HAVE_CKAN = True
except Exception:  # pragma: no cover - environment without CKAN
    HAVE_CKAN = False

pytestmark = pytest.mark.skipif(
    not HAVE_CKAN, reason="requires CKAN (ckan.model + sqlalchemy)")


@pytest.fixture
def session():
    engine = sa.create_engine('sqlite://')
    db.ensure_mappers()
    db.metadata.create_all(
        bind=engine,
        tables=[group_table, member_table, db.datashare_grant_table])
    db.Session.remove()
    db.Session.configure(bind=engine)
    try:
        yield db.Session
    finally:
        db.Session.remove()
        engine.dispose()


def _add_member(session, user_id, entity_id, capacity, state='active'):
    session.execute(
        sa.text(
            "INSERT INTO member (id, table_name, table_id, capacity, "
            "group_id, state) VALUES (:id, 'user', :uid, :cap, :gid, :state)"
        ),
        {'id': '%s-%s' % (user_id, entity_id), 'uid': user_id,
         'cap': capacity, 'gid': entity_id, 'state': state},
    )
    session.commit()


def test_upsert_creates_then_updates_in_place(session):
    grant = db.upsert_grant('pkg1', 'org', 'orgA', 'read', 'admin')
    session.commit()
    assert grant.id
    assert grant.capacity == 'read'

    db.upsert_grant('pkg1', 'org', 'orgA', 'edit', 'admin2')
    session.commit()

    grants = db.package_grants('pkg1')
    assert len(grants) == 1, 'upsert must not duplicate the unique key'
    assert grants[0].capacity == 'edit'
    assert grants[0].granted_by == 'admin2'


def test_delete_grant(session):
    db.upsert_grant('pkg1', 'org', 'orgA', 'read', 'admin')
    session.commit()
    assert db.delete_grant('pkg1', 'org', 'orgA') is True
    session.commit()
    assert db.package_grants('pkg1') == []
    assert db.delete_grant('pkg1', 'org', 'orgA') is False


def test_read_grant_via_membership(session):
    db.upsert_grant('pkg1', 'org', 'orgA', 'read', 'admin')
    session.commit()
    _add_member(session, 'alice', 'orgA', 'member')

    assert db.user_has_read_grant('alice', 'pkg1')
    assert not db.user_has_edit_grant('alice', 'pkg1'), \
        'a read grant never confers edit'
    assert not db.user_has_read_grant('bob', 'pkg1'), \
        'non-members get nothing'
    assert not db.user_has_read_grant('alice', 'pkg2'), \
        'grants are per dataset'


def test_edit_grant_requires_editor_role_in_grantee(session):
    db.upsert_grant('pkg1', 'group', 'initX', 'edit', 'admin')
    session.commit()
    _add_member(session, 'plain', 'initX', 'member')
    _add_member(session, 'editor', 'initX', 'editor')
    _add_member(session, 'boss', 'initX', 'admin')

    assert db.user_has_read_grant('plain', 'pkg1')
    assert not db.user_has_edit_grant('plain', 'pkg1'), \
        "plain members of the grantee only read, even on 'edit' grants"
    assert db.user_has_edit_grant('editor', 'pkg1')
    assert db.user_has_edit_grant('boss', 'pkg1')


def test_inactive_membership_confers_nothing(session):
    db.upsert_grant('pkg1', 'org', 'orgA', 'edit', 'admin')
    session.commit()
    _add_member(session, 'gone', 'orgA', 'admin', state='deleted')

    assert not db.user_has_read_grant('gone', 'pkg1')
    assert not db.user_has_edit_grant('gone', 'pkg1')


def test_granted_package_ids_for_user_distinct(session):
    db.upsert_grant('pkg1', 'org', 'orgA', 'read', 'admin')
    db.upsert_grant('pkg1', 'group', 'initX', 'read', 'admin')
    db.upsert_grant('pkg2', 'org', 'orgA', 'edit', 'admin')
    db.upsert_grant('pkg3', 'org', 'orgB', 'read', 'admin')
    session.commit()
    _add_member(session, 'alice', 'orgA', 'member')
    _add_member(session, 'alice', 'initX', 'member')

    ids = sorted(db.granted_package_ids_for_user('alice'))
    assert ids == ['pkg1', 'pkg2'], \
        'distinct ids across all her entities, never orgB packages'
    assert db.granted_package_ids_for_user('nobody') == []
    assert db.granted_package_ids_for_user(None) == []
