import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { ActivityIndicator, Alert, Image, Pressable, View } from 'react-native';

import * as authApi from '@/api/auth';
import { exportBackup, restoreBackup } from '@/api/backup';
import { setBaseCurrency } from '@/api/finance';
import { useAuth } from '@/auth/AuthContext';
import { AppText, Button, Card, Field, Screen } from '@/components/ui';
import { API_BASE } from '@/config';
import { pickAvatar } from '@/native/avatar';
import { pickBackupFile, shareBackup } from '@/native/backup';
import { colors, radius, spacing } from '@/theme/tokens';

export default function SettingsScreen() {
  const { user, isOperator, signOut, setUser } = useAuth();
  const qc = useQueryClient();
  const [name, setName] = useState(user?.display_name ?? '');
  const [savingName, setSavingName] = useState(false);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const [backupBusy, setBackupBusy] = useState(false);

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

  async function changeAvatar() {
    setAvatarBusy(true);
    try {
      const r = await pickAvatar();
      if (!r.ok) {
        if (r.reason === 'permission') Alert.alert('Permission needed', 'Allow photo access to set an avatar.');
        else if (r.reason === 'too_large') Alert.alert('Too large', 'Could not shrink that image enough — try another.');
        return;
      }
      const { user: updated } = await authApi.setAvatar(r.dataUrl);
      setUser(updated);
    } catch {
      Alert.alert('Error', 'Could not update your photo.');
    } finally {
      setAvatarBusy(false);
    }
  }

  async function removeAvatar() {
    setAvatarBusy(true);
    try {
      const { user: updated } = await authApi.setAvatar(null);
      setUser(updated);
    } catch {
      Alert.alert('Error', 'Could not remove your photo.');
    } finally {
      setAvatarBusy(false);
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

  async function doExport() {
    setBackupBusy(true);
    try {
      const data = await exportBackup();
      const shared = await shareBackup(data);
      if (!shared) Alert.alert('Unavailable', 'Sharing is not available on this device.');
    } catch {
      Alert.alert('Error', 'Backup failed. Operator access is required.');
    } finally {
      setBackupBusy(false);
    }
  }

  function doRestore() {
    Alert.alert(
      'Restore backup?',
      'This merges the chosen backup into the live instance. A pre-restore snapshot is saved first.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Choose file',
          style: 'destructive',
          onPress: async () => {
            setBackupBusy(true);
            try {
              const data = await pickBackupFile();
              if (!data) return;
              const res = await restoreBackup(data);
              qc.invalidateQueries();
              Alert.alert('Restored', `Done. Pre-restore snapshot ${res.pre_restore_saved ? 'saved' : 'NOT saved'}.`);
            } catch {
              Alert.alert('Error', 'Restore failed — invalid file or insufficient access.');
            } finally {
              setBackupBusy(false);
            }
          },
        },
      ],
    );
  }

  return (
    <Screen>
      <AppText variant="heading" style={{ paddingTop: spacing.sm }}>Settings</AppText>

      <Card style={{ gap: spacing.md }}>
        <AppText variant="subhead">Profile</AppText>

        <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.md }}>
          <Pressable onPress={changeAvatar} disabled={avatarBusy}>
            <View style={styles_avatar}>
              {avatarBusy ? (
                <ActivityIndicator color={colors.primary} />
              ) : user?.avatar ? (
                <Image source={{ uri: user.avatar }} style={{ width: 64, height: 64, borderRadius: 32 }} />
              ) : (
                <AppText variant="heading" style={{ color: colors.primary }}>
                  {(user?.display_name || user?.email || '?').slice(0, 1).toUpperCase()}
                </AppText>
              )}
            </View>
          </Pressable>
          <View style={{ flex: 1 }}>
            <AppText variant="body" style={{ fontWeight: '600' }}>{user?.display_name}</AppText>
            <AppText variant="muted">{user?.email}</AppText>
            <View style={{ flexDirection: 'row', gap: spacing.md, marginTop: spacing.xs }}>
              <Pressable onPress={changeAvatar} disabled={avatarBusy}>
                <AppText style={{ color: colors.primary, fontWeight: '600', fontSize: 13 }}>Change photo</AppText>
              </Pressable>
              {user?.avatar && (
                <Pressable onPress={removeAvatar} disabled={avatarBusy}>
                  <AppText style={{ color: colors.neg, fontWeight: '600', fontSize: 13 }}>Remove</AppText>
                </Pressable>
              )}
            </View>
          </View>
        </View>

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

      {isOperator && (
        <Card style={{ gap: spacing.md }}>
          <AppText variant="subhead">Backup & restore</AppText>
          <AppText variant="muted">Whole-instance snapshot. Operator only.</AppText>
          {backupBusy && <ActivityIndicator color={colors.primary} />}
          <Button title="Export backup" variant="ghost" onPress={doExport} disabled={backupBusy} />
          <Button title="Restore from file" variant="ghost" onPress={doRestore} disabled={backupBusy} />
        </Card>
      )}

      <Card style={{ gap: spacing.sm }}>
        <AppText variant="subhead">About</AppText>
        <AppText variant="muted">API: {API_BASE}</AppText>
        <AppText variant="muted">Khata mobile · v1.1</AppText>
      </Card>

      <View style={{ marginTop: spacing.md, borderRadius: radius.md, overflow: 'hidden' }}>
        <Button title="Log out" variant="ghost" onPress={signOut} />
      </View>
      <View style={{ height: spacing.xxl }} />
    </Screen>
  );
}

const styles_avatar = {
  width: 64,
  height: 64,
  borderRadius: 32,
  backgroundColor: colors.glow,
  alignItems: 'center' as const,
  justifyContent: 'center' as const,
  borderWidth: 1,
  borderColor: colors.line,
  overflow: 'hidden' as const,
};
