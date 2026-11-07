import { AlertTriangle, BadgeCheck, Building2, CheckCircle2, Scale, Users, Wallet } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  Alert,
  Amount,
  Badge,
  Button,
  Card,
  Empty,
  ErrorState,
  Input,
  KV,
  Modal,
  PageHeader,
  Pagination,
  Select,
  Spinner,
  Stat,
  Table,
  Tabs,
  Textarea,
} from "@/components/ui";
import { api, downloadFile } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dateOnly, dateTime, money, titleCase } from "@/lib/format";
import { useAction, useGet } from "@/lib/hooks";
import type { Business, Page, Transaction, User } from "@/lib/types";

// ------------------------------------------------------------------ overview
export function AdminOverview() {
  const [days, setDays] = useState("30");
  const o = useGet<any>(["admin-overview", days], "/admin/overview", { days });
  const providers = useGet<any>(["providers"], "/admin/providers");
  if (o.isLoading) return <Spinner />;
  if (o.error) return <ErrorState error={o.error} onRetry={o.refetch} />;
  const d = o.data;
  const daily = d.daily.map((r: any) => ({ day: r.day.slice(5), volume: Number(r.volume), count: r.count }));
  return (
    <>
      <PageHeader title="Platform overview" actions={<Select value={days} onChange={(e) => setDays(e.target.value)} aria-label="Period"><option value="7">7 days</option><option value="30">30 days</option><option value="90">90 days</option></Select>} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat tone="brand" label="Customer funds held" value={money(d.customer_funds)} icon={<Wallet className="h-5 w-5" />} sub={`Merchant funds ${money(d.merchant_funds)}`} />
        <Stat label="Fee revenue (all time)" value={money(d.fee_revenue_total)} icon={<Scale className="h-5 w-5" />} />
        <Stat label="Users" value={d.users} sub={`${d.new_users} new in period`} icon={<Users className="h-5 w-5" />} />
        <Stat label="Failure rate" value={`${(d.failure_rate * 100).toFixed(1)}%`} sub={`${d.transactions} transactions`} icon={<AlertTriangle className="h-5 w-5" />} />
      </div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Link to="/admin/kyc"><Stat label="Pending KYC" value={d.pending_kyc} icon={<BadgeCheck className="h-5 w-5" />} /></Link>
        <Link to="/admin/businesses"><Stat label="Pending businesses" value={d.pending_businesses} icon={<Building2 className="h-5 w-5" />} /></Link>
        <Link to="/admin/fraud"><Stat label="Open fraud alerts" value={d.open_fraud_alerts} icon={<AlertTriangle className="h-5 w-5" />} /></Link>
        <Link to="/admin/support"><Stat label="Open tickets" value={d.open_tickets} /></Link>
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card title="Daily successful volume" className="lg:col-span-2">
          {daily.length ? (
            <div className="h-64">
              <ResponsiveContainer>
                <LineChart data={daily}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="day" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: number, n) => (n === "volume" ? money(v.toFixed(2)) : v)} />
                  <Line type="monotone" dataKey="volume" stroke="#047857" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : <Empty title="No activity in this period" />}
        </Card>
        <Card title="By transaction type">
          <Table rows={d.by_type} keyFn={(r: any) => r.type}
            columns={[
              { header: "Type", cell: (r: any) => titleCase(r.type) },
              { header: "Count", cell: (r: any) => r.count },
              { header: "Volume", cell: (r: any) => money(r.volume), className: "text-right" },
            ]} />
        </Card>
      </div>
      <Card title="Payment providers" className="mt-6">
        {providers.data && (
          <>
            {!providers.data.live_payments_enabled && <div className="mb-3"><Alert tone="warning">Live payments are disabled. All provider calls are routed to the sandbox simulator.</Alert></div>}
            <Table rows={providers.data.providers} keyFn={(p: any) => p.code}
              columns={[
                { header: "Provider", cell: (p: any) => p.name },
                { header: "Configured", cell: (p: any) => (p.configured ? <Badge tone="active">yes</Badge> : <Badge tone="failed">missing credentials</Badge>) },
                { header: "Mode", cell: (p: any) => p.mode },
                { header: "Collect / pay out", cell: (p: any) => `${p.collection ? "✓" : "—"} / ${p.disbursement ? "✓" : "—"}`, hideOnMobile: true },
              ]} />
          </>
        )}
      </Card>
    </>
  );
}

