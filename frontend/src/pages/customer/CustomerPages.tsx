import { ArrowDownToLine, ArrowLeftRight, ArrowUpFromLine, Download, Plus, Star, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
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
  Textarea,
} from "@/components/ui";
import { api, downloadFile, newIdempotencyKey } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { amountError, dateOnly, dateTime, detectNetwork, maskPhone, money, NETWORKS, titleCase } from "@/lib/format";
import { useAction, useGet, useWallets } from "@/lib/hooks";
import { useToast } from "@/components/toast";
import type { Page, Transaction, Wallet } from "@/lib/types";

// ------------------------------------------------------------------ shared
export function TransactionRow({ t }: { t: Transaction }) {
  return (
    <div className="flex items-center justify-between gap-3 py-3">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-slate-800">{t.description || titleCase(t.type)}</p>
        <p className="text-xs text-slate-500">
          {dateTime(t.created_at)} · {titleCase(t.type)}
          {t.provider_mode === "sandbox" && <span className="ml-1 text-yellow-700">· simulated</span>}
        </p>
      </div>
      <div className="text-right">
        <Amount value={t.amount} direction={t.direction} />
        <div className="mt-0.5">{t.status !== "successful" && <Badge>{t.status}</Badge>}</div>
      </div>
    </div>
  );
}

export function TransactionDetail({ t, onClose }: { t: Transaction | null; onClose: () => void }) {
  const refresh = useAction((ref: string) => api(`/transactions/${ref}/refresh`, { method: "POST" }), { invalidate: [["transactions"], ["wallets"]] });
  const simulate = useAction((v: { ref: string; outcome: string }) => api(`/transactions/${v.ref}/simulate`, { method: "POST", query: { outcome: v.outcome } }), {
    invalidate: [["transactions"], ["wallets"]],
    success: "Simulated outcome applied",
    onSuccess: onClose,
  });
  if (!t) return null;
  const cp = t.counterparty || {};
  return (
    <Modal open={!!t} onClose={onClose} title="Transaction details">
      <div className="mb-4 text-center">
        <Amount value={t.amount} direction={t.direction} className="text-3xl" />
        <div className="mt-2 flex justify-center gap-2">
          <Badge>{t.status}</Badge>
          {t.provider_mode === "sandbox" && <Badge tone="sandbox">Simulated</Badge>}
        </div>
      </div>
      <KV
        items={[
          ["Reference", <CopyText key="r" text={t.reference} />],
          ["Type", titleCase(t.type)],
          ["Description", t.description],
          ["Fee", money(t.fee, t.currency)],
          ["Channel", titleCase(t.channel)],
          ["Counterparty", cp.name || cp.label || cp.account_number || maskPhone(cp.msisdn) || "—"],
          ["Date", dateTime(t.created_at)],
          ["Completed", dateTime(t.completed_at)],
          ...(t.failure_reason ? [["Reason", t.failure_reason] as [string, string]] : []),
        ]}
      />
      {t.status === "processing" && (
        <div className="mt-4 space-y-2">
          <Button variant="secondary" className="w-full" loading={refresh.isPending} onClick={() => refresh.mutate(t.reference)}>
            Check status
          </Button>
          {t.provider === "sandbox" && (
            <div className="grid grid-cols-2 gap-2">
              <Button size="sm" onClick={() => simulate.mutate({ ref: t.reference, outcome: "successful" })}>Simulate success</Button>
              <Button size="sm" variant="danger" onClick={() => simulate.mutate({ ref: t.reference, outcome: "failed" })}>Simulate failure</Button>
            </div>
          )}
        </div>
      )}
      <Button variant="secondary" className="mt-4 w-full" icon={<Download className="h-4 w-4" />}
        onClick={() => downloadFile(`/transactions/${t.reference}/receipt.pdf`, undefined, `fincore-receipt-${t.reference}.pdf`)}>
        Download receipt
      </Button>
      <p className="mt-4 text-center text-xs text-slate-500">
        Problem with this transaction? <Link className="text-brand-700" to={`/app/support?ref=${t.reference}`}>Contact support</Link>
      </p>
    </Modal>
  );
}

function WalletSelect({ wallets, value, onChange }: { wallets: Wallet[]; value: string; onChange: (v: string) => void }) {
  if (wallets.length <= 1) return null;
  return (
    <Select label="From wallet" value={value} onChange={(e) => onChange(e.target.value)}>
      {wallets.map((w) => (
        <option key={w.id} value={w.id}>
          {w.label} · {w.account_number} · {money(w.balance)}
        </option>
      ))}
    </Select>
  );
}

function useDefaultWallet() {
  const { data: wallets = [], ...rest } = useWallets();
  const [walletId, setWalletId] = useState("");
  useEffect(() => {
    if (!walletId && wallets.length) setWalletId((wallets.find((w) => w.is_default) ?? wallets[0]).id);
  }, [wallets, walletId]);
  const wallet = wallets.find((w) => w.id === walletId);
  return { wallets, wallet, walletId, setWalletId, ...rest };
}

