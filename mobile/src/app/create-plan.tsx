import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, View } from 'react-native';

import { createPlan } from '@/api/finance';
import { ApiError } from '@/api/client';
import type { PlanType } from '@/api/types';
import { AppText, Button, Card, Field, Screen } from '@/components/ui';
import { colors, radius, spacing } from '@/theme/tokens';

const TYPES: { key: PlanType; label: string }[] = [
  { key: 'asset', label: 'Asset' },
  { key: 'loan', label: 'Loan' },
  { key: 'holding', label: 'Holding' },
  { key: 'chit', label: 'Chit' },
  { key: 'retirement', label: 'Retirement' },
];

export default function CreatePlanScreen() {
  const router = useRouter();
  const qc = useQueryClient();
  const [type, setType] = useState<PlanType>('asset');
  const [currency, setCurrency] = useState<'INR' | 'USD'>('INR');
  const [f, setF] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (k: string) => (v: string) => setF((p) => ({ ...p, [k]: v }));

  async function submit() {
    setError(null);
    if (!(f.name || '').trim()) return setError('Name is required.');
    setBusy(true);
    try {
      await createPlan({ ...f, type, currency });
      qc.invalidateQueries({ queryKey: ['dashboard'] });
      qc.invalidateQueries({ queryKey: ['plans'] });
      qc.invalidateQueries({ queryKey: ['networth'] });
      router.back();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not create the plan.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingTop: spacing.sm }}>
        <AppText variant="heading">New plan</AppText>
        <Pressable onPress={() => router.back()} hitSlop={12}>
          <AppText style={{ color: colors.primary, fontWeight: '700' }}>Cancel</AppText>
        </Pressable>
      </View>

      <Card style={{ gap: spacing.md }}>
        <AppText variant="label">Type</AppText>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>
          {TYPES.map((t) => (
            <Chip key={t.key} label={t.label} active={type === t.key} onPress={() => setType(t.key)} />
          ))}
        </View>

        <Field label="Name" value={f.name ?? ''} onChangeText={set('name')} placeholder="e.g. Gold loan" />

        <AppText variant="label">Currency</AppText>
        <View style={{ flexDirection: 'row', gap: spacing.sm }}>
          {(['INR', 'USD'] as const).map((c) => (
            <Chip key={c} label={c} active={currency === c} onPress={() => setCurrency(c)} />
          ))}
        </View>

        {type === 'asset' && (
          <Field label="Total price" value={f.total_price ?? ''} onChangeText={set('total_price')} keyboardType="numeric" placeholder="500000" />
        )}

        {type === 'loan' && (
          <>
            <AppText variant="label">Direction</AppText>
            <View style={{ flexDirection: 'row', gap: spacing.sm }}>
              <Chip label="Taken (I borrowed)" active={f.direction === 'taken'} onPress={() => set('direction')('taken')} />
              <Chip label="Given (I lent)" active={f.direction === 'given'} onPress={() => set('direction')('given')} />
            </View>
            <Field label="Counterparty" value={f.counterparty ?? ''} onChangeText={set('counterparty')} placeholder="Bank / person" />
            <Field label="Tenure (months, optional)" value={f.tenure_months ?? ''} onChangeText={set('tenure_months')} keyboardType="numeric" placeholder="24" />
          </>
        )}

        {type === 'holding' && (
          <>
            <Field label="Asset class" value={f.asset_class ?? ''} onChangeText={set('asset_class')} placeholder="gold / stock / crypto" />
            <Field label="Unit" value={f.unit ?? ''} onChangeText={set('unit')} placeholder="grams / shares" />
            <Field label="Symbol (optional)" value={f.symbol ?? ''} onChangeText={set('symbol')} placeholder="AAPL" autoCapitalize="characters" />
          </>
        )}

        {type === 'chit' && (
          <>
            <Field label="Chit value" value={f.chit_value ?? ''} onChangeText={set('chit_value')} keyboardType="numeric" placeholder="1000000" />
            <Field label="Members" value={f.n_members ?? ''} onChangeText={set('n_members')} keyboardType="numeric" placeholder="20" />
            <Field label="Commission %" value={f.commission ?? ''} onChangeText={set('commission')} keyboardType="numeric" placeholder="5" />
          </>
        )}

        {type === 'retirement' && (
          <>
            <Field label="Current age" value={f.current_age ?? ''} onChangeText={set('current_age')} keyboardType="numeric" placeholder="30" />
            <Field label="Retirement age" value={f.retirement_age ?? ''} onChangeText={set('retirement_age')} keyboardType="numeric" placeholder="60" />
            <Field label="Current balance" value={f.current_balance ?? ''} onChangeText={set('current_balance')} keyboardType="numeric" placeholder="0" />
            <Field label="Monthly contribution" value={f.monthly_contribution ?? ''} onChangeText={set('monthly_contribution')} keyboardType="numeric" placeholder="20000" />
          </>
        )}

        {error && <AppText style={{ color: colors.neg }}>{error}</AppText>}
        <Button title="Create plan" onPress={submit} loading={busy} />
      </Card>
      <View style={{ height: spacing.xxl }} />
    </Screen>
  );
}

function Chip({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable
      onPress={onPress}
      style={{
        paddingHorizontal: spacing.md,
        paddingVertical: spacing.sm,
        borderRadius: radius.pill,
        borderWidth: 1,
        borderColor: active ? colors.primary : colors.line,
        backgroundColor: active ? colors.primary : 'transparent',
      }}
    >
      <AppText style={{ color: active ? '#fff' : colors.inkSoft, fontWeight: '600', fontSize: 13 }}>{label}</AppText>
    </Pressable>
  );
}
