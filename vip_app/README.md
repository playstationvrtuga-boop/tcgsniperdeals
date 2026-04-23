# TCG Sniper Deals VIP App

Flask + PWA VIP app for TCG Sniper Deals.

Path:

`C:\Users\Trabalho\Desktop\bot_pokemon\vip_app`

## Run locally

From the project root:

```powershell
python vip_app\manage.py run
```

For phone testing on the same Wi-Fi:

```powershell
python vip_app\manage.py run --host 0.0.0.0 --port 5000
```

Open:

[http://127.0.0.1:5000](http://127.0.0.1:5000)

## Demo users

- admin: `admin@tcgsniper.local` / `admin12345`
- vip: `vip@tcgsniper.local` / `vip12345`

If needed:

```powershell
python vip_app\manage.py seed-demo
```

On Render / production, `seed-demo` is blocked by default so it does not create public demo credentials by accident.
Only allow it intentionally with:

```env
ALLOW_DEMO_SEED=true
```

## Shared API key

The bot sends listings with:

`X-API-Key`

Set the same value in:

- `BOT_API_KEY`
- `APP_API_KEY` only as legacy fallback if needed

inside:

`C:\Users\Trabalho\Desktop\bot_pokemon\vip_app\.env`

## Android download page in production

The `/download-app` page can use a public APK link in production.

Set:

- `ANDROID_APK_URL`

Example:

```env
ANDROID_APK_URL=https://your-public-host/TCG-Sniper-Deals-Android.apk
```

If `ANDROID_APK_URL` is set, the download page uses that public link on Render.
If it is empty, the app falls back to the local debug APK path for local development.

## Production security notes

When `SITE_URL` uses `https://` or the app runs on Render, the app now enables:

- secure session cookies
- secure remember-me cookies
- HTTP-only cookies
- `SameSite=Lax` cookies

## Incoming listings API

Route:

`POST /api/listings`

Accepted fields:

- `title`
- `price` or `price_display`
- `url` or `external_url`
- `image_url`
- `platform`
- `source`
- `external_id`
- `tcg_type`
- `category`
- `score`
- `score_label`
- `badge_label`
- `detected_at`
- `source_published_at`
- `available_status`

Duplicate protection:

- primary: normalized URL
- fallback: `source + external_id`

Responses:

- `inserted`
- `duplicate`
- `validation_error`
- `unauthorized`
- `server_error`

## Test one demo listing

```powershell
python vip_app\manage.py test-api-listing
```

Then open:

[http://127.0.0.1:5000/feed](http://127.0.0.1:5000/feed)

The feed is ordered newest first using:

- `detected_at` first
- `created_at` as fallback

## Push notifications

Push is available for VIP users when these values are set in:

`C:\Users\Trabalho\Desktop\bot_pokemon\vip_app\.env`

```env
VAPID_SUBJECT=mailto:admin@example.com
VAPID_PUBLIC_KEY=your-public-vapid-key
VAPID_PRIVATE_KEY=your-private-vapid-key
SITE_URL=http://127.0.0.1:5000
```

### Local test flow

1. Run the app:

```powershell
python vip_app\manage.py run
```

2. Log in as the VIP demo user:

- `vip@tcgsniper.local`
- `vip12345`

3. Open:

[http://127.0.0.1:5000/feed](http://127.0.0.1:5000/feed)

4. Tap:

`Get instant alerts`

5. Allow notifications when the browser asks.

6. Insert a fresh demo listing:

```powershell
python vip_app\manage.py test-api-listing
```

7. Refresh the feed. The newest listing should appear at the top.

If your browser keeps the app open and notifications are allowed, the insert also triggers a push notification to subscribed VIP users.

### Browser and device notes

- Desktop Chrome, Edge and Firefox can work for local testing on `http://127.0.0.1` because localhost is treated as a secure context by modern browsers.
- Production push should use HTTPS.
- On iPhone and iPad, web push is practical only for a Home Screen installed web app, not a normal browser tab.
- For iPhone and iPad, the device should be on iOS / iPadOS 16.4 or newer.

## Mobile wrapper

The native Android / iPhone wrapper lives in:

[C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile](C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile)

That wrapper reuses this Flask app by URL instead of rebuilding it from scratch.

## Public HTTPS deployment for the mobile app

For a real phone-ready Android/iPhone build, the wrapper must point to a public HTTPS URL.

This project is now prepared for a simple Render deployment with:

- [C:\Users\Trabalho\Desktop\bot_pokemon\render.yaml](C:\Users\Trabalho\Desktop\bot_pokemon\render.yaml)
- [C:\Users\Trabalho\Desktop\bot_pokemon\vip_app\wsgi.py](C:\Users\Trabalho\Desktop\bot_pokemon\vip_app\wsgi.py)
- `gunicorn` for production serving
- PostgreSQL URL support via `psycopg`

### Minimal deployment path

1. Create a Render account.
2. Create a new web service from this project/repo.
3. Let Render use `render.yaml`.
4. Render will also create a PostgreSQL database from the same blueprint.
5. After the first deploy, set:

```env
SITE_URL=https://your-public-domain.onrender.com
MOBILE_APP_URL=https://your-public-domain.onrender.com
```

6. Rebuild the mobile wrapper after the public URL is known.

### What the Render setup now includes

- web service root: `vip_app`
- production server: `gunicorn`
- health check: `/health`
- managed PostgreSQL database
- fixed Python runtime via [C:\Users\Trabalho\Desktop\bot_pokemon\vip_app\runtime.txt](C:\Users\Trabalho\Desktop\bot_pokemon\vip_app\runtime.txt)

### Important note

Without an external hosting account or deploy target, this machine alone cannot become a permanent public HTTPS endpoint.

### Render performance settings

Recommended environment variables for the Render web service:

```env
WEB_CONCURRENCY=2
GUNICORN_THREADS=1
GUNICORN_TIMEOUT=60
GUNICORN_KEEPALIVE=5
RUN_STARTUP_SCHEMA_CHECK=false
RUN_DB_CREATE_ALL=false
LOG_STARTUP_TIMING=true
LOG_FEED_TIMING=false
FEED_CACHE_TTL_SECONDS=5
FEED_OPTIONS_CACHE_TTL_SECONDS=60
FEED_POLL_INTERVAL_MS=2500
FEED_DELTA_MAX_ITEMS=12
ENABLE_LIVE_RADAR=true
ENABLE_CARD_ENTRY_ANIMATIONS=true
ENABLE_RELATIVE_TIME_UPDATES=true
RELATIVE_TIME_UPDATE_MS=15000
DB_POOL_SIZE=2
DB_MAX_OVERFLOW=2
```

Recommended production command:

```powershell
gunicorn --config gunicorn_conf.py wsgi:app
```

This keeps app startup lighter, leaves `/health` cheap, and lets the worker process heavier background jobs instead of the web request path.

## Admin

The admin panel remains available at:

[http://127.0.0.1:5000/admin](http://127.0.0.1:5000/admin)

Admin can:

- manage users
- manage VIP access
- view recent listings
- review `pending_confirmation` payments
- mark payments as paid
