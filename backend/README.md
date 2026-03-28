# Backend (FastAPI)

FastAPI backend for IPTV ingestion, football metadata management, approved stream persistence, and device-based access control.

## Admin Authentication And Licensing

- Desktop admins now authenticate at application startup through:
  - `POST /admin/register`
  - `POST /admin/login`
  - `GET /admin/validate`
  - `POST /admin/renew`
- Compatibility routes remain available under:
  - `POST /admin/auth/register`
  - `POST /admin/auth/login`
  - `GET /admin/auth/validate`
- Each admin subscription is bound to:
  - one desktop `device_id`
  - one streaming `server_id`
- Server binding endpoints:
  - `POST /admin/register-server`
  - `POST /admin/reset-server`
- Device transfer endpoint:
  - `POST /admin/transfer-device`
- Protected desktop admin and analytics requests must present:
  - `Authorization: Bearer <api_token>`
  - `X-Device-Id: <device_id>`
  - `X-Server-Id: <server_id>` after server registration
- Requests are rejected when:
  - the subscription is expired
  - the desktop device does not match the bound `device_id`
  - the streaming server does not match the bound `server_id`
- Admin subscriptions are stored in `data/admins.json` with:
  - UUID admin id
  - hashed password
  - hashed API token
  - subscription dates and status
  - branding info
  - bound device and server metadata
- Registration and renewal accept payment placeholders for `stripe` and `paypal` so gateway integration can be layered in later.

## Tenant Data Isolation

- Admin-owned catalog and stream data no longer live in shared global files.
- Each admin now gets a dedicated tenant data folder:
  - `data/tenants/<admin_id>/providers.json`
  - `data/tenants/<admin_id>/approved_streams.json`
  - `data/tenants/<admin_id>/football_metadata.json`
  - `data/tenants/<admin_id>/analytics.json`
- New admin registrations create those files with empty defaults so new subscriptions start with an empty provider list, empty approved streams, and an empty football catalog.
- Public mobile APIs still use `tenant_id`, but the backend resolves that tenant back to its owning `admin_id` before loading catalog, provider, and analytics data.

## Tenant-Scoped Mobile API

- Mobile requests are now tenant-scoped and validated against the owning admin subscription.
- The branding bootstrap response includes:
  - `mobile_auth.api_token`
  - `mobile_auth.server_id`
- Mobile requests must send:
  - `X-Api-Token`
  - `X-Tenant-Id`
  - `X-Device-Id`
  - `X-Server-Id`
- The backend also cross-checks the same `tenant_id`, `device_id`, and `server_id` values from query parameters or payloads where relevant.
- If token, tenant, device, or server validation fails, the backend returns `403 Forbidden`.
- Tenant-scoped mobile enforcement now applies to:
  - `POST /device/register`
  - `GET /device/status`
  - `GET /streams/catalog`
  - `GET /streams/approved`
  - `GET /streams/leagues`
  - `GET /streams/token/{stream_id}`
  - `POST /viewer/start`
  - `POST /viewer/stop`

## Device And Server Binding Enforcement

- Each admin subscription stays bound to one desktop `device_id` and one streaming `server_id`.
- Desktop admin validation still happens through bearer-token protected admin routes.
- Mobile APIs additionally validate against the tenant-scoped mobile token plus the same bound `device_id` and `server_id`.
- Use `POST /admin/validate-device` to verify the current desktop binding before sensitive actions or troubleshooting.

## First-Time Setup Wizard

- Every tenant folder now includes `meta.json`.
- The file stores:
  - `setup_completed`
  - `mobile_api_token`
  - tenant binding metadata
- Desktop admins can query:
  - `GET /admin/setup-status`
  - `POST /admin/setup-complete`
- The intended setup sequence is:
  1. Register server
  2. Add IPTV provider
  3. Add league data
  4. Publish mobile app

## Install And Subscription Tracking

- Desktop apps can report platform client installs to:
  - `POST /analytics/register-install`
