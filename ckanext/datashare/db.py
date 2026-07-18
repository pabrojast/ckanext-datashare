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

_ALL_TABLES = [datashare_grant_table]


class DatashareGrant(DomainObject):
    pass


_mapped = False


def ensure_mappers():
    global _mapped
    if _mapped:
        return
    mapper(DatashareGrant, datashare_grant_table)
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
