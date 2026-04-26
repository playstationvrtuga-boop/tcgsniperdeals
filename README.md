# TCG Sniper Deals

This project has two connected parts:

1. Bot  
   Path: `C:\Users\Trabalho\Desktop\bot_pokemon`

2. VIP app (Flask + PWA)  
   Path: `C:\Users\Trabalho\Desktop\bot_pokemon\vip_app`

There is now also a lightweight pricing layer for production testing:

3. Pricing worker  
   Path: `C:\Users\Trabalho\Desktop\bot_pokemon\pricing_worker.py`

4. Gone-alert worker for FREE Telegram FOMO posts  
   Path: `C:\Users\Trabalho\Desktop\bot_pokemon\gone_alert_worker.py`

5. FREE Telegram promotional banner scheduler  
   Path: `C:\Users\Trabalho\Desktop\bot_pokemon\services\free_promos.py`

The bot now sends accepted listings into the VIP app automatically through:

`POST /api/listings`

## 1. Run the VIP app

Open a terminal in:

`C:\Users\Trabalho\Desktop\bot_pokemon`

Run:

```powershell
python vip_app\manage.py run
```

Open:

[http://127.0.0.1:5000](http://127.0.0.1:5000)

Demo logins:

- admin: `admin@tcgsniper.local` / `admin12345`
- vip: `vip@tcgsniper.local` / `vip12345`

## 2. Configure the shared API key

The app accepts bot listings with the header:

`X-API-Key`

App config lives in:

`C:\Users\Trabalho\Desktop\bot_pokemon\vip_app\.env`

Use the same key in:

- `BOT_API_KEY` inside `vip_app\.env`
- `BOT_API_KEY` for the bot
- `APP_API_KEY` only as legacy fallback if needed

Example app env values:

```env
BOT_API_KEY=change-me-bot-api-key
# APP_API_KEY=change-me-bot-api-key
SITE_URL=http://127.0.0.1:5000
```

Bot example values are in:

`C:\Users\Trabalho\Desktop\bot_pokemon\env.example`

The bot config file is:

`C:\Users\Trabalho\Desktop\bot_pokemon\config.py`

The bot now auto-reads values from `vip_app\.env` when possible, so on the same machine it usually needs little or no extra setup.

For the hourly FREE promotional banners, set:

- `APP_PUBLIC_URL` for the button target
- `FREE_PROMO_ENABLED=true`
- `FREE_PROMO_FOLDER=vip_app/app/static/promos`
- `FREE_PROMO_INTERVAL_MINUTES=60`

The banner image files live in:

`C:\Users\Trabalho\Desktop\bot_pokemon\vip_app\app\static\promos`

## 3. Run the bot

From:

`C:\Users\Trabalho\Desktop\bot_pokemon`

Run:

```powershell
python vinted_olx_bot.py
```

When the bot accepts a valid listing, the flow is now:

`validated listing -> app API -> app database -> VIP feed`

Telegram sending is still separate and optional.

The bot also starts a lightweight hourly promotional banner scheduler for the FREE channel. It sends one random promo image, one random caption, and one inline button that opens the app.

To test one promo immediately during development, run:

```powershell
python send_test_promo.py
```

## 3.3 Run the gone-alert worker

This worker only posts real listings that were previously detected and later became unavailable.

Run continuously:

```powershell
python gone_alert_worker.py
```

Run one cycle:

```powershell
python gone_alert_worker.py --once
```

The gone-alert worker is lightweight:

- no browser automation
- no scraping
- only database queries
- one post at a time
- state persists per day in the database

It uses these default windows:

- 10:00-13:00
- 15:00-19:00
- 20:00-23:00

It randomly picks a small daily target and spreads that target across the allowed windows.

## 3.1 Online production flow (Render)

Desired live flow:

`bot -> Render app API -> Render database -> Render pricing worker -> VIP app now + sampled FREE Telegram in real time`

This means:

- the bot can keep running on your PC
- the bot sends listings to the online app API
- the Render worker reads those pending listings from the same online database
- if a listing is a real deal, it appears in the app feed in real time
- a small sampled subset of VIP alerts is sent to FREE Telegram in real time
- FREE Telegram now mirrors the VIP announcement format instead of using a delay queue

To make that work online, Render must have:

- the `tcg-sniper-deals` web service
- the `tcg-sniper-deals-worker` background worker
- the same `DATABASE_URL` on both
- `TELEGRAM_BOT_TOKEN`
- `FREE_CHAT_ID`
- `VIP_CHAT_ID`
- `SITE_URL`
- `VAPID_SUBJECT`
- `VAPID_PUBLIC_KEY`
- `VAPID_PRIVATE_KEY`

Important:

- app feed shows only listings already classified as `is_deal = true`
- incoming listings enter as `pending`
- the worker is what turns `pending` into visible live deals

## 3.1 Configure lightweight pricing

Add these values to:

`C:\Users\Trabalho\Desktop\bot_pokemon\.env`

```env
PRICING_WORKER_MIN_SLEEP=1
PRICING_WORKER_MAX_SLEEP=3
PRICING_DEAL_MIN_DISCOUNT=20
PRICING_DEAL_MIN_MARGIN=5
PRICING_DEAL_MIN_SCORE=60
FREE_REALTIME_SAMPLE_PERCENT=10
```

## 3.2 Run the pricing worker

Run one listing only:

```powershell
python pricing_worker.py --once
```

Run continuously but still sequentially:

```powershell
python pricing_worker.py
```

The worker:

- reads one pending listing at a time from the app database
- checks official eBay API Buy Now prices first when credentials are configured
- uses lightweight `eBay sold`/Buy Now HTML lookup only as a fallback
- falls back to similar listings already stored in the local app database
- uses a lightweight TTL cache in memory
- stores `reference_price`, `discount_percent`, `gross_margin`, `pricing_score`, `is_deal`
- sends a Telegram alert only when a priced listing qualifies as a deal
- sleeps between loops to keep RAM and API load low
- does not manage the Free Telegram delay queue anymore

### Optional official eBay API pricing

The old HTML lookup can be blocked by eBay anti-bot pages. For production, set these on the Render pricing worker:

```env
EBAY_CLIENT_ID=your-ebay-app-client-id
EBAY_CLIENT_SECRET=your-ebay-app-client-secret
EBAY_ENABLE_OFFICIAL_API=true
EBAY_MARKETPLACE_ID=EBAY_US
```

With these values, the pricing worker uses the official eBay Browse API for active Buy Now comparables before trying the old fallback.

Test the official eBay API directly with:

```powershell
python -m services.ebay_api_client "pokemon charizard"
```

The command prints whether the token worked, which marketplace and endpoint were used, the search status, total results, and the first returned listings. Secrets are masked in logs.

Sold price history may require extra eBay Marketplace Insights access. If you get that access later, add:

```env
EBAY_ENABLE_MARKETPLACE_INSIGHTS=true
EBAY_MARKETPLACE_INSIGHTS_SEARCH_URL=your-approved-search-endpoint
```

## 4. Test one demo listing into the app

You can test the app API directly with:

```powershell
python vip_app\manage.py test-api-listing
```

Expected output:

- `API status: 201`
- `API response: {'status': 'inserted', ...}`
- `Stored listing: ...`

Then open:

[http://127.0.0.1:5000/feed](http://127.0.0.1:5000/feed)

Refresh the feed and the demo listing should appear near the top.

After that, run:

```powershell
python pricing_worker.py --once
```

This processes the newest pending listing with the lightweight pricing worker.

## 5. How to verify the bot -> app pipeline

1. Start the app:

```powershell
python vip_app\manage.py run
```

2. Start the bot:

```powershell
python vinted_olx_bot.py
```

3. Wait for a valid listing to be accepted by the bot.

4. Open:

[http://127.0.0.1:5000/feed](http://127.0.0.1:5000/feed)

5. The newest accepted listings should appear in the VIP feed automatically.

The feed is now ordered newest first using:

- `detected_at`
- fallback: `created_at`

Relative time on the cards also follows that same timestamp.

## 6. What the app API accepts

Supported incoming payload fields:

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
- `status` updates can also be posted to `/api/listings/status`

Duplicates are handled safely.

Primary duplicate logic:

- normalized URL
- fallback: `source + external_id`

Responses:

- `inserted`
- `duplicate`
- `validation_error`
- `unauthorized`
- `server_error`

## 8. Gone-alert status sync

The bot can now report when a tracked listing becomes unavailable, so the app database keeps the gone-alert pool fresh.

Status updates are sent to:

`POST /api/listings/status`

This lets the FREE gone-alert worker find real previously detected listings that are now unavailable.

## 7. What still remains manual

- VIP payment confirmation is still manual in the admin panel
- the admin still marks payments as paid
- production hosting / HTTPS is still not set up
- Telegram remains optional and separate from the app feed

## 7.1 Files added for lightweight pricing

- `C:\Users\Trabalho\Desktop\bot_pokemon\services\ebay_sold_client.py`
- `C:\Users\Trabalho\Desktop\bot_pokemon\services\local_history_client.py`
- `C:\Users\Trabalho\Desktop\bot_pokemon\services\price_cache.py`
- `C:\Users\Trabalho\Desktop\bot_pokemon\services\deal_detector.py`
- `C:\Users\Trabalho\Desktop\bot_pokemon\services\telegram_alerts.py`
- `C:\Users\Trabalho\Desktop\bot_pokemon\pricing_worker.py`

## 7.2 Current pricing design

- lightweight `eBay sold` lookup with `requests`
- fallback to local historical listings already stored in the app database
- reference price = median of collected comparable prices

This keeps the integration lightweight and avoids browser automation completely.

## 8. Push notifications

VIP users can enable push from the app feed with:

`Get instant alerts`

Push setup uses the existing PWA and Web Push flow.

Required app env values in:

`C:\Users\Trabalho\Desktop\bot_pokemon\vip_app\.env`

```env
VAPID_SUBJECT=mailto:admin@example.com
VAPID_PUBLIC_KEY=your-public-vapid-key
VAPID_PRIVATE_KEY=your-private-vapid-key
SITE_URL=http://127.0.0.1:5000
```

Quick local test:

1. Start the app
2. Log in as the VIP user
3. Tap `Get instant alerts`
4. Allow notifications
5. Run:

```powershell
python vip_app\manage.py test-api-listing
```

6. Confirm the new listing lands at the top of:

[http://127.0.0.1:5000/feed](http://127.0.0.1:5000/feed)

### Push limitations

- Local testing works on modern browsers because localhost is treated as a secure context.
- Production push should run over HTTPS.
- On iPhone / iPad, push is meant for the installed Home Screen web app, not a normal browser tab.
- iPhone / iPad push requires iOS / iPadOS 16.4 or newer.

## 9. Android / iPhone wrapper

The existing Flask + PWA app now also has a Capacitor wrapper in:

[C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile](C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile)

This keeps the current app intact and opens it inside native Android / iPhone shells.

Start with:

```powershell
cd C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile
npm.cmd run sync:config
```

Full mobile instructions are in:

[C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile\README.md](C:\Users\Trabalho\Desktop\bot_pokemon\vip_app_mobile\README.md)

## Render tuning

Recommended web service env values:

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

Recommended command from `vip_app`:

```powershell
gunicorn --config gunicorn_conf.py wsgi:app
```

These settings keep startup lighter, keep `/health` instant, and give the web service two workers by default without moving heavy work into the request path.
