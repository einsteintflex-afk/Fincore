import { ArrowRight, Building2, CheckCircle2, Code2, Lock, ShieldCheck, Smartphone, Wallet, XCircle } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { SandboxBanner } from "@/components/Layout";
import { Alert, Badge, Button, ErrorState, Input, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { amountError, detectNetwork, money, NETWORKS } from "@/lib/format";
import { useGet, useWallets } from "@/lib/hooks";

export function LandingPage() {
  const { user } = useAuth();
  const features = [
    { icon: <Wallet />, title: "GHS wallets", body: "Instant wallet-to-wallet transfers, statements and beneficiaries." },
    { icon: <Smartphone />, title: "Mobile money", body: "Top up from and cash out to MTN MoMo, Telecel Cash and AT Money." },
    { icon: <Building2 />, title: "Merchant payments", body: "Payment links, hosted checkout, refunds and settlements to your bank." },
    { icon: <Code2 />, title: "Developer APIs", body: "Sandbox keys, signed webhooks and idempotent APIs from day one." },
    { icon: <ShieldCheck />, title: "Bank-grade ledger", body: "Double-entry, immutable, reconciled — every pesewa accounted for." },
    { icon: <Lock />, title: "Security first", body: "2FA, session control, tiered KYC and real-time fraud screening." },
  ];
  return (
    <div className="min-h-screen bg-white">
      <SandboxBanner />
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-5">
        <div className="flex items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-700 font-bold text-gold-400">F</span>
          <span className="text-xl font-semibold">FinCore</span>
        </div>
        <div className="flex gap-2">
          {user ? (
            <Link to="/app"><Button>Open dashboard</Button></Link>
          ) : (
            <>
              <Link to="/login"><Button variant="ghost">Sign in</Button></Link>
              <Link to="/register"><Button>Get started</Button></Link>
            </>
          )}
        </div>
      </header>
      <section className="mx-auto max-w-6xl px-4 pb-16 pt-10 text-center sm:pt-20">
        <Badge tone="sandbox">Built in Ghana · GHS first</Badge>
        <h1 className="mx-auto mt-5 max-w-3xl text-4xl font-semibold tracking-tight text-slate-900 sm:text-6xl">
          The financial infrastructure for <span className="text-brand-700">Ghana's</span> next million businesses.
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-lg text-slate-600">
          FinCore gives people a secure wallet and gives businesses everything they need to collect, pay out and reconcile money — across mobile money and banks.
        </p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <Link to="/register"><Button size="lg" icon={<ArrowRight className="h-4 w-4" />}>Open a free account</Button></Link>
          <Link to="/register"><Button size="lg" variant="secondary">Accept payments</Button></Link>
        </div>
      </section>
      <section className="bg-slate-50 py-16">
        <div className="mx-auto grid max-w-6xl gap-6 px-4 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((f) => (
            <div key={f.title} className="rounded-xl bg-white p-6 shadow-card ring-1 ring-slate-200/70">
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-brand-50 text-brand-700 [&>svg]:h-5 [&>svg]:w-5">{f.icon}</span>
              <h3 className="mt-4 font-semibold">{f.title}</h3>
              <p className="mt-1 text-sm text-slate-600">{f.body}</p>
            </div>
          ))}
        </div>
      </section>
      <footer className="py-8 text-center text-xs text-slate-500">
        FinCore is in development. Live payment services require Bank of Ghana authorisation and licensed provider partners.
      </footer>
    </div>
  );
}

interface CheckoutView {
  reference: string;
  amount: string;
  currency: string;
  status: string;
  description: string | null;
  merchant_name: string;
  livemode: boolean;
  failure_reason: string | null;
  redirect_url: string | null;
}

function CheckoutShell({ children, merchant }: { children: React.ReactNode; merchant?: string }) {
  return (
    <div className="min-h-screen bg-gradient-to-b from-brand-950 to-ink-900 px-4 py-10">
      <div className="mx-auto max-w-md">
        <div className="mb-6 text-center text-white">
          <p className="text-sm text-brand-200">Pay {merchant ?? "merchant"}</p>
        </div>
        <div className="overflow-hidden rounded-2xl bg-white shadow-2xl">{children}</div>
        <p className="mt-6 flex items-center justify-center gap-1 text-xs text-brand-200">
          <Lock className="h-3 w-3" /> Secured by FinCore
        </p>
      </div>
    </div>
  );
}

