# ckanext-datashare

Dataset-level access flags and org/group-level data sharing for the UNESCO
IHP-WINS portal (CKAN 2.10).

## What it does

**Access levels** — a dataset-level `access_level` field (added to the
schemingdcat UNESCO schemas) with configurable categories:

| Level | Search (anon) | Dataset page | Resources/preview | Download |
|---|---|---|---|---|
| `public` (default) | yes | yes | yes | yes |
| `confidential` | invisible | denied | no | no |
| `findable` | yes | yes (metadata only) | no | no |
| `viewable` | yes | yes | yes | **no** |
| `restricted` | configurable | full for grantees | per grant | per grant |

Datasets without the field behave exactly as before (`public`).

**Entity grants** — the org/group-level analogue of CKAN's native per-user
collaborators: share a dataset with a whole organization or initiative
(group) with `read` or `edit` capacity (table `datashare_grant`,
auto-created on plugin load). Individual people keep using CKAN's native
collaborators, which stay fully supported.

## Enforcement layers

- `IPermissionLabels` (search + `package_show` auth at once) for
  `confidential` and `restricted` in hidden mode. **CKAN uses exactly one
  IPermissionLabels implementation** — do not enable another plugin that
  provides it.
- Chained `resource_show` / `package_update` auth (chained on purpose:
  schemingdcat registers plain overrides; a second plain override aborts
  startup).
- `datashare_resource_download` auth: separates "may preview" from "may
  fetch the file" (used by the download views).

## Config

```ini
# Categories offered in the dataset form (pending final UNESCO wording)
ckanext.datashare.levels = public confidential findable viewable restricted
# What unauthorized users see for 'restricted': findable | hidden
ckanext.datashare.restricted_unauthorized_behavior = findable
# Resource view types still rendered for 'viewable' datasets
ckanext.datashare.viewable_allowed_view_types = pdf_view image_view text_view video_view
```

## API

- `datashare_grant_create` `{package_id, grantee_type: org|group, grantee_id, capacity: read|edit}`
- `datashare_grant_delete` `{package_id, grantee_type, grantee_id}`
- `datashare_grant_list` `{package_id}` (managers only)
- `datashare_access_check` `{id}` (anyone; returns the caller's capabilities)

## Install (IHP-WINS)

1. Dockerfile: `pip install -e git+https://github.com/pabrojast/ckanext-datashare#egg=ckanext-datashare`
2. `production.ini`: add `datashare` to `ckan.plugins` **after `cloudstorage`**
   (blueprint ties resolve LIFO — the later plugin wins; datashare must win
   the `/download/<filename>` rule for the download gate to run).
3. `ckan search-index rebuild` after first deploy (labels must reach Solr).

## Tests

```bash
bash scripts/run-ckan-tests.sh   # docker: plugin-load smoke + pytest suite
```

## Known limits (by design, documented for UNESCO)

- Link-type resources (`url_type != upload`) point at external URLs and are
  not gateable server-side; the UI hides the button only.
- Previews always deliver renderable bytes; `viewable` limits *bulk*
  download, it is not an exfiltration-proof DRM.
- Resources of gated datasets should not be pushed to the DataStore until
  the DataStore auth chain lands (phase F4).
