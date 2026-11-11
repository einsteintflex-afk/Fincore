import { Briefcase, Copy, ExternalLink, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  Alert,
  Amount,
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
  Pagination,
  Select,
  Spinner,
  Stat,
  Table,
  Tabs,
} from "@/components/ui";
import { api, downloadFile, newIdempotencyKey } from "@/lib/api";
import { amountError, dateOnly, dateTime, maskPhone, money, NETWORKS, titleCase } from "@/lib/format";
import { useAction, useBusinesses, useGet } from "@/lib/hooks";
import type { Business, Page, PaymentLink, PaymentRequest, Transaction, Wallet } from "@/lib/types";
import { TransactionDetail } from "@/pages/customer/CustomerPages";
import { useToast } from "@/components/toast";

function useBiz() {
  const { bizId } = useParams();
  const q = useGet<Business>(["business", bizId], `/businesses/${bizId}`);
  const perms = useGet<{ role: string; permissions: string[] }>(["business-perms", bizId], `/businesses/${bizId}/permissions`);
  const can = (p: string) => perms.data?.permissions.includes(p) ?? false;
  return { bizId: bizId!, biz: q.data, can, ...q };
}

const BUSINESS_TYPES = ["sole_proprietorship", "partnership", "limited_company", "ngo", "public_company"];

// ------------------------------------------------------------------ onboarding
export function MerchantHome() {
  const { data, isLoading } = useBusinesses();
  if (isLoading) return <Spinner />;
  if (data && data.length) return <Navigate to={`/merchant/${data[0].id}`} replace />;
  return <CreateBusiness />;
}

export function CreateBusiness() {
  const nav = useNavigate();
  const [form, setForm] = useState({ name: "", trading_name: "", business_type: "sole_proprietorship", industry: "", email: "", phone: "", registration_number: "", tin: "", address: "", website: "" });
  const create = useAction(() => api<Business>("/businesses", { body: Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v || null])) }), {
    invalidate: [["businesses"]], success: "Business submitted for review", onSuccess: (b) => nav(`/merchant/${b.id}`),
  });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });
  return (
    <>
      <PageHeader title="Start accepting payments" subtitle="Register your business. You can test with sandbox keys while we review your details." />
      <Card className="max-w-3xl">
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); create.mutate(undefined); }}>
          <Input label="Registered business name" value={form.name} onChange={set("name")} required />
          <Input label="Trading name" value={form.trading_name} onChange={set("trading_name")} />
          <Select label="Business type" value={form.business_type} onChange={set("business_type")}>
            {BUSINESS_TYPES.map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}
          </Select>
          <Input label="Industry" value={form.industry} onChange={set("industry")} placeholder="e.g. Retail, Food & beverage" />
          <Input label="Business email" type="email" value={form.email} onChange={set("email")} required />
          <Input label="Business phone" value={form.phone} onChange={set("phone")} />
          <Input label="ORC registration number" value={form.registration_number} onChange={set("registration_number")} />
          <Input label="GRA TIN" value={form.tin} onChange={set("tin")} />
          <Input label="Address" value={form.address} onChange={set("address")} />
          <Input label="Website" value={form.website} onChange={set("website")} />
          <div className="sm:col-span-2">
            <Button type="submit" size="lg" icon={<Briefcase className="h-4 w-4" />} loading={create.isPending}>Submit business</Button>
          </div>
        </form>
      </Card>
    </>
  );
}

