// Shapes mirrored from the Flask API (src/khata/api/*). Kept minimal — extended
// as screens consume more fields. `[from-code]` _user_json + jsonify payloads.

export type User = {
  id: number;
  email: string;
  display_name: string;
  has_password: boolean;
  avatar: string | null;
};

export type AuthResponse = {
  user: User;
  token: string;
  created?: boolean;
};

export type MeResponse = {
  user: User;
  is_operator: boolean;
};

export type PlanType = 'asset' | 'loan' | 'holding' | 'chit' | 'retirement';

export type PlanSummary = {
  id: number;
  type: PlanType;
  name: string;
  currency: string;
  status?: string;
  role?: 'owner' | 'member';
  // type-specific fields (loan/holding/chit/...) arrive too; read as needed
  [k: string]: unknown;
};

export type Dashboard = {
  base_currency: string;
  net_position_minor: number;
  i_owe_minor: number;
  owed_to_me_minor: number;
  paid_to_date_minor: number;
  unconverted: Record<string, Record<string, number>>;
  plans: PlanSummary[];
};

export type HoldingRow = {
  id: number;
  name: string;
  asset_class: string;
  currency: string;
  qty_held_micro: number;
  current_value_minor: number | null;
  value_in_base_minor: number | null;
  unrealized_gain_minor: number | null;
  priced: boolean;
};

export type NetWorth = {
  base_currency: string;
  assets_minor: number;
  liabilities_minor: number;
  net_worth_minor: number;
  holdings: HoldingRow[];
  unpriced: { id: number; name: string; asset_class: string }[];
  unconverted: Record<string, Record<string, number>>;
};
