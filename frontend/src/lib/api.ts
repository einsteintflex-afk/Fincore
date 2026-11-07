/**
 * Thin fetch wrapper for the FinCore API.
 * - Attaches the access token, refreshes it once on 401 using the refresh token.
 * - Normalises errors to ApiError({ code, message, details }).
 */

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "/api/v1";
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
  set(access: string | null) {
    accessToken = access;
    setFlag(access !== null);
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

const WEB_HEADERS = { "X-FinCore-Client": "web" };

async function tryRefresh(): Promise<boolean> {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const res = await fetch(`${BASE}/auth/refresh`, {
          method: "POST",
          credentials: "include",
          headers: { ...WEB_HEADERS, "X-FinCore-CSRF": "1" },
        });
        if (!res.ok) {
          tokens.set(null);
          return false;
        }
        const data = await res.json();
        tokens.set(data.access_token);
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
  const url = new URL(BASE + path, window.location.origin);
  Object.entries(opts.query ?? {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  });
  const headers: Record<string, string> = { Accept: "application/json", ...WEB_HEADERS };
  if (opts.body !== undefined && !(opts.body instanceof FormData)) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;

  let res: Response;
  try {
    res = await fetch(url.toString().replace(window.location.origin, ""), {
      method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"),
      credentials: "include",
      headers,
      body: opts.body instanceof FormData ? opts.body : opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError(0, "network_error", "Can't reach FinCore. Check your connection and try again.");
  }

  if (res.status === 401 && retry && !path.startsWith("/auth/login") && tokens.hasSession()) {
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
