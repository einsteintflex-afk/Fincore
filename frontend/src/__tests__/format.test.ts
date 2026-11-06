import { amountError, compareDecimal, detectNetwork, maskPhone, money } from "@/lib/format";

describe("money", () => {
  it("formats decimal strings without float rounding", () => {
    expect(money("1118.5")).toBe("GH₵1,118.50");
    expect(money("0.1")).toBe("GH₵0.10");
    expect(money("1234567.89")).toBe("GH₵1,234,567.89");
    expect(money("-5")).toBe("-GH₵5.00");
    expect(money("100", "USD")).toBe("USD 100.00");
    expect(money(null)).toBe("—");
  });
});

describe("amount validation", () => {
  it("rejects bad input", () => {
    expect(amountError("")).toMatch(/Enter/);
    expect(amountError("1.234")).toMatch(/2 decimal/);
    expect(amountError("abc")).toBeTruthy();
    expect(amountError("0")).toMatch(/Minimum/);
    expect(amountError("0.01")).toBeNull();
    expect(amountError("250")).toBeNull();
  });
  it("compares decimals exactly", () => {
    expect(compareDecimal("10.10", "10.1")).toBe(0);
    expect(compareDecimal("9.99", "10")).toBe(-1);
    expect(compareDecimal("100", "99.999")).toBe(1);
  });
});

describe("ghana phone helpers", () => {
  it("detects networks", () => {
    expect(detectNetwork("0241234567")).toBe("mtn");
    expect(detectNetwork("+233 20 123 4567")).toBe("telecel");
    expect(detectNetwork("0571234567")).toBe("at");
    expect(detectNetwork("0111234567")).toBeNull();
  });
  it("masks msisdn to local format", () => {
    expect(maskPhone("233241234567")).toBe("024 123 4567");
  });
});