// ------------------------------------------------------------------ users
export function AdminUsers() {
  const nav = useNavigate();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const q = useGet<Page<User>>(["admin-users", page, search, status], "/admin/users", { page, search, status });
  return (
    <>
      <PageHeader title="Customers" />
      <Card>
        <div className="mb-4 grid gap-3 sm:grid-cols-3">
          <Input placeholder="Search name, email or phone" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Status">
            <option value="">All statuses</option>{["active", "restricted", "frozen", "closed"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
          </Select>
        </div>
        {q.isLoading ? <Spinner /> : !q.data?.items.length ? <Empty title="No users found" /> : (
          <>
            <Table rows={q.data.items} keyFn={(u) => u.id} onRowClick={(u) => nav(`/admin/users/${u.id}`)}
              columns={[
                { header: "Name", cell: (u) => <div><p className="font-medium">{u.full_name}</p><p className="text-xs text-slate-500">{u.email}</p></div> },
                { header: "Role", cell: (u) => titleCase(u.role), hideOnMobile: true },
                { header: "KYC", cell: (u) => `Tier ${u.kyc_tier}` },
                { header: "Status", cell: (u) => <Badge>{u.status}</Badge> },
                { header: "Joined", cell: (u) => dateOnly(u.created_at), hideOnMobile: true },
              ]} />
            <Pagination page={page} pageSize={20} total={q.data.total} onPage={setPage} />
          </>
        )}
      </Card>
    </>
  );
}

export function AdminUserDetail() {
  const { userId } = useParams();
  const { user: me } = useAuth();
  const q = useGet<any>(["admin-user", userId], `/admin/users/${userId}`);
  const [restrict, setRestrict] = useState({ type: "no_debit", reason: "" });
  const [statusForm, setStatusForm] = useState({ status: "frozen", reason: "" });
  const [role, setRole] = useState("");
  const inv = [["admin-user", userId], ["admin-users"]];
  const addR = useAction(() => api(`/admin/users/${userId}/restrictions`, { body: restrict }), { invalidate: inv, success: "Restriction applied" });
  const liftR = useAction((rid: string) => api(`/admin/users/${userId}/restrictions/${rid}`, { method: "DELETE" }), { invalidate: inv, success: "Restriction lifted" });
  const setSt = useAction(() => api(`/admin/users/${userId}/status`, { body: statusForm }), { invalidate: inv, success: "Status updated" });
  const setRl = useAction(() => api(`/admin/users/${userId}/role`, { body: { role } }), { invalidate: inv, success: "Role updated" });
  if (q.isLoading) return <Spinner />;
  if (q.error) return <ErrorState error={q.error} />;
  const d = q.data;
  return (
    <>
      <PageHeader title={d.user.full_name} subtitle={<>{d.user.email} · <Badge>{d.user.status}</Badge> · Tier {d.user.kyc_tier}</>} />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Profile">
          <KV items={[["Phone", d.user.phone], ["Role", titleCase(d.user.role)], ["Email verified", d.user.email_verified ? "Yes" : "No"], ["2FA", d.user.totp_enabled ? "On" : "Off"], ["Joined", dateTime(d.user.created_at)], ["Last login", dateTime(d.user.last_login_at)], ["Open alerts", d.open_alerts]]} />
          {d.businesses.length > 0 && (<><p className="mt-4 text-xs font-medium uppercase text-slate-500">Businesses</p>{d.businesses.map((b: any) => <p key={b.id} className="text-sm">{b.name} · {b.role} · <Badge>{b.status}</Badge></p>)}</>)}
        </Card>
        <Card title="Wallets">
          {d.wallets.map((w: any) => (
            <div key={w.id} className="flex justify-between border-b border-slate-100 py-2 text-sm last:border-0">
              <span>{w.label} <span className="font-mono text-xs text-slate-500">{w.account_number}</span></span>
              <span className="tabular font-medium">{money(w.balance)}</span>
            </div>
          ))}
        </Card>
        <Card title="Restrictions">
          {d.restrictions.filter((r: any) => !r.lifted_at).map((r: any) => (
            <div key={r.id} className="mb-2 flex items-center justify-between rounded-lg bg-orange-50 px-3 py-2 text-sm">
              <span><b>{titleCase(r.type)}</b> — {r.reason}</span>
              <Button size="sm" variant="ghost" onClick={() => liftR.mutate(r.id)}>Lift</Button>
            </div>
          ))}
          <form className="mt-2 space-y-2" onSubmit={(e) => { e.preventDefault(); addR.mutate(undefined); }}>
            <Select value={restrict.type} onChange={(e) => setRestrict({ ...restrict, type: e.target.value })} aria-label="Restriction type">
              {["no_debit", "no_credit", "full_freeze", "login_block"].map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}
            </Select>
            <Input placeholder="Reason (required)" value={restrict.reason} onChange={(e) => setRestrict({ ...restrict, reason: e.target.value })} required minLength={3} />
            <Button size="sm" type="submit" variant="danger" loading={addR.isPending}>Apply restriction</Button>
          </form>
          <form className="mt-4 space-y-2 border-t border-slate-100 pt-3" onSubmit={(e) => { e.preventDefault(); setSt.mutate(undefined); }}>
            <Select value={statusForm.status} onChange={(e) => setStatusForm({ ...statusForm, status: e.target.value })} aria-label="Status">
              {["active", "restricted", "frozen", "closed"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
            </Select>
            <Input placeholder="Reason" value={statusForm.reason} onChange={(e) => setStatusForm({ ...statusForm, reason: e.target.value })} required minLength={3} />
            <Button size="sm" type="submit" variant="secondary">Set account status</Button>
          </form>
          {me?.role === "super_admin" && (
            <form className="mt-4 flex gap-2 border-t border-slate-100 pt-3" onSubmit={(e) => { e.preventDefault(); setRl.mutate(undefined); }}>
              <Select value={role || d.user.role} onChange={(e) => setRole(e.target.value)} aria-label="Role">
                {["customer", "support", "compliance", "finance", "admin", "super_admin"].map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}
              </Select>
              <Button size="sm" type="submit" variant="secondary">Set role</Button>
            </form>
          )}
        </Card>
      </div>
      <Card title="Recent transactions" className="mt-6">
        {d.recent_transactions.length ? <AdminTxnTable rows={d.recent_transactions} /> : <Empty title="No transactions" />}
      </Card>
    </>
  );
}

// ------------------------------------------------------------------ KYC
export function AdminKyc() {
  const [status, setStatus] = useState("pending");
  const q = useGet<Page<any>>(["admin-kyc", status], "/admin/kyc", { status });
  const [sel, setSel] = useState<any>(null);
  const [note, setNote] = useState("");
  const review = useAction((decision: string) => api(`/admin/kyc/${sel.id}/review`, { body: { decision, note: note || null } }), {
    invalidate: [["admin-kyc"]], success: "Review recorded", onSuccess: () => { setSel(null); setNote(""); },
  });
  return (
    <>
      <PageHeader title="KYC review" />
      <Card>
        <Tabs value={status} onChange={setStatus} tabs={[{ value: "pending", label: "Pending" }, { value: "approved", label: "Approved" }, { value: "rejected", label: "Rejected" }]} />
        {q.isLoading ? <Spinner /> : !q.data?.items.length ? <Empty title="Queue is empty" body="Nice work." /> : (
          <Table rows={q.data.items} keyFn={(s) => s.id} onRowClick={setSel}
            columns={[
              { header: "Name", cell: (s) => `${s.first_name} ${s.last_name}` },
              { header: "ID", cell: (s) => <span className="font-mono text-xs">{titleCase(s.id_type)} {s.id_number}</span> },
              { header: "Tier", cell: (s) => s.tier_requested },
              { header: "Submitted", cell: (s) => dateTime(s.created_at), hideOnMobile: true },
              { header: "Status", cell: (s) => <Badge>{s.status}</Badge> },
            ]} />
        )}
      </Card>
      <Modal open={!!sel} onClose={() => setSel(null)} title="Review submission">
        {sel && (
          <>
            <KV items={[["Name", `${sel.first_name} ${sel.last_name}`], ["Date of birth", sel.date_of_birth], ["ID", `${titleCase(sel.id_type)} · ${sel.id_number}`], ["Tier requested", sel.tier_requested], ["Address", sel.address], ["GPS address", sel.digital_address], ["Automated check", sel.verification_result?.result ?? "—"], ["Submitted", dateTime(sel.created_at)]]} />
            <KycDocuments submissionId={sel.id} />
            {sel.status === "pending" && (
              <div className="mt-4 space-y-3">
                <Textarea label="Reviewer note (required for rejection)" value={note} onChange={(e) => setNote(e.target.value)} rows={3} />
                <div className="grid grid-cols-2 gap-2">
                  <Button variant="danger" onClick={() => review.mutate("reject")} loading={review.isPending}>Reject</Button>
                  <Button icon={<CheckCircle2 className="h-4 w-4" />} onClick={() => review.mutate("approve")} loading={review.isPending}>Approve</Button>
                </div>
              </div>
            )}
          </>
        )}
      </Modal>
    </>
  );
}

function KycDocuments({ submissionId }: { submissionId: string }) {
  const q = useGet<any[]>(["kyc-docs", submissionId], `/admin/kyc/${submissionId}/documents`);
  if (q.isLoading) return <Spinner label="Loading documents…" />;
  if (!q.data?.length) return <p className="mt-3 text-sm text-slate-500">No documents attached.</p>;
  return (
    <div className="mt-4 grid grid-cols-2 gap-3">
      {q.data.map((d) => (
        <a key={d.id} href={d.url} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-lg ring-1 ring-slate-200 hover:ring-brand-500">
          {d.content_type.startsWith("image/") ? (
            <img src={d.url} alt={titleCase(d.kind)} className="h-32 w-full bg-slate-100 object-cover" />
          ) : (
            <div className="flex h-32 items-center justify-center bg-slate-100 text-sm text-slate-600">PDF document</div>
          )}
          <p className="px-2 py-1 text-xs font-medium text-slate-700">{titleCase(d.kind)}</p>
        </a>
      ))}
      <p className="col-span-2 text-xs text-slate-400">Links expire after 5 minutes. Viewing is recorded in the audit log.</p>
    </div>
  );
}

// ------------------------------------------------------------------ businesses
export function AdminBusinesses() {
  const [status, setStatus] = useState("pending");
  const [search, setSearch] = useState("");
  const q = useGet<Page<Business>>(["admin-biz", status, search], "/admin/businesses", { status, search });
  const [sel, setSel] = useState<Business | null>(null);
  const [note, setNote] = useState("");
  const review = useAction((decision: string) => api(`/admin/businesses/${sel!.id}/review`, { body: { decision, note: note || null } }), {
    invalidate: [["admin-biz"]], success: "Business updated", onSuccess: () => { setSel(null); setNote(""); },
  });
  return (
    <>
      <PageHeader title="Businesses" />
      <Card>
        <Tabs value={status} onChange={setStatus} tabs={["pending", "active", "suspended", "rejected", ""].map((s) => ({ value: s, label: s ? titleCase(s) : "All" }))} />
        <div className="mb-4 max-w-sm"><Input placeholder="Search name, merchant code, email" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        {q.isLoading ? <Spinner /> : !q.data?.items.length ? <Empty title="No businesses" /> : (
          <Table rows={q.data.items} keyFn={(b) => b.id} onRowClick={setSel}
            columns={[
              { header: "Business", cell: (b) => <div><p className="font-medium">{b.name}</p><p className="text-xs text-slate-500">{b.merchant_code} · {b.email}</p></div> },
              { header: "Type", cell: (b) => titleCase(b.business_type), hideOnMobile: true },
              { header: "Status", cell: (b) => <Badge>{b.status}</Badge> },
              { header: "Created", cell: (b) => dateOnly(b.created_at), hideOnMobile: true },
            ]} />
        )}
      </Card>
      <Modal open={!!sel} onClose={() => setSel(null)} title={sel?.name ?? ""}>
        {sel && (
          <>
            <KV items={[["Trading name", sel.trading_name], ["Type", titleCase(sel.business_type)], ["Industry", sel.industry], ["ORC no.", sel.registration_number], ["TIN", sel.tin], ["Email", sel.email], ["Phone", sel.phone], ["Address", sel.address], ["Website", sel.website], ["Status", <Badge key="s">{sel.status}</Badge>]]} />
            <Textarea label="Note" value={note} onChange={(e) => setNote(e.target.value)} rows={2} />
            <div className="mt-3 grid grid-cols-2 gap-2">
              {sel.status === "pending" && <><Button variant="danger" onClick={() => review.mutate("reject")}>Reject</Button><Button onClick={() => review.mutate("approve")}>Approve</Button></>}
              {sel.status === "active" && <Button variant="danger" className="col-span-2" onClick={() => review.mutate("suspend")}>Suspend</Button>}
              {(sel.status === "suspended" || sel.status === "rejected") && <Button className="col-span-2" onClick={() => review.mutate("reactivate")}>Reactivate</Button>}
            </div>
          </>
        )}
      </Modal>
    </>
  );
}

// ------------------------------------------------------------------ transactions
function AdminTxnTable({ rows, onClick }: { rows: Transaction[]; onClick?: (t: Transaction) => void }) {
  return (
    <Table rows={rows} keyFn={(t) => t.id} onRowClick={onClick}
      columns={[
        { header: "Date", cell: (t) => dateTime(t.created_at), hideOnMobile: true },
        { header: "Reference", cell: (t) => <div><p className="font-mono text-xs">{t.reference}</p><p className="text-xs text-slate-500">{t.description}</p></div> },
        { header: "Type", cell: (t) => titleCase(t.type), hideOnMobile: true },
        { header: "Provider", cell: (t) => t.provider, hideOnMobile: true },
        { header: "Risk", cell: (t) => (t.risk_score >= 40 ? <Badge tone="high">{String(t.risk_score)}</Badge> : t.risk_score), hideOnMobile: true },
        { header: "Status", cell: (t) => <Badge>{t.status}</Badge> },
        { header: "Amount", cell: (t) => <Amount value={t.amount} />, className: "text-right" },
      ]} />
  );
}

export function AdminTransactions() {
  const [page, setPage] = useState(1);
  const [f, setF] = useState({ search: "", type: "", status: "", provider: "", min_risk: "" });
  const q = useGet<Page<Transaction>>(["admin-txns", page, f], "/admin/transactions", { page, page_size: 25, ...f });
  const [sel, setSel] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { setPage(1); setF({ ...f, [k]: e.target.value }); };
  return (
    <>
      <PageHeader title="Transaction monitoring" actions={<AdjustButton />} />
      <Card>
        <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Input placeholder="Reference / provider ref" value={f.search} onChange={set("search")} />
          <Select value={f.type} onChange={set("type")} aria-label="Type"><option value="">All types</option>{["deposit", "withdrawal", "transfer", "payment", "refund", "settlement", "reversal", "adjustment"].map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}</Select>
          <Select value={f.status} onChange={set("status")} aria-label="Status"><option value="">All statuses</option>{["pending", "processing", "successful", "failed", "reversed"].map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}</Select>
          <Select value={f.provider} onChange={set("provider")} aria-label="Provider"><option value="">All providers</option>{["internal", "sandbox", "mtn_momo", "paystack"].map((t) => <option key={t} value={t}>{t}</option>)}</Select>
          <Select value={f.min_risk} onChange={set("min_risk")} aria-label="Risk"><option value="">Any risk</option><option value="40">Risk ≥ 40</option><option value="70">Risk ≥ 70</option></Select>
        </div>
        {q.isLoading ? <Spinner /> : !q.data?.items.length ? <Empty title="No transactions" /> : (
          <>
            <AdminTxnTable rows={q.data.items} onClick={(t) => setSel(t.reference)} />
            <Pagination page={page} pageSize={25} total={q.data.total} onPage={setPage} />
          </>
        )}
      </Card>
      <AdminTxnDetail reference={sel} onClose={() => setSel(null)} />
    </>
  );
}

function AdminTxnDetail({ reference, onClose }: { reference: string | null; onClose: () => void }) {
  const q = useGet<any>(["admin-txn", reference], reference ? `/admin/transactions/${reference}` : null);
  const [reason, setReason] = useState("");
  const reverse = useAction(() => api(`/admin/transactions/${reference}/reverse`, { body: { reason } }), {
    invalidate: [["admin-txns"], ["admin-txn", reference], ["approvals"]],
    success: (r: any) => (r?.approval_required ? "Above threshold — sent for second approval" : "Transaction reversed"),
    onSuccess: onClose,
  });
  const requery = useAction(() => api(`/admin/transactions/${reference}/requery`, { method: "POST" }), { invalidate: [["admin-txns"], ["admin-txn", reference]], success: "Status refreshed" });
  const t = q.data?.transaction;
  return (
    <Modal open={!!reference} onClose={onClose} title={reference ?? ""} wide>
      {q.isLoading || !t ? <Spinner /> : (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <KV items={[["Type", titleCase(t.type)], ["Status", <Badge key="s">{t.status}</Badge>], ["Amount", money(t.amount)], ["Fee", money(t.fee)], ["Channel", t.channel], ["Provider", `${t.provider} (${t.provider_mode})`], ["Provider ref", t.provider_reference], ["Risk score", t.risk_score], ["Created", dateTime(t.created_at)], ["Failure", t.failure_reason]]} />
            <div>
              <p className="mb-2 text-xs font-medium uppercase text-slate-500">Ledger journals</p>
              {q.data.journals.map((j: any) => (
                <div key={j.reference} className="mb-3 rounded-lg bg-slate-50 p-3 text-xs">
                  <p className="font-mono font-medium">{j.reference} · {j.kind}</p>
                  {j.entries.map((e: any, i: number) => (
                    <p key={i} className="flex justify-between font-mono"><span>{e.direction === "debit" ? "DR" : "  CR"} {e.account}</span><span>{money(e.amount)}</span></p>
                  ))}
                </div>
              ))}
              {q.data.fraud_alerts.length > 0 && <Alert tone="warning">{q.data.fraud_alerts.length} fraud alert(s) linked</Alert>}
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-4">
            {t.status === "processing" && <Button variant="secondary" onClick={() => requery.mutate(undefined)} loading={requery.isPending}>Re-query provider</Button>}
            {t.status === "successful" && ["transfer", "payment", "deposit", "adjustment"].includes(t.type) && (
              <form className="flex flex-1 gap-2" onSubmit={(e) => { e.preventDefault(); reverse.mutate(undefined); }}>
                <Input placeholder="Reversal reason" value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} />
                <Button variant="danger" type="submit" loading={reverse.isPending}>Reverse</Button>
              </form>
            )}
          </div>
        </>
      )}
    </Modal>
  );
}

function AdjustButton() {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ wallet_account_number: "", amount: "", direction: "credit", reason: "" });
  const adj = useAction(() => api("/admin/adjustments", { body: f }), {
    invalidate: [["admin-txns"], ["approvals"]],
    success: (r: any) => (r?.approval_required ? "Above threshold — sent for second approval" : "Adjustment posted"),
    onSuccess: () => setOpen(false),
  });
  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)}>Manual adjustment</Button>
      <Modal open={open} onClose={() => setOpen(false)} title="Manual wallet adjustment">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); adj.mutate(undefined); }}>
          <Alert tone="warning">Adjustments post against the ADJUSTMENTS ledger account and are audit-logged. Large amounts need a second approver.</Alert>
          <Input label="Wallet account number" value={f.wallet_account_number} onChange={(e) => setF({ ...f, wallet_account_number: e.target.value })} required />
          <Input label="Amount" inputMode="decimal" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} required />
          <Select label="Direction" value={f.direction} onChange={(e) => setF({ ...f, direction: e.target.value })}><option value="credit">Credit wallet</option><option value="debit">Debit wallet</option></Select>
          <Input label="Reason" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} required minLength={3} />
          <Button type="submit" className="w-full" loading={adj.isPending}>Post adjustment</Button>
        </form>
      </Modal>
    </>
  );
}

