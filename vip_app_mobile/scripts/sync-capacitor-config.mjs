import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const wrapperRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(wrapperRoot, "..");
const vipAppEnvPath = path.join(repoRoot, "vip_app", ".env");
const outputPath = path.join(wrapperRoot, "capacitor.config.json");

function parseEnv(content) {
  const values = {};
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const [key, ...rest] = line.split("=");
    values[key.trim()] = rest.join("=").trim();
  }
  return values;
}

function pickServerUrl(envValues) {
  return (
    envValues.MOBILE_APP_URL ||
    envValues.CAP_SERVER_URL ||
    envValues.SITE_URL ||
    "http://127.0.0.1:5000"
  );
}

const envValues = fs.existsSync(vipAppEnvPath)
  ? parseEnv(fs.readFileSync(vipAppEnvPath, "utf8"))
  : {};

const targetUrl = pickServerUrl(envValues);
const parsedUrl = new URL(targetUrl);
const cleartext = parsedUrl.protocol === "http:";

const config = {
  appId: "com.tcgsniper.deals",
  appName: "TCG Sniper Deals",
  webDir: "web",
  server: {
    url: targetUrl,
    cleartext,
    allowNavigation: [parsedUrl.hostname],
  },
  android: {
    allowMixedContent: cleartext,
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 1400,
      backgroundColor: "#08111d",
      androidSplashResourceName: "splash",
      showSpinner: false,
    },
    StatusBar: {
      style: "DARK",
      backgroundColor: "#08111d",
      overlaysWebView: false,
    },
  },
};

fs.writeFileSync(outputPath, `${JSON.stringify(config, null, 2)}\n`, "utf8");
console.log(`[mobile] capacitor config synced -> ${outputPath}`);
console.log(`[mobile] target app URL -> ${targetUrl}`);
if (cleartext) {
  console.log("[mobile] using HTTP target. This is okay for Android/local testing, but production and iPhone distribution should use HTTPS.");
}
