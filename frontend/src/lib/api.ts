/**
 * Thin fetch wrapper for the FinCore API.
 * - Attaches the access token, refreshes it once on 401 using the refresh token.
 * - Normalises errors to ApiError({ code, message, details }).
 */

/** True inside the packaged apps (Capacitor on Android/iOS, Tauri on Windows/macOS). */
export function isNativeApp(): boolean {
  const w = window as any;
  if (w.Capacitor?.isNativePlatform?.()) return true;
  if (w.__TAURI_INTERNALS__ || w.__TAURI__) return true;
  return ["capacitor:", "tauri:"].includes(window.location.protocol) || window.location.hostname === "tauri.localhost";
}

const SERVER_KEY = "fincore.server";

/** The FinCore server the packaged apps talk to (not a secret). The web app always uses its own origin. */
export const server = {
  get(): string {
    try {
      return localStorage.getItem(SERVER_KEY) || (import.meta.env.VITE_SERVER_URL as string | undefined) || "";
    } catch {
      return (import.meta.env.VITE_SERVER_URL as string | undefined) || "";
    }
  },
  set(url: string) {
    const clean = url.trim().replace(/\/+$/, "");
    if (clean && !/^https:\/\//.test(clean) && !/^http:\/\/(localhost|127\.0\.0\.1|10\.0\.2\.2)(:\d+)?$/.test(clean))
      throw new Error("Use an https:// address");
    try {
      localStorage.setItem(SERVER_KEY, clean);
    } catch {
      /* storage unavailable */
    }
  },
};

function apiBase(): string {
  const explicit = import.meta.env.VITE_API_URL as string | undefined;
  if (isNativeApp()) return `${server.get()}/api/v1`;
  return explicit ?? "/api/v1";
}
// Packaged apps cannot use the HttpOnly cookie (different origin), so their refresh token is held in memory
// only — never written to disk. Closing the app signs the user out; nothing usable is left on the device.
let nativeRefreshToken: string | null = null;
// The refresh token lives in an HttpOnly cookie set by the API (never readable from JavaScript).
// We only remember *whether* a session exists, to avoid a pointless refresh call for anonymous visitors.
const SESSION_FLAG = "fincore.session";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onAuthLost: (() => void) | null = null;

function setFlag(on: boolean) {
  try {
    if (on) localStorage.setItem(SESSION_FLAG, "1");
    else localStorage.removeItem(SESSION_FLAG);
  } catch {
    /* storage unavailable */
  }
}

export const tokens = {
  /** Store the access token in memory; `null` signs out locally. */
  set(access: string | null, refresh?: string | null) {
    accessToken = access;
    if (refresh !== undefined) nativeRefreshToken = refresh;
    if (access === null) nativeRefreshToken = null;
    setFlag(access !== null && !isNativeApp());
  },
  hasSession(): boolean {
    try {
      return localStorage.getItem(SESSION_FLAG) === "1";
    } catch {
      return false;
    }
  },
  hasAccess: () => accessToken !== null,
  /** On page load: exchange the refresh cookie for an access token. */
  bootstrap: () => tryRefresh(),
  onAuthLost(fn: () => void) {
    onAuthLost = fn;
  },
};

const clientHeaders = (): Record<string, string> => (isNativeApp() ? { "X-FinCore-Client": "native" } : { "X-FinCore-Client": "web" });

async function tryRefresh(): Promise<boolean> {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const native = isNativeApp();
        if (native && !nativeRefreshToken) return false;
        const res = await fetch(`${apiBase()}/auth/refresh`, {
          method: "POST",
          credentials: native ? "omit" : "include",
          headers: native
            ? { ...clientHeaders(), "Content-Type": "application/json" }
            : { ...clientHeaders(), "X-FinCore-CSRF": "1" },
          body: native ? JSON.stringify({ refresh_token: nativeRefreshToken }) : undefined,
        });
        if (!res.ok) {
          tokens.set(null);
          return false;
        }
        const data = await res.json();
        tokens.set(data.access_token, native ? data.refresh_token ?? nativeRefreshToken : undefined);
        return true;
      } catch {
        return false;
      } finally {
        setTimeout(() => (refreshing = null), 0);
      }
    })();
  }
  return refreshing;
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  idempotencyKey?: string;
  raw?: boolean;
}

export async function api<T = any>(path: string, opts: RequestOptions = {}, retry = true): Promise<T> {
  const base = apiBase();
  const url = new URL(base + path, base.startsWith("http") ? undefined : window.location.origin);
  Object.entries(opts.query ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  });
  const headers: Record<string, string> = { Accept: "application/json", ...clientHeaders() };
  if (opts.body !== undefined && !(opts.body instanceof FormData)) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;

  let res: Response;
  try {
    res = await fetch(base.startsWith("http") ? url.toString() : url.toString().replace(window.location.origin, ""), {
      method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"),
      credentials: isNativeApp() ? "omit" : "include",
      headers,
      body: opts.body instanceof FormData ? opts.body : opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError(0, "network_error", "Can't reach FinCore. Check your connection and try again.");
  }

  if (res.status === 401 && retry && !path.startsWith("/auth/login") && (tokens.hasSession() || nativeRefreshToken)) {
    if (await tryRefresh()) return api<T>(path, opts, false);
    onAuthLost?.();
  }
  if (opts.raw) {
    if (!res.ok) throw new ApiError(res.status, "error", "Download failed");
    return res as unknown as T;
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const e = data?.error ?? {};
    throw new ApiError(res.status, e.code ?? "error", e.message ?? `Request failed (${res.status})`, e.details);
  }
  return data as T;
}

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export async function downloadFile(path: string, query: RequestOptions["query"], filename: string) {
  const res = await api<Response>(path, { query, raw: true });
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
