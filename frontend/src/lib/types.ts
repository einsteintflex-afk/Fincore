export type Money = string;

export interface User {
  id: string;
  email: string;
  phone: string | null;
  full_name: string;
  role: string;
  status: string;
  kyc_tier: number;
  email_verified: boolean;
  totp_enabled: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface Wallet {
  id: string;
  account_number: string;
  currency: string;
  label: string;
  is_default: boolean;
  status: string;
  balance: Money;
  created_at: string;
}

export interface Transaction {
  id: string;
  reference: string;
  type: string;
  status: string;
  channel: string;
  amount: Money;
  fee: Money;
  currency: string;
  provider: string | null;
  provider_mode: string;
  provider_reference: string | null;
  counterparty: Record<string, any>;
  description: string;
  failure_reason: string | null;
  risk_score: number;
  created_at: string;
  completed_at: string | null;
  direction?: "in" | "out" | null;
  source_wallet_id: string | null;
  destination_wallet_id: string | null;
  business_id: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Business {
  id: string;
  name: string;
  trading_name: string | null;
  business_type: string;
  industry: string | null;
  email: string;
  phone: string | null;
  address: string | null;
  website: string | null;
  registration_number: string | null;
  tin: string | null;
  status: string;
  review_note: string | null;
  merchant_code: string;
  settlement_schedule: string;
  settlement_destination: Record<string, any>;
  created_at: string;
  my_role: string | null;
}

export interface PaymentRequest {
  id: string;
  reference: string;
  merchant_reference: string | null;
  environment: string;
  amount: Money;
  currency: string;
  fee: Money;
  amount_refunded: Money;
  status: string;
  description: string | null;
  customer_name: string | null;
  customer_email: string | null;
  customer_phone: string | null;
  channel: string | null;
  network: string | null;
  failure_reason: string | null;
  paid_at: string | null;
  created_at: string;
  checkout_url: string | null;
  metadata: Record<string, any>;
}

export interface PaymentLink {
  id: string;
  slug: string;
  title: string;
  description: string | null;
  amount: Money | null;
  currency: string;
  active: boolean;
  single_use: boolean;
  payments_count: number;
  created_at: string;
  url: string;
}

export interface Notification {
  id: string;
  type: string;
  title: string;
  body: string;
  read_at: string | null;
  created_at: string;
}

export interface Platform {
  name: string;
  environment: string;
  live_payments_enabled: boolean;
  maintenance: { enabled: boolean; message?: string };
  support: { email?: string; phone?: string };
}
