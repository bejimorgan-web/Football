# Desktop IPTV Control Panel

Electron admin application for the football streaming workflow.

## Features

- SQLite-backed IPTV provider manager
- Startup authentication gate with separate login and registration screens
- Expired-subscription renewal screen that blocks the dashboard until `/admin/renew` succeeds
- Encrypted local storage for the desktop admin session using `electron-store`
- Automatic validation of the stored admin `api_token` before opening the control panel
- One-server-per-subscription licensing with server binding and device binding
- Admin-scoped local provider storage so IPTV provider lists do not mix between accounts
- Single active provider sync to the FastAPI backend
- HLS.js stream preview for source IPTV feeds
- Branding panel for app name, uploaded logo/icon assets, and tenant theme colors
- Auto-managed local FastAPI backend using the bundled Python runtime when the backend URL is local
- One-click backup button that runs the backend backup script through the embedded or portable Python runtime
- Backup settings panel for:
  - local backup folder
  - daily / weekly / monthly schedule
  - retention
  - optional S3 sync
- Backup management list with restore buttons and task logs
- User management panel:
  - total users
  - trial users
  - active users
  - blocked users
  - live viewers
- Per-device actions:
  - edit admin name
  - restore original device name
  - block / unblock
  - grant / remove free access
  - extend subscription
- Football catalog panel:
  - nations
  - competitions
  - clubs
  - logo uploads
- Stream approval panel with nation, competition, home club, away club, and logo preview before saving
- Analytics dashboard:
  - live viewers
  - active streams
  - top matches today
  - top competitions today
  - countries
  - charts for daily viewers and competition popularity
- Security dashboard:
  - flagged devices
  - VPN users
  - suspicious IP changes
  - blocked devices
  - security logs

## Authentication Flow

1. Launch the desktop app.
2. Before login, the app shows a minimal menu only:
   - `File -> Exit`
   - `Help -> About`
   - `Help -> Documentation`
3. The main process checks encrypted local storage for:
   - `api_token`
   - `device_id`
   - `server_id`
4. If the token is valid, the app validates it with the backend and opens the admin dashboard.
5. After login or renewal, the app swaps the menu to the full dashboard menu at runtime.
6. If no valid token is present, the app opens:
   - `desktop/src/ui/auth/login.html`
   - `desktop/src/ui/auth/register.html`
7. If the backend reports an expired subscription, the app opens:
   - `desktop/src/ui/auth/renewal.html`
8. After successful authentication or renewal the desktop app registers the current streaming server if needed and then loads the main control panel.

## Device And Server Binding

- A subscription is bound to one desktop `device_id`.
- A subscription is also bound to one streaming `server_id`.
- The desktop app includes the following headers on protected admin requests:
  - `Authorization: Bearer <api_token>`
  - `X-Device-Id: <device_id>`
  - `X-Server-Id: <server_id>`
- The backend rejects requests when:
  - the subscription is expired
  - the desktop device does not match
  - the server does not match
- The encrypted local session now stores:
  - `api_token`
  - `device_id`
  - `server_id`
  - admin identity fields
  - subscription state

## Logout Behavior

- The File menu now includes `Logout`.
- Logging out:
  - clears the encrypted `electron-store` session with `store.clear()`
  - removes the stored `api_token`, `device_id`, and `server_id`
  - stops dashboard polling in the renderer
  - returns the window to `login.html`

## Tenant Isolation And Migration

- Desktop provider definitions are now isolated per authenticated admin in the local SQLite store.
- Existing shared desktop provider rows are migrated one time into the first authenticated admin account after the update.
- After that migration:
  - the existing admin keeps the previous IPTV provider list
  - newly registered admins start with an empty provider list and empty dashboard data

## First-Time Setup Wizard

- After the first authenticated launch, the dashboard can show a setup card until `setup_completed` is marked true in the tenant meta file.
- The setup flow follows:
  1. Register server
  2. Add IPTV provider
  3. Add league
  4. Publish mobile app
- Tenant setup state is stored in:
  - `backend/data/tenants/<admin_id>/meta.json`
- The setup card also exposes the tenant mobile API token and bound server id used by the mobile app bootstrap.

## Tenant-Scoped Mobile API

- The mobile app now boots from `GET /config/branding?tenant_id=...` and receives tenant mobile credentials from the branding payload.
- Subsequent mobile requests send:
  - `X-Api-Token`
  - `X-Tenant-Id`
  - `X-Device-Id`
  - `X-Server-Id`
- This keeps catalog, streams, and viewer tracking isolated to the authenticated tenant and its bound device/server combination.

