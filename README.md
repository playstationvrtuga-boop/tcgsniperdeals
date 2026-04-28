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
- no heavy scraping
- only small database queries and limited HTTP checks
- one post at a time
- state persists per day in the database
- it marks recently detected listings as `sold`, `removed` or `unavailable` only when the listing page gives a clear signal

It uses these default windows:

- 10:00-13:00
- 15:00-19:00
- 20:00-23:00

It randomly picks a small daily target and spreads that target across the allowed windows.

Availability checks are deliberately small so the worker stays light:

```env
FREE_GONE_AVAILABILITY_CHECK_LIMIT=10
FREE_GONE_AVAILABILITY_MIN_AGE_MINUTES=5
FREE_GONE_AVAILABILITY_RECHECK_MINUTES=180
```

Useful logs:

```text
[availability] checking id=123 platform=Vinted
[availability] gone id=123 status=sold reason=text_marker:item sold
[availability] scanned=10 marked_gone=1
[gone_worker] discovered_gone=1
```

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
- parses imperfect titles with a generic Pokemon title parser before pricing
- creates multiple alias queries such as `charizard 125/094`, `pokemon 125/094`, `pfl 125`, or `pokemon charizard card`
- detects whether the original listing is RAW, graded/slab, sealed, lot/bundle, accessory or unknown before comparing prices
- never prices a RAW card using PSA/BGS/CGC/Beckett/Aura/RPA/slab comparables
- only compares graded listings against graded references, preferring the same grading company and grade
- checks official eBay API Buy Now prices first when credentials are configured
- keeps the old `eBay sold`/Buy Now HTML lookup disabled by default in production, because eBay can return anti-bot pages
- falls back to similar listings already stored in the local app database
- uses a lightweight TTL cache in memory
- stores `reference_price`, `discount_percent`, `gross_margin`, `pricing_score`, `is_deal`
- sends a Telegram alert only when a priced listing qualifies as a deal
- sleeps between loops to keep RAM and API load low
- does not manage the Free Telegram delay queue anymore

### Generic title parsing

The pricing worker no longer rejects listings just because the title is imperfect. It uses:

`C:\Users\Trabalho\Desktop\bot_pokemon\services\pokemon_title_parser.py`

The parser normalizes accents, emojis, languages and card-number formats, then extracts:

- Pokemon name when recognized
- card number and full number like `080/132`
- possible set code like `PFL`, `ME1`, `SV8`, `PAL`, `OBF`, `TWM`
- variants like `ex`, `gx`, `v`, `vmax`, `vstar`, `mega`
- rarity, language and grading hints
- listing kind: `single_card`, `graded_card`, `sealed_product`, `lot_bundle`, `unknown_pokemon`

It assigns confidence:

- `HIGH`: strong name/number/set or graded signal
- `MEDIUM`: usable partial identification
- `LOW`: Pokemon-related but incomplete
- `UNKNOWN`: no Pokemon signal

Important rule: if the title contains `pokemon` / `pokémon`, the listing is processed. It becomes `unknown_pokemon` with `LOW` confidence if the parser cannot identify a precise card. Number-only signals such as `003/182` are also processed with `LOW` confidence.

`LOW` confidence listings still go to pricing with safer generic queries. Only listings with no Pokemon word, no recognized Pokemon name, and no card-number signal are skipped. To expand name detection later, edit:

`C:\Users\Trabalho\Desktop\bot_pokemon\data\pokemon_names.json`

In worker logs, confirm this parser flow:

```text
[parser] raw_title=...
[parser] normalized_title=...
[parser] kind=unknown_pokemon
[parser] confidence=LOW
[parser] decision=process
[parser] fallback_mode=true
```

Pricing now tries a cascade of broader queries instead of stopping after one failed search. Example:

```text
[pricing] query_attempt=1 source=buy_now query="moramartik ex 003/182"
[pricing] results=0
[pricing] fallback_next_query=true
[pricing] query_attempt=2 source=buy_now query="moramartik 003/182"
[pricing] results=5
[pricing] SUCCESS
```

Before any query is sent to eBay, the worker now removes generic stopwords such as `des`, `premier`, `cards`, `bundle`, `lot`, `random`, `edition`, and other filler words. Junk queries are skipped and shown clearly:

```text
[pricing] raw_query=pokemon des 9
[pricing] cleaned_query=pokemon 9
[pricing] valid=false
[pricing] skipped_invalid_query=true
```

RAW vs graded protection is enforced after eBay returns results, so inflated graded references are rejected even if the API search returns them:

