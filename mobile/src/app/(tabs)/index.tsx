import { Ionicons } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { Pressable, RefreshControl, View } from 'react-native';

import { getDashboard } from '@/api/finance';
import type { PlanSummary } from '@/api/types';
import { AppText, Card, EmptyState, ErrorState, Loading, Screen } from '@/components/ui';
import { useAuth } from '@/auth/AuthContext';
import { fmt } from '@/money/format';
import { colors, spacing } from '@/theme/tokens';

const PLAN_ICON: Record<string, keyof typeof Ionicons.glyphMap> = {
  asset: 'cube-outline',
  loan: 'cash-outline',
  holding: 'trending-up-outline',
  chit: 'people-outline',
  retirement: 'umbrella-outline',
};

export default function DashboardScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const q = useQuery({ queryKey: ['dashboard'], queryFn: getDashboard });

  if (q.isLoading) return <Screen scroll={false}><Loading /></Screen>;
  if (q.isError) return <Screen scroll={false}><ErrorState message="Couldn't load your dashboard." onRetry={q.refetch} /></Screen>;

  const d = q.data!;
  const ccy = d.base_currency;

  return (
    <Screen refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} tintColor={colors.primary} />}>
      <View style={{ paddingTop: spacing.sm }}>
        <AppText variant="muted">Welcome back</AppText>
        <AppText variant="heading">{user?.display_name || 'You'}</AppText>
      </View>

      <Card>
        <AppText variant="label">Net position · {ccy}</AppText>
        <AppText
          variant="title"
          style={{ color: d.net_position_minor >= 0 ? colors.pos : colors.neg, marginTop: spacing.xs }}
        >
          {fmt(d.net_position_minor, ccy)}
        </AppText>
        <AppText variant="muted">across all plans</AppText>
      </Card>

      <View style={{ flexDirection: 'row', gap: spacing.md }}>
        <Stat label="Paid to date" value={fmt(d.paid_to_date_minor, ccy)} tint={colors.ink} />
        <Stat label="I owe" value={fmt(d.i_owe_minor, ccy)} tint={colors.neg} />
      </View>
      <View style={{ flexDirection: 'row', gap: spacing.md }}>
        <Stat label="Owed to me" value={fmt(d.owed_to_me_minor, ccy)} tint={colors.pos} />
        <Stat label="Plans" value={String(d.plans.length)} tint={colors.ink} />
      </View>

      <AppText variant="subhead" style={{ marginTop: spacing.md }}>Your plans</AppText>
      {d.plans.length === 0 ? (
        <EmptyState message="No plans yet. Tap + to create one." />
      ) : (
        d.plans.map((p) => <PlanRow key={p.id} plan={p} onPress={() => router.push(`/plan/${p.type}/${p.id}`)} />)
      )}

      <Pressable
        onPress={() => router.push('/create-plan')}
        style={({ pressed }) => [
          {
            marginTop: spacing.md,
            backgroundColor: colors.primary,
            borderRadius: 16,
            height: 52,
            alignItems: 'center',
            justifyContent: 'center',
            flexDirection: 'row',
            gap: spacing.sm,
          },
          pressed && { opacity: 0.85 },
        ]}
      >
        <Ionicons name="add" color="#fff" size={22} />
        <AppText style={{ color: '#fff', fontWeight: '700' }}>New plan</AppText>
      </Pressable>
    </Screen>
  );
}

function Stat({ label, value, tint }: { label: string; value: string; tint: string }) {
  return (
    <Card style={{ flex: 1 }}>
      <AppText variant="label">{label}</AppText>
      <AppText variant="mono" style={{ color: tint, marginTop: spacing.xs }} numberOfLines={1} adjustsFontSizeToFit>
        {value}
      </AppText>
    </Card>
  );
}

function PlanRow({ plan, onPress }: { plan: PlanSummary; onPress: () => void }) {
  return (
    <Pressable onPress={onPress}>
      {({ pressed }) => (
        <Card style={[{ flexDirection: 'row', alignItems: 'center', gap: spacing.md }, pressed && { opacity: 0.85 }]}>
          <View
            style={{
              width: 40,
              height: 40,
              borderRadius: 12,
              backgroundColor: colors.glow,
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Ionicons name={PLAN_ICON[plan.type] ?? 'document-outline'} color={colors.primary} size={20} />
          </View>
          <View style={{ flex: 1 }}>
            <AppText variant="body" style={{ fontWeight: '600' }} numberOfLines={1}>
              {plan.name}
            </AppText>
            <AppText variant="muted">
              {plan.type} · {plan.currency}
              {plan.role === 'member' ? ' · shared' : ''}
            </AppText>
          </View>
          <Ionicons name="chevron-forward" color={colors.inkFaint} size={18} />
        </Card>
      )}
    </Pressable>
  );
}