// ------------------------------------------------------------------ fraud
export function AdminFraud() {
  const [status, setStatus] = useState("open");
  const q = useGet<Page<any>>(["fraud", status], "/admin/fraud-alerts", { status });
  const [sel, setSel] = useState<any>(null);
  const [form, setForm] = useState({ status: "investigating", notes: "", restrict_user: false });
  const upd = useAction(() => api(`/admin/fraud-alerts/${sel.id}`, { method: "PATCH", body: form }), { invalidate: [["fraud"]], success: "Alert updated", onSuccess: () => setSel(null) });
  const scanNow = useAction(() => api("/admin/aml/scan", { method: "POST" }), {
    invalidate: [["fraud"]],
    success: (r: any) => {
      const n = Object.values(r.alerts_raised as Record<string, number>).reduce((a, b) => a + b, 0);
      return n ? `AML scan raised ${n} new alert(s)` : "AML scan complete — no new alerts";
    },
  });
  return (
    <>
      <PageHeader title="Fraud & AML investigation" subtitle="Real-time risk rules plus AML scenarios (structuring, rapid movement, fan-in, dormant reactivation)."
        actions={<>
          <Button variant="secondary" loading={scanNow.isPending} onClick={() => scanNow.mutate(undefined)}>Run AML scan</Button>
          <Button variant="secondary" onClick={() => downloadFile("/admin/fraud-alerts/export", { status: "open,investigating,resolved" }, "fincore-alerts.csv")}>Export CSV</Button>
        </>} />
      <Card>
        <Tabs value={status} onChange={setStatus} tabs={["open", "investigating", "resolved", "false_positive"].map((s) => ({ value: s, label: titleCase(s) }))} />
        {q.isLoading ? <Spinner /> : !q.data?.items.length ? <Empty title="No alerts" /> : (
          <Table rows={q.data.items} keyFn={(a) => a.id} onRowClick={(a) => { setSel(a); setForm({ status: a.status === "open" ? "investigating" : a.status, notes: a.notes ?? "", restrict_user: false }); }}
            columns={[
              { header: "Rule", cell: (a) => titleCase(a.rule) },
              { header: "Severity", cell: (a) => <Badge>{a.severity}</Badge> },
              { header: "Score", cell: (a) => a.score },
              { header: "User", cell: (a) => a.user_id ? <Link className="text-brand-700" to={`/admin/users/${a.user_id}`} onClick={(e) => e.stopPropagation()}>View</Link> : "—" },
              { header: "Raised", cell: (a) => dateTime(a.created_at), hideOnMobile: true },
            ]} />
        )}
      </Card>
      <Modal open={!!sel} onClose={() => setSel(null)} title="Fraud alert">
        {sel && (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); upd.mutate(undefined); }}>
            <KV items={[["Rule", titleCase(sel.rule)], ["Severity", sel.severity], ["Score", sel.score], ["Details", <code key="d" className="text-xs">{JSON.stringify(sel.details)}</code>]]} />
            <Select label="Status" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
              {["open", "investigating", "resolved", "false_positive"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
            </Select>
            <Textarea label="Investigation notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} rows={3} />
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.restrict_user} onChange={(e) => setForm({ ...form, restrict_user: e.target.checked })} /> Block outgoing transactions for this user</label>
            <Button type="submit" className="w-full" loading={upd.isPending}>Save</Button>
          </form>
        )}
      </Modal>
    </>
  );
}

