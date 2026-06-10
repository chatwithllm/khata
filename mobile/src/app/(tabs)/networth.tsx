import { useQuery } from '@tanstack/react-query';
import { RefreshControl, View } from 'react-native';

import { getNetWorth } from '@/api/finance';
import { AppText, Card, ErrorState, Loading, Screen } from '@/components/ui';
import { fmt } from '@/money/format';
import { colors, spacing } from '@/theme/tokens';

export default function NetWorthScreen() {
  const q = useQuery({ queryKey: ['networth'], queryFn: getNetWorth });

  if (q.isLoading) return <Screen scroll={false}><Loading /></Screen>;
  if (q.isError) return <Screen scroll={false}><ErrorState message="Couldn't load net worth." onRetry={q.refetch} /></Screen>;

  const d = q.data!;
  const ccy = d.base_currency;

  return (
    <Screen refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={q.refetch} tintColor={colors.primary} />}>
      <AppText variant="heading" style={{ paddingTop: spacing.sm }}>Net Worth</AppText>

      <Card>
        <AppText variant="label">Net worth · {ccy}</AppText>
        <AppText variant="title" style={{ color: d.net_worth_minor >= 0 ? colors.pos : colors.neg, marginTop: spacing.xs }}>
          {fmt(d.net_worth_minor, ccy)}
        </AppText>
      </Card>

      <View style={{ flexDirection: 'row', gap: spacing.md }}>
        <Card style={{ flex: 1 }}>
          <AppText variant="label">Assets</AppText>
          <AppText variant="mono" style={{ color: colors.pos, marginTop: spacing.xs }} numberOfLines={1} adjustsFontSizeToFit>
            {fmt(d.assets_minor, ccy)}
          </AppText>
        </Card>
        <Card style={{ flex: 1 }}>
          <AppText variant="label">Liabilities</AppText>
          <AppText variant="mono" style={{ color: colors.neg, marginTop: spacing.xs }} numberOfLines={1} adjustsFontSizeToFit>
            {fmt(d.liabilities_minor, ccy)}
          </AppText>
        </Card>
      </View>

      {d.holdings.length > 0 && (
        <>
          <AppText variant="subhead" style={{ marginTop: spacing.md }}>Holdings</AppText>
          {d.holdings.map((h) => (
            <Card key={h.id} style={{ flexDirection: 'row', alignItems: 'center' }}>
              <View style={{ flex: 1 }}>
                <AppText variant="body" style={{ fontWeight: '600' }} numberOfLines={1}>{h.name}</AppText>
                <AppText variant="muted">{h.asset_class} · {h.currency}{h.priced ? '' : ' · unpriced'}</AppText>
              </View>
              <View style={{ alignItems: 'flex-end' }}>
                <AppText variant="body" style={{ fontWeight: '700' }}>
                  {h.value_in_base_minor != null ? fmt(h.value_in_base_minor, ccy) : (h.current_value_minor != null ? fmt(h.current_value_minor, h.currency) : '—')}
                </AppText>
                {h.unrealized_gain_minor != null && (
                  <AppText variant="muted" style={{ color: h.unrealized_gain_minor >= 0 ? colors.pos : colors.neg }}>
                    {h.unrealized_gain_minor >= 0 ? '▲' : '▼'} {fmt(Math.abs(h.unrealized_gain_minor), h.currency)}
                  </AppText>
                )}
              </View>
            </Card>
          ))}
        </>
      )}

      {Object.keys(d.unconverted).length > 0 && (
        <Card>
          <AppText variant="label" style={{ color: colors.neg }}>Unconverted (no FX rate)</AppText>
          {Object.entries(d.unconverted).map(([c, b]) => (
            <AppText key={c} variant="muted">
              {c}: assets {fmt(b.assets_minor ?? 0, c)} · liabilities {fmt(b.liabilities_minor ?? 0, c)}
            </AppText>
          ))}
        </Card>
      )}
    </Screen>
  );
}
