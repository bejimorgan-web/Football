# Football Streaming App

End-to-end football IPTV platform with three coordinated applications:
- `backend/` FastAPI API for IPTV ingestion, device-based access, metadata storage, and public match catalog delivery
- `desktop/` Electron admin app for provider sync, user management, football catalog editing, asset uploads, and stream approval
- `mobile/` Flutter client that registers each device, checks status, and displays approved football matches

## Feature Summary

### White-label multi-tenant SaaS
- The backend now supports multiple tenant brands on one shared platform
- Tenants have isolated branding, subscription plans, trial policy, users, metadata, approved matches, and assets
- Existing single-tenant installs continue to work through the built-in `default` tenant
- Tenant branding is available publicly through `GET /config/branding?tenant_id=...`
- Tenant admins can authenticate through `POST /tenant/login`

### Public API Resolver
- The backend now exposes `GET /api/config` so mobile and desktop clients can resolve the public API address dynamically.
- `API_BASE_URL` now defaults to:
  - `https://computatively-intelligent-arlena.ngrok-free.dev`
- The resolver response includes:
  - `apiBaseUrl`
  - `validUntil`
  - `serverMappings`
- Mobile apps now fetch and cache the resolver response on startup, which lets the API target stay stable even when the physical backend host changes.
- Master admins can update the resolver URL from the desktop app, and the backend persists it in `backend/data/api_config.json`.
- If a tenant or admin server URL is blank, the backend now falls back automatically to the default free ngrok endpoint and reports that fallback in the response payload.

### Central admin subscriptions
- Desktop administration now starts with a subscription-bound admin account
- Admin records are stored persistently in `backend/data/admins.json`
- Each admin subscription keeps:
  - `admin_id`
  - `name`
  - `email`
  - hashed password
  - `subscription_start_date`
  - `subscription_end_date`
  - `device_id`
  - hashed `api_token`
  - `branding_info`
  - `status`
  - server binding metadata
- Admin account endpoints include:
  - `POST /admin/register`
  - `POST /admin/login`
  - `GET /admin/validate`
  - `POST /admin/renew`
  - `GET /admin/list`
- Legacy compatibility endpoints still exist under `POST /admin/auth/*`
- Registration and renewal accept Stripe or PayPal placeholder fields so payment processing can be wired later without changing the flow
- A 3-day trial is supported through the `trial` plan

### Desktop auto-update system
- The backend now serves desktop releases from `backend/updates/`
- Master admins can publish installers and forced updates from the Electron `Platform Clients -> System Updates` section
- The desktop app:
  - checks for updates on authenticated startup
  - supports manual checks from the Help menu
  - rechecks every 6 hours in the background
  - downloads updates with progress feedback
  - blocks the dashboard when a mandatory update is published

### Mobile App Generator
- Platform clients can now generate tenant-branded Android APKs without opening Flutter or Android Studio
- The reusable Flutter build template lives in `mobile-template/`
- Tenant mobile branding is stored in:
  - `backend/data/tenants/<admin_id>/branding.json`
- Generated APKs, queue data, and build logs are stored in:
  - `backend/generated_apps/<admin_id>/`
  - `backend/build_queue/`
  - `backend/logs/mobile-builder/`
- Tenant mobile builds embed:
  - `tenant_id`
  - `server_url`
  - brand colors
  - package name
  - app name
- The desktop app includes a `Mobile App Builder` workspace where client admins can:
  - set app name
  - set package name
  - set primary and secondary colors
  - upload logo and splash assets
  - queue APK builds
  - track build status
  - download completed APK files
- Build protection now includes:
  - authenticated tenant ownership checks
  - per-tenant download isolation
  - build queue serialization
  - automatic version incrementing
  - daily build limit of 5 APK builds per tenant

### Tenant Branding Engine
- Each tenant now has one branding profile backed by `backend/data/tenant_branding.json`
- Generated branding assets are stored per tenant under:
  - `backend/storage/branding/<tenant_id>/`
  - `backend/storage/cdn/branding/<tenant_id>/`
- Uploading one PNG logo automatically generates:
  - `logo.png`
  - `desktop_icon.ico`
  - `mobile_icon.png`
  - `favicon.ico`
  - `favicon-16.png`
  - `favicon-32.png`
  - `apple-touch-icon.png`
  - `splash.png`
- Branding APIs include:
  - `GET /tenant/branding`
  - `POST /tenant/branding/upload-logo`
  - `POST /tenant/branding/rebuild-assets`
- Tenant admins can edit only their own branding, while `master` admins can override branding for any tenant intentionally.
- The desktop dashboard, mobile template, and packaged desktop build now consume the generated tenant asset set.