// ------------------------------------------------------------------ overview
export function MerchantOverview() {
  const { bizId, biz, isLoading } = useBiz();
  const [env, setEnv] = useState("live");
  const a = useGet<any>(["merchant-analytics", bizId, env], `/businesses/${bizId}/analytics`, { environment: env });
  const wallets = useGet<Wallet[]>(["biz-wallets", bizId], `/businesses/${bizId}/wallets`);
  if (isLoading || !biz) return <Spinner />;
  const chart = (a.data?.daily ?? []).map((d: any) => ({ day: d.day.slice(5), volume: Number(d.volume) }));
  return (
    <>
      <PageHeader title={biz.trading_name || biz.name} subtitle={<>Merchant code <span className="font-mono">{biz.merchant_code}</span> · <Badge>{biz.status}</Badge></>}
        actions={<Tabs value={env} onChange={setEnv} tabs={[{ value: "live", label: "Live" }, { value: "sandbox", label: "Sandbox" }]} />} />
      {biz.status === "pending" && <div className="mb-4"><Alert tone="warning">Your business is under review. Live payments unlock once approved — use sandbox keys from the Developers portal to integrate now.</Alert></div>}
      {biz.status === "rejected" && <div className="mb-4"><Alert tone="error">Your application was not approved. {biz.review_note}</Alert></div>}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat tone="brand" label="Available balance" value={money(wallets.data?.[0]?.balance ?? "0")} sub={`Account ${wallets.data?.[0]?.account_number ?? ""}`} />
        <Stat label="Volume (30d)" value={money(a.data?.volume ?? "0")} sub={`${a.data?.successful ?? 0} successful payments`} />
        <Stat label="Conversion" value={`${((a.data?.conversion ?? 0) * 100).toFixed(1)}%`} sub={`${a.data?.charges ?? 0} payment attempts`} />
        <Stat label="Fees (30d)" value={money(a.data?.fees ?? "0")} sub={`Refunded ${money(a.data?.refunded ?? "0")}`} />
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card title="Daily volume" className="lg:col-span-2">
          {chart.length ? (
            <div className="h-64">
              <ResponsiveContainer>
                <AreaChart data={chart}>
                  <defs>
                    <linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#059669" stopOpacity={0.3} /><stop offset="100%" stopColor="#059669" stopOpacity={0} /></linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="day" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: number) => money(v.toFixed(2))} />
                  <Area type="monotone" dataKey="volume" stroke="#047857" fill="url(#g)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : <Empty title="No payments yet" body="Create a payment link or integrate the API to start collecting." />}
        </Card>
        <Card title="Payment channels">
          {a.data?.channels?.length ? (
            <ul className="space-y-2 text-sm">
              {a.data.channels.map((c: any) => (
                <li key={`${c.channel}-${c.network}`} className="flex justify-between">
                  <span>{c.network ? NETWORKS[c.network] : titleCase(c.channel)}</span>
                  <span className="font-medium">{c.count}</span>
                </li>
              ))}
            </ul>
          ) : <Empty title="No data" />}
        </Card>
      </div>
    </>
  );
}

// ------------------------------------------------------------------ payments
export function MerchantPayments() {
  const { bizId, can } = useBiz();
  const [env, setEnv] = useState("live");
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const list = useGet<Page<PaymentRequest>>(["payments", bizId, env, page, status, search], `/businesses/${bizId}/payment-requests`, { environment: env, page, status, search });
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<PaymentRequest | null>(null);
  return (
    <>
      <PageHeader title="Payments" actions={can("payments:create") && <Button icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>Request payment</Button>} />
      <Card>
        <Tabs value={env} onChange={(v) => { setEnv(v); setPage(1); }} tabs={[{ value: "live", label: "Live" }, { value: "sandbox", label: "Sandbox (API tests)" }]} />
        <div className="mb-4 grid gap-3 sm:grid-cols-3">
          <Input placeholder="Search reference, email, phone" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Status">
            <option value="">All statuses</option>
            {["pending", "processing", "successful", "failed", "refunded", "partially_refunded", "expired", "cancelled"].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
          </Select>
        </div>
        {list.isLoading ? <Spinner /> : list.error ? <ErrorState error={list.error} /> : !list.data?.items.length ? <Empty title="No payments" /> : (
          <>
            <Table rows={list.data.items} keyFn={(p) => p.id} onRowClick={setSelected}
              columns={[
                { header: "Date", cell: (p) => dateTime(p.created_at), hideOnMobile: true },
                { header: "Customer", cell: (p) => <div><p className="font-medium">{p.customer_name || p.customer_email || maskPhone(p.customer_phone) || "—"}</p><p className="text-xs text-slate-500">{p.reference}</p></div> },
                { header: "Channel", cell: (p) => (p.network ? NETWORKS[p.network] : titleCase(p.channel)), hideOnMobile: true },
                { header: "Status", cell: (p) => <Badge>{p.status}</Badge> },
                { header: "Amount", cell: (p) => <Amount value={p.amount} />, className: "text-right" },
              ]} />
            <Pagination page={page} pageSize={20} total={list.data.total} onPage={setPage} />
          </>
        )}
      </Card>
      <CreatePaymentRequest open={creating} onClose={() => setCreating(false)} bizId={bizId} />
      <PaymentDetail p={selected} onClose={() => setSelected(null)} bizId={bizId} canRefund={can("refunds:create")} />
    </>
  );
}

function CreatePaymentRequest({ open, onClose, bizId }: { open: boolean; onClose: () => void; bizId: string }) {
  const [form, setForm] = useState({ amount: "", description: "", customer_email: "", customer_phone: "", merchant_reference: "" });
  const [created, setCreated] = useState<PaymentRequest | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const create = useAction(() => api<PaymentRequest>(`/businesses/${bizId}/payment-requests`, { body: Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v || null])) }), {
    invalidate: [["payments", bizId]], onSuccess: setCreated,
  });
  const close = () => { setCreated(null); setForm({ amount: "", description: "", customer_email: "", customer_phone: "", merchant_reference: "" }); onClose(); };
  function submit(e: FormEvent) {
    e.preventDefault();
    const ae = amountError(form.amount);
    if (ae) return setErr(ae);
    setErr(null);
    create.mutate(undefined);
  }
  return (
    <Modal open={open} onClose={close} title="Request a payment">
      {created ? (
        <div className="space-y-3 text-center">
          <p className="text-sm text-slate-600">Share this checkout link with your customer:</p>
          <CopyText text={`${window.location.origin}/checkout/${created.reference}`} className="block w-full break-all" />
          <a href={`/checkout/${created.reference}`} target="_blank" rel="noreferrer"><Button variant="secondary" icon={<ExternalLink className="h-4 w-4" />}>Open checkout</Button></a>
        </div>
      ) : (
        <form className="space-y-3" onSubmit={submit}>
          {err && <Alert tone="error">{err}</Alert>}
          <Input label="Amount (GHS)" inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} required />
          <Input label="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          <Input label="Customer email" type="email" value={form.customer_email} onChange={(e) => setForm({ ...form, customer_email: e.target.value })} />
          <Input label="Customer phone" value={form.customer_phone} onChange={(e) => setForm({ ...form, customer_phone: e.target.value })} />
          <Input label="Your reference (optional)" value={form.merchant_reference} onChange={(e) => setForm({ ...form, merchant_reference: e.target.value })} />
          <Button type="submit" className="w-full" loading={create.isPending}>Create checkout link</Button>
        </form>
      )}
    </Modal>
  );
}

