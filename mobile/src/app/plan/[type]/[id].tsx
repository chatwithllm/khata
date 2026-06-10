import { Ionicons } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { Pressable, View } from 'react-native';

import { getPlan } from '@/api/finance';
import { AppText, Card, ErrorState, Loading, Screen } from '@/components/ui';
import { fmt } from '@/money/format';
import { colors, spacing } from '@/theme/tokens';

export default function PlanDetailScreen() {
  const { id } = useLocalSearchParams<{ type: string; id: string }>();
  const router = useRouter();
  const planId = Number(id);
  const q = useQuery({ queryKey: ['plan', planId], queryFn: () => getPlan(planId), enabled: Number.isFinite(planId) });

  if (q.isLoading) return <Screen scroll={false}><Loading /></Screen>;
  if (q.isError) return <Screen scroll={false}><ErrorState message="Couldn't load this plan." onRetry={q.refetch} /></Screen>;

  const { plan, state } = q.data!;
  const ccy = plan.currency;

  return (
    <Screen>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingTop: spacing.sm }}>
        <Pressable onPress={() => router.back()} hitSlop={12}>
          <Ionicons name="chevron-back" size={26} color={colors.ink} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <AppText variant="heading" numberOfLines={1}>{plan.name}</AppText>
          <AppText variant="muted">{plan.type} · {ccy}{plan.status ? ` · ${plan.status}` : ''}</AppText>
        </View>
      </View>

      <Card style={{ gap: spacing.sm }}>
        <AppText variant="subhead">Summary</AppText>
        {prettyRows(state, ccy).map((r) => (
          <View key={r.key} style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <AppText variant="muted" style={{ flex: 1 }}>{r.label}</AppText>
            <AppText variant="body" style={{ fontWeight: '600', color: r.tint ?? colors.ink, flexShrink: 0 }}>{r.value}</AppText>
          </View>
        ))}
        {prettyRows(state, ccy).length === 0 && <AppText variant="muted">No derived state.</AppText>}
      </Card>

      {Array.isArray((state as any).entries) && (state as any).entries.length > 0 && (
        <>
          <AppText variant="subhead" style={{ marginTop: spacing.md }}>Entries</AppText>
          {(state as any).entries.slice(0, 50).map((e: any, i: number) => (
            <Card key={e.id ?? i} style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
              <View style={{ flex: 1 }}>
                <AppText variant="body" style={{ fontWeight: '600' }}>{e.note || e.kind || e.method || 'Entry'}</AppText>
                {e.occurred_at && <AppText variant="muted">{String(e.occurred_at).slice(0, 10)}</AppText>}
              </View>
              {e.amount_minor != null && (
                <AppText variant="body" style={{ fontWeight: '700', color: e.direction === 'out' ? colors.neg : colors.pos }}>
                  {fmt(e.amount_minor, ccy)}
                </AppText>
              )}
            </Card>
          ))}
        </>
      )}

      <Card>
        <AppText variant="muted">
          Full editing (payments, entries, sharing) for {plan.type} plans is in the web app. This v1 mobile detail is read-only.
        </AppText>
      </Card>
      <View style={{ height: spacing.xxl }} />
    </Screen>
  );
}

// Render a derived-state object as labelled rows, formatting by key suffix:
// *_minor → money, *_micro → quantity, *_bps → percent.
function prettyRows(state: Record<string, any>, ccy: string) {
  const rows: { key: string; label: string; value: string; tint?: string }[] = [];
  for (const [key, val] of Object.entries(state ?? {})) {
    if (val == null || typeof val === 'object') continue;
    const label = key.replace(/_(minor|micro|bps)$/, '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
    if (key.endsWith('_minor')) {
      rows.push({ key, label, value: fmt(val as number, ccy), tint: (val as number) < 0 ? colors.neg : undefined });
    } else if (key.endsWith('_micro')) {
      rows.push({ key, label, value: ((val as number) / 1e6).toLocaleString() });
    } else if (key.endsWith('_bps')) {
      rows.push({ key, label, value: `${((val as number) / 100).toFixed(2)}%` });
    } else if (typeof val === 'boolean') {
      rows.push({ key, label, value: val ? 'Yes' : 'No' });
    } else {
      rows.push({ key, label, value: String(val) });
    }
  }
  return rows;
}
