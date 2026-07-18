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