function PaymentDetail({ p, onClose, bizId, canRefund }: { p: PaymentRequest | null; onClose: () => void; bizId: string; canRefund: boolean }) {
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [idem] = useState(newIdempotencyKey());
  const refund = useAction(() => api(`/businesses/${bizId}/payment-requests/${p!.reference}/refunds`, { body: { amount: amount || null, reason: reason || null }, idempotencyKey: idem + amount }), {
    invalidate: [["payments", bizId], ["biz-wallets", bizId]], success: "Refund processed", onSuccess: onClose,
  });
  const cancel = useAction(() => api(`/businesses/${bizId}/payment-requests/${p!.reference}/cancel`, { method: "POST" }), { invalidate: [["payments", bizId]], success: "Payment request cancelled", onSuccess: onClose });
  if (!p) return null;
  const refundable = ["successful", "partially_refunded"].includes(p.status) && p.environment === "live";
  return (
    <Modal open onClose={onClose} title={`Payment ${p.reference}`}>
      <div className="mb-4 text-center">
        <p className="tabular text-3xl font-semibold">{money(p.amount)}</p>
        <div className="mt-2 flex justify-center gap-2"><Badge>{p.status}</Badge>{p.environment === "sandbox" && <Badge tone="sandbox">Sandbox</Badge>}</div>
      </div>
      <KV items={[
        ["Fee", money(p.fee)],
        ["Net", money((Number(p.amount) - Number(p.fee)).toFixed(2))],
        ["Refunded", money(p.amount_refunded)],
        ["Customer", p.customer_name || p.customer_email || "—"],
        ["Phone", maskPhone(p.customer_phone) || "—"],
        ["Channel", p.network ? NETWORKS[p.network] : titleCase(p.channel)],
        ["Your reference", p.merchant_reference],
        ...((p.metadata?.form ?? []) as { label: string; value: string }[]).map((a) => [a.label, a.value] as [string, string]),
        ["Created", dateTime(p.created_at)],
        ["Paid", dateTime(p.paid_at)],
        ...(p.failure_reason ? [["Failure", p.failure_reason] as [string, string]] : []),
      ]} />
      {p.status === "pending" && <Button variant="secondary" className="mt-4 w-full" onClick={() => cancel.mutate(undefined)}>Cancel request</Button>}
      {p.paid_at && (
        <Button variant="secondary" className="mt-4 w-full" onClick={() => downloadFile(`/businesses/${bizId}/payment-requests/${p.reference}/receipt.pdf`, undefined, `fincore-payment-${p.reference}.pdf`)}>
          Download receipt
        </Button>
      )}
      {refundable && canRefund && (
        <form className="mt-5 space-y-3 border-t border-slate-100 pt-4" onSubmit={(e) => { e.preventDefault(); refund.mutate(undefined); }}>
          <p className="text-sm font-medium">Refund</p>
          <Input placeholder={`Full amount (${money((Number(p.amount) - Number(p.amount_refunded)).toFixed(2))})`} value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" />
          <Input placeholder="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          <Button variant="danger" type="submit" className="w-full" loading={refund.isPending}>Issue refund</Button>
        </form>
      )}
    </Modal>
  );
}

