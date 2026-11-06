import { api, ApiError, tokens } from "@/lib/api";

function respond(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

describe("api client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("normalises API errors", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => respond(422, { error: { code: "insufficient_funds", message: "Insufficient funds" } }));
    await expect(api("/transfers", { body: {} })).rejects.toMatchObject({ status: 422, code: "insufficient_funds", message: "Insufficient funds" });
  });

  it("refreshes via the HttpOnly cookie once on 401 and retries", async () => {
    tokens.set("expired"); // also marks that a session exists
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      calls.push({ url, init });
      if (url.endsWith("/auth/refresh")) return respond(200, { access_token: "fresh", refresh_token: null });
      if ((init?.headers as Record<string, string>)?.Authorization === "Bearer fresh") return respond(200, { ok: true });
      return respond(401, { error: { code: "token_expired", message: "Token expired" } });
    });
    await expect(api("/me")).resolves.toEqual({ ok: true });
    const refresh = calls.find((c) => c.url.endsWith("/auth/refresh"))!;
    expect(refresh.init?.credentials).toBe("include");
    expect((refresh.init?.headers as Record<string, string>)["X-FinCore-CSRF"]).toBe("1");
    expect(refresh.init?.body).toBeUndefined(); // token is never handled by JavaScript
    expect(Object.keys(localStorage)).not.toContain("fincore.refresh");
  });

  it("does not attempt a refresh for anonymous visitors", async () => {
    tokens.set(null);
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(() => respond(401, { error: { code: "unauthorized", message: "no" } }));
    await expect(api("/me")).rejects.toMatchObject({ status: 401 });
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("sends idempotency keys", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(() => respond(201, {}));
    await api("/transfers", { body: { a: 1 }, idempotencyKey: "k-1" });
    expect((spy.mock.calls[0][1]!.headers as Record<string, string>)["Idempotency-Key"]).toBe("k-1");
  });

  it("reports network failures clearly", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => Promise.reject(new TypeError("Failed to fetch")));
    await expect(api("/me")).rejects.toBeInstanceOf(ApiError);
  });
});
