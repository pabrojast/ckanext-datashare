# encoding: utf-8
"""Database model for ckanext-datashare.

One table, ``datashare_grant``: the org/group-level analogue of CKAN's
native per-user dataset collaborators. A row means "this organization or
initiative (group) has been granted ``read`` or ``edit`` access to this
dataset". Individual people keep using CKAN's native collaborators.

Classic ``Table`` + ``mapper`` style bound to CKAN's shared metadata, with an
idempotent ``ensure_tables()`` bootstrap (same pattern as ckanext-csunesco /
ckanext-colab so the table self-creates on plugin load - no manual migration).
"""
import datetime
import logging
import uuid

import sqlalchemy as sa
from sqlalchemy import Table, Column, types, UniqueConstraint

from ckan.model.meta import metadata, mapper, Session  # noqa: F401
from ckan.model.domain_object import DomainObject

log = logging.getLogger(__name__)

GRANTEE_ORG = 'org'
GRANTEE_GROUP = 'group'
GRANTEE_TYPES = (GRANTEE_ORG, GRANTEE_GROUP)

CAPACITY_READ = 'read'
CAPACITY_EDIT = 'edit'
CAPACITIES = (CAPACITY_READ, CAPACITY_EDIT)

# Roles inside the grantee entity that may EXERCISE an 'edit' grant. A plain
# 'member' of a grantee org/group gets read access only, even on edit grants.
EDITOR_ROLES = ('admin', 'editor')


def make_uuid():
    return str(uuid.uuid4())


def _utcnow():
    return datetime.datetime.utcnow()


datashare_grant_table = Table(
    'datashare_grant', metadata,
    Column('id', types.UnicodeText, primary_key=True, default=make_uuid),
    Column('package_id', types.UnicodeText, nullable=False, index=True),
    Column('grantee_type', types.UnicodeText, nullable=False),
    Column('grantee_id', types.UnicodeText, nullable=False, index=True),
    Column('capacity', types.UnicodeText, nullable=False,
           default=CAPACITY_READ),
    Column('granted_by', types.UnicodeText),
    Column('created_at', types.DateTime, default=_utcnow),
    UniqueConstraint('package_id', 'grantee_type', 'grantee_id',
                     name='uq_datashare_grant_pkg_grantee'),
)

REQUEST_PENDING = 'pending'
REQUEST_APPROVED = 'approved'
REQUEST_REJECTED = 'rejected'

datashare_access_request_table = Table(
    'datashare_access_request', metadata,
    Column('id', types.UnicodeText, primary_key=True, default=make_uuid),
    Column('package_id', types.UnicodeText, nullable=False, index=True),
    Column('user_id', types.UnicodeText, nullable=False, index=True),
    Column('message', types.Text, default=u''),
    Column('status', types.UnicodeText, index=True, default=REQUEST_PENDING),
    Column('decided_by', types.UnicodeText),
    Column('decided_at', types.DateTime),
    Column('decision_note', types.Text, default=u''),
    Column('created_at', types.DateTime, default=_utcnow),
)

_ALL_TABLES = [datashare_grant_table, datashare_access_request_table]


class DatashareGrant(DomainObject):
    pass


class DatashareAccessRequest(DomainObject):
    pass


_mapped = False


def ensure_mappers():
    global _mapped
    if _mapped:
        return
    mapper(DatashareGrant, datashare_grant_table)
    mapper(DatashareAccessRequest, datashare_access_request_table)
    _mapped = True


def ensure_tables():
    """Create the plugin table if missing and wire the mapper. Idempotent."""
    from ckan.model import meta
    ensure_mappers()
    metadata.create_all(bind=meta.engine, tables=_ALL_TABLES, checkfirst=True)


# ---------------------------------------------------------------------------
# Query helpers. CONVENTION (as in csunesco): helpers never commit; the
# calling action owns the transaction boundary.
# ---------------------------------------------------------------------------

def get_grant(package_id, grantee_type, grantee_id):
    ensure_mappers()
    return (
        Session.query(DatashareGrant)
        .filter(DatashareGrant.package_id == package_id)
        .filter(DatashareGrant.grantee_type == grantee_type)
        .filter(DatashareGrant.grantee_id == grantee_id)
        .first()
    )


def package_grants(package_id):
    ensure_mappers()
    return (
        Session.query(DatashareGrant)
        .filter(DatashareGrant.package_id == package_id)
        .order_by(DatashareGrant.created_at)
        .all()
    )


def upsert_grant(package_id, grantee_type, grantee_id, capacity, granted_by):
    """Create the grant or update its capacity in place. No commit."""
    ensure_mappers()
    grant = get_grant(package_id, grantee_type, grantee_id)
    if grant is None:
        grant = DatashareGrant()
        grant.package_id = package_id
        grant.grantee_type = grantee_type
        grant.grantee_id = grantee_id
        Session.add(grant)
    grant.capacity = capacity
    grant.granted_by = granted_by
    return grant


def delete_grant(package_id, grantee_type, grantee_id):
    """Delete the grant row if present. Returns True if one existed. No commit."""
    grant = get_grant(package_id, grantee_type, grantee_id)
    if grant is None:
        return False
    Session.delete(grant)
    return True


