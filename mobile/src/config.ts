/**
 * Runtime config. The API base URL is injected at build time via an
 * EXPO_PUBLIC_* env var (see .env.example). On a physical device "localhost"
 * is the phone, not your Mac, so dev must point at the Mac's LAN IP.
 */
const DEV_FALLBACK = 'http://192.168.50.189:5057'; // canonical Khata test instance (run-app.sh)

export const API_BASE = (process.env.EXPO_PUBLIC_API_BASE ?? DEV_FALLBACK).replace(/\/$/, '');
