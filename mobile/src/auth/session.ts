/**
 * Bearer-token persistence. The Flask API hands back a signed token on
 * login/register/google; we keep it in the device Keychain/Keystore via
 * expo-secure-store so it survives app restarts and never lands in plain
 * storage. An in-memory mirror avoids an async read on every API call.
 */
import * as SecureStore from 'expo-secure-store';

const KEY = 'khata.authToken';

let cached: string | null = null;

export async function loadToken(): Promise<string | null> {
  if (cached !== null) return cached;
  cached = (await SecureStore.getItemAsync(KEY)) ?? null;
  return cached;
}

export function peekToken(): string | null {
  return cached;
}

export async function setToken(token: string): Promise<void> {
  cached = token;
  await SecureStore.setItemAsync(KEY, token);
}

export async function clearToken(): Promise<void> {
  cached = null;
  await SecureStore.deleteItemAsync(KEY);
}
