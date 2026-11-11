import { useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Alert, Button, Input } from "@/components/ui";
import { api } from "@/lib/api";
import { isStaff, useAuth } from "@/lib/auth";
import { usePlatform } from "@/lib/hooks";

function AuthCard({ title, subtitle, children, footer }: { title: string; subtitle?: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <div className="hidden w-1/2 flex-col justify-between bg-gradient-to-br from-brand-900 via-brand-950 to-ink-900 p-12 text-white lg:flex">
        <Link to="/" className="flex items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-700 font-bold text-gold-400">F</span>
          <span className="text-xl font-semibold">FinCore</span>
        </Link>
        <div>
          <h2 className="text-3xl font-semibold leading-tight">Money that moves at the speed of Ghana.</h2>
          <p className="mt-4 max-w-md text-brand-100">
            Wallets, mobile money, bank transfers and merchant payments — on one secure, double-entry ledger.
          </p>
        </div>
        <p className="text-xs text-brand-200">© {new Date().getFullYear()} FinCore. Built for Ghana, ready for Africa.</p>
      </div>
      <div className="flex w-full items-center justify-center px-4 py-12 lg:w-1/2">
        <div className="w-full max-w-sm">
          <Link to="/" className="mb-8 flex items-center gap-2 lg:hidden">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-700 font-bold text-gold-400">F</span>
            <span className="text-lg font-semibold">FinCore</span>
          </Link>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
          <div className="mt-6">{children}</div>
          {footer && <div className="mt-6 text-center text-sm text-slate-600">{footer}</div>}
        </div>
      </div>
    </div>
  );
}

export function LoginPage() {
  const { user, login, completeTwoFactor } = useAuth();
  const loc = useLocation() as { state?: { from?: string } };
  const platform = usePlatform();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [challenge, setChallenge] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={loc.state?.from ?? (isStaff(user) ? "/admin" : "/app")} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (challenge) {
        await completeTwoFactor(challenge, code);
      } else {
        const r = await login(email, password);
        if (r.requires2fa) setChallenge(r.challengeToken!);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title={challenge ? "Two-factor authentication" : "Welcome back"}
      subtitle={challenge ? "Enter the 6-digit code from your authenticator app." : "Sign in to your FinCore account."}
      footer={!challenge && platform.data?.signup_enabled !== false && <>New to FinCore? <Link className="font-medium text-brand-700" to="/register">Create an account</Link></>}
    >
      <form onSubmit={submit} className="space-y-4">
        {error && <Alert tone="error">{error}</Alert>}
        {challenge ? (
          <Input label="Authentication code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} autoFocus maxLength={8} />
        ) : (
          <>
            <Input label="Email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            <Input label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            <div className="text-right text-sm">
              <Link to="/forgot-password" className="text-brand-700 hover:underline">Forgot password?</Link>
            </div>
          </>
        )}
        <Button type="submit" className="w-full" size="lg" loading={busy}>
          {challenge ? "Verify" : "Sign in"}
        </Button>
        {challenge && (
          <button type="button" className="w-full text-sm text-slate-500" onClick={() => setChallenge(null)}>
            Back to sign in
          </button>
        )}
      </form>
    </AuthCard>
  );
}

export function RegisterPage() {
  const platform = usePlatform();
  if (platform.data?.signup_enabled === false)
    return (
      <AuthCard title="Sign-up is closed" footer={<Link to="/login" className="text-brand-700">Sign in</Link>}>
        <Alert tone="info">This is a private FinCore. Ask the owner to create an account for you.</Alert>
      </AuthCard>
    );
  return <RegisterForm />;
}

function RegisterForm() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [form, setForm] = useState({ full_name: "", email: "", phone: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api("/auth/register", { body: { ...form, phone: form.phone || null } });
      await login(form.email, form.password);
      nav("/app");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Create your account" subtitle="Get a GHS wallet in under a minute." footer={<>Already have an account? <Link className="font-medium text-brand-700" to="/login">Sign in</Link></>}>
      <form onSubmit={submit} className="space-y-4">
        {error && <Alert tone="error">{error}</Alert>}
        <Input label="Full name" value={form.full_name} onChange={set("full_name")} required autoComplete="name" />
        <Input label="Email" type="email" value={form.email} onChange={set("email")} required autoComplete="email" />
        <Input label="Mobile number" placeholder="024 123 4567" value={form.phone} onChange={set("phone")} autoComplete="tel" hint="MTN, Telecel or AT number" />
        <Input
          label="Password"
          type="password"
          value={form.password}
          onChange={set("password")}
          required
          autoComplete="new-password"
          hint="At least 10 characters with upper & lower case letters and a digit"
        />
        <Button type="submit" className="w-full" size="lg" loading={busy}>Create account</Button>
        <p className="text-center text-xs text-slate-500">By continuing you agree to FinCore's terms and privacy policy.</p>
      </form>
    </AuthCard>
  );
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/auth/password/forgot", { body: { email } });
    } finally {
      setSent(true);
      setBusy(false);
    }
  }
  return (
    <AuthCard title="Reset your password" footer={<Link to="/login" className="text-brand-700">Back to sign in</Link>}>
      {sent ? (
        <Alert tone="success">If an account exists for {email}, we've sent a reset link. It expires in 30 minutes.</Alert>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <Input label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <Button type="submit" className="w-full" loading={busy}>Send reset link</Button>
        </form>
      )}
    </AuthCard>
  );
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/password/reset", { body: { token: params.get("token"), new_password: password } });
      nav("/login");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <AuthCard title="Choose a new password">
      <form onSubmit={submit} className="space-y-4">
        {error && <Alert tone="error">{error}</Alert>}
        <Input label="New password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="new-password" />
        <Button type="submit" className="w-full" loading={busy}>Update password</Button>
      </form>
    </AuthCard>
  );
}

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const [state, setState] = useState<"idle" | "ok" | "error">("idle");
  const [msg, setMsg] = useState("");
  async function verify() {
    try {
      await api("/auth/verify-email", { method: "POST", query: { token: params.get("token") } });
      setState("ok");
    } catch (e) {
      setState("error");
      setMsg((e as Error).message);
    }
  }
  return (
    <AuthCard title="Verify your email" footer={<Link to="/app" className="text-brand-700">Go to dashboard</Link>}>
      {state === "ok" && <Alert tone="success">Your email is verified. Thank you!</Alert>}
      {state === "error" && <Alert tone="error">{msg}</Alert>}
      {state === "idle" && <Button className="w-full" onClick={verify}>Confirm my email</Button>}
    </AuthCard>
  );
}
