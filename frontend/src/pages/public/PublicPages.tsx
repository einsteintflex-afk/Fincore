import { ArrowRight, Building2, CheckCircle2, Code2, Lock, ShieldCheck, Smartphone, Wallet, XCircle } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { SandboxBanner } from "@/components/Layout";
import { Alert, Badge, Button, ErrorState, Input, Select, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { amountError, detectNetwork, money, NETWORKS } from "@/lib/format";
import { useGet, usePlatform, useWallets } from "@/lib/hooks";

export function LandingPage() {
  const { user } = useAuth();
  const platform = usePlatform();
  if (platform.data && platform.data.signup_enabled === false) return <PrivateLanding signedIn={!!user} />;
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

function PrivateLanding({ signedIn }: { signedIn: boolean }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gradient-to-b from-brand-950 to-ink-900 px-4 text-center text-white">
      <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-700 text-2xl font-bold text-gold-400">F</span>
      <h1 className="mt-5 text-3xl font-semibold">FinCore</h1>
      <p className="mt-2 max-w-sm text-brand-100">Private payment system. Authorised staff only.</p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Link to={signedIn ? "/merchant" : "/login"}><Button variant="gold" size="lg">{signedIn ? "Open dashboard" : "Sign in"}</Button></Link>
        <Link to="/verify"><Button variant="secondary" size="lg">Verify a receipt</Button></Link>
      </div>
    </div>
  );
}

export function VerifyReceiptPage() {
  const [params] = useSearchParams();
  const [form, setForm] = useState({ reference: params.get("reference") ?? "", code: params.get("code") ?? "" });
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  async function check(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      setResult(await api("/verify-receipt", { query: form }));
    } catch (ex) {
      setResult({ valid: false, message: (ex as Error).message });
    } finally {
      setBusy(false);
    }
  }
  return (
    <CheckoutShell heading="Receipt verification">
      <div className="p-6">
        <h1 className="text-lg font-semibold">Verify a receipt</h1>
        <p className="mt-1 text-sm text-slate-500">Enter the reference and verification code printed on the receipt.</p>
        <form onSubmit={check} className="mt-5 space-y-4">
          <Input label="Reference" placeholder="PAY-20261111-…" value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} required />
          <Input label="Verification code" placeholder="ABCDE-FGHIJ" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required />
          <Button type="submit" className="w-full" loading={busy}>Check receipt</Button>
        </form>
        {result && (
          <div className="mt-5">
            <Alert tone={result.valid ? "success" : "error"}>{result.message}</Alert>
            {result.reference && (
              <dl className="mt-3 divide-y divide-slate-100 text-sm">
                {[["Paid to", result.merchant_name], ["For", result.description], ["Amount", money(result.amount, result.currency)],
                  ["Payer", result.payer_name], ["Paid on", result.paid_at ? new Date(result.paid_at).toLocaleString("en-GH") : "—"],
                  ...(result.form ?? []).map((a: any) => [a.label, a.value]),
                  ...(result.livemode ? [] : [["Note", "Test (sandbox) payment — not real money"]])].map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-4 py-2"><dt className="text-slate-500">{k}</dt><dd className="text-right font-medium">{v ?? "—"}</dd></div>
                ))}
              </dl>
            )}
          </div>
        )}
      </div>
    </CheckoutShell>
  );
}

