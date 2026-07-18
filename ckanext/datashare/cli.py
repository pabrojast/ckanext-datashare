# encoding: utf-8
"""CLI commands: ``ckan -c <ini> datashare <cmd>``."""
import click


@click.group(short_help='ckanext-datashare maintenance commands')
def datashare():
    pass


@datashare.command('init-db', short_help='Create the datashare tables')
def init_db():
    from ckanext.datashare import db
    db.ensure_tables()
    click.secho('datashare tables ensured', fg='green')
