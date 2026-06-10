import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { Pressable, RefreshControl, View } from 'react-native';

import { listPlans } from '@/api/finance';
import { AppText, Card, EmptyState, ErrorState, Loading, Screen } from '@/components/ui';
import { fmt } from '@/money/format';
import { colors, spacing } from '@/theme/tokens';

export default function HoldingsScreen() {
  const router = useRouter();
  const q = useQuery({ queryKey: ['plans'], queryFn: listPlans });

  if (q.isLoading) return <Screen scroll={false}><Loading /></Screen>;
  if (q.isError) return <Screen scroll={false}><ErrorState message="Couldn't load holdings." onRetry={q.refetch} /></Screen>;

  const holdings = q.data!.plans.filter((p) => p.type === 'holding');

  return (
    <Screen refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} tintColor={colors.primary} />}>
      <AppText variant="heading" style={{ paddingTop: spacing.sm }}>Holdings</AppText>

      {holdings.length === 0 ? (
        <EmptyState message="No holdings yet. Create a holding plan to track investments." />
      ) : (
        holdings.map((h) => {
          const price = h.current_price_minor as number | null;
          return (
            <Pressable key={h.id} onPress={() => router.push(`/plan/holding/${h.id}`)}>
              {({ pressed }) => (
                <Card style={[{ flexDirection: 'row', alignItems: 'center' }, pressed && { opacity: 0.85 }]}>
                  <View style={{ flex: 1 }}>
                    <AppText variant="body" style={{ fontWeight: '600' }} numberOfLines={1}>{h.name}</AppText>
                    <AppText variant="muted">
                      {String(h.asset_class ?? 'asset')}{h.symbol ? ` · ${h.symbol}` : ''} · {h.currency}
                    </AppText>
                  </View>
                  <AppText variant="body" style={{ fontWeight: '700' }}>
                    {price != null ? fmt(price, h.currency) : '—'}
                  </AppText>
                </Card>
              )}
            </Pressable>
          );
        })
      )}
    </Screen>
  );
}
