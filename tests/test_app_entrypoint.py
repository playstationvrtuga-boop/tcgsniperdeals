import json
import os
import tempfile
import unittest
from pathlib import Path

from vip_app.app import create_app
from vip_app.app.config import Config
from vip_app.app.extensions import db


REPO_ROOT = Path(__file__).resolve().parents[1]


class AppEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "app_entrypoint.db"
        test_db_uri = f"sqlite:///{db_path.as_posix()}"
        os.environ["DATABASE_URL"] = test_db_uri
        os.environ["RUN_DB_CREATE_ALL"] = "true"
        os.environ["RUN_STARTUP_SCHEMA_CHECK"] = "false"
        Config.SQLALCHEMY_DATABASE_URI = test_db_uri
        Config.SQLALCHEMY_ENGINE_OPTIONS = {}
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, PUBLIC_SITE_URL="https://tcgsniperdeals.com")
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.ctx.pop()
        self.tmpdir.cleanup()

    def test_public_homepage_stays_public_website(self):
        response = self.client.get("/")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Real-time Pokemon TCG deals", body)
        self.assertIn("Explore Live Pok", body)
        self.assertIn('rel="manifest" href="/manifest.webmanifest?v=pwa-app-v10"', body)

    def test_app_entrypoint_redirects_to_dashboard_flow(self):
        response = self.client.get("/app")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/eu-deals")

    def test_app_entrypoint_reaches_login_or_dashboard_experience(self):
        response = self.client.get("/app", follow_redirects=True)
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("TCG Sniper Deals", body)
        self.assertNotIn("Real-time Pokemon TCG deals", body)

    def test_manifest_starts_installed_pwa_at_app_entrypoint(self):
        response = self.client.get("/manifest.webmanifest")
        manifest = json.loads(response.get_data(as_text=True))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/manifest+json")
        self.assertIn("no-cache", response.headers["Cache-Control"])
        self.assertEqual(manifest["name"], "TCG Sniper Deals")
        self.assertEqual(manifest["short_name"], "TCG Sniper")
        self.assertEqual(manifest["id"], "/app")
        self.assertEqual(manifest["start_url"], "/app")
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["display_override"], ["standalone", "fullscreen"])
        self.assertEqual(manifest["theme_color"], "#0f172a")
        self.assertEqual(manifest["background_color"], "#07111f")
        response.close()

    def test_manifest_icons_are_accessible_pngs(self):
        response = self.client.get("/manifest.webmanifest")
        manifest = json.loads(response.get_data(as_text=True))
        response.close()

        for icon in manifest["icons"]:
            with self.subTest(icon=icon["src"]):
                icon_response = self.client.get(icon["src"])
                icon_body = icon_response.get_data()
                self.assertEqual(icon_response.status_code, 200)
                self.assertEqual(icon_response.mimetype, "image/png")
                self.assertGreater(len(icon_body), 0)
                icon_response.close()

    def test_service_worker_scope_and_navigation_cache_behavior(self):
        response = self.client.get("/service-worker.js")
        source = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/javascript")
        self.assertEqual(response.headers["Service-Worker-Allowed"], "/")
        self.assertIn("tcg-sniper-deals-v10-pwa-app-entry", source)
        self.assertIn('"/manifest.webmanifest"', source)
        self.assertIn('"manifest"', source)
        navigation_branch = source.split('if (request.mode === "navigate") {', 1)[1].split("if (mustRefresh)", 1)[0]
        self.assertNotIn("caches.match(request)", navigation_branch)
        self.assertIn("caches.match(OFFLINE_URL)", navigation_branch)
        self.assertNotIn('"/"', source)
        response.close()

    def test_capacitor_android_configs_launch_app_entrypoint(self):
        source_config = json.loads((REPO_ROOT / "vip_app_mobile" / "capacitor.config.json").read_text())
        sync_script = (REPO_ROOT / "vip_app_mobile" / "scripts" / "sync-capacitor-config.mjs").read_text()

        self.assertEqual(source_config["server"]["url"], "https://tcgsniperdeals.com/app")
        self.assertIn('"https://tcgsniperdeals.com/app"', sync_script)
        self.assertIn('parsedUrl.pathname = "/app"', sync_script)

        generated_android_config_path = (
            REPO_ROOT / "vip_app_mobile" / "android" / "app" / "src" / "main" / "assets" / "capacitor.config.json"
        )
        if generated_android_config_path.exists():
            android_config = json.loads(generated_android_config_path.read_text())
            self.assertEqual(android_config["server"]["url"], "https://tcgsniperdeals.com/app")


if __name__ == "__main__":
    unittest.main()
