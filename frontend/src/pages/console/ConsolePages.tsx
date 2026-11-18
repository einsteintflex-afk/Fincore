/**
 * The FinCore dashboard: five sections — Overview, Applications, Transactions, Payments, Settings.
 * Settings holds the subordinate pages (users, subscribers, withdrawal fee, security, API, audit, reports,
 * backups, system) as tabs rather than extra top-level sections.
 */
import { CheckCircle2, CircleAlert, Plus, RefreshCw } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  Card,
  CopyText,
  Empty,
  ErrorState,
  Input,
  KV,
  Modal,
  PageHeader,
  Select,
  Spinner,
  Stat,
  Table,
  Tabs,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dateTime, money, relative, titleCase } from "@/lib/format";
import { useAction, useGet } from "@/lib/hooks";
import type { Transaction } from "@/lib/types";
import {
  AdminApprovals,
  AdminAudit,
  AdminConfig,
  AdminFinance,
  AdminFraud,
  AdminTransactions,
} from "@/pages/admin/AdminPages";
import { FeeBreakdown, SecurityPage, type WithdrawalQuote } from "@/pages/customer/CustomerPages";

function Yes({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <span className={ok ? "inline-flex items-center gap-1 text-emerald-700" : "inline-flex items-center gap-1 text-amber-700"}>
      {ok ? <CheckCircle2 className="h-4 w-4" /> : <CircleAlert className="h-4 w-4" />} {children}
    </span>
  );
}

function TxnRows({ rows }: { rows: Transaction[] }) {
  return (
    <Table
      rows={rows}
      keyFn={(t) => t.reference}
      columns={[
        { header: "Reference", cell: (t) => <span className="font-mono text-xs">{t.reference}</span> },
        { header: "Type", cell: (t) => titleCase(t.type) },
        { header: "Amount", cell: (t) => money(t.amount, t.currency) },
        { header: "Fee", cell: (t) => (Number(t.fee) ? money(t.fee, t.currency) : "—") },
        { header: "Status", cell: (t) => <Badge>{t.status}</Badge> },
        { header: "When", cell: (t) => relative(t.created_at) },
      ]}
    />
  );
}

// ================================================================ A. Overview
export function ConsoleOverview() {
  const q = useGet<any>(["console", "overview"], "/console/overview", undefined, { refetchInterval: 30000 });
  if (q.isLoading) return <Spinner />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data;
  const t = d.totals;
  const sys = d.system;
  return (
    <>
      <PageHeader title="Overview" subtitle="Money in, money out and the health of the system." />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Total collections" value={money(t.collections)} tone="brand" />
        <Stat label="Total disbursements" value={money(t.disbursements)} sub="net amounts paid out" />
        <Stat label="Available balances" value={d.balances.map((b: any) => money(b.available, b.currency)).join(" · ") || money("0")} sub={`In-flight payouts ${money(d.pending_payouts)}`} />
        <Stat label="Withdrawal fees collected" value={money(t.withdrawal_fees)} sub={`Current fee ${sys.withdrawal_fee_percent}%`} />
      </div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Transactions" value={t.transactions} />
        <Stat label="Successful" value={t.successful} />
        <Stat label="Pending" value={t.pending} />
        <Stat label="Failed" value={t.failed} />
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card title="Recent transactions" className="lg:col-span-2" actions={<Link to="/console/transactions" className="text-sm text-brand-700">All transactions</Link>}>
          {d.recent.length ? <TxnRows rows={d.recent} /> : <Empty title="No transactions yet" />}
        </Card>
        <Card title="System status">
          <ul className="space-y-2 text-sm">
            <li><Yes ok={sys.database === "ok"}>Database {sys.database}</Yes></li>
            <li><Yes ok={sys.mtn_mode !== "off"}>MTN MoMo: {sys.mtn_mode === "off" ? "simulator (test only)" : sys.mtn_mode}</Yes></li>
            <li><Yes ok={sys.mtn_collections}>MTN Collections {sys.mtn_collections ? "configured" : "not configured"}</Yes></li>
            <li><Yes ok={sys.mtn_disbursements}>MTN Disbursements {sys.mtn_disbursements ? "configured" : "not configured"}</Yes></li>
            <li><Yes ok={sys.live_payments_enabled}>{sys.live_payments_enabled ? "Live payments on" : "Test mode — no real money moves"}</Yes></li>
            <li><Yes ok={sys.seats.used <= sys.seats.limit}>Dashboard users {sys.seats.used} of {sys.seats.limit}</Yes></li>
            <li><Yes ok={!!sys.last_backup}>{sys.last_backup ? `Last backup ${relative(sys.last_backup.created_at)}` : "No backup yet"}</Yes></li>
          </ul>
        </Card>
      </div>
    </>
  );
}

