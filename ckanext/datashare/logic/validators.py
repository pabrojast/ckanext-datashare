# encoding: utf-8
"""Validators for ckanext-datashare."""
import ckan.plugins.toolkit as tk

from ckanext.datashare import core


def datashare_access_level_validator(value):
    """Accept only a configured access level (empty = public default)."""
    if value in (None, ''):
        return value
    if value not in core.configured_levels():
        raise tk.Invalid(
            tk._('Invalid access level. Must be one of: %s')
            % ', '.join(core.configured_levels()))
    return value


def get_validators():
    return {
        'datashare_access_level_validator': datashare_access_level_validator,
    }
