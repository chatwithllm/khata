import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, View } from 'react-native';

import * as authApi from '@/api/auth';
import { ApiError } from '@/api/client';
import { useGoogleSignIn } from '@/auth/useGoogleSignIn';
import { useAuth } from '@/auth/AuthContext';
import { AppText, Button, Card, Field, Screen } from '@/components/ui';
import { colors, spacing } from '@/theme/tokens';

const ERRORS: Record<string, string> = {
  invalid_credentials: 'Wrong email or password.',
  email_taken: 'That email is already registered.',
  email_unverified: 'Your Google email is not verified.',
  invalid_token: 'Google sign-in failed. Try again.',
};

export default function LoginScreen() {
  const { signIn } = useAuth();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: cfg } = useQuery({ queryKey: ['authConfig'], queryFn: authApi.getAuthConfig });
  const google = useGoogleSignIn(cfg?.google_client_id ?? null);

  function show(e: unknown) {
    const code = e instanceof ApiError ? e.code : undefined;
    setError((code && ERRORS[code]) || 'Something went wrong. Check your connection.');
  }

  async function submit() {
    setError(null);
    setBusy(true);
    try {
      await signIn(() =>
        mode === 'login'
          ? authApi.login(email.trim(), password)
          : authApi.register(email.trim(), name.trim(), password),
      );
    } catch (e) {
      show(e);
    } finally {
      setBusy(false);
    }
  }

  async function googlePress() {
    setError(null);
    try {
      const credential = await google.signIn();
      if (!credential) return; // user cancelled
      await signIn(() => authApi.loginWithGoogle(credential));
    } catch (e) {
      show(e);
    }
  }

  return (
    <Screen>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={{ paddingTop: spacing.xxl, paddingBottom: spacing.lg }}>
          <AppText variant="title" style={{ color: colors.primary }}>
            Khata
          </AppText>
          <AppText variant="muted">Your money, plan by plan.</AppText>
        </View>

        <Card style={{ gap: spacing.md }}>
          <AppText variant="subhead">{mode === 'login' ? 'Sign in' : 'Create account'}</AppText>

          {mode === 'register' && (
            <Field label="Name" value={name} onChangeText={setName} autoCapitalize="words" placeholder="Your name" />
          )}
          <Field
            label="Email"
            value={email}
            onChangeText={setEmail}
            autoCapitalize="none"
            keyboardType="email-address"
            autoComplete="email"
            placeholder="you@example.com"
          />
          <Field
            label="Password"
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            placeholder="••••••••"
          />

          {error && <AppText style={{ color: colors.neg }}>{error}</AppText>}

          <Button title={mode === 'login' ? 'Sign in' : 'Create account'} onPress={submit} loading={busy} />

          {cfg?.google_client_id && google.available && (
            <Button title="Continue with Google" variant="ghost" onPress={googlePress} loading={google.busy} />
          )}

          <Button
            title={mode === 'login' ? "New here? Create an account" : 'Have an account? Sign in'}
            variant="ghost"
            onPress={() => {
              setError(null);
              setMode(mode === 'login' ? 'register' : 'login');
            }}
          />
        </Card>
      </KeyboardAvoidingView>
    </Screen>
  );
}