// ================================================================ B. Applications
interface App {
  id: string;
  name: string;
  description: string | null;
  status: string;
  business_name: string;
  permissions: string[];
  require_verified_subscribers: boolean;
  created_at: string;
  balance: string;
  keys: number;
  webhooks: number;
  subscribers: number;
  payouts: { count: number; volume: string };
  charges: { count: number; volume: string };
}

const PERMISSION_LABELS: Record<string, string> = {
  collections: "Collect payments",
  payouts: "Pay out (withdrawals)",
  refunds: "Refunds",
  balance: "Read balance",
  subscribers: "Manage subscribers",
};

export function ConsoleApplications() {
  const { user } = useAuth();
  const q = useGet<{ items: App[]; permissions: string[] }>(["console", "apps"], "/console/applications");
  const [open, setOpen] = useState(false);
  const nav = useNavigate();
  const canManage = user?.role === "admin" || user?.role === "super_admin";
  return (
    <>
      <PageHeader title="Applications" subtitle="Your apps that use FinCore (Send Me, Nurses & Midwives Hub, PharmaStock…). Each has its own ID, keys, permissions and records."
        actions={canManage && <Button icon={<Plus className="h-4 w-4" />} onClick={() => setOpen(true)}>Register application</Button>} />
      {q.isLoading ? <Spinner /> : !q.data?.items.length ? (
        <Empty title="No applications yet" body="Register an application to get its API keys." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {q.data.items.map((a) => (
            <button key={a.id} onClick={() => nav(`/console/applications/${a.id}`)} className="rounded-xl bg-white p-5 text-left shadow-card ring-1 ring-slate-200/70 hover:ring-brand-300">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold">{a.name}</h3>
                <Badge >{a.status}</Badge>
              </div>
              <p className="mt-1 truncate font-mono text-xs text-slate-500">{a.id}</p>
              <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
                <div><dt className="text-slate-500">Collected</dt><dd>{money(a.charges.volume)}</dd></div>
                <div><dt className="text-slate-500">Paid out</dt><dd>{money(a.payouts.volume)}</dd></div>
                <div><dt className="text-slate-500">Keys / webhooks</dt><dd>{a.keys} / {a.webhooks}</dd></div>
                <div><dt className="text-slate-500">Subscribers</dt><dd>{a.subscribers}</dd></div>
              </dl>
            </button>
          ))}
        </div>
      )}
      <CreateAppModal open={open} onClose={() => setOpen(false)} permissions={q.data?.permissions ?? []} />
    </>
  );
}

function PermissionBoxes({ value, onChange, all }: { value: string[]; onChange: (v: string[]) => void; all: string[] }) {
  return (
    <fieldset className="space-y-1">
      <legend className="mb-1 text-sm font-medium text-slate-700">Permissions</legend>
      {all.map((p) => (
        <label key={p} className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={value.includes(p)} onChange={(e) => onChange(e.target.checked ? [...value, p] : value.filter((x) => x !== p))} />
          {PERMISSION_LABELS[p] ?? p}
        </label>
      ))}
    </fieldset>
  );
}

function CreateAppModal({ open, onClose, permissions }: { open: boolean; onClose: () => void; permissions: string[] }) {
  const nav = useNavigate();
  const [form, setForm] = useState({ name: "", description: "", permissions: ["collections", "refunds", "balance", "subscribers"], require_verified_subscribers: false });
  const create = useAction(() => api<App>("/console/applications", { body: form }), {
    invalidate: [["console", "apps"]],
    success: "Application registered",
    onSuccess: (a) => { onClose(); nav(`/console/applications/${a.id}`); },
  });
  return (
    <Modal open={open} onClose={onClose} title="Register an application">
      <form onSubmit={(e) => { e.preventDefault(); create.mutate(undefined); }} className="space-y-4">
        <Input label="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required placeholder="Send Me" />
        <Input label="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        <PermissionBoxes all={permissions} value={form.permissions} onChange={(p) => setForm({ ...form, permissions: p })} />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={form.require_verified_subscribers} onChange={(e) => setForm({ ...form, require_verified_subscribers: e.target.checked })} />
          Only serve verified subscribers
        </label>
        <Button type="submit" className="w-full" loading={create.isPending}>Register</Button>
      </form>
    </Modal>
  );
}

