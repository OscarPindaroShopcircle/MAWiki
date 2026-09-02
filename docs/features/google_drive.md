# Google Drive Integration

Goal: let users pick files/folders from Google Drive and import them into a
Data Source. The backend downloads files one by one in the background.

## Architecture decision: user-based vs centralized

### Option A — Per-user OAuth tokens

Each user authorizes the app to access *their own* Google Drive. The backend
stores per-user `access_token` + `refresh_token` and impersonates the user when
calling the Drive API.

- Pro: respects Drive's native permissions — users only see what they already
  have access to.
- Con: store + refresh N tokens. Old users (logged in before Drive scopes were
  added) need a re-auth flow (`prompt=consent` + `access_type=offline` forces
  Google to re-issue a refresh token). More moving parts.

### Option B — Centralized service account

A single Google Cloud service account (or a dedicated Google account) with
access to a specific Shared Drive or folder. The backend uses these credentials
for *all* Drive API calls. No per-user token storage.

- Pro: one set of credentials. No re-auth for old users. Simpler.
- Con: everyone sees everything the service account can see. Need to scope the
  service account's permissions carefully (e.g. only the M&A folder).

## Google Picker vs server-side file browser

### Google Picker (client-side JS widget)

Runs in the browser with the *user's* Google identity — not the service
account's. This means:

- Users see whatever they personally have access to in Drive.
- You **cannot** restrict the Picker to only show what a service account can
  see.
- Workarounds:
  - Lock the Picker to a specific folder + hide navigation
    (`NAV_HIDDEN`). Requires all users to already have access to that folder.
  - Let users pick freely, then validate server-side: reject files the service
    account can't access. Leaky UX — users see files they can't import.

### Server-side file browser (custom UI)

The backend lists files using the service account's credentials. The frontend
renders a file/folder tree. Users only see what the service account can see.

- Pro: tight access control (e.g. only the M&A folder). Fits the existing htmx
  architecture. No client-side OAuth needed beyond what already exists.
- Con: need to build the tree UI (not huge — htmx-powered, server-rendered).

## Recommendation

For a Data Source that should pull from a shared org Drive (not personal
Drives), **Option B + server-side file browser** is the simpler, safer choice.
The service account's permissions *are* the access control — give it access to
the M&A folder and nothing else.

## Implementation outline (if we go with Option B + server-side browser)

1. **Google Cloud Console**: enable Drive API, create service account, share
   the M&A folder with the service account.
2. **Config**: add service account credentials to `config.yaml`.
3. **New module** `src/backend/drive/`:
   - `service.py` — `build_drive_client()`, `list_folder(folder_id)`,
     `download_file(file_id)`, `download_folder(folder_id)` (recursive).
   - `routes.py` — `GET /drive/browse?folder_id=...` (returns folder contents
     as JSON/HTML), `POST /drive/import` (receives file IDs, queues downloads).
4. **Frontend**: a JinjaX component that renders the folder tree with checkboxes.
   Selecting a folder selects all children. htmx drives the tree expansion.
5. **Storage**: downloaded files become `FileModel` rows, linked to the Data
   Source via the existing `source_files` table.
6. **Sync**: optionally, a background task that periodically checks for new
   files in the Drive folder and imports them.

## Open questions

- Should folders be imported recursively, or only top-level files?
- Google Docs/Sheets/Slides need export (e.g. `application/pdf`) — regular
  files use `alt=media` download. Handle both.
- Rate limiting: Google Drive API has quotas. Download one file at a time,
  respect `Retry-After` headers.
- Progress: how to show download progress in the UI? htmx polling or SSE.
