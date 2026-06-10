/**
 * Native Google sign-in via expo-auth-session. Returns a Google ID token
 * (the `credential`) that we POST to /api/auth/google — the same token the web
 * GIS button produces, so the backend verifier is unchanged.
 *
 * Requires OAuth client IDs from Google Cloud Console, supplied as env vars
 * (EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID / _ANDROID_ / _WEB_). When none are set the
 * hook reports `available: false` and the UI hides the button — email/password
 * still works. See docs/web-to-mobile for setup.
 */
import * as Google from 'expo-auth-session/providers/google';
import * as WebBrowser from 'expo-web-browser';
import { useEffect, useRef, useState } from 'react';

WebBrowser.maybeCompleteAuthSession();

const IOS = process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID;
const ANDROID = process.env.EXPO_PUBLIC_GOOGLE_ANDROID_CLIENT_ID;
const WEB = process.env.EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID;

export function useGoogleSignIn(_webClientIdFromServer: string | null) {
  const available = Boolean(IOS || ANDROID || WEB);
  const [busy, setBusy] = useState(false);

  const [request, response, promptAsync] = Google.useIdTokenAuthRequest({
    iosClientId: IOS,
    androidClientId: ANDROID,
    clientId: WEB,
  });

  // promptAsync resolves with the redirect result, but the id_token lands in
  // `response`; bridge the two with a deferred resolver.
  const resolver = useRef<((cred: string | null) => void) | null>(null);

  useEffect(() => {
    if (!resolver.current) return;
    if (!response) return;
    if (response.type === 'success') {
      resolver.current(response.params?.id_token ?? response.authentication?.idToken ?? null);
    } else {
      resolver.current(null); // dismissed / cancelled / error
    }
    resolver.current = null;
    setBusy(false);
  }, [response]);

  async function signIn(): Promise<string | null> {
    if (!available || !request) return null;
    setBusy(true);
    return new Promise<string | null>((resolve) => {
      resolver.current = resolve;
      promptAsync().catch(() => {
        resolve(null);
        resolver.current = null;
        setBusy(false);
      });
    });
  }

  return { available, busy, signIn };
}
