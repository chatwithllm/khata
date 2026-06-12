/**
 * Runtime config. The API base URL is injected at build time via an
 * EXPO_PUBLIC_* env var (see .env.example). On a physical device "localhost"
 * is the phone, not your Mac, so dev must point at the Mac's LAN IP.
 */
const DEV_FALLBACK = 'http://192.168.50.189:5057'; // canonical Khata test instance (run-app.sh)
const PROD_DEFAULT = 'https://khata.npalakurla.com'; // public server (CORS * + bearer auth)

// EXPO_PUBLIC_API_BASE always wins. Otherwise: LAN box in dev, prod domain in a release build.
export const API_BASE = (
  process.env.EXPO_PUBLIC_API_BASE ?? (__DEV__ ? DEV_FALLBACK : PROD_DEFAULT)
).replace(/\/$/, '');