```text
[pricing] LISTING_TYPE_DETECTED_RAW
[pricing] COMPARABLE_REJECTED_GRADED_FOR_RAW source=buy_now title=PSA 10 Zapdos Fossil 15/62
[pricing] PRICE_COMPARE_INSUFFICIENT_RAW_COMPARABLES
```

If a RAW card has no usable RAW comparables after filtering, Sniper Deals shows low confidence and `Market: Not enough RAW comparables` instead of showing a fake market price or inflated profit.

### Render setup: official eBay API pricing

The old HTML lookup can be blocked by eBay anti-bot pages. For production, set these on the Render worker service:

`tcg-sniper-deals-worker`

```env
EBAY_ENABLE_OFFICIAL_API=true
EBAY_CLIENT_ID=your_production_client_id
EBAY_CLIENT_SECRET=your_production_client_secret
EBAY_MARKETPLACE_ID=EBAY_US
EBAY_API_ENVIRONMENT=PRODUCTION
PRICING_ENABLE_EBAY_HTML_FALLBACK=false
```

Do not put real eBay credentials in code, commits, screenshots, or README files. `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET` must be configured directly in Render Environment Variables.

These variables must be on the worker because the pricing worker uses them for Buy Now pricing. Add the same variables to the web service only if you want the protected `/api/debug/ebay` endpoint to test eBay from the live website process too.

After changing them in Render:

1. Open Render.
2. Open `tcg-sniper-deals-worker`.
3. Go to `Environment`.
4. Click `Add Environment Variable`.
5. Add:

```env
EBAY_ENABLE_OFFICIAL_API=true
EBAY_CLIENT_ID=your_production_client_id
EBAY_CLIENT_SECRET=your_production_client_secret
EBAY_MARKETPLACE_ID=EBAY_US
PRICING_ENABLE_EBAY_HTML_FALLBACK=false
```

6. Optional but recommended: repeat on the web service `tcg-sniper-deals` for `/api/debug/ebay`.
7. Run `Manual Deploy -> Deploy latest commit`.

In Render Shell, test the official eBay API directly with:

```powershell
python -m services.ebay_api_client "pokemon charizard"
```

The command prints whether the API is enabled, whether the keys exist, whether the token worked, which marketplace and endpoint were used, the search status, total results, and the first three returned listings. Secrets are never printed. The pricing worker also prints the same startup check automatically after each deploy.

Confirm these logs:

```text
[ebay_api] config enabled=True client_id=present client_secret=present marketplace=EBAY_US
[ebay_api] environment=PRODUCTION
[ebay_api] STARTUP_CHECK
[ebay_api] token OK
[ebay_api] search OK
[ebay_api] results_count=...
[ebay_api] first_item_title=...
[ebay_api] first_item_price=...
search OK
[ebay_api] BUY_NOW_REFERENCE_FOUND
```

Also confirm this worker line:

```text
[pricing_worker] ebay_api enabled=True client_id=present client_secret=present marketplace=EBAY_US html_fallback=False
[config] environment variables loaded successfully
```

If something is wrong, look for:

```text
[pricing_worker] ebay_api enabled=True client_id=missing client_secret=missing marketplace=EBAY_US html_fallback=False
[config] required environment variables not found
[config] check deployment environment configuration
[ebay_api] API_DISABLED
[ebay_api] API_KEYS_MISSING
[ebay_api] Add EBAY_CLIENT_ID and EBAY_CLIENT_SECRET to Render service tcg-sniper-deals-worker Environment Variables
TOKEN_FAILED
TOKEN_INVALID_OR_EXPIRED
PERMISSION_DENIED
RATE_LIMIT
SEARCH_FAILED
ZERO_RESULTS
```

The web app also has a protected debug endpoint:

```text
GET /api/debug/ebay
```

Use it only while logged in as an admin or with the `X-API-Key` header. It returns JSON with `enabled`, `keys_present`, `token_status`, `search_status`, `results_count`, and sample items.

Sold price history may require extra eBay Marketplace Insights access. If you get that access later, add:

```env
EBAY_ENABLE_MARKETPLACE_INSIGHTS=true
EBAY_MARKETPLACE_INSIGHTS_SEARCH_URL=your-approved-search-endpoint
```

Only turn `PRICING_ENABLE_EBAY_HTML_FALLBACK=true` for local debugging. Keep it `false` on Render so the worker does not get stuck on eBay anti-bot HTML pages.

### Deployment configuration

Some values are deployment secrets and must only exist in the runtime environment. They should never be hardcoded in Python files, committed to GitHub, or pasted into public docs.

Configure required secrets in the service that uses them:

