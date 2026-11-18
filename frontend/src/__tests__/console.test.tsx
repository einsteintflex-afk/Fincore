import { render, screen } from "@testing-library/react";
import { api, isNativeApp, server, tokens } from "@/lib/api";
import { consoleNav } from "@/components/Layout";
import { FeeBreakdown } from "@/pages/customer/CustomerPages";

function respond(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

describe("dashboard", () => {
  it("has exactly five primary sections", () => {
    expect(consoleNav().map((n) => n.label)).toEqual(["Overview", "Applications", "Transactions", "Payments", "Settings"]);
  });

  it("shows the full withdrawal fee breakdown before confirming", () => {
    render(<FeeBreakdown q={{ currency: "GHS", requested_amount: "100.00", fee_percent: "15", fee_amount: "15.00", net_amount: "85.00", total_debit: "100.00" }} />);
    expect(screen.getByTestId("Requested withdrawal").textContent).toContain("100.00");
    expect(screen.getByTestId("Withdrawal fee (15%)").textContent).toContain("15.00");
    expect(screen.getByTestId("Recipient receives").textContent).toContain("85.00");
    expect(screen.getByTestId("Total deducted from balance").textContent).toContain("100.00");
  });
});

describe("packaged apps", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete (window as any).Capacitor;
    tokens.set(null);
    localStorage.clear();
  });

  it("is not native in a browser", () => expect(isNativeApp()).toBe(false));

  it("only accepts https server addresses (localhost allowed for development)", () => {
    expect(() => server.set("http://evil.example.com")).toThrow();
    server.set("https://fincore.example.com/");
    expect(server.get()).toBe("https://fincore.example.com");
    server.set("http://10.0.2.2:8000");
    expect(server.get()).toBe("http://10.0.2.2:8000");
  });

  it("keeps the native refresh token in memory only and sends it in the body", async () => {
    (window as any).Capacitor = { isNativePlatform: () => true };
    server.set("https://fincore.example.com");
    tokens.set("expired", "rt_secret");
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      calls.push({ url, init });
      if (url.endsWith("/auth/refresh")) return respond(200, { access_token: "fresh", refresh_token: "rt_next" });
      if ((init?.headers as Record<string, string>)?.Authorization === "Bearer fresh") return respond(200, { ok: true });
      return respond(401, { error: { code: "token_expired", message: "expired" } });
    });
    await expect(api("/me")).resolves.toEqual({ ok: true });
    const refresh = calls.find((c) => c.url.endsWith("/auth/refresh"))!;
    expect(refresh.url).toBe("https://fincore.example.com/api/v1/auth/refresh");
    expect(JSON.parse(String(refresh.init?.body))).toEqual({ refresh_token: "rt_secret" });
    expect((refresh.init?.headers as Record<string, string>)["X-FinCore-Client"]).toBe("native");
    expect(JSON.stringify(localStorage)).not.toContain("rt_");
  });
});