- Desktop apps can report subscription events to:
  - `POST /analytics/register-subscription`
- Aggregated analytics are available from:
  - `GET /analytics/install-stats`
- Install payload:
  - `admin_id`
  - `device_id`
  - `app_version`
  - `timestamp`
- Subscription payload:
  - `admin_id`
  - `subscription_plan`
  - `start_date`
  - `end_date`
- Records are stored centrally in:
  - `data/install_logs.json`
  - `data/subscription_logs.json`
  - `data/audit_logs.json`
  - `data/email_logs.json`
  - `data/app_release.json`
- The install stats endpoint returns per-admin counts such as:
  - total install events
  - unique desktop devices
  - subscription event counts
  - active subscription counts
  - estimated revenue

## Platform Clients System

- Master-only platform client endpoints:
  - `GET /admin/platform_clients`
  - `POST /admin/platform_clients/{id}/block`
  - `POST /admin/platform_clients/{id}/unblock`
  - `POST /admin/platform_clients/{id}/extend_trial`
  - `POST /admin/platform_clients/{id}/reset_server`
  - `DELETE /admin/platform_clients/{id}`
- Master analytics endpoints:
  - `GET /admin/platform_clients/dashboard`
  - `GET /admin/platform_clients/analytics`
  - `POST /admin/platform_clients/update_check`
- Compatibility aliases for the older `/admin/white_label/*` endpoints remain available.
- Tenant and admin isolation still applies:
  - `master` can review all platform client records and manage any tenant intentionally
  - `client` only receives its own installs, subscriptions, audit logs, and tenant resources
- The update check endpoint compares the current desktop version against `data/app_release.json` and returns:
  - `current_version`
  - `latest_version`
  - `has_update`
  - `is_supported`
  - `download_url`
  - `release_notes`

## Desktop Update Server

- The backend now includes a dedicated desktop update module under:
  - `backend/updates/`
  - `backend/updates/files/`
- Update manifests and history are stored in:
  - `backend/updates/latest.json`
  - `backend/updates/versions.json`
- Supported update endpoints:
  - `GET /updates/latest`
  - `GET /updates/history`
  - `GET /updates/download/{filename}`
  - `GET /updates/files/{filename}`
  - `POST /updates/publish`
- Electron updater feed files are generated automatically when supported installers are published:
  - `backend/updates/latest.yml`
  - `backend/updates/latest-mac.yml`
  - `backend/updates/latest-linux.yml`
- `POST /updates/publish` is restricted to `master` admins and validates:
  - semantic version format
  - installer extension: `.exe`, `.dmg`, `.AppImage`
  - max size: `500MB`
- `GET /updates/latest` can also receive:
  - `current_version`
  - `platform`
- With those query params, the response includes:
  - `update_available`
  - `latest_version`
  - `mandatory`
  - `download_url`
  - `release_notes`

## Public API Resolver

- The backend now serves a public API resolver at:
  - `GET /api/config`
- Resolver payload:
  - `apiBaseUrl`
  - `validUntil`
  - `serverMappings`
  - `updatedAt`
- The resolver defaults to `API_BASE_URL=https://computatively-intelligent-arlena.ngrok-free.dev`.
- `DEFAULT_API_URL` and `API_BASE_URL` are both supported as environment fallbacks, with `DEFAULT_API_URL` taking precedence when set.
- Backend public tenant responses now fall back to that resolver base URL automatically when tenant branding does not override `server_url` or `api_base_url`.
- Master admins can update the persisted resolver URL through:
  - `POST /api/config`
- The persisted value is stored in:
  - `data/api_config.json`
- When the backend falls back to the ngrok default, tenant/mobile payloads now include:
  - `backend_url_source=default_ngrok`
  - `backend_url_notice`

## Render Deployment

- The backend resolver now supports dynamic deployment URLs from environment variables.
- Supported environment variables:
  - `PUBLIC_SERVER_URL`
  - `API_BASE_URL`
  - `DEFAULT_API_URL`
  - `RENDER_EXTERNAL_URL`
  - `LOCAL_SERVER_URL`