// ------------------------------------------------------------------ finance
export function AdminFinance() {
  const [tab, setTab] = useState("recon");
  const runs = useGet<any[]>(["recon-runs"], "/admin/reconciliation/runs");
  const tb = useGet<any>(["trial-balance"], tab === "tb" ? "/admin/reports/trial-balance" : null);
  const rev = useGet<any>(["revenue"], tab === "revenue" ? "/admin/reports/revenue" : null);
  const fails = useGet<any>(["failures"], tab === "failures" ? "/admin/analytics/failures" : null);
  const merchants = useGet<any[]>(["merchant-perf"], tab === "merchants" ? "/admin/analytics/merchants" : null);
  const runLedger = useAction(() => api("/admin/reconciliation/ledger", { method: "POST" }), { invalidate: [["recon-runs"]], success: (r: any) => `Ledger ${r.status}` });
  const runProv = useAction(() => api("/admin/reconciliation/providers", { method: "POST" }), { invalidate: [["recon-runs"]], success: (r: any) => `Providers ${r.status}` });
  const [sel, setSel] = useState<any>(null);
  return (
    <>
      <PageHeader title="Finance & reconciliation" />
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "recon", label: "Reconciliation" }, { value: "tb", label: "Trial balance" }, { value: "revenue", label: "Revenue" }, { value: "failures", label: "Failure analysis" }, { value: "merchants", label: "Merchant performance" }]} />
      {tab === "recon" && (
        <Card title="Reconciliation runs" actions={<><Button size="sm" onClick={() => runLedger.mutate(undefined)} loading={runLedger.isPending}>Run ledger check</Button><Button size="sm" variant="secondary" onClick={() => runProv.mutate(undefined)} loading={runProv.isPending}>Run provider recon</Button></>}>
          {runs.isLoading ? <Spinner /> : !runs.data?.length ? <Empty title="No runs yet" /> : (
            <Table rows={runs.data} keyFn={(r) => r.id} onRowClick={setSel}
              columns={[
                { header: "When", cell: (r) => dateTime(r.created_at) },
                { header: "Kind", cell: (r) => titleCase(r.kind) },
                { header: "Result", cell: (r) => <Badge>{r.status}</Badge> },
                { header: "Issues", cell: (r) => r.discrepancies.length },
              ]} />
          )}
        </Card>
      )}
      {tab === "tb" && (tb.isLoading ? <Spinner /> : tb.data && (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card title="System accounts" className="lg:col-span-2">
            <Table rows={tb.data.system_accounts} keyFn={(a: any) => a.code}
              columns={[{ header: "Account", cell: (a: any) => <div><p className="font-mono text-xs">{a.code}</p><p className="text-xs text-slate-500">{a.name}</p></div> }, { header: "Type", cell: (a: any) => a.type }, { header: "Balance", cell: (a: any) => money(a.balance), className: "text-right tabular" }]} />
          </Card>
          <Card title="Integrity">
            {tb.data.integrity.balanced ? <Alert tone="success">Ledger balanced — {tb.data.integrity.accounts_checked} accounts, {tb.data.integrity.journals_checked} journals.</Alert> : <Alert tone="error">{tb.data.integrity.problems.length} problem(s) found</Alert>}
            {tb.data.customer_and_merchant_wallets.map((w: any) => <Stat key={w.currency} label={`Wallet liabilities (${w.currency})`} value={money(w.total_balance)} sub={`${w.accounts} accounts`} />)}
          </Card>
        </div>
      ))}
      {tab === "revenue" && (rev.isLoading ? <Spinner /> : rev.data && (
        <Card title={`Revenue ${dateOnly(rev.data.period_start)} – ${dateOnly(rev.data.period_end)}`}>
          <div className="mb-4 grid gap-3 sm:grid-cols-2"><Stat label="Customer fees" value={money(rev.data.total_fees)} /><Stat label="Merchant discount fees" value={money(rev.data.merchant_discount_fees)} /></div>
          <Table rows={rev.data.by_type} keyFn={(r: any) => r.type + r.channel} columns={[{ header: "Type", cell: (r: any) => titleCase(r.type) }, { header: "Channel", cell: (r: any) => titleCase(r.channel) }, { header: "Count", cell: (r: any) => r.count }, { header: "Fees", cell: (r: any) => money(r.fees), className: "text-right" }]} />
        </Card>
      ))}
      {tab === "failures" && (fails.isLoading ? <Spinner /> : fails.data && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card title="By provider">
            {fails.data.providers.length ? (
              <div className="h-56"><ResponsiveContainer><BarChart data={fails.data.providers}><XAxis dataKey="provider" tick={{ fontSize: 11 }} /><Tooltip /><Bar dataKey="total" fill="#94a3b8" /><Bar dataKey="failed" fill="#e11d48" /></BarChart></ResponsiveContainer></div>
            ) : <Empty title="No provider traffic" />}
          </Card>
          <Card title="Top failure reasons">
            {fails.data.reasons.length ? <Table rows={fails.data.reasons} keyFn={(r: any) => r.type + r.provider + r.reason} columns={[{ header: "Reason", cell: (r: any) => r.reason }, { header: "Type", cell: (r: any) => titleCase(r.type) }, { header: "Count", cell: (r: any) => r.count, className: "text-right" }]} /> : <Empty title="No failures 🎉" />}
          </Card>
        </div>
      ))}
      {tab === "merchants" && (merchants.isLoading ? <Spinner /> : (
        <Card title="Top merchants (30 days)">
          {merchants.data?.length ? <Table rows={merchants.data} keyFn={(m: any) => m.business_id} columns={[{ header: "Merchant", cell: (m: any) => <div><p className="font-medium">{m.name}</p><p className="text-xs text-slate-500">{m.merchant_code}</p></div> }, { header: "Charges", cell: (m: any) => m.charges }, { header: "Conversion", cell: (m: any) => `${(m.conversion * 100).toFixed(1)}%` }, { header: "Fees", cell: (m: any) => money(m.fees) }, { header: "Volume", cell: (m: any) => money(m.volume), className: "text-right" }]} /> : <Empty title="No merchant volume yet" />}
        </Card>
      ))}
      <Modal open={!!sel} onClose={() => setSel(null)} title="Reconciliation run" wide>
        {sel && <pre className="overflow-x-auto rounded-lg bg-slate-50 p-4 text-xs">{JSON.stringify({ summary: sel.summary, discrepancies: sel.discrepancies }, null, 2)}</pre>}
      </Modal>
    </>
  );
}