export function CheckoutPage() {
  const { reference } = useParams();
  const { data, error, isLoading, refetch } = useGet<CheckoutView>(["checkout", reference], `/checkout/${reference}`, undefined, {
    refetchInterval: 4000,
  });
  const { user } = useAuth();
  const wallets = useWallets();
  const [method, setMethod] = useState<"momo" | "wallet">("momo");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (isLoading) return <CheckoutShell><Spinner /></CheckoutShell>;
  if (error || !data) return <CheckoutShell><div className="p-6"><ErrorState error={error} onRetry={refetch} /></div></CheckoutShell>;

  async function pay(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      if (method === "momo") await api(`/checkout/${reference}/mobile-money`, { body: { phone } });
      else await api(`/checkout/${reference}/wallet`, { body: { wallet_id: wallets.data?.[0]?.id } });
      await refetch();
    } catch (ex) {
      setErr((ex as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const done = data.status === "successful" || data.status === "refunded" || data.status === "partially_refunded";
  const network = detectNetwork(phone);
  return (
    <CheckoutShell merchant={data.merchant_name}>
      <div className="border-b border-slate-100 bg-slate-50 px-6 py-5 text-center">
        {!data.livemode && <Badge tone="sandbox">Test payment</Badge>}
        <p className="mt-2 text-sm text-slate-500">{data.description || "Payment"}</p>
        <p className="tabular mt-1 text-3xl font-semibold">{money(data.amount, data.currency)}</p>
        <p className="mt-1 text-xs text-slate-400">Ref {data.reference}</p>
      </div>
      <div className="p-6">
        {done ? (
          <div className="text-center">
            <CheckCircle2 className="mx-auto h-12 w-12 text-emerald-600" />
            <p className="mt-3 text-lg font-semibold">Payment successful</p>
            <p className="text-sm text-slate-500">You can close this page.</p>
            {data.redirect_url && <a href={data.redirect_url}><Button className="mt-4">Return to merchant</Button></a>}
          </div>
        ) : data.status === "processing" ? (
          <div className="text-center">
            <Smartphone className="mx-auto h-10 w-10 animate-pulse text-brand-600" />
            <p className="mt-3 font-semibold">Approve on your phone</p>
            <p className="text-sm text-slate-500">Check your phone for the mobile money prompt and enter your PIN.</p>
          </div>
        ) : ["expired", "cancelled"].includes(data.status) ? (
          <div className="text-center">
            <XCircle className="mx-auto h-10 w-10 text-rose-500" />
            <p className="mt-3 font-semibold">This payment is {data.status}</p>
          </div>
        ) : (
          <form onSubmit={pay} className="space-y-4">
            {data.status === "failed" && data.failure_reason && <Alert tone="error">Last attempt failed: {data.failure_reason}</Alert>}
            {err && <Alert tone="error">{err}</Alert>}
            <div className="grid grid-cols-2 gap-2">
              {(["momo", "wallet"] as const).map((m) => (
                <button
                  type="button"
                  key={m}
                  onClick={() => setMethod(m)}
                  className={`rounded-lg px-3 py-2 text-sm font-medium ring-1 ${method === m ? "bg-brand-50 text-brand-800 ring-brand-500" : "ring-slate-200"}`}
                >
                  {m === "momo" ? "Mobile money" : "FinCore wallet"}
                </button>
              ))}
            </div>
            {method === "momo" ? (
              <Input label="Mobile money number" placeholder="024 123 4567" value={phone} onChange={(e) => setPhone(e.target.value)} required
                hint={network ? NETWORKS[network] : "MTN, Telecel or AT"} />
            ) : user ? (
              <Alert tone="info">Pay from your FinCore wallet ({money(wallets.data?.[0]?.balance ?? "0")} available).</Alert>
            ) : (
              <Alert tone="info">
                <Link className="font-medium underline" to="/login" state={{ from: `/checkout/${reference}` }}>Sign in</Link> to pay with your FinCore wallet.
              </Alert>
            )}
            <Button type="submit" className="w-full" size="lg" loading={busy} disabled={method === "wallet" && !user}>
              Pay {money(data.amount, data.currency)}
            </Button>
          </form>
        )}
      </div>
    </CheckoutShell>
  );
}

export function PaymentLinkPage() {
  const { slug } = useParams();
  const nav = useNavigate();
  const { data, isLoading, error } = useGet<any>(["link", slug], `/pay/${slug}`);
  const [form, setForm] = useState({ amount: "", customer_name: "", customer_email: "" });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (isLoading) return <CheckoutShell><Spinner /></CheckoutShell>;
  if (error || !data) return <CheckoutShell><div className="p-6"><ErrorState error={error} /></div></CheckoutShell>;
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!data.amount) {
      const ae = amountError(form.amount);
      if (ae) return setErr(ae);
    }
    setBusy(true);
    try {
      const pr = await api(`/pay/${slug}`, { body: { ...form, amount: data.amount ? null : form.amount, customer_email: form.customer_email || null } });
      nav(`/checkout/${pr.reference}`);
    } catch (ex) {
      setErr((ex as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <CheckoutShell merchant={data.merchant_name}>
      <div className="p-6">
        <h1 className="text-lg font-semibold">{data.title}</h1>
        {data.description && <p className="mt-1 text-sm text-slate-500">{data.description}</p>}
        {!data.active ? (
          <Alert tone="warning">This payment link is no longer accepting payments.</Alert>
        ) : (
          <form onSubmit={submit} className="mt-5 space-y-4">
            {err && <Alert tone="error">{err}</Alert>}
            {data.amount ? (
              <p className="tabular text-3xl font-semibold">{money(data.amount, data.currency)}</p>
            ) : (
              <Input label="Amount (GHS)" inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} required />
            )}
            <Input label="Your name" value={form.customer_name} onChange={(e) => setForm({ ...form, customer_name: e.target.value })} />
            <Input label="Email (for receipt)" type="email" value={form.customer_email} onChange={(e) => setForm({ ...form, customer_email: e.target.value })} />
            <Button type="submit" size="lg" className="w-full" loading={busy}>Continue to payment</Button>
          </form>
        )}
      </div>
    </CheckoutShell>
  );
}

export function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 px-4 text-center">
      <p className="text-5xl font-semibold text-brand-700">404</p>
      <p className="text-slate-600">We couldn't find that page.</p>
      <Link to="/"><Button variant="secondary">Go home</Button></Link>
    </div>
  );
}