export function ConsoleApplicationDetail() {
  const { appId } = useParams();
  const { user } = useAuth();
  const canManage = user?.role === "admin" || user?.role === "super_admin";
  const app = useGet<App>(["console", "app", appId], `/console/applications/${appId}`);
  const meta = useGet<{ permissions: string[] }>(["console", "apps"], "/console/applications");
  const keys = useGet<any[]>(["console", "app-keys", appId], canManage ? `/console/applications/${appId}/keys` : null);
  const hooks = useGet<any[]>(["console", "app-hooks", appId], canManage ? `/console/applications/${appId}/webhooks` : null);
  const txns = useGet<any>(["console", "app-txns", appId], `/console/applications/${appId}/transactions`);
  const [secret, setSecret] = useState<string | null>(null);
  const [hookUrl, setHookUrl] = useState("");
  const inv = [["console", "app", appId], ["console", "apps"], ["console", "app-keys", appId], ["console", "app-hooks", appId]];
  const patch = useAction((body: any) => api(`/console/applications/${appId}`, { method: "PATCH", body }), { invalidate: inv, success: "Saved" });
  const newKey = useAction((environment: string) => api(`/console/applications/${appId}/keys`, { body: { environment } }), { invalidate: inv, onSuccess: (k: any) => setSecret(k.secret_key) });
  const rotate = useAction((id: string) => api(`/console/applications/${appId}/keys/${id}/rotate`, { method: "POST" }), { invalidate: inv, onSuccess: (k: any) => setSecret(k.secret_key) });
  const revoke = useAction((id: string) => api(`/console/applications/${appId}/keys/${id}/revoke`, { method: "POST" }), { invalidate: inv, success: "Key revoked" });
  const addHook = useAction(() => api(`/console/applications/${appId}/webhooks`, { body: { url: hookUrl, environment: "live" } }), { invalidate: inv, onSuccess: (h: any) => { setHookUrl(""); setSecret(h.secret); } });
  const delHook = useAction((id: string) => api(`/console/applications/${appId}/webhooks/${id}`, { method: "DELETE" }), { invalidate: inv, success: "Webhook disabled" });
  if (app.isLoading) return <Spinner />;
  if (app.error) return <ErrorState error={app.error} />;
  const a = app.data!;
  return (
    <>
      <PageHeader title={a.name} subtitle={<Link to="/console/applications" className="text-brand-700">← Applications</Link>}
        actions={canManage && (a.status === "active"
          ? <Button variant="danger" onClick={() => patch.mutate({ status: "disabled" })}>Deactivate</Button>
          : <Button onClick={() => patch.mutate({ status: "active" })}>Activate</Button>)} />
      {secret && (
        <Alert tone="warning">
          Copy this secret now — it will not be shown again: <CopyText text={secret} />
          <button className="ml-2 text-sm underline" onClick={() => setSecret(null)}>Done</button>
        </Alert>
      )}
      <div className="mt-4 grid gap-6 lg:grid-cols-2">
        <Card title="Identity">
          <KV items={[
            ["Application ID", <CopyText key="id" text={a.id} />],
            ["Status", <Badge key="s" >{a.status}</Badge>],
            ["Balance", money(a.balance)],
            ["Created", dateTime(a.created_at)],
            ["Subscribers", a.subscribers],
          ]} />
        </Card>
        <Card title="Permissions">
          <PermissionBoxes all={meta.data?.permissions ?? Object.keys(PERMISSION_LABELS)} value={a.permissions} onChange={(p) => canManage && patch.mutate({ permissions: p })} />
          <label className="mt-3 flex items-center gap-2 text-sm">
            <input type="checkbox" disabled={!canManage} checked={a.require_verified_subscribers} onChange={(e) => patch.mutate({ require_verified_subscribers: e.target.checked })} />
            Only serve verified subscribers (requires X-Subscriber-Token)
          </label>
        </Card>
        {canManage && (
          <Card title="API credentials" actions={<div className="flex gap-2"><Button size="sm" variant="secondary" onClick={() => newKey.mutate("sandbox")}>New test key</Button><Button size="sm" onClick={() => newKey.mutate("live")}>New live key</Button></div>}>
            {!keys.data?.length ? <Empty title="No keys" /> : (
              <ul className="divide-y divide-slate-100 text-sm">
                {keys.data.map((k) => (
                  <li key={k.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                    <span><span className="font-mono">{k.secret_prefix}…{k.last4}</span> <Badge >{k.environment}</Badge> <Badge>{k.status}</Badge></span>
                    {k.status === "active" && (
                      <span className="flex gap-2">
                        <Button size="sm" variant="secondary" onClick={() => rotate.mutate(k.id)}>Rotate</Button>
                        <Button size="sm" variant="danger" onClick={() => revoke.mutate(k.id)}>Revoke</Button>
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        )}
        {canManage && (
          <Card title="Webhooks">
            <form className="mb-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); addHook.mutate(undefined); }}>
              <Input placeholder="https://yourapp.example/webhooks/fincore" value={hookUrl} onChange={(e) => setHookUrl(e.target.value)} required />
              <Button type="submit" loading={addHook.isPending}>Add</Button>
            </form>
            <ul className="divide-y divide-slate-100 text-sm">
              {hooks.data?.map((h) => (
                <li key={h.id} className="flex items-center justify-between gap-2 py-2">
                  <span className="truncate">{h.url} <Badge >{h.active ? "active" : "off"}</Badge></span>
                  {h.active && <Button size="sm" variant="secondary" onClick={() => delHook.mutate(h.id)}>Disable</Button>}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-slate-500">Deliveries are signed (FinCore-Signature) and retried with back-off. Events of this app go only to this app's endpoints.</p>
          </Card>
        )}
      </div>
      <Card title="Application transactions" className="mt-6">
        {txns.data?.payouts?.length ? <TxnRows rows={txns.data.payouts} /> : <p className="text-sm text-slate-500">No payouts yet.</p>}
        {!!txns.data?.charges?.length && (
          <div className="mt-4">
            <h4 className="mb-2 text-sm font-medium">Charges</h4>
            <Table rows={txns.data.charges} keyFn={(c: any) => c.reference} columns={[
              { header: "Reference", cell: (c: any) => <span className="font-mono text-xs">{c.merchant_reference || c.reference}</span> },
              { header: "Amount", cell: (c: any) => money(c.amount, c.currency) },
              { header: "Status", cell: (c: any) => <Badge>{c.status}</Badge> },
              { header: "Mode", cell: (c: any) => c.environment },
              { header: "When", cell: (c: any) => relative(c.created_at) },
            ]} />
          </div>
        )}
      </Card>
    </>
  );
}

// ================================================================ C. Transactions
export function ConsoleTransactions() {
  const [tab, setTab] = useState("all");
  return (
    <>
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "all", label: "All transactions" }, { value: "approvals", label: "Approvals" }, { value: "risk", label: "Risk alerts" }]} />
      <div className="mt-4">{tab === "all" ? <AdminTransactions /> : tab === "approvals" ? <AdminApprovals /> : <AdminFraud />}</div>
    </>
  );
}

// ================================================================ D. Payments
export function ConsolePayments() {
  const [tab, setTab] = useState("providers");
  const q = useGet<any>(["console", "payments"], "/console/payments");
  return (
    <>
      <PageHeader title="Payments" subtitle="MTN MoMo Collections & Disbursements, verification and reconciliation." />
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "providers", label: "MTN & providers" }, { value: "recon", label: "Reconciliation" }]} />
      <div className="mt-4">
        {tab === "recon" ? <AdminFinance /> : q.isLoading ? <Spinner /> : q.error ? <ErrorState error={q.error} /> : (
          <div className="grid gap-6 lg:grid-cols-2">
            <Card title="MTN MoMo">
              <KV items={[
                ["Environment", q.data.mtn.environment],
                ["Collections (Request to Pay)", <Yes key="c" ok={q.data.mtn.collections.configured}>{q.data.mtn.collections.configured ? "Configured" : "Not configured"}</Yes>],
                ["Disbursements (Transfer)", <Yes key="d" ok={q.data.mtn.disbursements.configured}>{q.data.mtn.disbursements.configured ? "Configured" : "Not configured"}</Yes>],
                ["Disbursement primary key", q.data.mtn.disbursements.primary_key_set ? "Set (server environment)" : "Not set"],
                ["Callback URL", q.data.mtn.collections.callback_url_set ? "Set" : "Not set"],
                ["Callback token", q.data.mtn.callback_token_set ? "Set" : "Not set"],
                ["Prompt expiry", `${q.data.mtn.request_expiry_minutes} minutes`],
                ["Live payments", q.data.live_payments_enabled ? "On" : "Off (test mode)"],
              ]} />
              <p className="mt-3 text-xs text-slate-500">Credentials are read from the server's environment only and are never shown here. Money is credited only after MTN confirms the status.</p>
            </Card>
            <Card title="Withdrawal fee">
              <p className="text-3xl font-semibold">{q.data.withdrawal_fee_percent}%</p>
              <p className="mt-1 text-sm text-slate-600">Deducted from each withdrawal / payout. Not charged on collections, transfers, settlements, refunds or reversals.</p>
              <Link to="/console/settings/fee" className="mt-3 inline-block text-sm text-brand-700">Change in Settings →</Link>
            </Card>
            <Card title="Waiting for provider confirmation" className="lg:col-span-2">
              {!q.data.pending_by_provider.length ? <p className="text-sm text-slate-500">Nothing pending.</p> : (
                <Table rows={q.data.pending_by_provider} keyFn={(r: any) => `${r.provider}-${r.type}`} columns={[
                  { header: "Provider", cell: (r: any) => r.provider },
                  { header: "Type", cell: (r: any) => titleCase(r.type) },
                  { header: "Pending", cell: (r: any) => r.count },
                ]} />
              )}
            </Card>
            <Card title="All providers" className="lg:col-span-2">
              <Table rows={q.data.providers} keyFn={(p: any) => p.code} columns={[
                { header: "Provider", cell: (p: any) => p.name },
                { header: "Mode", cell: (p: any) => p.mode },
                { header: "Configured", cell: (p: any) => (p.products ? `collections ${p.products.collection ? "✓" : "✗"} · disbursements ${p.products.disbursement ? "✓" : "✗"}` : p.configured ? "✓" : "✗") },
              ]} />
            </Card>
          </div>
        )}
      </div>
    </>
  );
}

// ================================================================ E. Settings
const SETTINGS_TABS = [
  { value: "users", label: "Users" },
  { value: "subscribers", label: "Subscribers" },
  { value: "fee", label: "Withdrawal fee" },
  { value: "security", label: "Security" },
  { value: "api", label: "API & webhooks" },
  { value: "audit", label: "Audit log" },
  { value: "reports", label: "Reports" },
  { value: "backups", label: "Backups" },
  { value: "system", label: "System" },
];

export function ConsoleSettings() {
  const { tab = "users" } = useParams();
  const nav = useNavigate();
  return (
    <>
      <PageHeader title="Settings" />
      <div className="overflow-x-auto">
        <Tabs value={tab} onChange={(v) => nav(`/console/settings/${v}`)} tabs={SETTINGS_TABS} />
      </div>
      <div className="mt-4">
        {tab === "users" && <UsersSettings />}
        {tab === "subscribers" && <SubscribersSettings />}
        {tab === "fee" && <FeeSettings />}
        {tab === "security" && <SecurityPage />}
        {tab === "api" && <ApiSettings />}
        {tab === "audit" && <AdminAudit />}
        {tab === "reports" && <AdminFinance />}
        {tab === "backups" && <BackupSettings />}
        {tab === "system" && <AdminConfig />}
      </div>
    </>
  );
}

const ROLE_LABELS: Record<string, string> = {
  super_admin: "Super admin",
  admin: "Administrator",
  finance: "Finance",
  compliance: "Compliance",
  support: "Support",
  customer: "Wallet user",
};

function UsersSettings() {
  const { user } = useAuth();
  const q = useGet<any>(["team"], "/admin/team");
  const [form, setForm] = useState({ email: "", full_name: "", role: "support", phone: "" });
  const [link, setLink] = useState<string | null>(null);
  const [activity, setActivity] = useState<string | null>(null);
  const invite = useAction(() => api("/admin/team/invitations", { body: { ...form, phone: form.phone || null } }), {
    invalidate: [["team"]],
    onSuccess: (r: any) => { setLink(r.invitation_link); setForm({ email: "", full_name: "", role: "support", phone: "" }); },
  });
  const act = useAction(({ id, action, body }: { id: string; action: string; body?: any }) => api(`/admin/team/${id}/${action}`, { body: body ?? {} }), {
    invalidate: [["team"]],
    success: "Done",
    onSuccess: (r: any) => r?.invitation_link && setLink(r.invitation_link),
  });
  if (q.isLoading) return <Spinner />;
  if (q.error) return <ErrorState error={q.error} />;
  const seats = q.data.seats;
  return (
    <div className="space-y-6">
      <Card title={`Dashboard users — ${seats.used} of ${seats.limit} seats used`}>
        <div className="mb-4 h-2 overflow-hidden rounded-full bg-slate-100" role="meter" aria-valuenow={seats.used} aria-valuemax={seats.limit} aria-label="Seats used">
          <div className="h-full bg-brand-600" style={{ width: `${Math.min(100, (seats.used / seats.limit) * 100)}%` }} />
        </div>
        <p className="mb-4 text-sm text-slate-600">At most {seats.limit} people (including you) can use this dashboard. Customers of your applications are subscribers and are not counted.</p>
        {link && <Alert tone="success">Invitation link (valid 7 days, also emailed): <CopyText text={link} /></Alert>}
        <form onSubmit={(e: FormEvent) => { e.preventDefault(); invite.mutate(undefined); }} className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Input placeholder="Full name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required aria-label="Full name" />
          <Input placeholder="Email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required aria-label="Email" />
          <Input placeholder="Phone (optional)" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} aria-label="Phone" />
          <Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} aria-label="Role">
            {(q.data.roles as string[]).filter((r) => r !== "super_admin" || user?.is_primary_admin).map((r) => <option key={r} value={r}>{ROLE_LABELS[r] ?? r}</option>)}
          </Select>
          <Button type="submit" loading={invite.isPending} disabled={seats.available === 0}>Invite</Button>
        </form>
        {seats.available === 0 && <p className="mt-2 text-sm text-amber-700">All seats are used. Deactivate or remove someone to invite another person.</p>}
      </Card>
      <Card padded={false}>
        <Table rows={q.data.users} keyFn={(u: any) => u.id} columns={[
          { header: "Name", cell: (u: any) => <span>{u.full_name}{u.is_primary_admin &&  <Badge tone="brand">primary admin</Badge>}<br /><span className="text-xs text-slate-500">{u.email}</span></span> },
          { header: "Role", cell: (u: any) => u.is_primary_admin || u.id === user?.id ? ROLE_LABELS[u.role] : (
            <Select aria-label={`Role for ${u.email}`} value={u.role} onChange={(e) => act.mutate({ id: u.id, action: "role", body: { role: e.target.value } })}>
              {(q.data.roles as string[]).map((r) => <option key={r} value={r}>{ROLE_LABELS[r] ?? r}</option>)}
            </Select>) },
          { header: "Status", cell: (u: any) => <Badge>{u.status}</Badge> },
          { header: "Last sign-in", cell: (u: any) => (u.last_login_at ? relative(u.last_login_at) : "—") },
          { header: "", cell: (u: any) => u.is_primary_admin || u.id === user?.id ? null : (
            <div className="flex flex-wrap gap-1">
              {u.status === "invited" && <Button size="sm" variant="secondary" onClick={() => act.mutate({ id: u.id, action: "invitation/resend" })}>New link</Button>}
              {["active", "invited", "restricted", "frozen"].includes(u.status) && <Button size="sm" variant="secondary" onClick={() => act.mutate({ id: u.id, action: "deactivate", body: { reason: "Deactivated by administrator" } })}>Deactivate</Button>}
              {u.status === "deactivated" && <Button size="sm" onClick={() => act.mutate({ id: u.id, action: "activate" })}>Activate</Button>}
              {u.status !== "closed" && <Button size="sm" variant="danger" onClick={() => confirm(`Remove ${u.full_name} permanently?`) && act.mutate({ id: u.id, action: "remove", body: { reason: "Removed by administrator" } })}>Remove</Button>}
              <Button size="sm" variant="ghost" onClick={() => setActivity(u.id)}>Activity</Button>
            </div>) },
        ]} />
      </Card>
      <ActivityModal userId={activity} onClose={() => setActivity(null)} />
    </div>
  );
}

function ActivityModal({ userId, onClose }: { userId: string | null; onClose: () => void }) {
  const q = useGet<any>(["team-activity", userId], userId ? `/admin/team/${userId}/activity` : null);
  const revoke = useAction(() => api(`/admin/team/${userId}/sessions/revoke`, { method: "POST" }), { invalidate: [["team-activity", userId]], success: "Signed out everywhere" });
  return (
    <Modal open={!!userId} onClose={onClose} title="User activity" wide>
      {q.isLoading ? <Spinner /> : q.data && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm">{q.data.sessions.filter((s: any) => s.active).length} active session(s)</p>
            <Button size="sm" variant="danger" onClick={() => revoke.mutate(undefined)}>Sign out all sessions</Button>
          </div>
          <ul className="max-h-80 divide-y divide-slate-100 overflow-y-auto text-sm">
            {q.data.events.map((e: any, i: number) => (
              <li key={i} className="flex justify-between gap-2 py-1.5"><span>{e.action}</span><span className="text-slate-500">{dateTime(e.at)}</span></li>
            ))}
            {!q.data.events.length && <li className="py-2 text-slate-500">No activity yet.</li>}
          </ul>
        </div>
      )}
    </Modal>
  );
}

function SubscribersSettings() {
  const [f, setF] = useState({ status: "", q: "" });
  const list = useGet<any>(["subscribers", f], "/admin/subscribers", f);
  const act = useAction(({ id, action }: { id: string; action: string }) => api(`/admin/subscribers/${id}`, { body: { action, reason: action === "deactivate" ? "Deactivated by administrator" : "" } }), {
    invalidate: [["subscribers"]],
    success: "Updated",
  });
  return (
    <Card title="Verified subscribers" actions={<span className="text-xs text-slate-500">Customers of your applications — not dashboard users</span>}>
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Input placeholder="Search id, name, phone, email" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} aria-label="Search subscribers" />
        <Select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} aria-label="Status">
          <option value="">All statuses</option><option value="pending">Pending verification</option><option value="active">Active</option><option value="inactive">Inactive</option>
        </Select>
      </div>
      {list.isLoading ? <Spinner /> : !list.data?.items.length ? <Empty title="No subscribers" body="Applications register their customers through the API." /> : (
        <Table rows={list.data.items} keyFn={(s: any) => s.id} columns={[
          { header: "Subscriber", cell: (s: any) => <span>{s.display_name || s.external_id}<br /><span className="text-xs text-slate-500">{s.app_name} · {s.external_id}</span></span> },
          { header: "Phone", cell: (s: any) => s.phone ?? "—" },
          { header: "Verified", cell: (s: any) => (s.verified ? `Yes (${s.verification_method})` : "No") },
          { header: "Status", cell: (s: any) => <Badge>{s.status}</Badge> },
          { header: "", cell: (s: any) => (
            <div className="flex flex-wrap gap-1">
              {!s.verified && s.status !== "inactive" && <Button size="sm" onClick={() => act.mutate({ id: s.id, action: "verify" })}>Verify</Button>}
              {s.status !== "inactive" ? <Button size="sm" variant="danger" onClick={() => act.mutate({ id: s.id, action: "deactivate" })}>Deactivate</Button>
                : <Button size="sm" variant="secondary" onClick={() => act.mutate({ id: s.id, action: "activate" })}>Activate</Button>}
            </div>) },
        ]} />
      )}
    </Card>
  );
}

