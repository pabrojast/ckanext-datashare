# encoding: utf-8
"""Template helpers for ckanext-datashare.

The theme guards every call with ``'datashare_...' in h`` so its templates
keep working when this plugin is not loaded.
"""
import logging

import ckan.plugins.toolkit as tk

from ckanext.datashare import core

log = logging.getLogger(__name__)

# Scheming accepts dict labels and resolves them per request language.
LEVEL_LABELS = {
    core.LEVEL_PUBLIC: {
        'en': 'Public', 'es': 'Público', 'fr': 'Public'},
    core.LEVEL_CONFIDENTIAL: {
        'en': 'Confidential (only the data provider)',
        'es': 'Confidencial (solo el proveedor de los datos)',
        'fr': 'Confidentiel (uniquement le fournisseur des données)'},
    core.LEVEL_FINDABLE: {
        'en': 'Findable (metadata only, data not accessible)',
        'es': 'Localizable (solo metadatos, datos no accesibles)',
        'fr': 'Trouvable (métadonnées seulement, données non accessibles)'},
    core.LEVEL_VIEWABLE: {
        'en': 'Viewable (preview only, not downloadable)',
        'es': 'Visualizable (solo vista previa, sin descarga)',
        'fr': 'Visualisable (aperçu seulement, pas de téléchargement)'},
    core.LEVEL_RESTRICTED: {
        'en': 'Restricted (selected organizations only)',
        'es': 'Restringido (solo organizaciones seleccionadas)',
        'fr': 'Restreint (organisations sélectionnées uniquement)'},
}


def _current_user_obj():
    try:
        return tk.g.userobj
    except (AttributeError, RuntimeError, TypeError):
        return None


def datashare_access_level_choices(field=None):
    """scheming ``choices_helper`` for the access_level select."""
    return [
        {'value': level,
         'label': LEVEL_LABELS.get(level, level.replace('_', ' ').title())}
        for level in core.configured_levels()
    ]


def datashare_access_level(pkg):
    return core.dataset_level(pkg)


def datashare_access(pkg):
    """Full AccessResult dict for the current user (for templates)."""
    if not pkg:
        return None
    try:
        return dict(core.get_access(pkg, user=_current_user_obj())._asdict())
    except Exception:
        # A template must never 500 because of a gating hiccup; fall back to
        # most restrictive-but-visible so nothing leaks via the UI.
        log.exception("datashare: access helper failed")
        return dict(core.policy.access_for(
            core.dataset_level(pkg), False)._asdict())


def datashare_can_view_resources(pkg):
    access = datashare_access(pkg)
    return bool(access and access['can_view_resources'])


def datashare_can_download(pkg, res=None):
    """May the current user download files of this dataset?

    ``res`` is accepted for template convenience; link-type resources
    (url_type != upload) are not gateable server-side, but the button is
    hidden for consistency anyway.
    """
    access = datashare_access(pkg)
    return bool(access and access['can_download'])


def datashare_pending_access_count():
    """Pending access requests the current user may review (approvals bell)."""
    user = _current_user_obj()
    if not user or getattr(user, 'is_anonymous', False):
        return 0
    try:
        return tk.get_action('datashare_access_request_count')(
            {'user': user.name, 'auth_user_obj': user}, {})
    except Exception:
        log.exception("datashare: pending access count failed")
        return 0


def datashare_my_pending_request(pkg):
    """The current user's pending access request on this dataset, or None."""
    user = _current_user_obj()
    if not user or not pkg or getattr(user, 'is_anonymous', False):
        return None
    try:
        from ckanext.datashare import db
        pkg_id = pkg.get('id') if isinstance(pkg, dict) else pkg.id
        return db.request_dictize(db.pending_request_for(pkg_id, user.id))
    except Exception:
        log.exception("datashare: pending request lookup failed")
        return None


def datashare_show_request_access(pkg):
    """Should the 'Request access' CTA appear for the current user?"""
    user = _current_user_obj()
    if not user or getattr(user, 'is_anonymous', False):
        return False
    access = datashare_access(pkg)
    return bool(access and not access['can_download']
                and access['level'] != core.LEVEL_CONFIDENTIAL)


def get_helpers():
    return {
        'datashare_access_level_choices': datashare_access_level_choices,
        'datashare_access_level': datashare_access_level,
        'datashare_access': datashare_access,
        'datashare_can_view_resources': datashare_can_view_resources,
        'datashare_can_download': datashare_can_download,
        'datashare_pending_access_count': datashare_pending_access_count,
        'datashare_my_pending_request': datashare_my_pending_request,
        'datashare_show_request_access': datashare_show_request_access,
    }
