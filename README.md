# TCG Sniper Deals

This project has two connected parts:

1. Bot  
   Path: `C:\Users\Trabalho\Desktop\bot_pokemon`

2. VIP app (Flask + PWA)  
   Path: `C:\Users\Trabalho\Desktop\bot_pokemon\vip_app`

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

- `BOT_API_KEY` or `APP_API_KEY` inside `vip_app\.env`
- `APP_API_KEY` for the bot

Example app env values:

```env
BOT_API_KEY=change-me-bot-api-key
APP_API_KEY=change-me-bot-api-key
SITE_URL=http://127.0.0.1:5000
```

Bot example values are in:

`C:\Users\Trabalho\Desktop\bot_pokemon\env.example`

The bot config file is:

`C:\Users\Trabalho\Desktop\bot_pokemon\config.py`

The bot now auto-reads values from `vip_app\.env` when possible, so on the same machine it usually needs little or no extra setup.

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

## 7. What still remains manual

- VIP payment confirmation is still manual in the admin panel
- the admin still marks payments as paid
- production hosting / HTTPS is still not set up
- Telegram remains optional and separate from the app feed

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
