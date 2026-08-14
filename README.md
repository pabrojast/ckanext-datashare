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

**One visibility control** — the dataset form has no Public/Private select any
more: `access_level` is the single control, and CKAN's core `private` flag is
*derived* from it by chained `package_create`/`package_update`:

```
private = (access_level == 'confidential')
```

`confidential` is the only level that means "not published" in CKAN's own
terms, so it is the only one that sets `private=True`; every other level keeps
the dataset in the public index and gates the resources instead. The
derivation only fires when the caller actually sends `access_level`, so
harvesters, partial `package_patch` calls and dataset types without the field
keep CKAN's stock behaviour. **To make a dataset private through the API, send
`access_level: confidential` rather than `private: true`** — a `private` sent
alongside `access_level` is overwritten.

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
- Chained `package_create` / `package_update` actions that derive `private`
  from the level. Chained rather than plain for the same reason as the auth
  functions, and because schemingdcat already chains these two.
  `IPackageController` has no `before_dataset_create/update` hook in CKAN
  2.10, so a chained action is the only pre-validation entry point.

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
4. **Immediately after the deploy that removes the Public/Private select**, run
   the backfill below. Until it has run, editing a dataset that was made
   private *before* `access_level` existed reads its level as `public` and
   publishes it.

## Migrations

```bash
ckan -c /app/production.ini datashare backfill-access-level --dry-run
ckan -c /app/production.ini datashare backfill-access-level
```

Stamps `access_level = confidential` on every active dataset that is
`private=True` and carries no level, preserving exactly the visibility it has
today, then reindexes those datasets. Idempotent, so it is safe to re-run (and
safe to wire into `afterinit.d/` if you would rather not rely on running it by
hand — mind that the first run reindexes one dataset at a time, which can be
slow on a large catalogue).

It also prints, in yellow, any dataset that is `private=True` while carrying a
*non*-confidential level: those are genuinely ambiguous and **will become
public on their next edit**, so review them before or right after the deploy.

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
- The organization "Make public/private" bulk buttons
  (`organization/bulk_process.html` → `bulk_update_private`) write `private`
  with direct SQL and never reach our chained actions, so they can leave
  `private` out of step with the level until the dataset is next edited.