// ------------------------------------------------------------------ dashboard
export function CustomerDashboard() {
  const { user } = useAuth();
  const { data: wallets, isLoading, error, refetch } = useWallets();
  const recent = useGet<Page<Transaction>>(["transactions", "recent"], "/transactions", { page_size: 6 });
  const summary = useGet<any>(["summary"], "/me/summary");
  const [selected, setSelected] = useState<Transaction | null>(null);
  const main = wallets?.find((w) => w.is_default) ?? wallets?.[0];
  const chart = useMemo(() => (summary.data?.by_type ?? []).map((r: any) => ({ name: titleCase(r.type), total: Number(r.total) })), [summary.data]);

  if (isLoading) return <Spinner />;
  if (error) return <ErrorState error={error} onRetry={refetch} />;
  return (
    <>
      <PageHeader title={`Hello, ${user?.full_name.split(" ")[0]}`} subtitle="Here's what's happening with your money." />
      {user && user.kyc_tier < 2 && (
        <div className="mb-6">
          <Alert tone="warning">
            You're on verification tier {user.kyc_tier}. <Link to="/app/verification" className="font-medium underline">Verify with your Ghana Card</Link> to raise your limits.
          </Alert>
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-2xl bg-gradient-to-br from-brand-800 via-brand-900 to-ink-900 p-6 text-white shadow-lg lg:col-span-2">
          <p className="text-sm text-brand-100">Available balance</p>
          <p className="tabular mt-1 text-4xl font-semibold">{money(main?.balance ?? "0")}</p>
          <p className="mt-2 text-sm text-brand-200">
            Account <span className="font-mono">{main?.account_number}</span> · {main?.label}
          </p>
          <div className="mt-6 grid grid-cols-3 gap-2 sm:max-w-md">
            {[
              { to: "/app/deposit", label: "Add", icon: <ArrowDownToLine className="h-5 w-5" /> },
              { to: "/app/send", label: "Send", icon: <ArrowLeftRight className="h-5 w-5" /> },
              { to: "/app/withdraw", label: "Withdraw", icon: <ArrowUpFromLine className="h-5 w-5" /> },
            ].map((a) => (
              <Link key={a.to} to={a.to} className="flex flex-col items-center gap-1 rounded-xl bg-white/10 py-3 text-sm hover:bg-white/20">
                {a.icon}
                {a.label}
              </Link>
            ))}
          </div>
        </div>
        <div className="grid gap-4">
          <Stat label="Money in (30 days)" value={money(summary.data?.money_in ?? "0")} />
          <Stat label="Money out (30 days)" value={money(summary.data?.money_out ?? "0")} />
        </div>
      </div>
      {wallets && wallets.length > 1 && (
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          {wallets.filter((w) => w.id !== main?.id).map((w) => (
            <Stat key={w.id} label={w.label} value={money(w.balance, w.currency)} sub={w.account_number} />
          ))}
        </div>
      )}
      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card title="Recent activity" className="lg:col-span-2" actions={<Link to="/app/transactions" className="text-sm text-brand-700">View all</Link>}>
          {recent.isLoading ? (
            <Spinner />
          ) : recent.data?.items.length ? (
            <div className="divide-y divide-slate-100">
              {recent.data.items.map((t) => (
                <button key={t.id} className="block w-full text-left" onClick={() => setSelected(t)}>
                  <TransactionRow t={t} />
                </button>
              ))}
            </div>
          ) : (
            <Empty title="No transactions yet" body="Add money from mobile money to get started." action={<Link to="/app/deposit"><Button size="sm">Add money</Button></Link>} />
          )}
        </Card>
        <Card title="Spending by type (30 days)">
          {chart.length ? (
            <div className="h-56">
              <ResponsiveContainer>
                <BarChart data={chart}>
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: number) => money(v.toFixed(2))} />
                  <Bar dataKey="total" fill="#047857" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <Empty title="No spending yet" />
          )}
        </Card>
      </div>
      <TransactionDetail t={selected} onClose={() => setSelected(null)} />
    </>
  );
}

// ------------------------------------------------------------------ send / deposit / withdraw
function ResultCard({ t, onAgain }: { t: Transaction; onAgain: () => void }) {
  const nav = useNavigate();
  const ok = t.status === "successful";
  return (
    <Card>
      <div className="py-4 text-center">
        <Badge>{t.status}</Badge>
        <p className="mt-3 text-2xl font-semibold">
          <Amount value={t.amount} />
        </p>
        <p className="mt-1 text-sm text-slate-500">{t.description}</p>
        {t.failure_reason && <p className="mt-2 text-sm text-rose-600">{t.failure_reason}</p>}
        {t.status === "processing" && <p className="mt-2 text-sm text-slate-600">We're waiting for the provider to confirm. You'll get a notification.</p>}
        <p className="mt-3 text-xs text-slate-400">Ref {t.reference}</p>
        <div className="mt-5 flex justify-center gap-2">
          <Button variant="secondary" onClick={onAgain}>{ok ? "New transaction" : "Try again"}</Button>
          <Button onClick={() => nav("/app/transactions")}>View history</Button>
        </div>
      </div>
    </Card>
  );
}