## Install And Subscription Tracking

- After successful login and subscription validation, the desktop app reports an install event to the backend analytics API.
- After subscription renewal, the desktop app reports a subscription event.
- Tracking endpoints used by the desktop app:
  - `POST /analytics/register-install`
  - `POST /analytics/register-subscription`
  - `GET /analytics/install-stats`
- The tracked install payload contains:
  - `admin_id`
  - `device_id`
  - `app_version`
  - `timestamp`

## Platform Clients Dashboard And Updates

- Master admins now have a dedicated `System Updates` section inside the Platform Clients workspace.
- The master update panel lets you:
  - upload a desktop installer
  - set the semantic version
  - enter release notes
  - toggle mandatory updates
  - review version history
- Supported installer types:
  - `.exe`
  - `.dmg`
  - `.AppImage`
- Maximum installer size:
  - `500MB`
- Published update metadata is served from the backend at:
  - `GET /updates/latest`
  - `GET /updates/history`
  - `GET /updates/download/{filename}`
  - `POST /updates/publish`
- Only `master` admins can publish updates.
- The desktop checks for updates:
  - after a successful authenticated launch
  - from `Help -> Check for Updates`
  - from `Branding -> Server Management -> Check Desktop Updates`
  - automatically every 6 hours in the background
- Update UI states now include:
  - `Checking for updates...`
  - `Update available`
  - `Downloading update...`
  - `Restart to install`
- The dashboard footer and sidebar now show the current desktop version.

## Mobile App Builder

- Client admins now have a dedicated `Mobile App Builder` section in the sidebar.
- The builder form lets each tenant configure:
  - app name
  - Android package name
  - backend server URL
  - primary and secondary colors
  - logo upload
  - splash upload
- Clicking `Generate APK` does all of the following from the desktop UI:
  - uploads branding assets
  - saves tenant branding to the backend
  - starts a queued mobile build job
  - begins polling build status automatically
- Build states shown in the UI:
  - `Queued`
  - `Building`
  - `Completed`
  - `Failed`
- The progress card shows:
  - current status
  - progress percentage
  - generated version
  - artifact name
  - build error text when a build fails
- Completed jobs expose a `Download APK` action that securely fetches the tenant's generated file from the backend.

## Public API Base URL

- The backend settings panel now shows both:
  - the local desktop `Backend API`
  - the public `API Base URL`
- `Backend API` is the address the Electron app talks to directly.
- `Public API Base URL` is the resolver-backed address exposed to mobile clients and public config payloads.
- When a master admin saves settings, the desktop syncs the public API base to the backend resolver endpoint so generated mobile config stays aligned.
- The default public resolver target is:
  - `https://computatively-intelligent-arlena.ngrok-free.dev`
- If the backend URL field is left blank, the desktop now saves and uses that default ngrok domain automatically instead of clearing the value.
- Override the backend URL manually only when you intentionally move the public API to another domain or reserved ngrok endpoint.

## Mobile Build Workflow

1. Sign in as a client admin.
2. Open `Mobile App Builder`.
3. Update the tenant branding values if needed.
4. Upload a logo or splash asset.
5. Click `Generate APK`.
6. Wait for the queued build to move to `Completed`.
7. Click `Download APK`.

## Forced Updates

- If the published backend manifest sets `mandatory: true`, the Electron app blocks dashboard interaction with a full-screen update overlay.
- Mandatory updates remove the `Remind Later` path and immediately start the download flow.
- After the installer is downloaded:
  - Windows uses a silent installer launch when possible
  - macOS opens the downloaded installer package and exits the app
  - Linux launches the downloaded AppImage and exits the app
- When `electron-updater` is available in the installed dependencies, the desktop uses it first and falls back to the manual installer flow if needed.

## Platform Clients System

- The desktop header now shows:
  - `Welcome, {client_name}`
  - subscription status
  - plan
  - bound server id
- Master users can manage platform clients from the sidebar table with:
  - block / unblock
  - delete
  - extend trial days
  - reset server binding

## Branding Uploads

- Branding assets now upload through backend APIs instead of manual URL entry:
  - `POST /admin/branding/upload_logo`
  - `POST /admin/branding/upload_icon`
  - `POST /admin/branding/upload_splash`
- Uploaded files are stored under:
  - `backend/data/assets/branding/<admin_id>/`
- The returned branding URLs are automatically included in `GET /config/branding` for desktop and mobile clients.

## Tenant Branding Engine

- One tenant logo can now drive the full branding set for desktop, mobile, and dashboard surfaces.
- Generated tenant assets are served from:
  - `backend/storage/branding/<tenant_id>/`
  - `backend/storage/cdn/branding/<tenant_id>/`
