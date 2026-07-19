# encoding: utf-8
"""Behavioral tests for the datashare_access_request table + scoping.

Same fixture style as test_db_grants.py: fresh in-memory SQLite with the
plugin tables plus the core ``package``/``group``/``member`` tables so the
owner-org scoping joins run against the real schema.
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
        tables=[group_table, member_table,
                db.datashare_grant_table, db.datashare_access_request_table])
    # Minimal stand-in for the core package table: the real one maps
    # Postgres-only types (JSONB plugin_data) that SQLite cannot create,
    # and the db helpers only join on these columns via raw SQL.
    with engine.begin() as conn:
        conn.execute(sa.text(
            "CREATE TABLE package (id TEXT PRIMARY KEY, name TEXT, "
            "title TEXT, state TEXT, type TEXT, owner_org TEXT, "
            "private BOOLEAN)"))
    db.Session.remove()
    db.Session.configure(bind=engine)
    try:
        yield db.Session
    finally:
        db.Session.remove()
        engine.dispose()


def _add_package(session, pkg_id, owner_org):
    session.execute(
        sa.text("INSERT INTO package (id, name, title, state, type, "
                "owner_org, private) VALUES (:id, :id, :id, 'active', "
                "'dataset', :org, 0)"),
        {'id': pkg_id, 'org': owner_org})
    session.commit()


def _add_member(session, user_id, entity_id, capacity, state='active'):
    session.execute(
        sa.text("INSERT INTO member (id, table_name, table_id, capacity, "
                "group_id, state) VALUES (:id, 'user', :uid, :cap, :gid, "
                ":state)"),
        {'id': '%s-%s' % (user_id, entity_id), 'uid': user_id,
         'cap': capacity, 'gid': entity_id, 'state': state})
    session.commit()


def test_request_lifecycle_and_single_pending(session):
    req = db.create_access_request('pkg1', 'alice', 'please')
    session.commit()
    assert req.status == 'pending'
    assert db.pending_request_for('pkg1', 'alice') is not None
    assert db.pending_request_for('pkg1', 'bob') is None
    assert db.pending_request_for('pkg2', 'alice') is None

    req.status = db.REQUEST_APPROVED
    session.commit()
    assert db.pending_request_for('pkg1', 'alice') is None, \
        'a decided request is no longer pending'


def test_pending_requests_scoped_by_owner_org(session):
    _add_package(session, 'pkg-a', 'orgA')
    _add_package(session, 'pkg-b', 'orgB')
    db.create_access_request('pkg-a', 'alice', '')
    db.create_access_request('pkg-b', 'bob', '')
    session.commit()

    assert len(db.pending_requests(None)) == 2, 'sysadmin scope sees all'
    only_a = db.pending_requests(['orgA'])
    assert len(only_a) == 1 and only_a[0]['package_id'] == 'pkg-a'
    assert only_a[0]['package_name'] == 'pkg-a'
    assert db.pending_requests([]) == [], 'empty scope sees nothing'
    assert db.count_pending_requests(None) == 2
    assert db.count_pending_requests(['orgB']) == 1
    assert db.count_pending_requests([]) == 0


def test_managed_org_ids_only_admin_editor_active(session):
    _add_member(session, 'alice', 'orgA', 'admin')
    _add_member(session, 'alice', 'orgB', 'editor')
    _add_member(session, 'alice', 'orgC', 'member')
    _add_member(session, 'alice', 'orgD', 'admin', state='deleted')

    assert sorted(db.managed_org_ids('alice')) == ['orgA', 'orgB']
    assert db.managed_org_ids('nobody') == []
    assert db.managed_org_ids(None) == []