// ------------------------------------------------------------------ config
export function AdminConfig() {
  const [tab, setTab] = useState("fees");
  const fees = useGet<any[]>(["admin-fees"], "/admin/fees");
  const limits = useGet<any[]>(["admin-limits"], "/admin/limits");
  const settings = useGet<any[]>(["admin-settings"], "/admin/settings");
  const [fee, setFee] = useState<any>(null);
  const [limit, setLimit] = useState<any>(null);
  const [setting, setSetting] = useState<{ key: string; value: string } | null>(null);
  const saveFee = useAction(() => api(fee.id ? `/admin/fees/${fee.id}` : "/admin/fees", { method: fee.id ? "PUT" : "POST", body: { ...fee, id: undefined, updated_at: undefined, channel: fee.channel || null, max_fee: fee.max_fee || null } }), { invalidate: [["admin-fees"]], success: "Fee rule saved", onSuccess: () => setFee(null) });
  const saveLimit = useAction(() => api("/admin/limits", { method: "PUT", body: { ...limit, id: undefined, per_transaction_max: limit.per_transaction_max || null, daily_max: limit.daily_max || null, monthly_max: limit.monthly_max || null, max_balance: limit.max_balance || null } }), { invalidate: [["admin-limits"]], success: "Limit saved", onSuccess: () => setLimit(null) });
  const saveSetting = useAction(() => api(`/admin/settings/${setting!.key}`, { method: "PUT", body: { value: JSON.parse(setting!.value) } }), { invalidate: [["admin-settings"], ["platform"]], success: "Setting saved", onSuccess: () => setSetting(null) });
  return (
    <>
      <PageHeader title="Fees, limits & system configuration" />
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "fees", label: "Fee schedule" }, { value: "limits", label: "Transaction limits" }, { value: "settings", label: "System settings" }]} />
      {tab === "fees" && (
        <Card actions={<Button size="sm" onClick={() => setFee({ name: "", transaction_type: "transfer", channel: "", currency: "GHS", payer: "customer", flat_fee: "0", percent_fee: "0", min_fee: "0", max_fee: "", active: true })}>Add rule</Button>}>
          {fees.isLoading ? <Spinner /> : <Table rows={fees.data ?? []} keyFn={(f) => f.id} onRowClick={(f) => setFee({ ...f, max_fee: f.max_fee ?? "", channel: f.channel ?? "" })}
            columns={[
              { header: "Rule", cell: (f) => <div><p className="font-medium">{f.name}</p><p className="text-xs text-slate-500">{f.transaction_type} · {f.channel ?? "any channel"} · paid by {f.payer}</p></div> },
              { header: "Flat", cell: (f) => money(f.flat_fee) },
              { header: "Percent", cell: (f) => `${(Number(f.percent_fee) * 100).toFixed(2)}%` },
              { header: "Min / Max", cell: (f) => `${money(f.min_fee)} / ${f.max_fee ? money(f.max_fee) : "∞"}`, hideOnMobile: true },
              { header: "Active", cell: (f) => <Badge>{f.active ? "active" : "revoked"}</Badge> },
            ]} />}
        </Card>
      )}
      {tab === "limits" && (
        <Card actions={<Button size="sm" onClick={() => setLimit({ kyc_tier: 0, transaction_type: "transfer", currency: "GHS", per_transaction_max: "", daily_max: "", monthly_max: "", max_balance: "", active: true })}>Add limit</Button>}>
          <Alert tone="warning">Limits are placeholders until confirmed by compliance against current Bank of Ghana e-money guidelines.</Alert>
          {limits.isLoading ? <Spinner /> : <Table rows={limits.data ?? []} keyFn={(l) => l.id} onRowClick={(l) => setLimit(Object.fromEntries(Object.entries(l).map(([k, v]) => [k, v ?? ""])))}
            columns={[
              { header: "Tier", cell: (l) => l.kyc_tier },
              { header: "Type", cell: (l) => (l.transaction_type === "*" ? "Max balance" : titleCase(l.transaction_type)) },
              { header: "Per txn", cell: (l) => (l.per_transaction_max ? money(l.per_transaction_max) : "—") },
              { header: "Daily", cell: (l) => (l.daily_max ? money(l.daily_max) : "—") },
              { header: "Monthly", cell: (l) => (l.monthly_max ? money(l.monthly_max) : "—"), hideOnMobile: true },
              { header: "Max balance", cell: (l) => (l.max_balance ? money(l.max_balance) : "—"), hideOnMobile: true },
            ]} />}
        </Card>
      )}
      {tab === "settings" && (
        <Card>
          {settings.isLoading ? <Spinner /> : <Table rows={settings.data ?? []} keyFn={(s) => s.key} onRowClick={(s) => setSetting({ key: s.key, value: JSON.stringify(s.value, null, 2) })}
            columns={[{ header: "Key", cell: (s) => <code className="text-xs">{s.key}</code> }, { header: "Value", cell: (s) => <code className="text-xs">{JSON.stringify(s.value)}</code> }, { header: "Description", cell: (s) => s.description, hideOnMobile: true }]} />}
        </Card>
      )}
      <Modal open={!!fee} onClose={() => setFee(null)} title={fee?.id ? "Edit fee rule" : "New fee rule"}>
        {fee && (
          <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); saveFee.mutate(undefined); }}>
            <div className="sm:col-span-2"><Input label="Name" value={fee.name} onChange={(e) => setFee({ ...fee, name: e.target.value })} required /></div>
            <Select label="Transaction type" value={fee.transaction_type} onChange={(e) => setFee({ ...fee, transaction_type: e.target.value })}>{["deposit", "withdrawal", "transfer", "payment", "settlement"].map((t) => <option key={t}>{t}</option>)}</Select>
            <Select label="Channel" value={fee.channel} onChange={(e) => setFee({ ...fee, channel: e.target.value })}><option value="">Any</option>{["wallet", "mobile_money", "bank", "card"].map((t) => <option key={t}>{t}</option>)}</Select>
            <Select label="Paid by" value={fee.payer} onChange={(e) => setFee({ ...fee, payer: e.target.value })}><option value="customer">Customer</option><option value="merchant">Merchant</option></Select>
            <Input label="Flat fee (GHS)" value={fee.flat_fee} onChange={(e) => setFee({ ...fee, flat_fee: e.target.value })} />
            <Input label="Percent (0.015 = 1.5%)" value={fee.percent_fee} onChange={(e) => setFee({ ...fee, percent_fee: e.target.value })} />
            <Input label="Minimum fee" value={fee.min_fee} onChange={(e) => setFee({ ...fee, min_fee: e.target.value })} />
            <Input label="Maximum fee (blank = none)" value={fee.max_fee} onChange={(e) => setFee({ ...fee, max_fee: e.target.value })} />
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={fee.active} onChange={(e) => setFee({ ...fee, active: e.target.checked })} /> Active</label>
            <div className="sm:col-span-2"><Button type="submit" className="w-full" loading={saveFee.isPending}>Save</Button></div>
          </form>
        )}
      </Modal>
      <Modal open={!!limit} onClose={() => setLimit(null)} title="Transaction limit">
        {limit && (
          <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); saveLimit.mutate(undefined); }}>
            <Select label="KYC tier" value={limit.kyc_tier} onChange={(e) => setLimit({ ...limit, kyc_tier: Number(e.target.value) })}>{[0, 1, 2, 3].map((t) => <option key={t} value={t}>{t}</option>)}</Select>
            <Select label="Type" value={limit.transaction_type} onChange={(e) => setLimit({ ...limit, transaction_type: e.target.value })}>{["*", "deposit", "withdrawal", "transfer", "payment"].map((t) => <option key={t} value={t}>{t === "*" ? "Max balance" : t}</option>)}</Select>
            <Input label="Per transaction max" value={limit.per_transaction_max} onChange={(e) => setLimit({ ...limit, per_transaction_max: e.target.value })} />
            <Input label="Daily max" value={limit.daily_max} onChange={(e) => setLimit({ ...limit, daily_max: e.target.value })} />
            <Input label="Monthly max" value={limit.monthly_max} onChange={(e) => setLimit({ ...limit, monthly_max: e.target.value })} />
            <Input label="Max balance" value={limit.max_balance} onChange={(e) => setLimit({ ...limit, max_balance: e.target.value })} />
            <div className="sm:col-span-2"><Button type="submit" className="w-full" loading={saveLimit.isPending}>Save</Button></div>
          </form>
        )}
      </Modal>
      <Modal open={!!setting} onClose={() => setSetting(null)} title={setting?.key ?? ""}>
        {setting && (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); try { JSON.parse(setting.value); saveSetting.mutate(undefined); } catch { alert("Value must be valid JSON"); } }}>
            <Textarea label="Value (JSON)" value={setting.value} onChange={(e) => setSetting({ ...setting, value: e.target.value })} rows={6} />
            <Button type="submit" className="w-full" loading={saveSetting.isPending}>Save</Button>
          </form>
        )}
      </Modal>
    </>
  );
}

