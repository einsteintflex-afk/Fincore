import clsx from "clsx";
import { CheckCircle2, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

interface Toast {
  id: number;
  kind: "success" | "error";
  message: string;
}

const Ctx = createContext<{ success(m: string): void; error(m: unknown): void } | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], message: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, message }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
  }, []);
  const api = {
    success: (m: string) => push("success", m),
    error: (e: unknown) => push("error", e instanceof Error ? e.message : String(e)),
  };
  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[60] flex flex-col items-center gap-2 px-4 sm:bottom-auto sm:right-4 sm:top-4 sm:items-end">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={clsx(
              "pointer-events-auto flex max-w-sm items-start gap-2 rounded-lg px-4 py-3 text-sm shadow-lg ring-1",
              t.kind === "success" ? "bg-white text-slate-800 ring-emerald-200" : "bg-white text-slate-800 ring-rose-200",
            )}
          >
            {t.kind === "success" ? <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600" /> : <XCircle className="h-5 w-5 shrink-0 text-rose-600" />}
            <span>{t.message}</span>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useToast outside ToastProvider");
  return v;
}
