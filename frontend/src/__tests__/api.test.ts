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

  it("refreshes the access token once on 401 and retries", async () => {
    localStorage.setItem("fincore.refresh", "rt_old");
    tokens.set("expired");
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      calls.push(`${url} ${(init?.headers as Record<string, string>)?.Authorization ?? ""}`);
      if (url.endsWith("/auth/refresh")) return respond(200, { access_token: "fresh", refresh_token: "rt_new" });
      if ((init?.headers as Record<string, string>)?.Authorization === "Bearer fresh") return respond(200, { ok: true });
      return respond(401, { error: { code: "token_expired", message: "Token expired" } });
    });
    await expect(api("/me")).resolves.toEqual({ ok: true });
    expect(calls.some((c) => c.includes("/auth/refresh"))).toBe(true);
    expect(localStorage.getItem("fincore.refresh")).toBe("rt_new");
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