// ------------------------------------------------------------------ links
type FieldDraft = { label: string; type: string; required: boolean; options: string };
const FIELD_TYPES: [string, string][] = [["text", "Text"], ["phone", "Phone number"], ["email", "Email"], ["number", "Number"], ["date", "Date"], ["select", "Choice list"]];

function LinkEditor({ bizId, link, onDone }: { bizId: string; link: PaymentLink | null; onDone: () => void }) {
  const [form, setForm] = useState({
    title: link?.title ?? "", description: link?.description ?? "", amount: link?.amount ?? "", single_use: link?.single_use ?? false,
    redirect_url: "",
  });
  const [fields, setFields] = useState<FieldDraft[]>(
    (link?.fields ?? []).map((f: any) => ({ label: f.label, type: f.type, required: f.required, options: (f.options ?? []).join(", ") })),
  );
  const payloadFields = () => fields.filter((f) => f.label.trim()).map((f) => ({
    label: f.label, type: f.type, required: f.required, options: f.type === "select" ? f.options.split(",").map((o) => o.trim()).filter(Boolean) : [],
  }));
  const save = useAction(() => link
    ? api(`/businesses/${bizId}/payment-links/${link.id}`, { method: "PATCH", body: { title: form.title, description: form.description || null, amount: form.amount || null, fields: payloadFields() } })
    : api(`/businesses/${bizId}/payment-links`, { body: { ...form, amount: form.amount || null, redirect_url: form.redirect_url || null, description: form.description || null, fields: payloadFields() } }), {
    invalidate: [["links", bizId]], success: link ? "Payment link updated" : "Payment link created", onSuccess: onDone,
  });
  const setField = (i: number, patch: Partial<FieldDraft>) => setFields(fields.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(undefined); }}>
      <Input label="Title (what people are paying for)" placeholder="e.g. Nursing admission form" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} required />
      <Input label="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
      <Input label="Price in GHS (leave blank to let the payer enter an amount)" inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
      <div className="rounded-lg bg-slate-50 p-3">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-sm font-medium text-slate-700">Questions the payer must answer</p>
          <Button type="button" size="sm" variant="secondary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setFields([...fields, { label: "", type: "text", required: true, options: "" }])}>Add question</Button>
        </div>
        {fields.length === 0 && <p className="text-xs text-slate-500">None yet — e.g. Full name, Programme, Index number, Phone.</p>}
        <div className="space-y-2">
          {fields.map((f, i) => (
            <div key={i} className="grid grid-cols-12 items-end gap-2 rounded-md bg-white p-2 ring-1 ring-slate-200">
              <div className="col-span-12 sm:col-span-5"><Input aria-label={`Question ${i + 1}`} placeholder="Question, e.g. Index number" value={f.label} onChange={(e) => setField(i, { label: e.target.value })} /></div>
              <div className="col-span-6 sm:col-span-3">
                <Select aria-label={`Answer type ${i + 1}`} value={f.type} onChange={(e) => setField(i, { type: e.target.value })}>
                  {FIELD_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </Select>
              </div>
              <label className="col-span-4 flex items-center gap-1 pb-2 text-xs sm:col-span-3"><input type="checkbox" checked={f.required} onChange={(e) => setField(i, { required: e.target.checked })} /> Required</label>
              <button type="button" className="col-span-2 pb-2 text-xs text-rose-600 sm:col-span-1" onClick={() => setFields(fields.filter((_, j) => j !== i))} aria-label="Remove question">✕</button>
              {f.type === "select" && (
                <div className="col-span-12"><Input placeholder="Choices separated by commas, e.g. Registered Nursing, Midwifery" value={f.options} onChange={(e) => setField(i, { options: e.target.value })} /></div>
              )}
            </div>
          ))}
        </div>
      </div>
      {!link && (
        <>
          <Input label="Redirect URL after payment (optional)" value={form.redirect_url} onChange={(e) => setForm({ ...form, redirect_url: e.target.value })} />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.single_use} onChange={(e) => setForm({ ...form, single_use: e.target.checked })} /> Single use</label>
        </>
      )}
      <Button type="submit" className="w-full" loading={save.isPending}>{link ? "Save changes" : "Create link"}</Button>
    </form>
  );
}

