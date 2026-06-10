import { api } from './client';
import type { Dashboard, NetWorth, PlanSummary } from './types';

export function getDashboard() {
  return api<Dashboard>('/api/dashboard');
}

export function getNetWorth() {
  return api<NetWorth>('/api/networth');
}

export function listPlans() {
  return api<{ plans: PlanSummary[] }>('/api/plans');
}

export function getPlan(id: number) {
  return api<{ plan: PlanSummary; state: Record<string, any> }>(`/api/plans/${id}`);
}

export type HoldVsSellResult = {
  asset_value_minor: number;
  borrow_amount_minor: number;
  horizon_months: number;
  future_value_minor: number;
  appreciation_gain_minor: number;
  interest_cost_minor: number;
  net_hold_advantage_minor: number;
  verdict: 'hold' | 'sell';
};

export function getHoldVsSell(params: {
  asset_value: string;
  appreciation: string;
  borrow: string;
  interest: string;
  horizon: string;
}) {
  const qs = new URLSearchParams(params).toString();
  return api<HoldVsSellResult>(`/api/analysis/hold-vs-sell?${qs}`);
}

export function createPlan(body: Record<string, unknown>) {
  return api<{ plan: PlanSummary; state: Record<string, any> }>('/api/plans', { method: 'POST', body });
}

export function setBaseCurrency(currency: 'INR' | 'USD') {
  return api<{ base_currency: string }>('/api/base-currency', { method: 'POST', body: { currency } });
}
