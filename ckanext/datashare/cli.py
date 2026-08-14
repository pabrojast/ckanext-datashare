# encoding: utf-8
"""CLI commands: ``ckan -c <ini> datashare <cmd>``."""
import io

import click


@click.group(short_help='ckanext-datashare maintenance commands')
def datashare():
    pass


@datashare.command('init-db', short_help='Create the datashare tables')
def init_db():
    from ckanext.datashare import db
    db.ensure_tables()
    click.secho('datashare tables ensured', fg='green')


# ---------------------------------------------------------------------------
# Backfill: legacy private datasets predate the access_level control
# ---------------------------------------------------------------------------

def _active_level(pkg):
    """The dataset's stored access_level, ignoring soft-deleted extras."""
    from ckanext.datashare import core
    extra = pkg._extras.get(core.FIELD_NAME)
    if extra is None or extra.state != 'active':
        return None
    return (extra.value or '').strip() or None


@datashare.command('backfill-access-level',
                   short_help='Stamp legacy private datasets as confidential')
@click.option('--dry-run', is_flag=True, help='Report only; write nothing')
@click.option('--no-reindex', is_flag=True,
              help='Skip the Solr reindex (rebuild the index yourself)')
def backfill_access_level(dry_run, no_reindex):
    """Give every legacy private dataset the 'confidential' sharing level.

    The Public/Private select is gone from the dataset form: ``private`` is
    now derived from ``access_level``. Datasets made private before that
    change carry no level, so the next time somebody edited one it would read
    as 'public' and be silently published. Stamping them 'confidential'
    preserves exactly the visibility they have today.

    Idempotent: datasets that already carry a level are left alone.
    """
    import ckan.model as model
    from ckanext.datashare import core

    pkgs = (model.Session.query(model.Package)
            .filter(model.Package.state == 'active')
            .filter(model.Package.private.is_(True))
            .order_by(model.Package.name).all())

    todo = [p for p in pkgs if _active_level(p) is None]
    conflicts = [(p, _active_level(p)) for p in pkgs
                 if _active_level(p) not in (None, core.LEVEL_CONFIDENTIAL)]

    click.echo('%d active private dataset(s); %d without access_level'
               % (len(pkgs), len(todo)))
    for pkg, level in conflicts:
        click.secho('  CONFLICT %s: private=True but access_level=%s -> it '
                    'will become PUBLIC on its next edit' % (pkg.name, level),
                    fg='yellow')

    if dry_run:
        for pkg in todo:
            click.echo('  would set confidential: %s' % pkg.name)
        click.secho('dry run: nothing written', fg='yellow')
        return

    if not todo:
        click.secho('nothing to do', fg='green')
        return

    for pkg in todo:
        extra = pkg._extras.get(core.FIELD_NAME)
        if extra is None:
            pkg.extras[core.FIELD_NAME] = core.LEVEL_CONFIDENTIAL
        else:
            # A soft-deleted row: revive it instead of inserting a duplicate
            # (only the (package, key) pair is unique).
            extra.value = core.LEVEL_CONFIDENTIAL
            extra.state = 'active'
    model.Session.commit()
    click.secho('%d dataset(s) stamped confidential' % len(todo), fg='green')

    if no_reindex:
        click.secho('reindex skipped: run `ckan search-index rebuild` or '
                    'package_show will keep serving the cached dict without '
                    'access_level', fg='yellow')
        return

    # Not optional in practice: package_show serves the validated_data_dict
    # cached in Solr, so without a reindex the level would stay invisible to
    # the derivation above.
    import ckan.lib.search as search
    failed = 0
    for pkg in todo:
        try:
            search.rebuild(pkg.id)
        except Exception as exc:
            failed += 1
            click.secho('  reindex failed for %s: %s' % (pkg.name, exc),
                        fg='yellow')
    click.secho('reindexed %d dataset(s)%s'
                % (len(todo) - failed,
                   '' if not failed else ', %d failed' % failed),
                fg='green' if not failed else 'yellow')


# ---------------------------------------------------------------------------
# Gulf Country Platform demo seed (idempotent - safe to re-run)
# ---------------------------------------------------------------------------

GULF_GROUP = {'name': 'gulf-country-platform',
              'title': 'Gulf Country Platform'}

GULF_ORGS = [
    ('ihp-demo-bahrain', 'IHP Bahrain (demo)'),
    ('ihp-demo-kuwait', 'IHP Kuwait (demo)'),
    ('ihp-demo-qatar', 'IHP Qatar (demo)'),
    ('ihp-demo-saudi-arabia', 'IHP Saudi Arabia (demo)'),
    ('ihp-demo-uae', 'IHP United Arab Emirates (demo)'),
    ('ihp-demo-oman', 'IHP Oman (demo)'),
]

PROVIDER_ORG = 'ihp-demo-bahrain'

# One dataset per access level. 'restricted' is shared with Kuwait (read)
# and Qatar (edit) to demonstrate transboundary sharing.
GULF_DATASETS = [
    ('gulf-demo-rainfall', 'Gulf rainfall observations (public demo)',
     'public'),
    ('gulf-demo-groundwater-levels',
     'National groundwater levels (confidential demo)', 'confidential'),
    ('gulf-demo-borehole-inventory',
     'Borehole inventory (findable demo)', 'findable'),
    ('gulf-demo-water-quality',
     'Coastal water quality (viewable demo)', 'viewable'),
    ('gulf-demo-shared-aquifer',
     'Shared aquifer monitoring (restricted demo)', 'restricted'),
]