export function SendPage() {
  const { wallets, wallet, walletId, setWalletId } = useDefaultWallet();
  const bens = useGet<any[]>(["beneficiaries"], "/beneficiaries");
  const [account, setAccount] = useState("");
  const [amount, setAmount] = useState("");
  const [narration, setNarration] = useState("");
  const [name, setName] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [idem, setIdem] = useState(newIdempotencyKey());
  const [result, setResult] = useState<Transaction | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setName(null);
    if (account.length !== 10) return;
    api("/wallets/lookup", { query: { account_number: account } })
      .then((r) => setName(r.valid ? r.account_name : `⚠ ${r.message}`))
      .catch(() => setName(null));
  }, [account]);

  const send = useAction(
    () => api<Transaction>("/transfers", { body: { wallet_id: walletId, destination_account: account, amount, narration: narration || null }, idempotencyKey: idem }),
    { invalidate: [["wallets"], ["transactions"]], onSuccess: (t) => setResult(t) },
  );

  function review(e: FormEvent) {
    e.preventDefault();
    const ae = amountError(amount);
    if (ae) return setErr(ae);
    if (!name || name.startsWith("⚠")) return setErr("Enter a valid FinCore account number");
    setErr(null);
    setConfirm(true);
  }

  if (result)
    return (
      <>
        <PageHeader title="Send money" />
        <ResultCard t={result} onAgain={() => { setResult(null); setAmount(""); setIdem(newIdempotencyKey()); }} />
      </>
    );
  const walletBens = (bens.data ?? []).filter((b) => b.type === "wallet");
  return (
    <>
      <PageHeader title="Send money" subtitle="Instant and free between FinCore accounts." />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <form onSubmit={review} className="space-y-4">
            {err && <Alert tone="error">{err}</Alert>}
            <WalletSelect wallets={wallets} value={walletId} onChange={setWalletId} />
            <Input label="Recipient FinCore account number" inputMode="numeric" maxLength={10} value={account} onChange={(e) => setAccount(e.target.value.replace(/\D/g, ""))}
              hint={name ? <span className={name.startsWith("⚠") ? "text-rose-600" : "font-medium text-emerald-700"}>{name}</span> : "10-digit account number"} />
            <Input label="Amount (GHS)" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} hint={wallet && `Available: ${money(wallet.balance)}`} />
            <Input label="Narration (optional)" value={narration} onChange={(e) => setNarration(e.target.value)} maxLength={200} />
            <Button type="submit" size="lg" className="w-full">Review transfer</Button>
          </form>
        </Card>
        <Card title="Saved recipients">
          {walletBens.length ? (
            <ul className="divide-y divide-slate-100">
              {walletBens.map((b) => (
                <li key={b.id}>
                  <button className="w-full py-2 text-left text-sm hover:text-brand-700" onClick={() => setAccount(b.identifier)}>
                    <span className="font-medium">{b.nickname || b.name}</span>
                    <span className="block font-mono text-xs text-slate-500">{b.identifier}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <Empty title="No saved recipients" action={<Link to="/app/beneficiaries"><Button size="sm" variant="secondary">Add one</Button></Link>} />
          )}
        </Card>
      </div>
      <Modal open={confirm} onClose={() => setConfirm(false)} title="Confirm transfer">
        <KV items={[["To", name], ["Account", account], ["Amount", money(amount)], ["Fee", "Free"], ["Narration", narration || "—"]]} />
        <Button className="mt-5 w-full" size="lg" loading={send.isPending} onClick={() => { setConfirm(false); send.mutate(undefined); }}>
          Send {money(amount)}
        </Button>
      </Modal>
    </>
  );
}

export function DepositPage() {
  const { user } = useAuth();
  const { wallets, walletId, setWalletId } = useDefaultWallet();
  const [phone, setPhone] = useState(user?.phone ? "0" + user.phone.slice(3) : "");
  const [amount, setAmount] = useState("");
  const [result, setResult] = useState<Transaction | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [idem, setIdem] = useState(newIdempotencyKey());
  const network = detectNetwork(phone);
  const deposit = useAction(() => api<Transaction>("/deposits", { body: { wallet_id: walletId, amount, phone }, idempotencyKey: idem }), {
    invalidate: [["wallets"], ["transactions"]],
    onSuccess: setResult,
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    const ae = amountError(amount);
    if (ae) return setErr(ae);
    if (!network) return setErr("Enter a valid MTN, Telecel or AT number");
    setErr(null);
    deposit.mutate(undefined);
  }
  if (result) return (<><PageHeader title="Add money" /><ResultCard t={result} onAgain={() => { setResult(null); setIdem(newIdempotencyKey()); }} /></>);
  return (
    <>
      <PageHeader title="Add money" subtitle="Top up your wallet from mobile money. You'll get a prompt on your phone to approve." />
      <Card className="max-w-xl">
        <form onSubmit={submit} className="space-y-4">
          {err && <Alert tone="error">{err}</Alert>}
          <WalletSelect wallets={wallets} value={walletId} onChange={setWalletId} />
          <Input label="Mobile money number" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="024 123 4567" hint={network ? NETWORKS[network] : "MTN, Telecel or AT"} />
          <Input label="Amount (GHS)" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
          <div className="flex flex-wrap gap-2">
            {["20", "50", "100", "200", "500"].map((v) => (
              <button type="button" key={v} onClick={() => setAmount(v)} className="rounded-full bg-slate-100 px-3 py-1 text-sm hover:bg-brand-50 hover:text-brand-700">
                {money(v)}
              </button>
            ))}
          </div>
          <Button type="submit" size="lg" className="w-full" loading={deposit.isPending}>Request payment</Button>
          <p className="text-xs text-slate-500">Sandbox tip: numbers ending 0000 fail, 1111 stay pending, anything else succeeds.</p>
        </form>
      </Card>
    </>
  );
}

export function WithdrawPage() {
  const { user } = useAuth();
  const { wallets, wallet, walletId, setWalletId } = useDefaultWallet();
  const banks = useGet<{ code: string; name: string }[]>(["banks"], "/banks");
  const [channel, setChannel] = useState<"mobile_money" | "bank">("mobile_money");
  const [phone, setPhone] = useState(user?.phone ? "0" + user.phone.slice(3) : "");
  const [bankCode, setBankCode] = useState("");
  const [accountNumber, setAccountNumber] = useState("");
  const [accountName, setAccountName] = useState("");
  const [amount, setAmount] = useState("");
  const [lookup, setLookup] = useState<string | null>(null);
  const [result, setResult] = useState<Transaction | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [idem, setIdem] = useState(newIdempotencyKey());

  async function checkName() {
    try {
      const r = channel === "mobile_money"
        ? await api("/wallets/lookup-momo", { query: { phone } })
        : await api("/wallets/lookup-bank", { query: { bank_code: bankCode, account_number: accountNumber } });
      setLookup(r.valid ? r.account_name ?? "Verified" : `⚠ ${r.message}`);
      if (r.valid && r.account_name) setAccountName(r.account_name);
    } catch (e) {
      setLookup(`⚠ ${(e as Error).message}`);
    }
  }

  const withdraw = useAction(
    () => api<Transaction>("/withdrawals", {
      body: { wallet_id: walletId, amount, channel, phone: channel === "mobile_money" ? phone : null, bank_code: channel === "bank" ? bankCode : null,
        account_number: channel === "bank" ? accountNumber : null, account_name: accountName || null },
      idempotencyKey: idem,
    }),
    { invalidate: [["wallets"], ["transactions"]], onSuccess: setResult },
  );
  function submit(e: FormEvent) {
    e.preventDefault();
    const ae = amountError(amount);
    if (ae) return setErr(ae);
    setErr(null);
    withdraw.mutate(undefined);
  }
  if (result) return (<><PageHeader title="Withdraw" /><ResultCard t={result} onAgain={() => { setResult(null); setIdem(newIdempotencyKey()); }} /></>);
  return (
    <>
      <PageHeader title="Withdraw" subtitle="Cash out to mobile money or a Ghanaian bank account." />
      <Card className="max-w-xl">
        <form onSubmit={submit} className="space-y-4">
          {err && <Alert tone="error">{err}</Alert>}
          <Tabs value={channel} onChange={(v) => { setChannel(v as any); setLookup(null); }} tabs={[{ value: "mobile_money", label: "Mobile money" }, { value: "bank", label: "Bank account" }]} />
          <WalletSelect wallets={wallets} value={walletId} onChange={setWalletId} />
          {channel === "mobile_money" ? (
            <Input label="Mobile money number" value={phone} onChange={(e) => { setPhone(e.target.value); setLookup(null); }} onBlur={checkName}
              hint={lookup ?? (detectNetwork(phone) ? NETWORKS[detectNetwork(phone)!] : "MTN, Telecel or AT")} />
          ) : (
            <>
              <Select label="Bank" value={bankCode} onChange={(e) => setBankCode(e.target.value)} required>
                <option value="">Select bank</option>
                {banks.data?.map((b) => <option key={b.code} value={b.code}>{b.name}</option>)}
              </Select>
              <Input label="Account number" inputMode="numeric" value={accountNumber} onChange={(e) => setAccountNumber(e.target.value)} onBlur={checkName} hint={lookup ?? undefined} required />
            </>
          )}
          <Input label="Amount (GHS)" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} hint={wallet && `Available: ${money(wallet.balance)} · fees apply (see summary)`} />
          <Alert tone="info">{channel === "mobile_money" ? "Fee: 0.75% (min GH₵0.50, max GH₵15)." : "Fee: GH₵2.00 per bank transfer."}</Alert>
          <Button type="submit" size="lg" className="w-full" loading={withdraw.isPending}>Withdraw</Button>
        </form>
      </Card>
    </>
  );
}

// ------------------------------------------------------------------ history
export function TransactionsPage() {
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({ type: "", status: "", search: "", start: "", end: "" });
  const { data, isLoading, error, refetch } = useGet<Page<Transaction>>(["transactions", "list"], "/transactions", { page, page_size: 20, ...filters });
  const [selected, setSelected] = useState<Transaction | null>(null);
  const set = (k: keyof typeof filters) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { setPage(1); setFilters({ ...filters, [k]: e.target.value }); };
  return (
    <>
      <PageHeader title="Transactions" />
      <Card>
        <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Input placeholder="Search reference or description" value={filters.search} onChange={set("search")} />
          <Select value={filters.type} onChange={set("type")} aria-label="Type">
            <option value="">All types</option>
            {["deposit", "withdrawal", "transfer", "payment", "refund", "reversal", "adjustment"].map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}
          </Select>
          <Select value={filters.status} onChange={set("status")} aria-label="Status">
            <option value="">All statuses</option>
            {["successful", "processing", "pending", "failed", "reversed"].map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}
          </Select>
          <Input type="date" value={filters.start} onChange={set("start")} aria-label="From" />
          <Input type="date" value={filters.end} onChange={set("end")} aria-label="To" />
        </div>
        {isLoading ? <Spinner /> : error ? <ErrorState error={error} onRetry={refetch} /> : !data?.items.length ? (
          <Empty title="No transactions match" body="Try adjusting your filters." />
        ) : (
          <>
            <Table
              rows={data.items}
              keyFn={(t) => t.id}
              onRowClick={setSelected}
              columns={[
                { header: "Date", cell: (t) => <span className="whitespace-nowrap text-slate-600">{dateTime(t.created_at)}</span>, hideOnMobile: true },
                { header: "Description", cell: (t) => <div><p className="font-medium">{t.description || titleCase(t.type)}</p><p className="text-xs text-slate-500">{t.reference}</p></div> },
                { header: "Type", cell: (t) => titleCase(t.type), hideOnMobile: true },
                { header: "Status", cell: (t) => <Badge>{t.status}</Badge> },
                { header: "Amount", cell: (t) => <Amount value={t.amount} direction={t.direction} />, className: "text-right" },
              ]}
            />
            <Pagination page={page} pageSize={20} total={data.total} onPage={setPage} />
          </>
        )}
      </Card>
      <TransactionDetail t={selected} onClose={() => setSelected(null)} />
    </>
  );
}

export function BeneficiariesPage() {
  const { data, isLoading } = useGet<any[]>(["beneficiaries"], "/beneficiaries");
  const banks = useGet<{ code: string; name: string }[]>(["banks"], "/banks");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ type: "wallet", name: "", nickname: "", identifier: "", bank_code: "" });
  const add = useAction(() => api("/beneficiaries", { body: { ...form, bank_code: form.bank_code || null, nickname: form.nickname || null } }), {
    invalidate: [["beneficiaries"]], success: "Beneficiary saved", onSuccess: () => setOpen(false),
  });
  const fav = useAction((id: string) => api(`/beneficiaries/${id}/favourite`, { method: "POST" }), { invalidate: [["beneficiaries"]] });
  const del = useAction((id: string) => api(`/beneficiaries/${id}`, { method: "DELETE" }), { invalidate: [["beneficiaries"]], success: "Removed" });
  return (
    <>
      <PageHeader title="Beneficiaries" actions={<Button icon={<Plus className="h-4 w-4" />} onClick={() => setOpen(true)}>Add beneficiary</Button>} />
      <Card padded={false}>
        {isLoading ? <Spinner /> : !data?.length ? <Empty title="No beneficiaries yet" body="Save people you pay often." /> : (
          <ul className="divide-y divide-slate-100">
            {data.map((b) => (
              <li key={b.id} className="flex items-center justify-between px-5 py-3">
                <div>
                  <p className="font-medium">{b.nickname || b.name} <span className="ml-1"><Badge>{b.type}</Badge></span></p>
                  <p className="font-mono text-xs text-slate-500">{b.type === "mobile_money" ? `${maskPhone(b.identifier)} · ${NETWORKS[b.network]}` : b.bank_code ? `${b.bank_code} ${b.identifier}` : b.identifier}</p>
                </div>
                <div className="flex gap-1">
                  <button onClick={() => fav.mutate(b.id)} className="rounded p-2 hover:bg-slate-100" aria-label="Favourite">
                    <Star className={`h-4 w-4 ${b.favourite ? "fill-gold-400 text-gold-500" : "text-slate-400"}`} />
                  </button>
                  <button onClick={() => del.mutate(b.id)} className="rounded p-2 text-slate-400 hover:bg-rose-50 hover:text-rose-600" aria-label="Delete">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Modal open={open} onClose={() => setOpen(false)} title="Add beneficiary">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); add.mutate(undefined); }}>
          <Select label="Type" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
            <option value="wallet">FinCore account</option>
            <option value="mobile_money">Mobile money</option>
            <option value="bank">Bank account</option>
          </Select>
          <Input label="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          <Input label="Nickname (optional)" value={form.nickname} onChange={(e) => setForm({ ...form, nickname: e.target.value })} />
          {form.type === "bank" && (
            <Select label="Bank" value={form.bank_code} onChange={(e) => setForm({ ...form, bank_code: e.target.value })} required>
              <option value="">Select bank</option>
              {banks.data?.map((b) => <option key={b.code} value={b.code}>{b.name}</option>)}
            </Select>
          )}
          <Input label={form.type === "mobile_money" ? "Phone number" : "Account number"} value={form.identifier} onChange={(e) => setForm({ ...form, identifier: e.target.value })} required />
          <Button type="submit" className="w-full" loading={add.isPending}>Save</Button>
        </form>
      </Modal>
    </>
  );
}

export function StatementsPage() {
  const { wallets, walletId, setWalletId } = useDefaultWallet();
  const today = new Date().toISOString().slice(0, 10);
  const monthAgo = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10);
  const [range, setRange] = useState({ start: monthAgo, end: today });
  const st = useGet<any>(["statement", walletId, range], walletId ? `/wallets/${walletId}/statement` : null, range);
  return (
    <>
      <PageHeader title="Statements" subtitle="Ledger-backed statements with opening and closing balances."
        actions={<>
          <Button icon={<Download className="h-4 w-4" />} onClick={() => downloadFile(`/wallets/${walletId}/statement`, { ...range, format: "pdf" }, `fincore-statement-${range.start}-${range.end}.pdf`)}>Download PDF</Button>
          <Button variant="secondary" icon={<Download className="h-4 w-4" />} onClick={() => downloadFile(`/wallets/${walletId}/statement`, { ...range, format: "csv" }, `fincore-statement-${range.start}-${range.end}.csv`)}>CSV</Button>
        </>} />
      <Card>
        <div className="mb-4 grid gap-3 sm:grid-cols-3">
          {wallets.length > 1 ? <WalletSelect wallets={wallets} value={walletId} onChange={setWalletId} /> : null}
          <Input label="From" type="date" value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} />
          <Input label="To" type="date" value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} />
        </div>
        {st.isLoading ? <Spinner /> : st.error ? <ErrorState error={st.error} /> : st.data && (
          <>
            <div className="mb-4 grid gap-3 sm:grid-cols-4">
              <Stat label="Opening" value={money(st.data.opening_balance)} />
              <Stat label="Money in" value={money(st.data.total_credits)} />
              <Stat label="Money out" value={money(st.data.total_debits)} />
              <Stat label="Closing" value={money(st.data.closing_balance)} tone="brand" />
            </div>
            {st.data.lines.length === 0 ? <Empty title="No activity in this period" /> : (
              <Table rows={st.data.lines} keyFn={(l: any) => l.reference + l.date + l.balance}
                columns={[
                  { header: "Date", cell: (l: any) => dateOnly(l.date) },
                  { header: "Description", cell: (l: any) => <div><p>{l.description}</p><p className="text-xs text-slate-500">{l.reference}</p></div> },
                  { header: "Debit", cell: (l: any) => (l.debit !== "0.00" ? money(l.debit) : ""), className: "text-right tabular" },
                  { header: "Credit", cell: (l: any) => (l.credit !== "0.00" ? money(l.credit) : ""), className: "text-right tabular text-emerald-700" },
                  { header: "Balance", cell: (l: any) => money(l.balance), className: "text-right tabular font-medium" },
                ]} />
            )}
          </>
        )}
      </Card>
    </>
  );
}

