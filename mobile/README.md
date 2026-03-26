# Mobile (Flutter)

Football-oriented Flutter client for browsing approved matches on a registered device.

## Features

- Automatic backend discovery for web, emulators, and LAN devices
- Manual backend override in app settings
- Persistent tenant id with runtime white-label branding fetch
- Persistent device identity with no registration form
- First-launch device registration against `POST /device/register`
- Tenant branding fetch through `GET /config/branding?tenant_id=...`
- Access gating through `GET /device/status`
- Viewer analytics tracking through `POST /viewer/start` and `POST /viewer/stop`
- Tokenized playback through `GET /streams/token/{stream_id}` and `/play/{token}`
- Trial, active, free, expired, and blocked UI states
- Tenant app name and theme colors applied at startup
- Watermark overlay during playback
- Native anti-piracy checks for secure playback, root/jailbreak, VPN state, and app integrity scaffolding
- Football-first catalog layout:
  - nation sections
  - competition sections
  - match cards
  - club logos
  - competition logos
- Stream playback for approved matches

## Data Source

The app uses:
- `GET /config/branding`
- `POST /device/register`
- `GET /device/status`
- `POST /viewer/start`
- `POST /viewer/stop`
- `GET /streams/catalog`
- `GET /streams/token/{stream_id}`

## Notes

- If the device trial expires, the app shows the subscription page with `6 Months` and `1 Year` plans.
- Backend settings now include both the backend URL and `tenant_id`.
- If the backend returns `blocked`, the app shows an access-disabled screen.
- Catalog loads are tied to the device id so backend access rules can be enforced.
- The player starts analytics when playback starts and stops analytics when the player pauses or closes.
- Playback requests use temporary signed URLs instead of raw IPTV URLs.