function FeeSettings() {
  const { user } = useAuth();
  const q = useGet<{ percent: string; example: WithdrawalQuote; applies_to: string[]; never_applies_to: string[] }>(["fee-setting"], "/console/settings/withdrawal-fee");
  const [pct, setPct] = useState("");
  const save = useAction(() => api("/console/settings/withdrawal-fee", { method: "PUT", body: { percent: pct } }), {
    invalidate: [["fee-setting"], ["console"], ["withdrawal-quote", "100"]],
    success: "Withdrawal fee updated",
    onSuccess: () => setPct(""),
  });
  const canEdit = ["finance", "admin", "super_admin"].includes(user?.role ?? "");
  if (q.isLoading) return <Spinner />;
  if (q.error) return <ErrorState error={q.error} />;
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title={`Withdrawal fee: ${q.data!.percent}%`}>
        <FeeBreakdown q={q.data!.example} />
        <p className="mt-3 text-sm text-slate-600">Applies to: {q.data!.applies_to.join(", ")}.<br />Never applied to: {q.data!.never_applies_to.join(", ")}.</p>
        <p className="mt-2 text-xs text-slate-500">Each withdrawal records the rate it was charged at, so changing the fee never alters past transactions.</p>
      </Card>
      {canEdit && (
        <Card title="Change the fee">
          <form onSubmit={(e) => { e.preventDefault(); save.mutate(undefined); }} className="space-y-3">
            <Input label="Fee percentage" inputMode="decimal" placeholder={q.data!.percent} value={pct} onChange={(e) => setPct(e.target.value)} hint="0 to 50, up to 2 decimal places" required />
            <Button type="submit" loading={save.isPending}>Save</Button>
          </form>
        </Card>
      )}
    </div>
  );
}