def user_grant_rows(user_id, package_id):
    """(grant_capacity, member_capacity) pairs linking ``user_id`` to
    ``package_id`` through an active membership in a grantee org/group.

    Joins CKAN's core ``member`` table (org and group memberships both live
    there); read-only, bound parameters only.
    """
    if not user_id or not package_id:
        return []
    rows = Session.execute(
        sa.text(
            'SELECT g.capacity, m.capacity FROM datashare_grant g '
            'JOIN member m ON m.group_id = g.grantee_id '
            "WHERE m.table_name = 'user' AND m.state = 'active' "
            'AND m.table_id = :uid AND g.package_id = :pid'
        ),
        {'uid': user_id, 'pid': package_id},
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


def user_has_read_grant(user_id, package_id):
    """Any active membership in any grantee entity confers read access."""
    return bool(user_grant_rows(user_id, package_id))


def user_has_edit_grant(user_id, package_id):
    """Edit needs an 'edit' grant AND an admin/editor role in that entity."""
    return any(
        grant_cap == CAPACITY_EDIT and member_cap in EDITOR_ROLES
        for grant_cap, member_cap in user_grant_rows(user_id, package_id)
    )


def granted_package_ids_for_user(user_id):
    """Distinct package ids shared (read or edit) with any org/group the user
    is an active member of. Feeds the user's permission labels."""
    if not user_id:
        return []
    rows = Session.execute(
        sa.text(
            'SELECT DISTINCT g.package_id FROM datashare_grant g '
            'JOIN member m ON m.group_id = g.grantee_id '
            "WHERE m.table_name = 'user' AND m.state = 'active' "
            'AND m.table_id = :uid'
        ),
        {'uid': user_id},
    ).fetchall()
    return [row[0] for row in rows]


# ---------------------------------------------------------------------------
# Access-request helpers (same no-commit convention)
# ---------------------------------------------------------------------------

def get_request(request_id):
    ensure_mappers()
    if not request_id:
        return None
    return Session.query(DatashareAccessRequest).get(request_id)


def pending_request_for(package_id, user_id):
    ensure_mappers()
    return (
        Session.query(DatashareAccessRequest)
        .filter(DatashareAccessRequest.package_id == package_id)
        .filter(DatashareAccessRequest.user_id == user_id)
        .filter(DatashareAccessRequest.status == REQUEST_PENDING)
        .first()
    )


def create_access_request(package_id, user_id, message):
    ensure_mappers()
    req = DatashareAccessRequest()
    req.package_id = package_id
    req.user_id = user_id
    req.message = message or u''
    req.status = REQUEST_PENDING
    Session.add(req)
    return req


def managed_org_ids(user_id):
    """Org/group ids where the user is an active admin or editor."""
    if not user_id:
        return []
    rows = Session.execute(
        sa.text(
            "SELECT m.group_id FROM member m "
            "WHERE m.table_name = 'user' AND m.state = 'active' "
            "AND m.table_id = :uid AND m.capacity IN ('admin', 'editor')"
        ),
        {'uid': user_id},
    ).fetchall()
    return [row[0] for row in rows]


# Raw-SQL join with the core package table (not the ORM: model.Package maps
# Postgres-only columns like JSONB plugin_data, which would also make the
# SQLite behavioural tests impossible). Bound parameters only.

def pending_requests(owner_org_ids=None, limit=100):
    """Pending requests as dicts (+ package name/title), newest first.

    ``owner_org_ids=None`` means every dataset (sysadmin scope); an empty
    list means no scope at all.
    """
    if owner_org_ids is not None and not owner_org_ids:
        return []
    sql = (
        "SELECT r.id, r.package_id, r.user_id, r.message, r.created_at, "
        "p.name, p.title FROM datashare_access_request r "
        "JOIN package p ON p.id = r.package_id "
        "WHERE r.status = 'pending' AND p.state = 'active'"
    )
    params = {'limit': limit}
    if owner_org_ids is not None:
        sql += " AND p.owner_org IN :orgs"
        params['orgs'] = list(owner_org_ids)
    sql += " ORDER BY r.created_at DESC LIMIT :limit"
    stmt = sa.text(sql)
    if owner_org_ids is not None:
        stmt = stmt.bindparams(sa.bindparam('orgs', expanding=True))
    rows = Session.execute(stmt, params).fetchall()
    return [{
        'id': row[0],
        'package_id': row[1],
        'user_id': row[2],
        'message': row[3],
        'created_at': row[4].isoformat() if hasattr(row[4], 'isoformat')
        else row[4],
        'package_name': row[5],
        'package_title': row[6],
    } for row in rows]


def count_pending_requests(owner_org_ids=None):
    if owner_org_ids is not None and not owner_org_ids:
        return 0
    sql = (
        "SELECT COUNT(*) FROM datashare_access_request r "
        "JOIN package p ON p.id = r.package_id "
        "WHERE r.status = 'pending' AND p.state = 'active'"
    )
    params = {}
    if owner_org_ids is not None:
        sql += " AND p.owner_org IN :orgs"
        params['orgs'] = list(owner_org_ids)
    stmt = sa.text(sql)
    if owner_org_ids is not None:
        stmt = stmt.bindparams(sa.bindparam('orgs', expanding=True))
    return Session.execute(stmt, params).scalar() or 0


def request_dictize(req):
    if req is None:
        return None
    return {
        'id': req.id,
        'package_id': req.package_id,
        'user_id': req.user_id,
        'message': req.message,
        'status': req.status,
        'decided_by': req.decided_by,
        'decided_at': (req.decided_at.isoformat()
                       if req.decided_at else None),
        'decision_note': req.decision_note,
        'created_at': (req.created_at.isoformat()
                       if req.created_at else None),
    }


def grant_dictize(grant):
    if grant is None:
        return None
    return {
        'id': grant.id,
        'package_id': grant.package_id,
        'grantee_type': grant.grantee_type,
        'grantee_id': grant.grantee_id,
        'capacity': grant.capacity,
        'granted_by': grant.granted_by,
        'created_at': (grant.created_at.isoformat()
                       if grant.created_at else None),
    }