- On Render, `RENDER_EXTERNAL_URL` can be used automatically as the public resolver base URL.
- `GET /api/config` now returns the runtime public backend URL instead of requiring a hardcoded domain in source code.

## Roles And RBAC

- Admin accounts now carry a `role` field:
  - `master`: full global access across all platform clients
  - `client`: restricted to that admin's tenant data only
- The first registered admin is promoted to `master`.
- Later registered admins default to `client`.
- FastAPI role enforcement is handled with:
  - `get_current_user`
  - `require_role("master")`
  - `require_role("master", "client")`
- Master-only endpoints include:
  - `GET /analytics/install-stats`
  - `GET /admin/platform_clients`
  - `GET /admin/platform_clients/dashboard`
  - `GET /admin/platform_clients/analytics`
  - `GET /admin/list`
  - `POST /admin/tenants`
- Shared admin endpoints still allow either role, but remain tenant-scoped for `client` users:
  - `GET /analytics/live`
  - `GET /analytics/streams`
  - `GET /analytics/top-matches`
  - `GET /analytics/top-competitions`
  - `GET /analytics/daily-viewers`
  - `GET /analytics/countries`
  - stream workflow routes
  - approved stream routes
  - catalog management routes
  - branding routes
  - tenant-scoped user management routes
- Requests that fail role checks now return `403 Forbidden`.

## Branding Uploads

- Branding assets are now file-backed per client tenant.
- Upload endpoints:
  - `POST /admin/branding/upload_logo`
  - `POST /admin/branding/upload_icon`
  - `POST /admin/branding/upload_splash`
- Uploaded files are stored under:
  - `data/assets/branding/<admin_id>/`
- Returned asset URLs look like:
  - `/assets/branding/<admin_id>/logo.png`
- Tenant branding is also mirrored into:
  - `data/tenants/<admin_id>/branding.json`

## Tenant Branding Engine

- The backend now maintains one tenant branding profile per tenant in:
  - `data/tenant_branding.json`
- Generated branding files live under:
  - `storage/branding/<tenant_id>/`
  - `storage/cdn/branding/<tenant_id>/`
- The branding engine accepts one PNG logo and generates:
  - `logo.png`
  - `desktop_icon.ico`
  - `mobile_icon.png`
  - `favicon.ico`
  - `favicon-16.png`
  - `favicon-32.png`
  - `apple-touch-icon.png`
  - `splash.png`
- Tenant branding routes:
  - `GET /tenant/branding`
  - `POST /tenant/branding/upload-logo`
  - `POST /tenant/branding/rebuild-assets`
- Branding write routes require tenant or admin bearer authentication.
- Master admins can override branding for any tenant by passing `tenant_id`, while client tenants stay isolated to their own asset namespace.

## Mobile App Builder

- The backend now includes a tenant APK generation pipeline driven by the real Flutter project at:
  - `../mobile/`
- APK builds run inside the Docker image defined at:
  - `docker/flutter-android-builder.Dockerfile`
- Tenant branding records for APK generation can include:
  - `app_name`
  - `package_name`
  - `primary_color`
  - `secondary_color`
  - `logo_file`
  - `splash_screen`
  - `server_url`
- Mobile builder endpoints:
  - `POST /mobile/build`
  - `GET /mobile/build/status/{build_id}`
  - `GET /mobile/build/history`
  - `GET /mobile/download/{build_id}`
- `POST /mobile/build` is restricted to authenticated admins and:
  - loads tenant branding
  - increments the tenant app version automatically
  - copies `mobile/` into an isolated build workspace
  - injects app name, package name, tenant id, backend URL, colors, and branding assets
  - runs `flutter pub get`, `flutter clean`, and `flutter build apk --release` inside Docker
  - queues the build for background processing
- Download access is tenant-scoped so admins cannot fetch another tenant's APK.

## Mobile Build Queue