- The dashboard branding payload is available from:
  - `GET /tenant/branding`
- Desktop runtime branding now applies:
  - app title
  - logo
  - theme colors
  - favicon
- Packaged desktop builds can preload tenant installer icons through the `beforeBuild` hook.
- Set `TENANT_BRANDING_ID=<tenant_id>` before running `electron-builder` if you want a tenant-specific installer icon set applied during packaging.

## Desktop Licensing

- The desktop app now uses an encrypted locally stored license token in the same protected Electron store as the admin session.
- On first authenticated launch:
  - the app fetches or creates the admin's assigned license key
  - shows the license activation screen if the current machine has not been activated yet
  - binds the returned license token to the current device fingerprint
- On every launch:
  - the app validates the stored license token against the backend using the current `device_id`
  - invalid, revoked, expired, or mismatched licenses are redirected back to the license activation screen
- The activation UI lives in `desktop/src/ui/auth/license.html`.

## Run

```bash
cd desktop
npm install
npm start
```

When `backendUrl` points to `http://127.0.0.1:8000` or `http://localhost:8000`, the Electron main process now starts the bundled backend automatically if it is not already running.

## Backup Runtime

For packaged builds, place the portable Python runtime under one of these layouts:

- Windows:
  - `desktop/runtime/python/windows/python.exe`
  - `desktop/runtime/python/python.exe`
  - `desktop/runtime/python/Scripts/python.exe`
- macOS:
  - `desktop/runtime/python/macos/bin/python3`
- Linux:
  - `desktop/runtime/python/linux/bin/python3`

During development, the app can also use `backend/.venv/Scripts/python.exe` on Windows or `backend/.venv/bin/python3` on macOS and Linux.

The runtime must include the backend dependencies from `backend/requirements.txt`.

Prepare the runtime before packaging:

Windows:

```powershell
cd desktop
.\scripts\setup-portable-python.ps1
```

macOS or Linux:

```bash
cd desktop
./scripts/setup-portable-python.sh macos
./scripts/setup-portable-python.sh linux
```

The Windows script downloads the official embeddable Python build from `python.org`, enables `site-packages`, installs `pip`, and installs `backend/requirements.txt`. The macOS and Linux script builds an isolated runtime under `desktop/runtime/python/<platform>/`.

## Packaging And Installers

Install dependencies:

```bash
cd desktop
npm install
```

Create an unpacked application bundle:

```bash
npm run package
```

Generate installers:

```bash
npm run make
npm run make:win
npm run make:mac
npm run make:linux
```

The Electron builder configuration packages:

- the Electron admin frontend
- `desktop/runtime/`
- `backend/app`
- `backend/data`
- backend requirements metadata

The packaged app resolves the portable Python runtime from Electron's `resources/` directory first and uses it to launch the backend.

## Starting The Packaged App

1. Build the portable runtime for the target OS.
2. Run one of the `make` scripts.
3. Open the generated installer or unpacked bundle from `desktop/dist/`.
4. Launch the desktop app.
5. If the configured backend URL is local, the app starts `uvicorn app.main:app` from the bundled runtime automatically.

No external Python installation is required for packaged end users.

## Backup Usage

- Click `Backup Now` in the top bar to create an immediate backup.
- Open the `Backups` section to:
  - change the local backup folder
  - enable or disable scheduled backups
  - set retention
  - review backup logs
  - restore an archive back into `backend/data`

Scheduled backups are managed by the Electron main process and continue while the desktop admin app is open.

## Expected Backend

The desktop app talks to the FastAPI backend and expects:
- `/admin/register`
- `/admin/login`
- `/admin/validate`
- `/admin/renew`
- `/admin/config`
- `/admin/refresh`
- `/admin/users`
- `/admin/users/online`
- `/admin/nations`
- `/admin/competitions`
- `/admin/clubs`
- `/admin/assets/upload`
- `/admin/streams`
- `/admin/streams/approved`
- `/admin/streams/approve`
- `/analytics/live`
- `/analytics/streams`
- `/analytics/top-matches`
- `/analytics/top-competitions`
- `/analytics/daily-viewers`
- `/analytics/countries`
- `/admin/users/reset-device`
- `/admin/users/set-vpn-policy`
- `/admin/security`
- `/tenant/login`
- `/tenant/profile`
- `/config/branding`
- `/admin/tenants`
- `/admin/branding`

## Backup Tests

Run the desktop backup helper tests with:

```bash
cd desktop
npm run test:backup
npm run test:packaging
```
