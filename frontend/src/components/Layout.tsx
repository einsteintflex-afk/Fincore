import clsx from "clsx";
import {
  ArrowDownToLine,
  ArrowLeftRight,
  ArrowUpFromLine,
  BadgeCheck,
  Bell,
  BookOpen,
  Briefcase,
  Building2,
  ChevronDown,
  Code2,
  CreditCard,
  FileBarChart,
  FileText,
  Gauge,
  HandCoins,
  KeyRound,
  LayoutDashboard,
  Link2,
  LogOut,
  Menu,
  ReceiptText,
  Scale,
  ScrollText,
  Settings,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Users,
  LifeBuoy,
  Wallet,
  X,
} from "lucide-react";
import { Suspense, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { api } from "@/lib/api";
import { isStaff, useAuth } from "@/lib/auth";
import { relative } from "@/lib/format";
import { Spinner } from "@/components/ui";
import { useAction, useBusinesses, useNotifications, usePlatform } from "@/lib/hooks";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  end?: boolean;
}

const i = (C: any) => <C className="h-4 w-4" />;

function customerNav(): NavItem[] {
  return [
    { to: "/app", label: "Home", icon: i(LayoutDashboard), end: true },
    { to: "/app/send", label: "Send money", icon: i(ArrowLeftRight) },
    { to: "/app/deposit", label: "Add money", icon: i(ArrowDownToLine) },
    { to: "/app/withdraw", label: "Withdraw", icon: i(ArrowUpFromLine) },
    { to: "/app/transactions", label: "Transactions", icon: i(ReceiptText) },
    { to: "/app/beneficiaries", label: "Beneficiaries", icon: i(Users) },
    { to: "/app/statements", label: "Statements", icon: i(FileText) },
    { to: "/app/verification", label: "Verification", icon: i(BadgeCheck) },
    { to: "/app/security", label: "Security", icon: i(ShieldCheck) },
    { to: "/app/support", label: "Help & support", icon: i(LifeBuoy) },
  ];
}

function merchantNav(id: string): NavItem[] {
  const b = `/merchant/${id}`;
  return [
    { to: b, label: "Overview", icon: i(Gauge), end: true },
    { to: `${b}/payments`, label: "Payments", icon: i(CreditCard) },
    { to: `${b}/links`, label: "Payment links", icon: i(Link2) },
    { to: `${b}/transactions`, label: "Transactions", icon: i(ReceiptText) },
    { to: `${b}/settlements`, label: "Settlements", icon: i(HandCoins) },
    { to: `${b}/reports`, label: "Reports", icon: i(FileBarChart) },
    { to: `${b}/team`, label: "Team", icon: i(Users) },
    { to: `${b}/settings`, label: "Settings", icon: i(Settings) },
  ];
}

function developerNav(id: string): NavItem[] {
  return [
    { to: `/developer/${id}`, label: "Apps & keys", icon: i(KeyRound), end: true },
    { to: `/developer/${id}/docs`, label: "API quick start", icon: i(BookOpen) },
  ];
}

function adminNav(): NavItem[] {
  return [
    { to: "/admin", label: "Overview", icon: i(Gauge), end: true },
    { to: "/admin/users", label: "Customers", icon: i(Users) },
    { to: "/admin/kyc", label: "KYC review", icon: i(BadgeCheck) },
    { to: "/admin/businesses", label: "Businesses", icon: i(Building2) },
    { to: "/admin/transactions", label: "Transactions", icon: i(ReceiptText) },
    { to: "/admin/fraud", label: "Fraud alerts", icon: i(ShieldAlert) },
    { to: "/admin/finance", label: "Finance & recon", icon: i(Scale) },
    { to: "/admin/config", label: "Fees & limits", icon: i(SlidersHorizontal) },
    { to: "/admin/support", label: "Support", icon: i(LifeBuoy) },
    { to: "/admin/audit", label: "Audit log", icon: i(ScrollText) },
  ];
}

