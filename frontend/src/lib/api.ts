/**
 * Thin fetch wrapper for the FinCore API.
 * - Attaches the access token, refreshes it once on 401 using the refresh token.
 * - Normalises errors to ApiError({ code, message, details }).
 */

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "/api/v1";
const REFRESH_KEY = "fincore.refresh";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onAuthLost: (() => void) | null = null;

export const tokens = {
  set(access: string | null, refresh?: string | null) {
    accessToken = access;
    if (refresh !== undefined) {
      try {
        if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
        else localStorage.removeItem(REFRESH_KEY);
      } catch {
        /* storage unavailable */
      }
    }
  },
  refreshToken(): string | null {
    try {
      return localStorage.getItem(REFRESH_KEY);
    } catch {
      return null;
    }
  },
  hasAccess: () => accessToken !== null,
  /** On page load: exchange a stored refresh token for an access token. */
  bootstrap: () => tryRefresh(),
  onAuthLost(fn: () => void) {
    onAuthLost = fn;
  },
};

async function tryRefresh(): Promise<boolean> {
  const rt = tokens.refreshToken();
  if (!rt) return false;
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const res = await fetch(`${BASE}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: rt }),
        });
        if (!res.ok) {
          tokens.set(null, null);
          return false;
        }
        const data = await res.json();
        tokens.set(data.access_token, data.refresh_token);
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
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;

  let res: Response;
  try {
    res = await fetch(url.toString().replace(window.location.origin, ""), {
      method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"),
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError(0, "network_error", "Can't reach FinCore. Check your connection and try again.");
  }

  if (res.status === 401 && retry && !path.startsWith("/auth/login")) {
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
