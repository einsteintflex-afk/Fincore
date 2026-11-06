/** Money arrives from the API as decimal strings. We never do arithmetic in floats for anything
 *  that's sent back to the server; formatting only. */

export function money(value: string | number | null | undefined, currency = "GHS", opts: { sign?: boolean } = {}): string {
  if (value === null || value === undefined || value === "") return "—";
  const str = String(value);
  const negative = str.startsWith("-");
  const [intPart, fracPart = ""] = str.replace("-", "").split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const frac = (fracPart + "00").slice(0, Math.max(2, fracPart.replace(/0+$/, "").length));
  const prefix = negative ? "-" : opts.sign ? "+" : "";
  const symbol = currency === "GHS" ? "GH₵" : currency + " ";
  return `${prefix}${symbol}${grouped}.${frac}`;
}

/** Validate a user-entered amount string without using floats. Returns an error message or null. */
export function amountError(input: string, { min = "0.01" }: { min?: string } = {}): string | null {
  const v = input.trim();
  if (!v) return "Enter an amount";
  if (!/^\d+(\.\d{1,2})?$/.test(v)) return "Use numbers with up to 2 decimal places";
  if (compareDecimal(v, min) < 0) return `Minimum is ${money(min)}`;
  return null;
}

export function compareDecimal(a: string, b: string): number {
  const norm = (s: string) => {
    const [i, f = ""] = s.split(".");
    return [i.replace(/^0+(?=\d)/, ""), (f + "0000").slice(0, 4)] as const;
  };
  const [ai, af] = norm(a);
  const [bi, bf] = norm(b);
  if (ai.length !== bi.length) return ai.length > bi.length ? 1 : -1;
  if (ai !== bi) return ai > bi ? 1 : -1;
  if (af !== bf) return af > bf ? 1 : -1;
  return 0;
}

export function dateTime(iso?: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-GH", { dateStyle: "medium", timeStyle: "short" });
}

export function dateOnly(iso?: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-GH", { dateStyle: "medium" });
}

export function relative(iso?: string | null): string {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return dateOnly(iso);
}

export function titleCase(s?: string | null): string {
  if (!s) return "";
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function maskPhone(msisdn?: string | null): string {
  if (!msisdn) return "";
  const local = msisdn.startsWith("233") ? "0" + msisdn.slice(3) : msisdn;
  return local.replace(/(\d{3})(\d{3})(\d{4})/, "$1 $2 $3");
}

export const NETWORKS: Record<string, string> = { mtn: "MTN MoMo", telecel: "Telecel Cash", at: "AT Money" };

export function detectNetwork(phone: string): string | null {
  const d = phone.replace(/\D/g, "");
  const nsn = d.startsWith("233") ? d.slice(3) : d.startsWith("0") ? d.slice(1) : d;
  const p = nsn.slice(0, 2);
  if (["24", "25", "53", "54", "55", "59"].includes(p)) return "mtn";
  if (["20", "50"].includes(p)) return "telecel";
  if (["26", "27", "56", "57"].includes(p)) return "at";
  return null;
}