// ------------------------------------------------------------------ verification
export function VerificationPage() {
  const { user, reload } = useAuth();
  const subs = useGet<any[]>(["kyc"], "/me/kyc");
  const limits = useGet<any>(["limits"], "/me/limits");
  const [form, setForm] = useState({ tier_requested: String(Math.min((user?.kyc_tier ?? 0) + 1, 3)), id_type: "ghana_card", id_number: "", first_name: "", last_name: "", date_of_birth: "", address: "", digital_address: "" });
  const [docs, setDocs] = useState<Record<string, { id: string; name: string }>>({});
  const [uploading, setUploading] = useState<string | null>(null);
  const toast = useToast();
  const tier = Number(form.tier_requested);
  const needed = tier >= 3 ? ["id_front", "selfie", "proof_of_address"] : tier === 2 ? ["id_front", "selfie"] : [];
  async function upload(kind: string, file: File | undefined) {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) return toast.error("Files must be 5 MB or smaller");
    const fd = new FormData();
    fd.append("kind", kind);
    fd.append("file", file);
    setUploading(kind);
    try {
      const doc = await api("/me/kyc/documents", { body: fd });
      setDocs((d) => ({ ...d, [kind]: { id: doc.id, name: file.name } }));
    } catch (e) {
      toast.error(e);
    } finally {
      setUploading(null);
    }
  }
  const submit = useAction(() => api("/me/kyc", { body: { ...form, tier_requested: tier, document_ids: Object.values(docs).map((d) => d.id) } }), {
    invalidate: [["kyc"]], success: "Submitted for review", onSuccess: () => { setDocs({}); reload(); },
  });
  const pending = subs.data?.find((s) => s.status === "pending");
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });
  return (
    <>
      <PageHeader title="Identity verification" subtitle={`You're currently on tier ${user?.kyc_tier}. Higher tiers unlock higher limits.`} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Your limits">
          {limits.data && (
            <Table rows={limits.data.limits} keyFn={(r: any) => r.transaction_type}
              columns={[
                { header: "Type", cell: (r: any) => (r.transaction_type === "*" ? "Max wallet balance" : titleCase(r.transaction_type)) },
                { header: "Per txn", cell: (r: any) => (r.per_transaction_max ? money(r.per_transaction_max) : r.max_balance ? money(r.max_balance) : "—") },
                { header: "Daily", cell: (r: any) => (r.daily_max ? `${money(r.daily_used)} / ${money(r.daily_max)}` : "—"), hideOnMobile: true },
                { header: "Monthly", cell: (r: any) => (r.monthly_max ? money(r.monthly_max) : "—"), hideOnMobile: true },
              ]} />
          )}
        </Card>
        <Card title={pending ? "Under review" : "Upgrade verification"}>
          {pending ? (
            <Alert tone="info">Your tier {pending.tier_requested} verification ({titleCase(pending.id_type)}) was submitted {dateOnly(pending.created_at)} and is being reviewed.</Alert>
          ) : (user?.kyc_tier ?? 0) >= 3 ? (
            <Alert tone="success">You're fully verified.</Alert>
          ) : (
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); submit.mutate(undefined); }}>
              <div className="grid gap-3 sm:grid-cols-2">
                <Select label="Tier" value={form.tier_requested} onChange={set("tier_requested")}>
                  {[1, 2, 3].filter((t) => t > (user?.kyc_tier ?? 0)).map((t) => <option key={t} value={t}>Tier {t}</option>)}
                </Select>
                <Select label="ID type" value={form.id_type} onChange={set("id_type")}>
                  <option value="ghana_card">Ghana Card</option>
                  <option value="passport">Passport</option>
                  <option value="voter_id">Voter ID</option>
                  <option value="drivers_license">Driver's licence</option>
                </Select>
              </div>
              <Input label="ID number" placeholder={form.id_type === "ghana_card" ? "GHA-123456789-0" : ""} value={form.id_number} onChange={set("id_number")} required />
              <div className="grid gap-3 sm:grid-cols-2">
                <Input label="First name" value={form.first_name} onChange={set("first_name")} required />
                <Input label="Last name" value={form.last_name} onChange={set("last_name")} required />
              </div>
              <Input label="Date of birth" type="date" value={form.date_of_birth} onChange={set("date_of_birth")} required />
              <Input label="Residential address" value={form.address} onChange={set("address")} />
              <Input label="GhanaPost GPS address" placeholder="GA-123-4567" value={form.digital_address} onChange={set("digital_address")} />
              <div className="space-y-2 rounded-lg bg-slate-50 p-3">
                <p className="text-sm font-medium text-slate-700">Documents {needed.length ? "(required)" : "(optional)"}</p>
                {DOC_KINDS.filter(([k]) => needed.includes(k) || k === "id_back" || (k === "proof_of_address" && tier < 3)).map(([kind, label]) => (
                  <label key={kind} className="flex items-center justify-between gap-3 text-sm">
                    <span>{label}{needed.includes(kind) && <span className="text-rose-600"> *</span>}</span>
                    <span className="flex items-center gap-2">
                      {docs[kind] && <span className="max-w-[10rem] truncate text-xs text-emerald-700">✓ {docs[kind].name}</span>}
                      <span className="cursor-pointer rounded-md bg-white px-2 py-1 text-xs font-medium ring-1 ring-slate-300 hover:bg-slate-100">
                        {uploading === kind ? "Uploading…" : docs[kind] ? "Replace" : "Choose file"}
                      </span>
                      <input type="file" className="sr-only" accept="image/jpeg,image/png,application/pdf" capture={kind === "selfie" ? "user" : undefined}
                        aria-label={label} onChange={(e) => upload(kind, e.target.files?.[0])} />
                    </span>
                  </label>
                ))}
                <p className="text-xs text-slate-500">JPEG, PNG or PDF, up to 5 MB. Files are stored privately and only seen by our compliance team.</p>
              </div>
              <Button type="submit" className="w-full" loading={submit.isPending} disabled={needed.some((k) => !docs[k]) || !!uploading}>Submit for verification</Button>
            </form>
          )}
          {subs.data && subs.data.filter((s) => s.status !== "pending").length > 0 && (
            <div className="mt-5 border-t border-slate-100 pt-3">
              <p className="mb-2 text-xs font-medium uppercase text-slate-500">History</p>
              {subs.data.filter((s) => s.status !== "pending").map((s) => (
                <p key={s.id} className="flex justify-between py-1 text-sm">
                  <span>Tier {s.tier_requested} · {dateOnly(s.created_at)}</span>
                  <span><Badge>{s.status}</Badge></span>
                </p>
              ))}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

const DOC_KINDS: [string, string][] = [
  ["id_front", "ID card — front"],
  ["id_back", "ID card — back"],
  ["selfie", "Selfie holding your ID"],
  ["proof_of_address", "Proof of address (utility bill / bank statement)"],
];

// ------------------------------------------------------------------ security
export function SecurityPage() {
  const { user, reload } = useAuth();
  const sessions = useGet<any[]>(["sessions"], "/auth/sessions");
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [disable, setDisable] = useState({ password: "", code: "" });
  const change = useAction(() => api("/auth/password/change", { body: pw }), { success: "Password changed", onSuccess: () => setPw({ current_password: "", new_password: "" }) });
  const start2fa = useAction(() => api("/auth/2fa/setup", { method: "POST" }), { onSuccess: setSetup });
  const enable2fa = useAction(() => api("/auth/2fa/enable", { body: { code } }), { success: "Two-factor authentication enabled", onSuccess: () => { setSetup(null); reload(); } });
  const disable2fa = useAction(() => api("/auth/2fa/disable", { body: disable }), { success: "Two-factor authentication disabled", onSuccess: () => reload() });
  const revoke = useAction((id: string) => api(`/auth/sessions/${id}`, { method: "DELETE" }), { invalidate: [["sessions"]], success: "Session signed out" });
  const revokeOthers = useAction(() => api("/auth/sessions/revoke-others", { method: "POST" }), { invalidate: [["sessions"]], success: "Other sessions signed out" });
  return (
    <>
      <PageHeader title="Security" />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Two-factor authentication">
          {user?.totp_enabled ? (
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); disable2fa.mutate(undefined); }}>
              <Alert tone="success">2FA is on. You'll need a code from your authenticator app to sign in.</Alert>
              <Input label="Password" type="password" value={disable.password} onChange={(e) => setDisable({ ...disable, password: e.target.value })} />
              <Input label="Current code" inputMode="numeric" value={disable.code} onChange={(e) => setDisable({ ...disable, code: e.target.value })} />
              <Button variant="danger" type="submit" loading={disable2fa.isPending}>Turn off 2FA</Button>
            </form>
          ) : setup ? (
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); enable2fa.mutate(undefined); }}>
              <p className="text-sm text-slate-600">Add this key to Google Authenticator, Authy or 1Password, then enter the 6-digit code.</p>
              <CopyText text={setup.secret} className="block w-full text-center text-sm" />
              <a href={setup.otpauth_uri} className="block text-center text-xs text-brand-700 underline">Open in authenticator app</a>
              <Input label="Code" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} maxLength={8} />
              <Button type="submit" loading={enable2fa.isPending}>Enable 2FA</Button>
            </form>
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-slate-600">Protect your account with a second step at sign-in.</p>
              <Button onClick={() => start2fa.mutate(undefined)} loading={start2fa.isPending}>Set up 2FA</Button>
            </div>
          )}
        </Card>
        <Card title="Change password">
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); change.mutate(undefined); }}>
            <Input label="Current password" type="password" autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} required />
            <Input label="New password" type="password" autoComplete="new-password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} required hint="Changing your password signs out your other devices." />
            <Button type="submit" loading={change.isPending}>Update password</Button>
          </form>
        </Card>
        <Card title="Active sessions" className="lg:col-span-2" actions={<Button size="sm" variant="secondary" onClick={() => revokeOthers.mutate(undefined)}>Sign out other sessions</Button>}>
          {sessions.isLoading ? <Spinner /> : (
            <Table rows={sessions.data ?? []} keyFn={(s) => s.id}
              columns={[
                { header: "Device", cell: (s) => <span className="line-clamp-1 max-w-xs text-slate-700">{s.user_agent || "Unknown device"}</span> },
                { header: "IP", cell: (s) => s.ip_address ?? "—", hideOnMobile: true },
                { header: "Last active", cell: (s) => dateTime(s.last_used_at ?? s.created_at) },
                { header: "", cell: (s) => <Button size="sm" variant="ghost" onClick={() => revoke.mutate(s.id)}>Sign out</Button>, className: "text-right" },
              ]} />
          )}
        </Card>
      </div>
    </>
  );
}