- Build queue state is stored in:
  - PostgreSQL via `MOBILE_BUILD_DATABASE_URL`
  - `data/mobile_builds.db` as the local fallback when no PostgreSQL URL is configured
  - `build_queue/workspaces/`
- Generated APKs are stored in:
  - `generated_apps/<tenant_id>/` when using local artifact storage
  - S3/object storage when `MOBILE_BUILD_ARTIFACT_STORAGE=s3`
- Build logs are stored in:
  - `data/mobile_builds.db`
  - `logs/mobile-builder/` for local worker diagnostics
- Job statuses:
  - `queued`
  - `building`
  - `completed`
  - `failed`
- Only one Flutter build runs at a time, which avoids concurrent workspace collisions on the shared host.
- The API process only auto-starts the worker outside Render-managed environments.
- Set `MOBILE_BUILD_WORKER_ENABLED=false` on the web/API service to force queue-only behavior.
- Run the dedicated worker process with:
  - `python -m app.mobile_build_worker_service`
- The dedicated worker host must have Docker access because APK builds run through `football-streaming-mobile-builder:latest`.

## Mobile Version History

- Tenant app versions are tracked in:
  - `data/tenants/<admin_id>/app_versions.json`
- Each new build increments the latest tenant version automatically.
- Generated APK filenames follow:
  - `<AppName>-<version>.apk`

## Mobile Build Security

- Build creation requires a valid admin token.
- APK downloads check both authentication and build ownership.
- Tenants are limited to 5 APK builds per day.
- Embedded tenant config ensures the resulting app connects only to the intended tenant backend.

## Mobile Builder Deployment Split

- Recommended production split:
  - web/API service: serves HTTP endpoints and queues builds
  - mobile builder worker: claims jobs from the API and performs Docker APK builds
- Detailed deployment guide:
  - `MOBILE_BUILD_DEPLOYMENT.md`
- Example environment file:
  - `.env.example`
- Recommended environment variables for the web/API service:
  - `MOBILE_BUILDER_BACKEND=docker`
  - `MOBILE_BUILD_WORKER_ENABLED=false`
  - `MOBILE_BUILD_WORKER_TOKEN=<shared-secret>`
  - `MOBILE_BUILD_DATABASE_URL=postgresql://...`
- Recommended environment variables for the dedicated worker host:
  - `MOBILE_BUILDER_BACKEND=docker`
  - `MOBILE_BUILD_WORKER_ENABLED=true`
  - `MOBILE_BUILD_WORKER_API_URL=https://your-api-host`
  - `MOBILE_BUILD_WORKER_TOKEN=<shared-secret>`
- On Render web services, the worker is disabled by default when Render environment variables are detected.
- Use `MOBILE_BUILD_ARTIFACT_STORAGE=s3` when the worker host does not share the API filesystem.

## Desktop Licensing

- Desktop licensing is stored centrally in `data/licenses.json`.
- Each license record includes:
  - `license_key`
  - `admin_id`
  - `device_id`
  - `status`
  - `issued_at`
  - `activated_at`
  - `expires_at`
  - `activation_count`
  - `activation_limit`
  - `subscription_plan`
- License endpoints:
  - `POST /license/generate`
  - `POST /license/activate`
  - `POST /license/validate`
  - `POST /license/revoke`
  - `POST /license/reassign`
- Local development may use `http://127.0.0.1` or `http://localhost`, but non-local license requests are expected to use HTTPS.
- Licenses are device-bound by `device_id` and reject activation or validation on unauthorized machines.

## Renewal Reminder Emails

- Subscription reminder templates live in `app/email_templates.py`.
- Periodic reminder checks run through APScheduler in `app/notifications.py`.
- The scheduler looks for subscriptions expiring within 7 days and logs each reminder attempt.
- SMTP is optional. Without SMTP settings, reminders are still written to `data/email_logs.json`.
- Supported environment variables:
  - `SUBSCRIPTION_REMINDER_SCHEDULE`
  - `SMTP_HOST`
  - `SMTP_PORT`
  - `SMTP_USERNAME`
  - `SMTP_PASSWORD`
  - `SMTP_FROM_EMAIL`
  - `SMTP_USE_TLS`
  - `PLATFORM_BASE_URL`
  - `DESKTOP_DOWNLOAD_URL`