// ------------------------------------------------------------------ support
export function AdminSupport() {
  const [status, setStatus] = useState("open");
  const q = useGet<Page<any>>(["admin-tickets", status], "/admin/tickets", { status });
  const [sel, setSel] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="Customer support" />
      <Card>
        <Tabs value={status} onChange={setStatus} tabs={["open", "pending", "resolved", "closed"].map((s) => ({ value: s, label: titleCase(s) }))} />
        {q.isLoading ? <Spinner /> : !q.data?.items.length ? <Empty title="No tickets" /> : (
          <Table rows={q.data.items} keyFn={(t) => t.id} onRowClick={(t) => setSel(t.id)}
            columns={[
              { header: "Subject", cell: (t) => <div><p className="font-medium">{t.subject}</p><p className="text-xs text-slate-500">{titleCase(t.category)}{t.transaction_reference && ` · ${t.transaction_reference}`}</p></div> },
              { header: "Priority", cell: (t) => <Badge>{t.priority}</Badge> },
              { header: "Updated", cell: (t) => dateTime(t.updated_at), hideOnMobile: true },
            ]} />
        )}
      </Card>
      <AdminTicket id={sel} onClose={() => setSel(null)} />
    </>
  );
}

function AdminTicket({ id, onClose }: { id: string | null; onClose: () => void }) {
  const t = useGet<any>(["admin-ticket", id], id ? `/admin/tickets/${id}` : null);
  const [body, setBody] = useState("");
  const [internal, setInternal] = useState(false);
  const reply = useAction(() => api(`/admin/tickets/${id}/messages`, { body: { body, internal } }), { invalidate: [["admin-ticket", id], ["admin-tickets"]], onSuccess: () => setBody("") });
  const update = useAction((b: any) => api(`/admin/tickets/${id}`, { method: "PATCH", body: b }), { invalidate: [["admin-ticket", id], ["admin-tickets"]], success: "Ticket updated" });
  return (
    <Modal open={!!id} onClose={onClose} title={t.data?.ticket.subject ?? "Ticket"} wide>
      {t.isLoading || !t.data ? <Spinner /> : (
        <>
          <p className="mb-3 text-sm text-slate-600">
            {t.data.customer.full_name} · {t.data.customer.email} · <Link className="text-brand-700" to={`/admin/users/${t.data.customer.id}`}>Open customer</Link>
          </p>
          <div className="max-h-80 space-y-2 overflow-y-auto">
            {t.data.messages.map((m: any) => (
              <div key={m.id} className={`rounded-lg px-3 py-2 text-sm ${m.internal ? "bg-amber-50" : m.author_id === t.data.customer.id ? "bg-slate-50" : "bg-brand-50"}`}>
                {m.internal && <p className="text-xs font-medium text-amber-700">Internal note</p>}
                <p className="whitespace-pre-wrap">{m.body}</p>
                <p className="mt-1 text-xs text-slate-400">{dateTime(m.created_at)}</p>
              </div>
            ))}
          </div>
          <form className="mt-4 space-y-2" onSubmit={(e) => { e.preventDefault(); reply.mutate(undefined); }}>
            <Textarea value={body} onChange={(e) => setBody(e.target.value)} rows={3} placeholder="Reply…" required />
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} /> Internal note (hidden from customer)</label>
            <div className="flex flex-wrap gap-2">
              <Button type="submit" loading={reply.isPending}>Send</Button>
              <Button type="button" variant="secondary" onClick={() => update.mutate({ assign_to_me: true })}>Assign to me</Button>
              <Button type="button" variant="secondary" onClick={() => update.mutate({ status: "resolved" })}>Mark resolved</Button>
            </div>
          </form>
        </>
      )}
    </Modal>
  );
}

