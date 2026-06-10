import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Alert, View } from 'react-native';

import * as authApi from '@/api/auth';
import { setBaseCurrency } from '@/api/finance';
import { useAuth } from '@/auth/AuthContext';
import { AppText, Button, Card, Field, Screen } from '@/components/ui';
import { API_BASE } from '@/config';
import { colors, radius, spacing } from '@/theme/tokens';

export default function SettingsScreen() {
  const { user, signOut, setUser } = useAuth();
  const qc = useQueryClient();
  const [name, setName] = useState(user?.display_name ?? '');
  const [savingName, setSavingName] = useState(false);

  async function saveName() {
    setSavingName(true);
    try {
      const { user: updated } = await authApi.updateProfile(name.trim());
      setUser(updated);
      Alert.alert('Saved', 'Your name was updated.');
    } catch {
      Alert.alert('Error', 'Could not update your name.');
    } finally {
      setSavingName(false);
    }
  }

  async function pickCurrency(ccy: 'INR' | 'USD') {
    try {
      await setBaseCurrency(ccy);
      qc.invalidateQueries({ queryKey: ['dashboard'] });
      qc.invalidateQueries({ queryKey: ['networth'] });
      Alert.alert('Base currency', `Now showing totals in ${ccy}.`);
    } catch {
      Alert.alert('Error', 'Could not change base currency.');
    }
  }

  return (
    <Screen>
      <AppText variant="heading" style={{ paddingTop: spacing.sm }}>Settings</AppText>

      <Card style={{ gap: spacing.md }}>
        <AppText variant="subhead">Profile</AppText>
        <AppText variant="muted">{user?.email}</AppText>
        <Field label="Display name" value={name} onChangeText={setName} autoCapitalize="words" />
        <Button title="Save name" onPress={saveName} loading={savingName} disabled={!name.trim() || name.trim() === user?.display_name} />
      </Card>

      <Card style={{ gap: spacing.md }}>
        <AppText variant="subhead">Base currency</AppText>
        <AppText variant="muted">All cross-plan totals are shown in this currency.</AppText>
        <View style={{ flexDirection: 'row', gap: spacing.md }}>
          {(['INR', 'USD'] as const).map((c) => (
            <View key={c} style={{ flex: 1 }}>
              <Button title={c} variant="ghost" onPress={() => pickCurrency(c)} />
            </View>
          ))}
        </View>
      </Card>

      <Card style={{ gap: spacing.sm }}>
        <AppText variant="subhead">About</AppText>
        <AppText variant="muted">API: {API_BASE}</AppText>
        <AppText variant="muted">Khata mobile · v1</AppText>
      </Card>

      <View style={{ marginTop: spacing.md, borderRadius: radius.md, overflow: 'hidden' }}>
        <Button title="Log out" variant="ghost" onPress={signOut} />
      </View>
      <View style={{ height: spacing.xxl }} />
    </Screen>
  );
}