function buttonCode(l: PaymentLink): string {
  const label = l.amount ? `Pay ${money(l.amount)}` : "Pay now";
  return `<a href="${window.location.origin}/pay/${l.slug}" style="display:inline-block;background:#047857;color:#ffffff;padding:12px 22px;border-radius:8px;font-family:Arial,sans-serif;font-weight:bold;text-decoration:none">${label} — ${l.title.replace(/[<>"]/g, "")}</a>`;
}

export function MerchantLinks() {
  const { bizId, can } = useBiz();
  const links = useGet<PaymentLink[]>(["links", bizId], `/businesses/${bizId}/payment-links`);
  const [editing, setEditing] = useState<PaymentLink | "new" | null>(null);
  const [embed, setEmbed] = useState<PaymentLink | null>(null);
  const toast = useToast();
  const toggle = useAction((l: PaymentLink) => api(`/businesses/${bizId}/payment-links/${l.id}`, { method: "PATCH", body: { active: !l.active } }), { invalidate: [["links", bizId]] });
  const copy = (text: string, what: string) => { navigator.clipboard?.writeText(text); toast.success(`${what} copied`); };
  return (
    <>
      <PageHeader title="Payment links" subtitle="A link or button for each fee or product — paste it into your website, WhatsApp or SMS."
        actions={can("payments:create") && <Button icon={<Plus className="h-4 w-4" />} onClick={() => setEditing("new")}>New link</Button>} />
      <Card padded={false}>
        {links.isLoading ? <Spinner /> : !links.data?.length ? <Empty title="No payment links yet" body="Create one for each fee, e.g. 'Admission form — GH₵150'." /> : (
          <ul className="divide-y divide-slate-100">
            {links.data.map((l) => (
              <li key={l.id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="font-medium">{l.title} {!l.active && <Badge>inactive</Badge>}</p>
                  <p className="text-sm text-slate-500">
                    {l.amount ? money(l.amount) : "Payer enters amount"} · {l.payments_count} payments
                    {l.fields?.length ? ` · ${l.fields.length} question${l.fields.length > 1 ? "s" : ""}` : ""}{l.single_use && " · single use"}
                  </p>
                  <p className="truncate font-mono text-xs text-brand-700">{window.location.origin}/pay/{l.slug}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="secondary" icon={<Copy className="h-3.5 w-3.5" />} onClick={() => copy(`${window.location.origin}/pay/${l.slug}`, "Link")}>Copy link</Button>
                  <Button size="sm" variant="secondary" onClick={() => setEmbed(l)}>Button code</Button>
                  {can("payments:create") && <Button size="sm" variant="ghost" onClick={() => setEditing(l)}>Edit</Button>}
                  <Button size="sm" variant="ghost" onClick={() => toggle.mutate(l)}>{l.active ? "Deactivate" : "Activate"}</Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Modal open={!!editing} onClose={() => setEditing(null)} title={editing === "new" ? "New payment link" : "Edit payment link"} wide>
        {editing && <LinkEditor key={editing === "new" ? "new" : editing.id} bizId={bizId} link={editing === "new" ? null : editing} onDone={() => setEditing(null)} />}
      </Modal>
      <Modal open={!!embed} onClose={() => setEmbed(null)} title="Pay button for your website" wide>
        {embed && (
          <div className="space-y-4">
            <p className="text-sm text-slate-600">Paste this code into your website where the button should appear. It opens FinCore's secure payment page.</p>
            <div className="rounded-lg bg-slate-50 p-4 text-center" dangerouslySetInnerHTML={{ __html: buttonCode(embed) }} />
            <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-ink-900 p-3 text-xs text-emerald-200">{buttonCode(embed)}</pre>
            <Button className="w-full" icon={<Copy className="h-4 w-4" />} onClick={() => copy(buttonCode(embed), "Button code")}>Copy button code</Button>
          </div>
        )}
      </Modal>
    </>
  );
}

// ------------------------------------------------------------------ transactions
export function MerchantTransactions() {
  const { bizId } = useBiz();
  const [page, setPage] = useState(1);
  const [type, setType] = useState("");
  const list = useGet<Page<Transaction>>(["biz-txns", bizId, page, type], `/businesses/${bizId}/transactions`, { page, type });
  const [selected, setSelected] = useState<Transaction | null>(null);
  return (
    <>
      <PageHeader title="Transactions" subtitle="Every movement on your business wallet." />
      <Card>
        <div className="mb-4 max-w-xs">
          <Select value={type} onChange={(e) => { setType(e.target.value); setPage(1); }} aria-label="Type">
            <option value="">All types</option>
            {["payment", "refund", "settlement", "reversal", "adjustment"].map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}
          </Select>
        </div>
        {list.isLoading ? <Spinner /> : !list.data?.items.length ? <Empty title="No transactions" /> : (
          <>
            <Table rows={list.data.items} keyFn={(t) => t.id} onRowClick={setSelected}
              columns={[
                { header: "Date", cell: (t) => dateTime(t.created_at), hideOnMobile: true },
                { header: "Description", cell: (t) => <div><p className="font-medium">{t.description}</p><p className="text-xs text-slate-500">{t.reference}</p></div> },
                { header: "Status", cell: (t) => <Badge>{t.status}</Badge> },
                { header: "Fee", cell: (t) => money(t.fee), hideOnMobile: true },
                { header: "Amount", cell: (t) => <Amount value={t.amount} direction={t.direction} />, className: "text-right" },
              ]} />
            <Pagination page={page} pageSize={20} total={list.data.total} onPage={setPage} />
          </>
        )}
      </Card>
      <TransactionDetail t={selected} onClose={() => setSelected(null)} />
    </>
  );
}

// ------------------------------------------------------------------ settlements
export function MerchantSettlements() {
  const { bizId, biz, can } = useBiz();
  const list = useGet<any[]>(["settlements", bizId], `/businesses/${bizId}/settlements`);
  const wallets = useGet<Wallet[]>(["biz-wallets", bizId], `/businesses/${bizId}/wallets`);
  const [amount, setAmount] = useState("");
  const [idem, setIdem] = useState(newIdempotencyKey());
  const settle = useAction(() => api(`/businesses/${bizId}/settlements`, { body: { amount: amount || null }, idempotencyKey: idem }), {
    invalidate: [["settlements", bizId], ["biz-wallets", bizId]], success: (s: any) => `Settlement ${s.status}`, onSuccess: () => { setAmount(""); setIdem(newIdempotencyKey()); },
  });
  const dest = biz?.settlement_destination ?? {};
  return (
    <>
      <PageHeader title="Settlements" subtitle="Move your collections to your bank or mobile money account." />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Pay out">
          <Stat label="Available" value={money(wallets.data?.[0]?.balance ?? "0")} />
          {!dest.channel ? (
            <div className="mt-4"><Alert tone="warning">Add a settlement account in Settings first.</Alert></div>
          ) : (
            <form className="mt-4 space-y-3" onSubmit={(e) => { e.preventDefault(); settle.mutate(undefined); }}>
              <p className="text-sm text-slate-600">To {dest.channel === "bank" ? `${dest.bank_code} ****${String(dest.account_number).slice(-4)}` : maskPhone(dest.msisdn)}</p>
              <Input placeholder="Amount (blank = everything available)" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
              <Button type="submit" className="w-full" loading={settle.isPending} disabled={!can("settlements:create")}>Settle now</Button>
            </form>
          )}
        </Card>
        <Card title="History" className="lg:col-span-2" padded={false}>
          {list.isLoading ? <Spinner /> : !list.data?.length ? <Empty title="No settlements yet" /> : (
            <div className="p-4">
              <Table rows={list.data} keyFn={(s) => s.id}
                columns={[
                  { header: "Date", cell: (s) => dateTime(s.created_at) },
                  { header: "Reference", cell: (s) => <span className="font-mono text-xs">{s.reference}</span>, hideOnMobile: true },
                  { header: "Status", cell: (s) => <Badge>{s.status}</Badge> },
                  { header: "Fee", cell: (s) => money(s.fee), hideOnMobile: true },
                  { header: "Amount", cell: (s) => money(s.amount), className: "text-right tabular" },
                ]} />
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

// ------------------------------------------------------------------ reports
export function MerchantReports() {
  const { bizId } = useBiz();
  const today = new Date().toISOString().slice(0, 10);
  const [range, setRange] = useState({ start: new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10), end: today });
  const r = useGet<any>(["report", bizId, range], `/businesses/${bizId}/reports/settlement`, range);
  return (
    <>
      <PageHeader title="Reports" subtitle="Settlement and financial statement for a period." actions={<Button variant="secondary" onClick={() => window.print()}>Print</Button>} />
      <Card>
        <div className="mb-4 grid max-w-md grid-cols-2 gap-3">
          <Input label="From" type="date" value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} />
          <Input label="To" type="date" value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} />
        </div>
        {r.isLoading ? <Spinner /> : r.data && (
          <>
            <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <Stat label="Payments" value={r.data.payments_count} />
              <Stat label="Gross" value={money(r.data.gross_volume)} />
              <Stat label="Fees" value={money(r.data.fees)} />
              <Stat label="Refunds" value={money(r.data.refunds)} />
              <Stat label="Net" value={money(r.data.net_volume)} tone="brand" />
              <Stat label="Settled" value={money(r.data.settled)} />
            </div>
            <h3 className="mb-2 mt-6 text-sm font-semibold">Settlements in period</h3>
            {r.data.settlements.length ? (
              <Table rows={r.data.settlements} keyFn={(s: any) => s.reference}
                columns={[
                  { header: "Reference", cell: (s: any) => s.reference },
                  { header: "Date", cell: (s: any) => dateOnly(s.created_at) },
                  { header: "Status", cell: (s: any) => <Badge>{s.status}</Badge> },
                  { header: "Amount", cell: (s: any) => money(s.amount), className: "text-right" },
                ]} />
            ) : <Empty title="No settlements in this period" />}
          </>
        )}
      </Card>
    </>
  );
}

// ------------------------------------------------------------------ team
export function MerchantTeam() {
  const { bizId, can } = useBiz();
  const members = useGet<any[]>(["members", bizId], `/businesses/${bizId}/members`);
  const [form, setForm] = useState({ email: "", role: "viewer" });
  const add = useAction(() => api(`/businesses/${bizId}/members`, { body: form }), { invalidate: [["members", bizId]], success: "Team member added", onSuccess: () => setForm({ email: "", role: "viewer" }) });
  const update = useAction((v: { id: string; role?: string; remove?: boolean }) => api(`/businesses/${bizId}/members/${v.id}`, { method: "PATCH", body: v }), { invalidate: [["members", bizId]], success: "Updated" });
  const roles = ["admin", "finance", "developer", "support", "viewer"];
  return (
    <>
      <PageHeader title="Team" subtitle="Give colleagues access with the right permissions." />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Members" className="lg:col-span-2">
          {members.isLoading ? <Spinner /> : (
            <Table rows={members.data ?? []} keyFn={(m) => m.id}
              columns={[
                { header: "Name", cell: (m) => <div><p className="font-medium">{m.full_name}</p><p className="text-xs text-slate-500">{m.email}</p></div> },
                { header: "Role", cell: (m) => m.role === "owner" || !can("members:manage") ? <Badge>{m.role}</Badge> : (
                  <select className="rounded-md border-slate-300 text-sm" value={m.role} onChange={(e) => update.mutate({ id: m.id, role: e.target.value })}>
                    {roles.map((r) => <option key={r}>{r}</option>)}
                  </select>
                ) },
                { header: "", cell: (m) => m.role !== "owner" && can("members:manage") && <Button size="sm" variant="ghost" onClick={() => update.mutate({ id: m.id, remove: true })}>Remove</Button>, className: "text-right" },
              ]} />
          )}
        </Card>
        {can("members:manage") && (
          <Card title="Invite">
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); add.mutate(undefined); }}>
              <Input label="Email of FinCore user" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
              <Select label="Role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                {roles.map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}
              </Select>
              <Button type="submit" className="w-full" loading={add.isPending}>Add member</Button>
            </form>
          </Card>
        )}
      </div>
    </>
  );
}

// ------------------------------------------------------------------ settings
export function MerchantSettings() {
  const { bizId, biz, can } = useBiz();
  const banks = useGet<{ code: string; name: string }[]>(["banks"], "/banks");
  const [dest, setDest] = useState<any>(null);
  const [profile, setProfile] = useState<any>(null);
  const d = dest ?? { channel: biz?.settlement_destination?.channel ?? "bank", bank_code: biz?.settlement_destination?.bank_code ?? "", account_number: biz?.settlement_destination?.account_number ?? "", phone: "", account_name: biz?.settlement_destination?.account_name ?? "" };
  const p = profile ?? { trading_name: biz?.trading_name ?? "", industry: biz?.industry ?? "", address: biz?.address ?? "", website: biz?.website ?? "", settlement_schedule: biz?.settlement_schedule ?? "manual" };
  const saveDest = useAction(() => api(`/businesses/${bizId}/settlement-destination`, { method: "PUT", body: d }), { invalidate: [["business", bizId]], success: "Settlement account saved" });
  const saveProfile = useAction(() => api(`/businesses/${bizId}`, { method: "PATCH", body: p }), { invalidate: [["business", bizId], ["businesses"]], success: "Business updated" });
  if (!biz) return <Spinner />;
  const editable = can("business:manage");
  return (
    <>
      <PageHeader title="Settings" />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Business profile">
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); saveProfile.mutate(undefined); }}>
            <KV items={[["Registered name", biz.name], ["Merchant code", biz.merchant_code], ["Type", titleCase(biz.business_type)], ["Status", <Badge key="s">{biz.status}</Badge>]]} />
            <Input label="Trading name" value={p.trading_name} onChange={(e) => setProfile({ ...p, trading_name: e.target.value })} disabled={!editable} />
            <Input label="Industry" value={p.industry} onChange={(e) => setProfile({ ...p, industry: e.target.value })} disabled={!editable} />
            <Input label="Address" value={p.address} onChange={(e) => setProfile({ ...p, address: e.target.value })} disabled={!editable} />
            <Input label="Website" value={p.website} onChange={(e) => setProfile({ ...p, website: e.target.value })} disabled={!editable} />
            <Select label="Settlement schedule" value={p.settlement_schedule} onChange={(e) => setProfile({ ...p, settlement_schedule: e.target.value })} disabled={!editable}>
              <option value="manual">Manual</option><option value="daily">Daily</option><option value="weekly">Weekly</option>
            </Select>
            {editable && <Button type="submit" loading={saveProfile.isPending}>Save profile</Button>}
          </form>
        </Card>
        <Card title="Settlement account">
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); saveDest.mutate(undefined); }}>
            <Select label="Channel" value={d.channel} onChange={(e) => setDest({ ...d, channel: e.target.value })} disabled={!editable}>
              <option value="bank">Bank account</option><option value="mobile_money">Mobile money</option>
            </Select>
            {d.channel === "bank" ? (
              <>
                <Select label="Bank" value={d.bank_code} onChange={(e) => setDest({ ...d, bank_code: e.target.value })} disabled={!editable}>
                  <option value="">Select bank</option>
                  {banks.data?.map((b) => <option key={b.code} value={b.code}>{b.name}</option>)}
                </Select>
                <Input label="Account number" value={d.account_number} onChange={(e) => setDest({ ...d, account_number: e.target.value })} disabled={!editable} />
              </>
            ) : (
              <Input label="Mobile money number" value={d.phone} onChange={(e) => setDest({ ...d, phone: e.target.value })} disabled={!editable} />
            )}
            <Input label="Account name" value={d.account_name} onChange={(e) => setDest({ ...d, account_name: e.target.value })} disabled={!editable} />
            {editable && <Button type="submit" loading={saveDest.isPending}>Save settlement account</Button>}
          </form>
        </Card>
      </div>
    </>
  );
}