## Legacy Migration

- On startup, and also when the first admin registers, the backend checks for legacy shared files such as:
  - `data/providers.json`
  - `data/approved_streams.json`
  - `data/football_metadata.json`
  - `data/viewers.json`
- If those files exist and at least one admin account is present, the backend migrates them into the first admin's tenant folder and removes the old shared copies.
- This preserves test IPTV mappings and existing approved football data from older installations.

## Responsibilities

- Host multiple platform clients on one backend
- Isolate tenant branding, trial rules, plans, devices, metadata, approved matches, and assets

- Load IPTV streams from Xtream or M3U providers
- Persist device users with trial, active, expired, blocked, and free states
- Store football metadata:
  - nations
  - competitions
  - clubs
  - uploaded logos
- Approve raw IPTV streams into football match records
- Serve mobile-safe football catalog data
- Keep approved match metadata when provider stream URLs refresh
- Track live and historical viewer analytics
- Enforce anti-piracy protections such as device lock, tokenized playback, session limits, and security monitoring
- Run automatic backups of persistent backend data with optional S3 upload

## Main Endpoints

### Device endpoints
- `POST /device/register`
- `GET /device/status?tenant_id=...&device_id=...`
- `POST /viewer/start`
- `POST /viewer/stop`
- `GET /streams/token/{stream_id}?tenant_id=...&device_id=...`
- `GET /play/{token}`

### Tenant and branding endpoints
- `POST /tenant/login`
- `GET /tenant/profile`
- `GET /config/branding?tenant_id=...`

### Analytics endpoints
- `GET /analytics/live`
- `GET /analytics/streams`
- `GET /analytics/top-matches`
- `GET /analytics/top-competitions`
- `GET /analytics/daily-viewers`
- `GET /analytics/countries`
- `POST /analytics/register-install`
- `POST /analytics/register-subscription`
- `GET /analytics/install-stats`

### Public stream endpoints
- `GET /streams/catalog?device_id=...`
- `GET /streams/approved?device_id=...`
- `GET /streams/leagues`

### Security and admin endpoints
- `POST /admin/register`
- `POST /admin/login`
- `GET /admin/validate`
- `POST /admin/renew`
- `GET /admin/list`
- `POST /admin/register-server`
- `POST /admin/reset-server`
- `POST /admin/transfer-device`
- `POST /admin/users/reset-device`
- `POST /admin/users/set-vpn-policy`
- `GET /admin/security`
- `GET /admin/tenants`
- `POST /admin/tenants`
- `GET /admin/branding?tenant_id=...`
- `POST /admin/branding?tenant_id=...`
- `GET /admin/backup/status`
- `POST /admin/backup/run`
- `POST /mobile/build`
- `GET /mobile/build/status/{build_id}`
- `GET /mobile/build/history`
- `GET /mobile/download/{build_id}`

### Admin provider and status
- `GET /admin/config`
- `POST /admin/config`
- `GET /admin/status`
- `POST /admin/refresh`

### Admin users
- `GET /admin/users`
- `GET /admin/users/online`
- `POST /admin/users/block`
- `POST /admin/users/unblock`
- `POST /admin/users/free-access`
- `POST /admin/users/remove-free-access`
- `POST /admin/users/extend-subscription`
- `POST /admin/users/rename`
- `POST /admin/users/restore-name`

### Admin football metadata and approval
- `GET/POST/DELETE /admin/nations`
- `GET/POST/DELETE /admin/competitions`
- `GET/POST/DELETE /admin/clubs`
- `POST /admin/assets/upload`
- `GET /admin/streams`
- `GET /admin/streams/approved`
- `POST /admin/streams/approve`
- `POST /admin/streams/remove?stream_id=...`

## Storage