// ------------------------------------------------------------------ audit
export function AdminAudit() {
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const q = useGet<Page<any>>(["audit", page, action], "/admin/audit-logs", { page, action });
  const [sel, setSel] = useState<any>(null);
  return (
    <>
      <PageHeader title="Audit log" subtitle="Append-only record of every sensitive action." />
      <Card>
        <div className="mb-4 max-w-sm"><Input placeholder="Filter by action prefix, e.g. kyc. or wallet." value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }} /></div>
        {q.isLoading ? <Spinner /> : !q.data?.items.length ? <Empty title="No entries" /> : (
          <>
            <Table rows={q.data.items} keyFn={(a) => a.id} onRowClick={setSel}
              columns={[
                { header: "When", cell: (a) => dateTime(a.created_at) },
                { header: "Action", cell: (a) => <code className="text-xs">{a.action}</code> },
                { header: "Actor", cell: (a) => `${a.actor_type}${a.actor_id ? ` · ${a.actor_id.slice(0, 8)}` : ""}`, hideOnMobile: true },
                { header: "Target", cell: (a) => (a.target_type ? `${a.target_type}:${(a.target_id ?? "").slice(0, 24)}` : "—"), hideOnMobile: true },
                { header: "IP", cell: (a) => a.ip_address ?? "—", hideOnMobile: true },
              ]} />
            <Pagination page={page} pageSize={50} total={q.data.total} onPage={setPage} />
          </>
        )}
      </Card>
      <Modal open={!!sel} onClose={() => setSel(null)} title={sel?.action ?? ""} wide>
        {sel && <pre className="overflow-x-auto rounded-lg bg-slate-50 p-4 text-xs">{JSON.stringify(sel, null, 2)}</pre>}
      </Modal>
    </>
  );
}

