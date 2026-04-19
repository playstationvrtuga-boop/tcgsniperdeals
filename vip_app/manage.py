print("[startup] 1) manage.py started", flush=True)

import argparse
import socket
from decimal import Decimal
from threading import Thread
from urllib.request import urlopen

from app import create_app
from app.extensions import db
from app.models import Listing, Payment, User, utcnow
from werkzeug.serving import make_server

print("[startup] 2) imports completed", flush=True)

print("[startup] 2.1) before create_app()", flush=True)
app = create_app()
print("[startup] 2.2) app instance created", flush=True)


def create_admin(email: str, password: str, telegram: str | None = None):
    with app.app_context():
        user = User.query.filter_by(email=email.lower().strip()).first()
        if not user:
            user = User(email=email.lower().strip(), telegram_username=telegram, is_admin=True, is_vip=True)
            user.set_password(password)
            db.session.add(user)
        else:
            user.is_admin = True
            user.is_vip = True
            if telegram:
                user.telegram_username = telegram
            user.set_password(password)
        user.apply_paid_plan("yearly")
        db.session.commit()
        print(f"Admin ready: {user.email}")


def seed_demo():
    with app.app_context():
        if not User.query.filter_by(email="admin@tcgsniper.local").first():
            admin = User(email="admin@tcgsniper.local", telegram_username="@tcgsniper", is_admin=True, is_vip=True)
            admin.set_password("admin12345")
            admin.apply_paid_plan("yearly")
            db.session.add(admin)

        if not User.query.filter_by(email="vip@tcgsniper.local").first():
            vip = User(email="vip@tcgsniper.local", telegram_username="@vipbuyer", is_vip=True)
            vip.set_password("vip12345")
            vip.apply_paid_plan("monthly")
            db.session.add(vip)

        db.session.commit()

        demo_items = [
            {
                "source": "vinted",
                "external_id": "vinted-demo-1",
                "external_url": "https://www.vinted.pt/items/demo-charizard",
                "image_url": "https://images.unsplash.com/photo-1613771404721-1f92d799e49f?auto=format&fit=crop&w=800&q=80",
                "title": "Pokémon TCG Charizard ex 223/197 Obsidian Flames",
                "price_display": "79.00 €",
                "platform": "Vinted",
                "badge_label": "Off-market",
                "score_label": "HIGH",
            },
            {
                "source": "ebay",
                "external_id": "ebay-demo-1",
                "external_url": "https://www.ebay.com/itm/demo-mew",
                "image_url": "https://images.unsplash.com/photo-1627856013091-fed6e4e30025?auto=format&fit=crop&w=800&q=80",
                "title": "Pokémon TCG Mew ex 151/165 Double Rare",
                "price_display": "US$ 12",
                "platform": "eBay",
                "badge_label": "Strong",
                "score_label": "MEDIUM",
            },
        ]

        for item in demo_items:
            if Listing.query.filter_by(source=item["source"], external_id=item["external_id"]).first():
                continue
            listing = Listing(
                source=item["source"],
                external_id=item["external_id"],
                external_url=item["external_url"],
                image_url=item["image_url"],
                title=item["title"],
                price_display=item["price_display"],
                platform=item["platform"],
                badge_label=item["badge_label"],
                score_label=item["score_label"],
                posted_at=utcnow(),
            )
            db.session.add(listing)

        vip_user = User.query.filter_by(email="vip@tcgsniper.local").first()
        if vip_user and not Payment.query.filter_by(user_id=vip_user.id).first():
            payment = Payment(
                user_id=vip_user.id,
                plan="monthly",
                amount=Decimal("3.90"),
                method="PayPal",
                status="paid",
                paid_at=utcnow(),
                notes="Demo payment",
            )
            db.session.add(payment)

        db.session.commit()
        print("Demo data ready.")


def test_api_listing():
    with app.app_context():
        client = app.test_client()
        stamp = utcnow().strftime("%Y%m%d%H%M%S")
        payload = {
            "source": "vinted",
            "external_id": f"demo-api-{stamp}",
            "title": f"Pokemon TCG API Demo Listing {stamp}",
            "price": "12.50 €",
            "url": f"https://www.vinted.pt/items/demo-api-{stamp}",
            "image_url": "https://images.unsplash.com/photo-1613771404721-1f92d799e49f?auto=format&fit=crop&w=800&q=80",
            "platform": "Vinted",
            "tcg_type": "pokemon",
            "category": "single_card",
            "score": 87,
            "score_label": "HIGH",
            "badge_label": "Off-market",
            "detected_at": utcnow().isoformat(),
            "available_status": "available",
        }

        response = client.post(
            "/api/listings",
            json=payload,
            headers={"X-API-Key": app.config["BOT_API_KEY"]},
        )
        data = response.get_json() or {}
        print(f"API status: {response.status_code}")
        print(f"API response: {data}")

        listing_id = data.get("id")
        if listing_id:
            listing = db.session.get(Listing, listing_id)
            print(f"Stored listing: {listing.title} ({listing.platform})")

        print(f"Open {app.config['SITE_URL'].rstrip('/')}/feed to verify it in the VIP feed.")


def port_is_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def run(port: int = 5000, host: str = "127.0.0.1"):
    if not port_is_available(host, port):
        print(
            f"[startup] Port {port} is already in use on {host}. "
            f"Close the old server or run: python vip_app\\manage.py run --port {port + 1}",
            flush=True,
        )
        return

    print(f"[startup] 6) server starting at http://{host}:{port}", flush=True)
    app.run(debug=True, use_reloader=False, host=host, port=port)


def run_minimal_probe():
    print("[startup] 1) manage.py started", flush=True)
    print("[startup] 2) imports completed", flush=True)
    print("[startup] 2.1) before create_app()", flush=True)
    minimal_app = create_app(minimal=True, skip_db=True, skip_blueprints=True)
    print("[startup] 2.2) minimal app instance created", flush=True)

    server = make_server("127.0.0.1", 5000, minimal_app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print("[startup] 6) running on http://127.0.0.1:5000", flush=True)

    response = urlopen("http://127.0.0.1:5000/", timeout=3)
    body = response.read().decode("utf-8")
    print(f"[startup] probe status={response.status} body={body}", flush=True)

    server.shutdown()
    thread.join(timeout=3)
    server.server_close()
    print("[startup] minimal probe finished", flush=True)


print("[startup] 7) manage.py module load bottom reached", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TCG Sniper Deals MVP manager")
    sub = parser.add_subparsers(dest="command")

    create_admin_parser = sub.add_parser("create-admin")
    create_admin_parser.add_argument("--email", required=True)
    create_admin_parser.add_argument("--password", required=True)
    create_admin_parser.add_argument("--telegram", default=None)

    sub.add_parser("seed-demo")
    sub.add_parser("test-api-listing")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--port", type=int, default=5000)
    run_parser.add_argument("--host", default="127.0.0.1")
    sub.add_parser("probe-minimal")

    args = parser.parse_args()

    if args.command == "create-admin":
        create_admin(args.email, args.password, args.telegram)
    elif args.command == "seed-demo":
        seed_demo()
    elif args.command == "test-api-listing":
        test_api_listing()
    elif args.command == "probe-minimal":
        run_minimal_probe()
    else:
        run(getattr(args, "port", 5000), getattr(args, "host", "127.0.0.1"))