function ApiSettings() {
  return (
    <Card title="API & webhooks">
      <p className="text-sm text-slate-600">
        Each connected application has its own ID, API keys (test and live), permissions and signed webhooks. Manage them in{" "}
        <Link to="/console/applications" className="text-brand-700">Applications</Link>.
      </p>
      <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-600">
        <li>Base URL: <span className="font-mono">/api/v1/gateway</span> — authenticate with <span className="font-mono">Authorization: Bearer sk_…</span></li>
        <li>Send an <span className="font-mono">Idempotency-Key</span> header on every money request; retries never charge twice.</li>
        <li>Payouts: <span className="font-mono">GET /gateway/payouts/quote</span> shows the fee, <span className="font-mono">POST /gateway/payouts</span> sends it.</li>
        <li>Subscribers: register, verify by SMS code, then send <span className="font-mono">X-Subscriber-Token</span>.</li>
        <li>Full reference: <a href="/docs" className="text-brand-700">OpenAPI docs</a> and docs/API.md.</li>
      </ul>
    </Card>
  );
}

function BackupSettings() {
  const { user } = useAuth();
  const q = useGet<any>(["backups"], "/console/settings/backups");
  const run = useAction(() => api("/console/settings/backups", { method: "POST" }), { invalidate: [["backups"]], success: "Backup created" });
  if (q.isLoading) return <Spinner />;
  if (q.error) return <ErrorState error={q.error} />;
  return (
    <Card title="Database backups" actions={user?.role === "super_admin" && q.data.directory_configured && <Button icon={<RefreshCw className="h-4 w-4" />} loading={run.isPending} onClick={() => run.mutate(undefined)}>Back up now</Button>}>
      {!q.data.directory_configured ? (
        <Alert tone="warning">Automatic backups are off. Set FINCORE_BACKUP_DIR on the server (see docs/OPERATIONS.md).</Alert>
      ) : (
        <p className="mb-3 text-sm text-slate-600">Automatic every {q.data.interval_hours} h; the newest {q.data.keep} are kept. Verify a restore with <span className="font-mono">python -m app.cli verify-backup</span>.</p>
      )}
      {!q.data.backups.length ? <Empty title="No backups yet" /> : (
        <Table rows={q.data.backups} keyFn={(b: any) => b.name} columns={[
          { header: "File", cell: (b: any) => <span className="font-mono text-xs">{b.name}</span> },
          { header: "Size", cell: (b: any) => `${(b.size_bytes / 1024 / 1024).toFixed(1)} MB` },
          { header: "Created", cell: (b: any) => dateTime(b.created_at) },
        ]} />
      )}
    </Card>
  );
}