### Subscription enforcement
- The Electron app checks encrypted local session storage on startup
- If a stored admin token is valid, the dashboard opens
- If the token is missing or invalid, the desktop app opens login or registration
- If the subscription is expired, the desktop app opens a renewal screen and blocks the control panel
- Backend admin requests are rejected when:
  - the subscription is expired
  - the bound desktop `device_id` does not match
  - the bound streaming `server_id` does not match

### Device and server binding
- One admin subscription can control only one desktop device and one streaming server at a time
- The desktop device fingerprint is generated from machine and OS characteristics and stored locally as `device_id`
- The backend binds:
  - one `device_id` per admin subscription
  - one `server_id` per admin subscription
- Server transfer is limited through `POST /admin/reset-server`
- Device transfer is limited through `POST /admin/transfer-device`

### Device-based user system
- No registration flow in the mobile app
- First launch registers the device with `POST /device/register`
- Every catalog load checks `GET /device/status`
- Supported access states: `trial`, `active`, `expired`, `blocked`, `free`
- Trial duration: 3 days
- Subscription plans supported by admin tools: `6_months`, `1_year`
- Each subscription is tied to one device record in `backend/data/users.json`

### Football metadata system
- Nations, competitions, clubs, and uploaded logos are stored persistently
- Assets are saved under `backend/data/assets/` and served from `/assets/...`
- Approved stream mappings are stored in `backend/data/approved_streams.json`
- Provider URL refreshes keep admin-defined football metadata intact

### Admin controls
- IPTV provider manager and HLS preview in Electron
- Users panel with:
  - device id
  - device name
  - admin name
  - status
  - trial end
  - subscription end
  - last seen
- User actions:
  - rename
  - restore name
  - block
  - unblock
  - grant/remove free access
  - extend subscription
- Football catalog panel for nations, competitions, clubs, and logos
- Stream approval panel with nation, competition, home club, away club, and preview logos
- Analytics dashboard with live viewer monitoring, top matches, top competitions, country breakdowns, and charts

### Viewer analytics
- Mobile playback starts a viewer session with `POST /viewer/start`
- Leaving or pausing the player stops the session with `POST /viewer/stop`
- Live analytics are available through `/analytics/live` and `/analytics/streams`
- Historical analytics are available through top matches, top competitions, daily viewers, and country endpoints
- Viewer sessions are stored in `backend/data/viewers.json` and trimmed to a rolling history window

### Anti-piracy security
- Device lock metadata binds playback access to a known installation fingerprint
- Admins can reset the stored device lock with `POST /admin/users/reset-device`
- Mobile playback uses signed temporary stream URLs from `GET /streams/token/{stream_id}`
- `/play/{token}` validates token expiry, device access, and active stream session before redirecting
- IP and country changes are tracked in the user record
- Suspicious activity, VPN usage, insecure devices, and signature mismatches are logged in the security dashboard
- Active playback sessions are stored in `backend/data/sessions.json`
- Security events are stored in `backend/data/security_logs.json`

### Automatic backups
- The backend snapshots its persistent storage under `backend/data/`
- Scheduled backups run from `BACKUP_SCHEDULE` using APScheduler cron syntax
- Backup archives are stored in `backend/backups/` by default and rotated to keep only the latest `BACKUP_RETENTION`
- Backup logs are stored in `backend/data/backup_logs.json`
- Optional S3 upload is available when `CLOUD_BACKUP_ENABLED=true`

## Main API Endpoints

### Device and mobile
- `POST /device/register`
- `GET /device/status`
- `POST /viewer/start`
- `POST /viewer/stop`
- `GET /streams/catalog`
- `GET /streams/approved`
- `GET /streams/token/{stream_id}`
- `GET /play/{token}`

### Analytics
- `GET /analytics/live`
- `GET /analytics/streams`
- `GET /analytics/top-matches`
- `GET /analytics/top-competitions`
- `GET /analytics/daily-viewers`
- `GET /analytics/countries`

### Admin
- `POST /admin/register`
- `POST /admin/login`
- `GET /admin/validate`
- `POST /admin/renew`
- `GET /admin/list`
- `POST /tenant/login`
- `GET /tenant/profile`
- `GET /config/branding`
- `GET /admin/config`
- `POST /admin/config`
- `POST /admin/refresh`
- `GET /admin/status`
- `GET /admin/users`
- `GET /admin/users/online`
- `POST /admin/users/block`
- `POST /admin/users/unblock`
- `POST /admin/users/free-access`
- `POST /admin/users/remove-free-access`
- `POST /admin/users/extend-subscription`
- `POST /admin/users/rename`
- `POST /admin/users/restore-name`
- `POST /admin/users/reset-device`
- `POST /admin/users/set-vpn-policy`
- `GET /admin/security`
- `GET /admin/tenants`
- `POST /admin/tenants`
- `GET /admin/branding`
- `POST /admin/branding`
- `GET /admin/backup/status`
- `POST /admin/backup/run`
- `POST /mobile/build`
- `GET /mobile/build/status/{build_id}`
- `GET /mobile/build/history`
- `GET /mobile/download/{build_id}`
- `GET/POST/DELETE /admin/nations`
- `GET/POST/DELETE /admin/competitions`
- `GET/POST/DELETE /admin/clubs`
- `POST /admin/assets/upload`
- `GET /admin/streams`
- `GET /admin/streams/approved`
- `POST /admin/streams/approve`
- `POST /admin/streams/remove?stream_id=...`