DEMO_CSV = (
    'station,date,value\n'
    'GULF-001,2026-01-01,12.4\n'
    'GULF-002,2026-01-01,10.9\n'
)


def _site_context():
    import ckan.plugins.toolkit as tk
    site_user = tk.get_action('get_site_user')({'ignore_auth': True}, {})
    return {'ignore_auth': True, 'user': site_user['name']}


def _get_or_create(show_action, create_action, id_key, data):
    """package/org/group/user get-or-create; returns (obj, created)."""
    import ckan.plugins.toolkit as tk
    try:
        obj = tk.get_action(show_action)(_site_context(),
                                         {'id': data[id_key]})
        return obj, False
    except tk.ObjectNotFound:
        return tk.get_action(create_action)(_site_context(), data), True


def _fluent(text):
    return {'en': text, 'es': text, 'fr': text, 'ar': text}


@datashare.command('seed-gulf-demo',
                   short_help='Seed the Gulf Country Platform demo')
@click.option('--password', required=True,
              help='Password for the demo users (one editor per demo org)')
def seed_gulf_demo(password):
    """Create the Gulf Country Platform initiative, demo orgs/users and one
    dataset per access level, with sharing grants on the restricted one.

    Idempotent: existing objects are kept; the access_level of the demo
    datasets is re-asserted so the demo state self-heals.
    """
    import ckan.plugins.toolkit as tk
    from werkzeug.datastructures import FileStorage

    group, created = _get_or_create(
        'group_show', 'group_create', 'name',
        {'name': GULF_GROUP['name'], 'title': GULF_GROUP['title'],
         'description': 'Demonstration platform for transboundary '
                        'sharing of sensitive water data in the Gulf '
                        'region (demo content).'})
    click.echo('group %s: %s' % (group['name'],
                                 'created' if created else 'exists'))

    for org_name, org_title in GULF_ORGS:
        org, created = _get_or_create(
            'organization_show', 'organization_create', 'name',
            {'name': org_name, 'title': org_title,
             'description': 'Demo organization for the Gulf Country '
                            'Platform.'})
        click.echo('org %s: %s' % (org_name,
                                   'created' if created else 'exists'))

        user_name = org_name.replace('ihp-demo-', 'demo-gulf-')
        user, created = _get_or_create(
            'user_show', 'user_create', 'name',
            {'name': user_name,
             'email': '%s@example.org' % user_name,
             'password': password})
        tk.get_action('organization_member_create')(
            _site_context(),
            {'id': org_name, 'username': user_name, 'role': 'editor'})
        click.echo('  user %s (editor): %s' % (
            user_name, 'created' if created else 'exists'))

    for ds_name, ds_title, level in GULF_DATASETS:
        try:
            pkg, created = _get_or_create(
                'package_show', 'package_create', 'name',
                {
                    'name': ds_name,
                    'owner_org': PROVIDER_ORG,
                    'title_translated': _fluent(ds_title),
                    'notes_translated': _fluent(
                        'Demo dataset for the Gulf Country Platform '
                        'showing the "%s" data sharing level.' % level),
                    'identifier': ds_name,
                    'dcat_type': 'http://inspire.ec.europa.eu/metadata-codelist/ResourceType/dataset',
                    'theme_eu': ['http://publications.europa.eu/resource/authority/data-theme/ENVI'],
                    'language': 'http://publications.europa.eu/resource/authority/language/ENG',
                    'topic': 'http://inspire.ec.europa.eu/metadata-codelist/TopicCategory/inlandWaters',
                    'contact_email': 'ihp-wins@unesco.org',
                    'access_level': level,
                })
        except tk.ValidationError as e:
            click.secho('dataset %s FAILED: %s' % (ds_name, e.error_summary),
                        fg='red')
            continue

        if not created and pkg.get('access_level') != level:
            pkg = tk.get_action('package_patch')(
                _site_context(), {'id': pkg['id'], 'access_level': level})
            click.echo('dataset %s: access_level healed to %s'
                       % (ds_name, level))
        else:
            click.echo('dataset %s (%s): %s' % (
                ds_name, level, 'created' if created else 'exists'))

        if not pkg.get('resources'):
            try:
                tk.get_action('resource_create')(_site_context(), {
                    'package_id': pkg['id'],
                    'name': 'Demo measurements (CSV)',
                    'format': 'CSV',
                    'upload': FileStorage(
                        io.BytesIO(DEMO_CSV.encode('utf-8')),
                        filename='%s.csv' % ds_name),
                })
                click.echo('  resource uploaded')
            except Exception as e:
                click.secho('  resource upload failed: %s' % e, fg='yellow')

        try:
            tk.get_action('member_create')(_site_context(), {
                'id': GULF_GROUP['name'], 'object': pkg['id'],
                'object_type': 'package', 'capacity': 'public'})
        except Exception:
            pass  # already a member

    restricted = GULF_DATASETS[-1][0]
    for grantee, capacity in (('ihp-demo-kuwait', 'read'),
                              ('ihp-demo-qatar', 'edit')):
        grant = tk.get_action('datashare_grant_create')(_site_context(), {
            'package_id': restricted, 'grantee_type': 'org',
            'grantee_id': grantee, 'capacity': capacity})
        click.echo('grant: %s -> %s (%s)' % (
            restricted, grant['grantee_name'], capacity))

    click.secho('Gulf Country Platform demo seeded. Demo users '
                '(password as given): %s' % ', '.join(
                    o[0].replace('ihp-demo-', 'demo-gulf-')
                    for o in GULF_ORGS), fg='green')
