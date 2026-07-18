# IHP-WINS data sharing levels — proposal for discussion with UNESCO

*Draft prepared for review before final implementation of the categories
(Terms of Reference, item iii.1). The categories below are already
implemented behind a configuration switch, so renaming, removing or adding
one only requires a configuration change — no data migration.*

## Proposed categories

Every dataset carries a **Data sharing level** field. Datasets keep the
current open behaviour unless a data provider explicitly selects another
level. "Authorized members" always means: members of the organization that
owns the dataset, individual collaborators invited by the provider, and —
where noted — organizations or initiatives the dataset was shared with.

| Level | Who finds it in search | Who sees the description (metadata) | Who can preview the data | Who can download the data |
|---|---|---|---|---|
| **Public** (default) | everyone | everyone | everyone | everyone |
| **Confidential** | only the data provider | only the data provider | only the data provider | only the data provider |
| **Findable** | everyone | everyone | authorized members | authorized members |
| **Viewable** | everyone | everyone | everyone | authorized members |
| **Restricted** | everyone¹ | everyone¹ | selected organizations | selected organizations |

¹ Configurable: a restricted dataset can instead be fully hidden from
non-authorized users (like Confidential). **Open question 1** below.

### Level definitions

- **Public** — the current IHP-WINS behaviour, unchanged.
- **Confidential** — *"data exclusively manageable by the data provider"*.
  The dataset is invisible in search, its page is not reachable, and its
  data cannot be accessed by anyone outside the providing organization
  (individual collaborators explicitly invited by the provider keep
  access). Sharing with other organizations is deliberately not possible
  at this level.
- **Findable** — *"findable but not accessible"*. The dataset appears in
  the catalogue with its full description, so the existence of the data is
  transparent, but the resource files are hidden and cannot be opened or
  downloaded. Useful to signal "this data exists — contact the provider".
- **Viewable** — *"viewable but not downloadable"*. Visitors can open the
  dataset and preview the data online (maps, tables, PDF preview), but the
  file itself cannot be downloaded in bulk.
- **Restricted** — *"accessible to selected organisations within a country
  or transboundary setting"*. The provider shares the dataset with specific
  organizations and/or initiatives (e.g. the Gulf Country Platform
  members); their members get full access (view + download, and optionally
  edit). Everyone else sees it as Findable (default) or not at all.

## Sharing rights (Terms of Reference, item ii)

Independent of the level, a provider can grant, per dataset:

- **A person** — CKAN's standard "collaborator" mechanism (already active).
- **An organization or an initiative** — new: every member of that entity
  gets read access; with "can edit", its admins/editors can also update
  the dataset. This is the building block for transboundary platforms.

## Honest limitations (accepted and documented)

- A preview always delivers *some* rendered data to the browser; "Viewable"
  prevents bulk download of the original file, it is not DRM.
- Resources that are external links (not files uploaded to IHP-WINS) cannot
  be blocked server-side; the button is hidden but the external URL is not
  under our control.
- Files of gated datasets should not be loaded into the tabular DataStore
  preview until its access chain is finished (planned, phase F4/F5).

## Open questions for UNESCO

1. **Restricted datasets for outsiders**: should they appear in search
   with metadata only (transparent, recommended) or be completely hidden?
2. **Request access**: should a "Request access" button on Findable /
   Restricted datasets create a request the provider can approve (planned
   as a follow-up phase)? Who should approve — the providing organization's
   admins, or also UNESCO?
3. **Naming**: are "Public / Confidential / Findable / Viewable /
   Restricted" the final labels? (Renaming is configuration only.)
4. **Scope**: levels currently apply to the whole dataset (all its files).
   Is per-file flagging needed for any concrete use case?