function PortalSwitcher() {
  const { user } = useAuth();
  const { data: businesses } = useBusinesses();
  const loc = useLocation();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const first = businesses?.[0]?.id;
  const portals = [
    { key: "app", label: "Personal", to: "/app", icon: <Wallet className="h-4 w-4" /> },
    { key: "merchant", label: "Business", to: first ? `/merchant/${first}` : "/merchant", icon: <Briefcase className="h-4 w-4" /> },
    { key: "developer", label: "Developers", to: first ? `/developer/${first}` : "/merchant", icon: <Code2 className="h-4 w-4" /> },
    ...(isStaff(user) ? [{ key: "admin", label: "Admin console", to: "/admin", icon: <ShieldCheck className="h-4 w-4" /> }] : []),
  ];
  const current = portals.find((p) => loc.pathname.startsWith("/" + p.key)) ?? portals[0];
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between rounded-lg bg-white/10 px-3 py-2 text-sm text-white hover:bg-white/15">
        <span className="flex items-center gap-2">
          {current.icon} {current.label}
        </span>
        <ChevronDown className="h-4 w-4 opacity-70" />
      </button>
      {open && (
        <div className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg bg-white py-1 shadow-lg ring-1 ring-slate-200">
          {portals.map((p) => (
            <button
              key={p.key}
              onClick={() => {
                setOpen(false);
                nav(p.to);
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
            >
              {p.icon} {p.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function BusinessPicker({ base }: { base: "merchant" | "developer" }) {
  const { bizId } = useParams();
  const { data } = useBusinesses();
  const nav = useNavigate();
  if (!data || data.length === 0) return null;
  return (
    <select
      value={bizId}
      onChange={(e) => nav(`/${base}/${e.target.value}`)}
      className="mt-2 w-full rounded-lg border-0 bg-white/10 py-2 pl-3 pr-8 text-sm text-white ring-0 focus:ring-2 focus:ring-gold-400"
      aria-label="Select business"
    >
      {data.map((b) => (
        <option key={b.id} value={b.id} className="text-slate-900">
          {b.trading_name || b.name}
        </option>
      ))}
    </select>
  );
}

function NotificationsBell() {
  const { data } = useNotifications();
  const [open, setOpen] = useState(false);
  const readAll = useAction(() => api("/me/notifications/read-all", { method: "POST" }), { invalidate: [["notifications"]] });
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} className="relative rounded-full p-2 text-slate-500 hover:bg-slate-100" aria-label="Notifications">
        <Bell className="h-5 w-5" />
        {!!data?.unread && (
          <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-semibold text-white">
            {data.unread > 9 ? "9+" : data.unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-80 max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl bg-white shadow-xl ring-1 ring-slate-200">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2">
            <span className="text-sm font-semibold">Notifications</span>
            <button className="text-xs text-brand-700 hover:underline" onClick={() => readAll.mutate(undefined)}>
              Mark all read
            </button>
          </div>
          <ul className="max-h-96 divide-y divide-slate-100 overflow-y-auto">
            {(data?.items ?? []).length === 0 && <li className="px-4 py-6 text-center text-sm text-slate-500">You're all caught up</li>}
            {data?.items.map((n) => (
              <li key={n.id} className={clsx("px-4 py-3 text-sm", !n.read_at && "bg-brand-50/50")}>
                <p className="font-medium text-slate-800">{n.title}</p>
                <p className="text-slate-600">{n.body}</p>
                <p className="mt-1 text-xs text-slate-400">{relative(n.created_at)}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function SandboxBanner() {
  const { data } = usePlatform();
  if (!data) return null;
  if (data.maintenance?.enabled)
    return <div className="bg-amber-500 px-4 py-2 text-center text-sm font-medium text-white">{data.maintenance.message || "FinCore is under maintenance."}</div>;
  if (!data.live_payments_enabled)
    return (
      <div className="bg-gold-400 px-4 py-1.5 text-center text-xs font-medium text-ink-900">
        Sandbox mode — payments are simulated and no real money moves.
      </div>
    );
  return null;
}

export function AppShell({ portal }: { portal: "app" | "merchant" | "developer" | "admin" }) {
  const { user, logout } = useAuth();
  const { bizId } = useParams();
  const [mobileOpen, setMobileOpen] = useState(false);
  const items =
    portal === "app" ? customerNav() : portal === "merchant" ? merchantNav(bizId!) : portal === "developer" ? developerNav(bizId!) : adminNav();

  const sidebar = (
    <div className="flex h-full flex-col bg-ink-900 px-3 py-4">
      <Link to="/app" className="mb-5 flex items-center gap-2 px-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-700 font-bold text-gold-400">F</span>
        <span className="text-lg font-semibold tracking-tight text-white">FinCore</span>
      </Link>
      <PortalSwitcher />
      {(portal === "merchant" || portal === "developer") && <BusinessPicker base={portal} />}
      <nav className="mt-4 flex-1 space-y-0.5 overflow-y-auto">
        {items.map((it) => (
          <NavLink
            key={it.to}
            to={it.to}
            end={it.end}
            onClick={() => setMobileOpen(false)}
            className={({ isActive }) =>
              clsx(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition",
                isActive ? "bg-brand-700 text-white" : "text-slate-300 hover:bg-white/5 hover:text-white",
              )
            }
          >
            {it.icon}
            {it.label}
          </NavLink>
        ))}
      </nav>
      <div className="mt-4 border-t border-white/10 pt-4">
        <p className="truncate px-2 text-sm font-medium text-white">{user?.full_name}</p>
        <p className="truncate px-2 text-xs text-slate-400">{user?.email}</p>
        <button onClick={() => logout()} className="mt-3 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-300 hover:bg-white/5 hover:text-white">
          <LogOut className="h-4 w-4" /> Sign out
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen">
      <SandboxBanner />
      <div className="lg:flex">
        <aside className="hidden lg:fixed lg:inset-y-0 lg:block lg:w-64">{sidebar}</aside>
        {mobileOpen && (
          <div className="fixed inset-0 z-40 lg:hidden">
            <div className="absolute inset-0 bg-slate-900/60" onClick={() => setMobileOpen(false)} />
            <div className="absolute inset-y-0 left-0 w-72">
              {sidebar}
              <button className="absolute right-3 top-4 text-slate-300" onClick={() => setMobileOpen(false)} aria-label="Close menu">
                <X className="h-5 w-5" />
              </button>
            </div>
          </div>
        )}
        <div className="flex-1 lg:pl-64">
          <header className="sticky top-0 z-20 flex items-center justify-between border-b border-slate-200 bg-white/90 px-4 py-2 backdrop-blur sm:px-6">
            <button className="rounded-md p-2 text-slate-600 lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open menu">
              <Menu className="h-5 w-5" />
            </button>
            <span className="text-sm font-medium capitalize text-slate-500">{portal === "app" ? "Personal" : portal}</span>
            <div className="flex items-center gap-2">
              <NotificationsBell />
              <span className="hidden h-8 w-8 items-center justify-center rounded-full bg-brand-100 text-sm font-semibold text-brand-800 sm:flex">
                {user?.full_name?.[0]}
              </span>
            </div>
          </header>
          <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
            <Suspense fallback={<Spinner />}>
              <Outlet />
            </Suspense>
          </main>
        </div>
      </div>
    </div>
  );
}