// ------------------------------------------------------------------ support
export function SupportPage() {
  const ref = new URLSearchParams(window.location.search).get("ref") ?? "";
  const tickets = useGet<any[]>(["tickets"], "/me/tickets");
  const [open, setOpen] = useState(!!ref);
  const [active, setActive] = useState<string | null>(null);
  const [form, setForm] = useState({ subject: ref ? `Issue with transaction ${ref}` : "", category: ref ? "transaction" : "general", message: "", transaction_reference: ref });
  const create = useAction(() => api("/me/tickets", { body: { ...form, transaction_reference: form.transaction_reference || null } }), {
    invalidate: [["tickets"]], success: "Ticket created — we'll get back to you soon", onSuccess: () => setOpen(false),
  });
  return (
    <>
      <PageHeader title="Help & support" actions={<Button icon={<Plus className="h-4 w-4" />} onClick={() => setOpen(true)}>New ticket</Button>} />
      <Card padded={false}>
        {tickets.isLoading ? <Spinner /> : !tickets.data?.length ? <Empty title="No support tickets" body="Need help? Open a ticket and our team will respond." /> : (
          <ul className="divide-y divide-slate-100">
            {tickets.data.map((t) => (
              <li key={t.id}>
                <button onClick={() => setActive(t.id)} className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-slate-50">
                  <span>
                    <span className="font-medium">{t.subject}</span>
                    <span className="block text-xs text-slate-500">{titleCase(t.category)} · updated {dateTime(t.updated_at)}</span>
                  </span>
                  <Badge>{t.status}</Badge>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Modal open={open} onClose={() => setOpen(false)} title="New support ticket">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(undefined); }}>
          <Input label="Subject" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} required />
          <Select label="Category" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
            {["general", "transaction", "account", "verification", "business", "fraud"].map((c) => <option key={c} value={c}>{titleCase(c)}</option>)}
          </Select>
          <Input label="Transaction reference (optional)" value={form.transaction_reference} onChange={(e) => setForm({ ...form, transaction_reference: e.target.value })} />
          <Textarea label="How can we help?" value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} required />
          <Button type="submit" className="w-full" loading={create.isPending}>Submit</Button>
        </form>
      </Modal>
      <TicketThread id={active} onClose={() => setActive(null)} />
    </>
  );
}

function TicketThread({ id, onClose }: { id: string | null; onClose: () => void }) {
  const t = useGet<any>(["ticket", id], id ? `/me/tickets/${id}` : null);
  const [body, setBody] = useState("");
  const reply = useAction(() => api(`/me/tickets/${id}/messages`, { body: { body } }), { invalidate: [["ticket", id], ["tickets"]], onSuccess: () => setBody("") });
  return (
    <Modal open={!!id} onClose={onClose} title={t.data?.ticket.subject ?? "Ticket"} wide>
      {t.isLoading ? <Spinner /> : t.data && (
        <>
          <div className="max-h-96 space-y-3 overflow-y-auto">
            {t.data.messages.map((m: any) => (
              <div key={m.id} className="rounded-lg bg-slate-50 px-3 py-2 text-sm">
                <p className="whitespace-pre-wrap">{m.body}</p>
                <p className="mt-1 text-xs text-slate-400">{dateTime(m.created_at)}</p>
              </div>
            ))}
          </div>
          <form className="mt-4 space-y-2" onSubmit={(e) => { e.preventDefault(); reply.mutate(undefined); }}>
            <Textarea value={body} onChange={(e) => setBody(e.target.value)} placeholder="Write a reply…" required rows={3} />
            <Button type="submit" loading={reply.isPending}>Send reply</Button>
          </form>
        </>
      )}
    </Modal>
  );
}