interface CheckoutView {
  channel: string | null;
  card: string | null;
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

function CheckoutShell({ children, merchant, heading }: { children: React.ReactNode; merchant?: string; heading?: string }) {
  return (
    <div className="min-h-screen bg-gradient-to-b from-brand-950 to-ink-900 px-4 py-10">
      <div className="mx-auto max-w-md">
        <div className="mb-6 text-center text-white">
          <p className="text-sm text-brand-200">{heading ?? `Pay ${merchant ?? "merchant"}`}</p>
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
  const platform = usePlatform();
  const [method, setMethod] = useState<"momo" | "card" | "wallet">("momo");
  const [params, setParams] = useSearchParams();
  const returning = params.get("card_return") === "1";
  useEffect(() => {
    if (!returning) return;
    // Back from the card page: ask FinCore (which asks the acquirer) for the outcome.
    api(`/checkout/${reference}/card/complete`, { method: "POST" }).catch(() => undefined).finally(() => {
      setParams({}, { replace: true });
      refetch();
    });
  }, [returning]); // eslint-disable-line react-hooks/exhaustive-deps
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
      if (method === "card") {
        const { redirect_url } = await api(`/checkout/${reference}/card`, { method: "POST" });
        window.location.assign(redirect_url);
        return;
      }
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
  const walletAllowed = platform.data?.signup_enabled !== false;
  const cardInProgress = data.status === "processing" && data.channel === "card";
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
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              <a href={`${import.meta.env.VITE_API_URL ?? "/api/v1"}/checkout/${data.reference}/receipt.pdf`} download>
                <Button variant="secondary">Download receipt</Button>
              </a>
              {data.redirect_url && <a href={data.redirect_url}><Button>Return to merchant</Button></a>}
            </div>
          </div>
        ) : returning ? (
          <Spinner label="Confirming your card payment…" />
        ) : data.status === "processing" && !cardInProgress ? (
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
            {cardInProgress && <Alert tone="warning">Your card payment wasn't completed. You can try again or choose another method.</Alert>}
            {err && <Alert tone="error">{err}</Alert>}
            <div className={`grid gap-2 ${walletAllowed ? "grid-cols-3" : "grid-cols-2"}`}>
              {(walletAllowed ? (["momo", "card", "wallet"] as const) : (["momo", "card"] as const)).map((m) => (
                <button
                  type="button"
                  key={m}
                  onClick={() => setMethod(m)}
                  className={`rounded-lg px-3 py-2 text-sm font-medium ring-1 ${method === m ? "bg-brand-50 text-brand-800 ring-brand-500" : "ring-slate-200"}`}
                >
                  {m === "momo" ? "Mobile money" : m === "card" ? "Card" : "FinCore wallet"}
                </button>
              ))}
            </div>
            {method === "card" ? (
              <Alert tone="info">You'll enter your card on the bank's secure page, then come back here automatically. Visa and Mastercard accepted.</Alert>
            ) : method === "momo" ? (
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
  const [answers, setAnswers] = useState<Record<string, string>>({});
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
      const pr = await api(`/pay/${slug}`, { body: { ...form, answers, amount: data.amount ? null : form.amount, customer_email: form.customer_email || null } });
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
            <Input label="Your name" value={form.customer_name} onChange={(e) => setForm({ ...form, customer_name: e.target.value })} required={!!data.fields?.length} />
            {(data.fields ?? []).map((f: any) => {
              const label = f.label + (f.required ? "" : " (optional)");
              const set = (v: string) => setAnswers({ ...answers, [f.key]: v });
              return f.type === "select" ? (
                <Select key={f.key} label={label} value={answers[f.key] ?? ""} onChange={(e) => set(e.target.value)} required={f.required}>
                  <option value="">Choose…</option>
                  {f.options.map((o: string) => <option key={o} value={o}>{o}</option>)}
                </Select>
              ) : (
                <Input key={f.key} label={label} required={f.required} value={answers[f.key] ?? ""} onChange={(e) => set(e.target.value)}
                  type={f.type === "email" ? "email" : f.type === "date" ? "date" : "text"}
                  inputMode={f.type === "phone" ? "tel" : f.type === "number" ? "decimal" : undefined} />
              );
            })}
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


// ------------------------------------------------------------------ simulated acquirer card page (sandbox only)
export function SandboxCardPage() {
  const { token } = useParams();
  const { data, error, isLoading } = useGet<any>(["sandbox-card", token], `/sandbox/card/${token}`);
  const [card, setCard] = useState({ number: "", expiry: "", cvc: "", name: "" });
  const [stage, setStage] = useState<"form" | "3ds" | "done">("form");
  const [result, setResult] = useState<{ status: string; message: string; return_url: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (data?.awaiting_3ds) setStage("3ds");
  }, [data?.awaiting_3ds]);
  useEffect(() => {
    if (stage === "done" && result) {
      const t = setTimeout(() => window.location.assign(result.return_url), 1500);
      return () => clearTimeout(t);
    }
  }, [stage, result]);
  if (isLoading) return <CheckoutShell heading="Card payment"><Spinner /></CheckoutShell>;
  if (error || !data) return <CheckoutShell heading="Card payment"><div className="p-6"><ErrorState error={error} /></div></CheckoutShell>;

  async function run(fn: () => Promise<any>) {
    setErr(null);
    setBusy(true);
    try {
      const r = await fn();
      setResult(r);
      setStage(r.status === "requires_3ds" ? "3ds" : "done");
    } catch (ex) {
      setErr((ex as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const fmtNumber = (v: string) => v.replace(/\D/g, "").slice(0, 19).replace(/(\d{4})(?=\d)/g, "$1 ");
  const fmtExpiry = (v: string) => { const d = v.replace(/\D/g, "").slice(0, 4); return d.length > 2 ? `${d.slice(0, 2)}/${d.slice(2)}` : d; };
  return (
    <CheckoutShell heading="Secure card payment">
      <div className="bg-gold-400 px-4 py-2 text-center text-xs font-semibold text-ink-900">TEST MODE — simulated bank card page. No real card is charged.</div>
      <div className="border-b border-slate-100 bg-slate-50 px-6 py-4 text-center">
        <p className="text-sm text-slate-500">{data.merchant_name} · {data.description}</p>
        <p className="tabular mt-1 text-3xl font-semibold">{money(data.amount, data.currency)}</p>
      </div>
      <div className="p-6">
        {err && <div className="mb-3"><Alert tone="error">{err}</Alert></div>}
        {stage === "done" && result ? (
          <div className="text-center">
            {result.status === "successful" ? <CheckCircle2 className="mx-auto h-12 w-12 text-emerald-600" /> : <XCircle className="mx-auto h-12 w-12 text-rose-500" />}
            <p className="mt-3 font-semibold">{result.status === "successful" ? "Payment approved" : "Payment not approved"}</p>
            <p className="text-sm text-slate-500">{result.message}</p>
            <p className="mt-3 text-xs text-slate-400">Returning to the merchant…</p>
          </div>
        ) : stage === "3ds" ? (
          <div className="space-y-4 text-center">
            <ShieldCheck className="mx-auto h-10 w-10 text-brand-600" />
            <p className="font-semibold">Bank verification (test)</p>
            <p className="text-sm text-slate-500">Your bank asks you to confirm this payment. In test mode, choose an outcome.</p>
            <div className="grid grid-cols-2 gap-2">
              <Button variant="danger" loading={busy} onClick={() => run(() => api(`/sandbox/card/${token}/3ds`, { body: { approve: false } }))}>Decline</Button>
              <Button loading={busy} onClick={() => run(() => api(`/sandbox/card/${token}/3ds`, { body: { approve: true } }))}>Approve</Button>
            </div>
          </div>
        ) : (
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); run(() => api(`/sandbox/card/${token}`, { body: card })); }}>
            <Input label="Card number" inputMode="numeric" autoComplete="cc-number" placeholder="4111 1111 1111 1111" value={card.number}
              onChange={(e) => setCard({ ...card, number: fmtNumber(e.target.value) })} required />
            <div className="grid grid-cols-2 gap-3">
              <Input label="Expiry (MM/YY)" inputMode="numeric" autoComplete="cc-exp" placeholder="12/30" value={card.expiry}
                onChange={(e) => setCard({ ...card, expiry: fmtExpiry(e.target.value) })} required />
              <Input label="CVC" inputMode="numeric" autoComplete="cc-csc" placeholder="123" value={card.cvc}
                onChange={(e) => setCard({ ...card, cvc: e.target.value.replace(/\D/g, "").slice(0, 4) })} required />
            </div>
            <Input label="Name on card" autoComplete="cc-name" value={card.name} onChange={(e) => setCard({ ...card, name: e.target.value })} />
            <Button type="submit" className="w-full" size="lg" loading={busy}>Pay {money(data.amount, data.currency)}</Button>
            <details className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
              <summary className="cursor-pointer font-medium">Test cards</summary>
              <ul className="mt-2 space-y-1 font-mono">
                {data.test_cards.map((c: any) => (
                  <li key={c.number}>
                    <button type="button" className="hover:text-brand-700" onClick={() => setCard({ number: fmtNumber(c.number), expiry: "12/30", cvc: "123", name: "Test Payer" })}>
                      {fmtNumber(c.number)} → {c.result.replace("_", " ")}
                    </button>
                  </li>
                ))}
              </ul>
            </details>
          </form>
        )}
      </div>
    </CheckoutShell>
  );
}