// ------------------------------------------------------------------ maker-checker approvals
export function AdminApprovals() {
  const { user } = useAuth();
  const [status, setStatus] = useState("pending");
  const q = useGet<any[]>(["approvals", status], "/admin/approvals", { status });
  const [sel, setSel] = useState<any>(null);
  const [note, setNote] = useState("");
  const review = useAction((decision: string) => api(`/admin/approvals/${sel.id}/review`, { body: { decision, note: note || null } }), {
    invalidate: [["approvals"], ["admin-txns"]],
    success: (r: any) => `Request ${r.status}`,
    onSuccess: () => { setSel(null); setNote(""); },
  });
  return (
    <>
      <PageHeader title="Approvals" subtitle="Four-eyes control: high-value adjustments and reversals need a second finance/admin user." />
      <Card>
        <Tabs value={status} onChange={setStatus} tabs={["pending", "executed", "rejected", "failed"].map((s) => ({ value: s, label: titleCase(s) }))} />
        {q.isLoading ? <Spinner /> : !q.data?.length ? <Empty title="Nothing waiting" /> : (
          <Table rows={q.data} keyFn={(a) => a.id} onRowClick={setSel}
            columns={[
              { header: "Action", cell: (a) => titleCase(a.action) },
              { header: "Amount", cell: (a) => money(a.amount) },
              { header: "Reason", cell: (a) => a.reason },
              { header: "Requested", cell: (a) => dateTime(a.created_at), hideOnMobile: true },
              { header: "Status", cell: (a) => <Badge>{a.status}</Badge> },
            ]} />
        )}
      </Card>
      <Modal open={!!sel} onClose={() => setSel(null)} title={`${titleCase(sel?.action)} approval`}>
        {sel && (
          <>
            <KV items={[["Amount", money(sel.amount)], ["Reason", sel.reason], ["Requested", dateTime(sel.created_at)],
              ...Object.entries(sel.payload).filter(([k]) => !["reason", "amount"].includes(k)).map(([k, v]) => [titleCase(k), String(v)] as [string, string]),
              ...(sel.result?.message || sel.result?.transaction ? [["Result", sel.result.transaction ?? sel.result.message] as [string, string]] : [])]} />
            {sel.status === "pending" && (sel.requested_by_id === user?.id ? (
              <div className="mt-4"><Alert tone="info">You raised this request — another finance or admin user must review it.</Alert></div>
            ) : (
              <div className="mt-4 space-y-3">
                <Textarea label="Note" value={note} onChange={(e) => setNote(e.target.value)} rows={2} />
                <div className="grid grid-cols-2 gap-2">
                  <Button variant="danger" onClick={() => review.mutate("reject")} loading={review.isPending}>Reject</Button>
                  <Button onClick={() => review.mutate("approve")} loading={review.isPending}>Approve & execute</Button>
                </div>
              </div>
            ))}
          </>
        )}
      </Modal>
    </>
  );
}
