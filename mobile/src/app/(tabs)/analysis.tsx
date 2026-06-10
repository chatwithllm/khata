import { useState } from 'react';
import { View } from 'react-native';

import { getHoldVsSell, type HoldVsSellResult } from '@/api/finance';
import { ApiError } from '@/api/client';
import { AppText, Button, Card, Field, Screen } from '@/components/ui';
import { fmt } from '@/money/format';
import { colors, spacing } from '@/theme/tokens';

export default function AnalysisScreen() {
  const [assetValue, setAssetValue] = useState('');
  const [appreciation, setAppreciation] = useState('');
  const [borrow, setBorrow] = useState('');
  const [interest, setInterest] = useState('');
  const [horizon, setHorizon] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<HoldVsSellResult | null>(null);

  async function run() {
    setError(null);
    setBusy(true);
    try {
      const r = await getHoldVsSell({
        asset_value: assetValue,
        appreciation: appreciation || '0',
        borrow: borrow || '0',
        interest: interest || '0',
        horizon: horizon || '0',
      });
      setResult(r);
    } catch (e) {
      setResult(null);
      setError(e instanceof ApiError ? e.message : 'Could not run the analysis.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <AppText variant="heading" style={{ paddingTop: spacing.sm }}>Hold vs Sell</AppText>
      <AppText variant="muted">Borrow against an appreciating asset, or sell it? (amounts in INR)</AppText>

      <Card style={{ gap: spacing.md }}>
        <Field label="Asset value" value={assetValue} onChangeText={setAssetValue} keyboardType="numeric" placeholder="1000000" />
        <Field label="Annual appreciation %" value={appreciation} onChangeText={setAppreciation} keyboardType="numeric" placeholder="8" />
        <Field label="Borrow amount" value={borrow} onChangeText={setBorrow} keyboardType="numeric" placeholder="500000" />
        <Field label="Loan interest %" value={interest} onChangeText={setInterest} keyboardType="numeric" placeholder="9" />
        <Field label="Horizon (months)" value={horizon} onChangeText={setHorizon} keyboardType="numeric" placeholder="24" />
        {error && <AppText style={{ color: colors.neg }}>{error}</AppText>}
        <Button title="Calculate" onPress={run} loading={busy} />
      </Card>

      {result && (
        <Card style={{ gap: spacing.sm }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
            <AppText variant="subhead">Verdict</AppText>
            <View style={{ backgroundColor: result.verdict === 'hold' ? colors.pos : colors.neg, paddingHorizontal: spacing.md, paddingVertical: spacing.xs, borderRadius: 999 }}>
              <AppText style={{ color: '#fff', fontWeight: '700', textTransform: 'uppercase' }}>{result.verdict}</AppText>
            </View>
          </View>
          <Row k="Future value" v={fmt(result.future_value_minor, 'INR')} />
          <Row k="Appreciation gain" v={fmt(result.appreciation_gain_minor, 'INR')} tint={colors.pos} />
          <Row k="Interest cost" v={fmt(result.interest_cost_minor, 'INR')} tint={colors.neg} />
          <Row k="Net hold advantage" v={fmt(result.net_hold_advantage_minor, 'INR')} tint={result.net_hold_advantage_minor >= 0 ? colors.pos : colors.neg} />
        </Card>
      )}
    </Screen>
  );
}

function Row({ k, v, tint }: { k: string; v: string; tint?: string }) {
  return (
    <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
      <AppText variant="muted">{k}</AppText>
      <AppText variant="body" style={{ fontWeight: '700', color: tint ?? colors.ink }}>{v}</AppText>
    </View>
  );
}