## Persistent Storage

- `backend/data/config.json`
- `backend/data/users.json`
- `backend/data/football_metadata.json`
- `backend/data/approved_streams.json`
- `backend/data/viewers.json`
- `backend/data/sessions.json`
- `backend/data/security_logs.json`
- `backend/data/backup_logs.json`
- `backend/data/tenants.json`
- `backend/data/admins.json`
- `backend/data/assets/`

## Migration Guide

1. Keep existing data files in place.
2. Start the updated backend once so it creates `backend/data/tenants.json`.
3. Existing users, metadata, and approved streams are treated as part of the `default` tenant.
4. Create additional tenants from `POST /admin/tenants` or the Electron tenant controls.
5. Point branded mobile builds or runtime tenant settings at the correct `tenant_id`.

## Mobile Builder Workflow

1. Sign in to the Electron desktop app as a platform client.
2. Open `Mobile App Builder`.
3. Set the tenant app name, Android package name, colors, and branding assets.
4. Click `Generate APK`.
5. The backend copies `mobile-template/`, injects tenant values, queues the build, and runs:
   - `flutter clean`
   - `flutter pub get`
   - `flutter build apk --release`
6. The finished APK is saved under `backend/generated_apps/<admin_id>/`.
7. Download the APK from the completed build row in the desktop app.

## Branding Workflow

1. Save tenant branding values from the desktop dashboard.
2. Upload one PNG logo through the tenant branding API or the desktop branding tools.
3. The backend resizes the logo to a 1024x1024 master asset and regenerates all icons plus the splash screen.
4. Generated assets are published under the tenant branding storage path and mirrored to the branding CDN path.
5. Mobile builds copy the tenant `logo.png`, `mobile_icon.png`, and `splash.png` into the Flutter workspace automatically.
6. Desktop packaging can load `backend/storage/branding/<tenant_id>/desktop_icon.ico` before `electron-builder` runs.

## Forced Tenant Linking In Generated Apps

- Each generated mobile build embeds the tenant identity in `lib/config/app_config.dart`.
- The compiled APK includes the tenant's:
  - `tenant_id`
  - `server_url`
- This keeps the branded app pointed at the correct backend and tenant scope without manual Flutter edits.

## Backup Configuration

Set these backend environment variables to enable scheduled backups:

- `BACKUP_SCHEDULE`: cron expression, default `0 3 * * *`
- `BACKUP_PATH`: local directory for archives, default `backend/backups`
- `BACKUP_RETENTION`: number of archives to keep, default `7`
- `CLOUD_BACKUP_ENABLED`: `true` or `false`
- `S3_BUCKET`: target bucket name for cloud uploads
- `S3_PREFIX`: optional folder prefix inside the bucket, default `football-iptv-backups`
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`: optional AWS credentials when not provided by the host environment

## Backup Restore

1. Stop the backend service.
2. Pick a backup from `backend/backups/` or download one from S3.
3. Extract the archive so it restores the `data/` folder contents.
4. Replace `backend/data/` with the extracted snapshot.
5. Start the backend again.

## Manual Backup

Run a backup from the admin API:

```bash
curl -X POST http://localhost:8000/admin/backup/run
```

Or from the backend folder:

```bash
cd backend
python -m app.backup
```

## Local Setup

### Backend
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Set `API_BASE_URL` in `backend/.env.example` or your host environment if your ngrok dev domain differs from the default.

For ngrok-based deployments, open the ngrok dashboard and copy the dev domain shown under `Domains`, then set `API_BASE_URL` to that value if it differs from the bundled default.

Leave the server URL blank when you want the platform to use the default ngrok endpoint automatically. Override it manually only when you move to another public entrypoint or a different reserved ngrok domain.

### Desktop
```bash
cd desktop
npm install
npm start
```

### Mobile
```bash
cd mobile
flutter pub get
flutter run
```

## Recommended Local Flow

1. Start the FastAPI backend.
2. Start the Electron desktop app.
3. Register an admin subscription or sign in with an existing admin account.
4. If the subscription is expired, renew it from the startup renewal screen before the dashboard opens.
5. Add or activate an IPTV provider, then click `Sync Active Provider`.
6. Create nations, competitions, clubs, and upload logos.
7. Approve provider streams into football matches.
8. Launch the Flutter app on a device or emulator.
9. The mobile app will register the device, check access, and then open the football match catalog.