- `tcg-sniper-deals-worker`: eBay API variables used by `pricing_worker`.
- `tcg-sniper-deals`: app secrets, API key, VAPID keys, and optional `/api/debug/ebay` eBay variables.
- `tcg-sniper-deals-gone-worker`: Telegram variables used by missed/gone alerts.

If required variables are missing, workers stay alive in limited mode and print:

```text
[config] required environment variables not found
[config] check deployment environment configuration
```

When configured correctly, workers print:

```text
[config] environment variables loaded successfully
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

The bot can report when a tracked listing becomes unavailable, and the gone-alert worker also performs lightweight availability checks on recent listings. This keeps the Missed Deals page and the FREE gone-alert pool fresh without browser automation.

Status updates are sent to:

`POST /api/listings/status`

The worker also checks a small number of recent listing URLs per cycle. If a listing is clearly sold, removed or unavailable, it updates:

- `status`
- `available_status`
- `status_updated_at`
- `gone_detected_at`
- `sold_after_seconds`

This is separate from eBay sold-price lookup. Sold-price data helps pricing, while availability status feeds Missed Deals.

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

## AI Market Intel

VIP users now have an `AI Market Intel` tab inside the app.

Purpose:

- collect a lightweight daily Cardmarket public trends snapshot
- show Best Sellers and Best Bargains inside the VIP app
- connect those trends to Sniper Deals when a live listing matches the market movement
- add an `AI Market Intel: Trending on Cardmarket` badge to matched Sniper Deals

The collector is intentionally conservative:

- it runs once every 24 hours
- it uses the public Cardmarket Pokemon page only
- it does not bypass login, CAPTCHA, paywalls or anti-bot systems
- if Cardmarket blocks or fails, the app keeps showing the last successful snapshot

Local commands:

```powershell
cd C:\Users\Trabalho\Desktop\bot_pokemon
python cardmarket_trends_worker.py --once
python cardmarket_trends_worker.py
```

Render setup:

Create or keep the background worker:

`tcg-sniper-deals-market-intel-worker`

Command from `vip_app`:

```powershell
python cardmarket_trends_worker_entry.py
```

Environment variables:

```env
CARDMARKET_TRENDS_ENABLED=true
CARDMARKET_TRENDS_INTERVAL_HOURS=24
CARDMARKET_TRENDS_MAX_ITEMS=20
CARDMARKET_TRENDS_SOURCE_URL=https://www.cardmarket.com/en/Pokemon
CARDMARKET_TRENDS_TIMEOUT_SECONDS=20
CARDMARKET_TRENDS_USER_AGENT=TCGSniperDealsBot/1.0
```

Expected logs:

```text
[ai_market_intel] AI_MARKET_INTEL_STARTED
[ai_market_intel] CARDMARKET_TRENDS_FETCH_OK
[ai_market_intel] CARDMARKET_TRENDS_PARSE_OK count=...
[ai_market_intel] CARDMARKET_TRENDS_SAVED count=...
[ai_market_intel] AI_MARKET_INTEL_MATCHED_LISTING listing_id=...
[ai_market_intel] AI_MARKET_INTEL_SNIPER_SCORE_BOOSTED listing_id=...
```

If Cardmarket is unavailable, look for:

```text
[ai_market_intel] CARDMARKET_TRENDS_FAILED error=...
[ai_market_intel] AI_MARKET_INTEL_USING_LAST_SNAPSHOT
```

### Manual screenshot import

If Cardmarket blocks the worker with `403 Forbidden`, use the safe manual import flow:

1. Open the Cardmarket Pokemon trends page in your browser.
2. Take one screenshot where `Best Sellers` and `Best Bargains` are visible, or take two screenshots: one for `Best Sellers` and one for `Best Bargains`.
3. Open the VIP app admin panel.
4. Click `AI Market Intel Import`.
5. Upload the screenshot in `Combined screenshot`, or upload the two screenshots in `Best Sellers screenshot` and `Best Bargains screenshot`.
6. Open `AI Market Intel` in the VIP app.

The importer crops the top 3 Best Sellers and top 3 Best Bargains from the screenshot(s) and saves them as app images. If optional OCR is available, it also tries to read product names and prices. If OCR is not available, the app still shows the cropped images with safe fallback names.

Optional helper:

- paste the visible Cardmarket trend text into the import page textarea to improve names and prices
- keep the screenshot clean so the top 3 cards are visible
- mobile screenshots are supported when uploaded into the separate Best Sellers / Best Bargains fields

This does not bypass Cardmarket login, CAPTCHA, paywalls or anti-bot protection. It uses only the screenshot you provide.
