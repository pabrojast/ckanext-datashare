# encoding: utf-8
"""Main plugin for ckanext-datashare.

Dataset-level access flags (confidential / findable / viewable / restricted)
plus org/group-level sharing grants for the UNESCO IHP-WINS portal.

Interface map:
  IPermissionLabels  - confidential + restricted-hidden in search AND read
  IAuthFunctions     - chained resource_show/package_update, download auth
  IActions           - grant management + access probe
  IConfigurable      - idempotent table bootstrap (no manual migrations)
"""
import logging

import ckan.plugins as p
import ckan.plugins.toolkit as tk

log = logging.getLogger(__name__)

_tables_ensured = False


class DatasharePlugin(p.SingletonPlugin):
    p.implements(p.IConfigurer)
    p.implements(p.IConfigurable, inherit=True)
    p.implements(p.IActions)
    p.implements(p.IAuthFunctions)
    p.implements(p.IValidators)
    p.implements(p.ITemplateHelpers)
    p.implements(p.IPermissionLabels)
    p.implements(p.IClick)

    # IConfigurer

    def update_config(self, config):
        tk.add_template_directory(config, 'templates')

    # IConfigurable

    def configure(self, config):
        global _tables_ensured
        if _tables_ensured:
            return
        try:
            from ckanext.datashare import db
            db.ensure_tables()
            _tables_ensured = True
        except Exception:
            log.error("ckanext-datashare: could not initialize database "
                      "tables")

    # IActions

    def get_actions(self):
        from ckanext.datashare.logic import action
        return action.get_actions()

    # IAuthFunctions

    def get_auth_functions(self):
        from ckanext.datashare.logic import auth
        return auth.get_auth_functions()

    # IValidators

    def get_validators(self):
        from ckanext.datashare.logic import validators
        return validators.get_validators()

    # ITemplateHelpers

    def get_helpers(self):
        from ckanext.datashare import helpers
        return helpers.get_helpers()

    # IPermissionLabels

    def get_dataset_labels(self, dataset_obj):
        from ckanext.datashare import labels
        return labels.get_dataset_labels(dataset_obj)

    def get_user_dataset_labels(self, user_obj):
        from ckanext.datashare import labels
        return labels.get_user_dataset_labels(user_obj)

    # IClick

    def get_commands(self):
        from ckanext.datashare import cli
        return [cli.datashare]
