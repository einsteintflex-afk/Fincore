import clsx from "clsx";
import { AlertTriangle, Inbox, Loader2, X } from "lucide-react";
import { forwardRef, useEffect, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";
import { money, titleCase } from "@/lib/format";

// ------------------------------------------------------------------ Button
type Variant = "primary" | "secondary" | "ghost" | "danger" | "gold";
const variants: Record<Variant, string> = {
  primary: "bg-brand-700 text-white hover:bg-brand-800 focus-visible:ring-brand-500",
  secondary: "bg-white text-slate-800 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 focus-visible:ring-brand-500",
  ghost: "text-slate-700 hover:bg-slate-100",
  danger: "bg-rose-600 text-white hover:bg-rose-700 focus-visible:ring-rose-500",
  gold: "bg-gold-400 text-ink-900 hover:bg-gold-500 focus-visible:ring-gold-500",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading, icon, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-60",
        size === "sm" && "px-3 py-1.5 text-sm",
        size === "md" && "px-4 py-2 text-sm",
        size === "lg" && "px-5 py-3 text-base",
        variants[variant],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
});

// ------------------------------------------------------------------ Form controls
interface FieldProps {
  label?: string;
  hint?: ReactNode;
  error?: string | null;
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & FieldProps>(function Input(
  { label, hint, error, className, id, ...rest },
  ref,
) {
  const inputId = id ?? rest.name;
  return (
    <label className="block" htmlFor={inputId}>
      {label && <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>}
      <input
        ref={ref}
        id={inputId}
        className={clsx(
          "block w-full rounded-lg border-0 px-3 py-2 text-slate-900 shadow-sm ring-1 ring-inset placeholder:text-slate-400 focus:ring-2 focus:ring-inset sm:text-sm",
          error ? "ring-rose-400 focus:ring-rose-500" : "ring-slate-300 focus:ring-brand-600",
          className,
        )}
        aria-invalid={!!error}
        {...rest}
      />
      {error ? <span className="mt-1 block text-xs text-rose-600">{error}</span> : hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
});

export function Select({ label, hint, error, className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement> & FieldProps) {
  return (
    <label className="block">
      {label && <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>}
      <select
        className={clsx(
          "block w-full rounded-lg border-0 py-2 pl-3 pr-8 text-slate-900 shadow-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600 sm:text-sm",
          className,
        )}
        {...rest}
      >
        {children}
      </select>
      {error ? <span className="mt-1 block text-xs text-rose-600">{error}</span> : hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export function Textarea({ label, ...rest }: React.TextareaHTMLAttributes<HTMLTextAreaElement> & { label?: string }) {
  return (
    <label className="block">
      {label && <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>}
      <textarea
        className="block w-full rounded-lg border-0 px-3 py-2 text-slate-900 shadow-sm ring-1 ring-inset ring-slate-300 focus:ring-2 focus:ring-brand-600 sm:text-sm"
        rows={4}
        {...rest}
      />
    </label>
  );
}

// ------------------------------------------------------------------ Layout pieces
export function Card({ title, actions, children, className, padded = true }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; padded?: boolean }) {
  return (
    <section className={clsx("rounded-xl bg-white shadow-card ring-1 ring-slate-200/70", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3 sm:px-5">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={clsx(padded && "p-4 sm:p-5")}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-slate-900 sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({ label, value, sub, icon, tone = "default" }: { label: string; value: ReactNode; sub?: ReactNode; icon?: ReactNode; tone?: "default" | "brand" }) {
  return (
    <div className={clsx("rounded-xl p-4 shadow-card ring-1", tone === "brand" ? "bg-gradient-to-br from-brand-800 to-brand-950 text-white ring-brand-900" : "bg-white ring-slate-200/70")}>
      <div className="flex items-center justify-between">
        <p className={clsx("text-xs font-medium uppercase tracking-wide", tone === "brand" ? "text-brand-100" : "text-slate-500")}>{label}</p>
        {icon && <span className={tone === "brand" ? "text-gold-400" : "text-brand-600"}>{icon}</span>}
      </div>
      <p className="tabular mt-2 text-2xl font-semibold">{value}</p>
      {sub && <p className={clsx("mt-1 text-xs", tone === "brand" ? "text-brand-100" : "text-slate-500")}>{sub}</p>}
    </div>
  );
}

// ------------------------------------------------------------------ Status
const statusTone: Record<string, string> = {
  successful: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  paid: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  active: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  approved: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  succeeded: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  balanced: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  resolved: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  pending: "bg-amber-50 text-amber-700 ring-amber-600/20",
  processing: "bg-sky-50 text-sky-700 ring-sky-600/20",
  investigating: "bg-sky-50 text-sky-700 ring-sky-600/20",
  open: "bg-amber-50 text-amber-700 ring-amber-600/20",
  failed: "bg-rose-50 text-rose-700 ring-rose-600/20",
  rejected: "bg-rose-50 text-rose-700 ring-rose-600/20",
  suspended: "bg-rose-50 text-rose-700 ring-rose-600/20",
  frozen: "bg-rose-50 text-rose-700 ring-rose-600/20",
  revoked: "bg-slate-100 text-slate-600 ring-slate-500/20",
  discrepancies: "bg-rose-50 text-rose-700 ring-rose-600/20",
  critical: "bg-rose-50 text-rose-700 ring-rose-600/20",
  high: "bg-orange-50 text-orange-700 ring-orange-600/20",
  medium: "bg-amber-50 text-amber-700 ring-amber-600/20",
  restricted: "bg-orange-50 text-orange-700 ring-orange-600/20",
  reversed: "bg-violet-50 text-violet-700 ring-violet-600/20",
  refunded: "bg-violet-50 text-violet-700 ring-violet-600/20",
  partially_refunded: "bg-violet-50 text-violet-700 ring-violet-600/20",
  sandbox: "bg-gold-400/20 text-yellow-800 ring-yellow-600/30",
};

export function Badge({ children, tone }: { children: ReactNode; tone?: string }) {
  const key = tone ?? (typeof children === "string" ? children : "");
  return (
    <span className={clsx("inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", statusTone[key] ?? "bg-slate-50 text-slate-600 ring-slate-500/20")}>
      {typeof children === "string" ? titleCase(children) : children}
    </span>
  );
}

export function Amount({ value, currency = "GHS", direction, className }: { value: string; currency?: string; direction?: "in" | "out" | null; className?: string }) {
  return (
    <span className={clsx("tabular font-medium", direction === "in" && "text-emerald-700", direction === "out" && "text-slate-900", className)}>
      {direction === "in" ? "+" : direction === "out" ? "−" : ""}
      {money(value, currency)}
    </span>
  );
}

// ------------------------------------------------------------------ States
export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500" role="status">
      <Loader2 className="h-5 w-5 animate-spin text-brand-600" /> {label}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : "Something went wrong";
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg bg-rose-50 px-4 py-8 text-center text-sm text-rose-700" role="alert">
      <AlertTriangle className="h-6 w-6" />
      <p>{message}</p>
      {onRetry && <Button variant="secondary" size="sm" onClick={onRetry}>Try again</Button>}
    </div>
  );
}

export function Empty({ title, body, action }: { title: string; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-12 text-center">
      <Inbox className="h-8 w-8 text-slate-300" />
      <p className="font-medium text-slate-700">{title}</p>
      {body && <p className="max-w-sm text-sm text-slate-500">{body}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function Alert({ tone = "info", children }: { tone?: "info" | "error" | "success" | "warning"; children: ReactNode }) {
  const tones = {
    info: "bg-sky-50 text-sky-800 ring-sky-200",
    error: "bg-rose-50 text-rose-800 ring-rose-200",
    success: "bg-emerald-50 text-emerald-800 ring-emerald-200",
    warning: "bg-amber-50 text-amber-900 ring-amber-200",
  };
  return <div className={clsx("rounded-lg px-3 py-2 text-sm ring-1", tones[tone])} role={tone === "error" ? "alert" : "status"}>{children}</div>;
}

// ------------------------------------------------------------------ Modal
export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-0 backdrop-blur-sm sm:items-center sm:p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={clsx("max-h-[92vh] w-full overflow-y-auto rounded-t-2xl bg-white shadow-xl sm:rounded-2xl", wide ? "sm:max-w-3xl" : "sm:max-w-lg")}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 flex items-center justify-between border-b border-slate-100 bg-white px-5 py-4">
          <h3 className="font-semibold text-slate-900">{title}</h3>
          <button onClick={onClose} className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Table
export interface Column<T> {
  header: string;
  cell: (row: T) => ReactNode;
  className?: string;
  hideOnMobile?: boolean;
}

export function Table<T>({ rows, columns, onRowClick, keyFn }: { rows: T[]; columns: Column<T>[]; onRowClick?: (row: T) => void; keyFn: (row: T) => string }) {
  return (
    <div className="-mx-4 overflow-x-auto sm:mx-0">
      <table className="min-w-full divide-y divide-slate-100 text-sm">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.header} className={clsx("whitespace-nowrap px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-500", c.hideOnMobile && "hidden md:table-cell", c.className)}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r) => (
            <tr key={keyFn(r)} onClick={onRowClick ? () => onRowClick(r) : undefined} className={clsx(onRowClick && "cursor-pointer hover:bg-slate-50")}>
              {columns.map((c) => (
                <td key={c.header} className={clsx("px-3 py-3 align-middle", c.hideOnMobile && "hidden md:table-cell", c.className)}>
                  {c.cell(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return null;
  return (
    <div className="flex items-center justify-between border-t border-slate-100 pt-3 text-sm text-slate-600">
      <span>
        Page {page} of {pages} · {total} total
      </span>
      <div className="flex gap-2">
        <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
        <Button size="sm" variant="secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button>
      </div>
    </div>
  );
}

export function Tabs({ tabs, value, onChange }: { tabs: { value: string; label: string }[]; value: string; onChange: (v: string) => void }) {
  return (
    <div className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200">
      {tabs.map((t) => (
        <button
          key={t.value}
          onClick={() => onChange(t.value)}
          className={clsx("whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition", value === t.value ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-700")}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="divide-y divide-slate-100 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-4 py-2">
          <dt className="text-slate-500">{k}</dt>
          <dd className="break-all text-right font-medium text-slate-800">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function CopyText({ text, className }: { text: string; className?: string }) {
  return (
    <button
      type="button"
      className={clsx("rounded bg-slate-100 px-2 py-1 font-mono text-xs text-slate-700 hover:bg-slate-200", className)}
      onClick={() => navigator.clipboard?.writeText(text)}
      title="Copy"
    >
      {text}
    </button>
  );
}

export { money };
