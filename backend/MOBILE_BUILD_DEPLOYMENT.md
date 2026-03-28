# Mobile Build Deployment

Use a split deployment for APK generation:

- Render web/API service:
  - serves HTTP routes
  - queues mobile build jobs
  - owns the shared mobile build database
  - does not run the APK worker
- Separate mobile build worker host:
  - runs `python -m app.mobile_build_worker_service`
  - has Docker access
  - connects back to the API over HTTPS

## Render API Service

Set these environment variables on the Render web service:

```env
MOBILE_BUILDER_BACKEND=docker
MOBILE_BUILD_WORKER_ENABLED=false
MOBILE_BUILD_WORKER_TOKEN=replace-with-a-long-random-secret
MOBILE_BUILD_DATABASE_URL=postgresql://user:password@host:5432/mobile_builds
```

Keep the existing API start command for the backend service.

The API service will:

- accept `POST /mobile/build`
- persist jobs in PostgreSQL
- expose build status, logs, and downloads
- never try to run Flutter locally
- never start the embedded APK worker when this flag is disabled

## Dedicated Worker Host

Run the worker on a machine or service that has:

- Docker CLI installed
- Docker daemon access
- the project source available
- access to the Render API over the network

Set these environment variables on the worker host:

```env
MOBILE_BUILDER_BACKEND=docker
MOBILE_BUILD_WORKER_ENABLED=true
MOBILE_BUILD_WORKER_API_URL=https://your-render-api-host
MOBILE_BUILD_WORKER_TOKEN=replace-with-the-same-secret
MOBILE_BUILDER_DOCKER_IMAGE=football-streaming-mobile-builder:latest
```

Start the worker with:

```bash
cd backend
python -m app.mobile_build_worker_service
```

Optional artifact storage settings:

```env
MOBILE_BUILD_ARTIFACT_STORAGE=s3
MOBILE_BUILD_S3_BUCKET=your-bucket
MOBILE_BUILD_S3_PREFIX=mobile-builds
MOBILE_BUILD_S3_REGION=eu-west-3
MOBILE_BUILD_S3_ENDPOINT_URL=
MOBILE_BUILD_S3_PUBLIC_BASE_URL=
MOBILE_BUILD_S3_PRESIGN_TTL_SECONDS=900
```

Use `MOBILE_BUILD_ARTIFACT_STORAGE=local` only when the API and worker can both access the same filesystem path for `generated_apps/`.

## Shared State

The API owns shared state for build jobs in:

- PostgreSQL via `MOBILE_BUILD_DATABASE_URL`

The remote worker does not need direct access to that file because it claims jobs and reports progress through token-protected worker endpoints.

Use S3 artifact storage when the API and worker do not share a filesystem. Without S3 or another shared local path:

- the API will not be able to serve completed APKs generated on the worker machine

## Recommended Layout

- Render web service:
  - repo checkout for backend API
  - persistent backend disk
  - `MOBILE_BUILD_WORKER_ENABLED=false`
  - `MOBILE_BUILD_WORKER_TOKEN=<shared-secret>`
  - `MOBILE_BUILD_DATABASE_URL=postgresql://...`
- Worker VM or Docker-capable service:
  - same repo checkout or deployed backend code
  - `MOBILE_BUILD_WORKER_ENABLED=true`
  - `MOBILE_BUILD_WORKER_API_URL=https://your-render-api-host`
  - `MOBILE_BUILD_WORKER_TOKEN=<shared-secret>`
  - `MOBILE_BUILD_ARTIFACT_STORAGE=s3`

## Resulting Flow

```text
Control panel -> Render API -> PostgreSQL
Dedicated worker -> claim/build/report over HTTPS -> S3 or shared generated_apps/<tenant_id>/
Render API -> status/download endpoints -> control panel
```

## Notes

- The worker builds APKs through `football-streaming-mobile-builder:latest`.
- Render should be treated as queue-only for mobile builds.
- If the worker host cannot access Docker, APK jobs will fail.
- Remote workers authenticate with `X-Mobile-Worker-Token`.
- Local/dev can still fall back to SQLite when `MOBILE_BUILD_DATABASE_URL` is not set.