- `data/config.json`
- `data/users.json`
- `data/sessions.json`
- `data/security_logs.json`
- `data/backup_logs.json`
- `data/tenants.json`
- `data/admins.json`
- `data/tenants/<admin_id>/providers.json`
- `data/tenants/<admin_id>/approved_streams.json`
- `data/tenants/<admin_id>/football_metadata.json`
- `data/tenants/<admin_id>/analytics.json`
- `data/assets/...`
- `../backups/...`

## Notes

- Trial duration is 3 days.
- Subscription plans currently supported are `6_months` and `1_year`.
- Free access overrides normal subscription/trial checks.
- Tenant subscription plans default to `trial`, `6_months`, and `1_year`, but can be customized per tenant.
- Blocked users are denied even if their device is already known.
- Approved stream records store football-facing names and logos while still following provider URL updates.
- Viewer sessions are stored in `viewers.json` with rolling trimming to limit file growth.
- Live viewers are held in memory and exposed through the analytics endpoints.
- Playback URLs returned to the mobile app are tokenized and expire after 60 seconds.
- Device fingerprint, VPN state, IP changes, and insecure-device checks feed the security dashboard.
- Admin subscriptions are persisted in `data/admins.json` with hashed passwords, hashed API tokens, device binding, and server binding metadata.
- Set `STREAM_TOKEN_SECRET` in the backend environment for stable signed playback tokens outside local development.
- Set `TENANT_AUTH_SECRET` for stable tenant admin bearer tokens outside local development.
- Docker must be installed and able to build/run `docker/flutter-android-builder.Dockerfile` for APK generation jobs to complete.

## Multi-Tenant Migration

Existing standalone installs are migrated by treating current records as the `default` tenant. New tenant records live in `data/tenants.json`, and new public or admin requests can pass `tenant_id` to scope branding, users, and match catalogs.

## Backup Configuration

Automatic backups are scheduled with APScheduler using the following environment variables:

- `BACKUP_SCHEDULE`: cron expression, default `0 3 * * *`
- `BACKUP_PATH`: optional override for the local archive folder
- `BACKUP_RETENTION`: number of local backups to keep, default `7`
- `CLOUD_BACKUP_ENABLED`: set to `true` to upload each archive to S3
- `S3_BUCKET`: bucket name used when cloud backup is enabled
- `S3_PREFIX`: optional prefix inside the bucket, default `football-iptv-backups`
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`: optional AWS settings

Backups include the full `backend/data/` tree, which covers:

- users and subscription state
- football metadata
- approved streams
- viewer analytics
- security/session state
- uploaded logos and other assets

## Manual Backups

From the admin API:

```bash
curl -X POST http://localhost:8000/admin/backup/run
```

From the command line:

```bash
cd backend
python -m app.backup
```

Other CLI actions:

```bash
python -m app.backup --action status
python -m app.backup --action list
python -m app.backup --action restore --file C:\path\to\backup_20260323_030000.zip
```

Inspect recent backup runs with:

```bash
curl http://localhost:8000/admin/backup/status
```

## Restore Process

1. Stop the FastAPI process.
2. Select a `.zip` archive from `backend/backups/` or S3.
3. Extract the archive so it recreates the `data/` directory.
4. Replace the current `backend/data/` contents with the extracted snapshot.
5. Start the backend again.

The Electron desktop app can also trigger the same restore flow through the bundled backup runner.

## Packaged Desktop Runtime

When the Electron admin app is packaged with the bundled Python runtime, it starts the backend through the embedded interpreter instead of relying on a system Python install:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Packaged Electron resources include:

- `backend/app`
- `backend/data`
- `backend/requirements.txt`
- `desktop/runtime/python/...`

This lets the packaged desktop app run the backend, backup tools, branding flows, and subscription controls without a separate Python installation on the admin machine.

## Restore In Packaged Desktop Builds

The desktop restore flow now stops the managed backend process, restores the selected archive into `backend/data`, and then starts the bundled backend again. For manual restores outside Electron, keep following the restore steps above and ensure the backend process is stopped first.
