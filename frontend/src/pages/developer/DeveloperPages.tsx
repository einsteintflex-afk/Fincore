import { KeyRound, Plus, RefreshCw, Send, Trash2, Webhook } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { Alert, Badge, Button, Card, CopyText, Empty, Input, Modal, PageHeader, Select, Spinner, Stat, Table, Tabs } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useAction, useGet } from "@/lib/hooks";

export function DeveloperApps() {
  const { bizId } = useParams();
  const apps = useGet<any[]>(["apps", bizId], `/developer/apps`, { business_id: bizId });
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const create = useAction(() => api("/developer/apps", { body: { business_id: bizId, name } }), {
    invalidate: [["apps", bizId]], success: "App created", onSuccess: (a: any) => { setName(""); setSelected(a.id); },
  });
  const current = selected ?? apps.data?.[0]?.id ?? null;
  return (
    <>
      <PageHeader title="Developers" subtitle={<>Integrate FinCore payments. <Link to={`/developer/${bizId}/docs`} className="text-brand-700">Read the quick start →</Link></>} />
      {apps.error && <Alert tone="error">{(apps.error as Error).message}</Alert>}
      <div className="grid gap-6 lg:grid-cols-4">
        <Card title="Apps">
          {apps.isLoading ? <Spinner /> : (
            <ul className="mb-4 space-y-1">
              {apps.data?.map((a) => (
                <li key={a.id}>
                  <button onClick={() => setSelected(a.id)} className={`w-full rounded-lg px-3 py-2 text-left text-sm ${current === a.id ? "bg-brand-50 font-medium text-brand-800" : "hover:bg-slate-50"}`}>{a.name}</button>
                </li>
              ))}
              {!apps.data?.length && <p className="text-sm text-slate-500">No apps yet.</p>}
            </ul>
          )}
          <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); create.mutate(undefined); }}>
            <Input placeholder="New app name" value={name} onChange={(e) => setName(e.target.value)} required minLength={2} />
            <Button size="sm" type="submit" className="w-full" icon={<Plus className="h-4 w-4" />} loading={create.isPending}>Create app</Button>
          </form>
        </Card>
        <div className="lg:col-span-3">{current ? <AppDetail appId={current} /> : <Card><Empty title="Create an app to get API keys" /></Card>}</div>
      </div>
    </>
  );
}

function AppDetail({ appId }: { appId: string }) {
  const [tab, setTab] = useState("keys");
  return (
    <Card>
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "keys", label: "API keys" }, { value: "webhooks", label: "Webhooks" }, { value: "deliveries", label: "Event log" }, { value: "usage", label: "Usage" }]} />
      {tab === "keys" && <Keys appId={appId} />}
      {tab === "webhooks" && <Webhooks appId={appId} />}
      {tab === "deliveries" && <Deliveries appId={appId} />}
      {tab === "usage" && <Usage appId={appId} />}
    </Card>
  );
}

function Keys({ appId }: { appId: string }) {
  const keys = useGet<any[]>(["keys", appId], `/developer/apps/${appId}/keys`);
  const [secret, setSecret] = useState<string | null>(null);
  const create = useAction((env: string) => api(`/developer/apps/${appId}/keys`, { body: { environment: env } }), { invalidate: [["keys", appId]], onSuccess: (k: any) => setSecret(k.secret_key) });
  const revoke = useAction((id: string) => api(`/developer/apps/${appId}/keys/${id}/revoke`, { method: "POST" }), { invalidate: [["keys", appId]], success: "Key revoked" });
  const roll = useAction((id: string) => api(`/developer/apps/${appId}/keys/${id}/roll`, { method: "POST" }), { invalidate: [["keys", appId]], onSuccess: (k: any) => setSecret(k.secret_key) });
  return (
    <>
      <div className="mb-4 flex flex-wrap gap-2">
        <Button size="sm" icon={<KeyRound className="h-4 w-4" />} onClick={() => create.mutate("sandbox")} loading={create.isPending}>New sandbox key</Button>
        <Button size="sm" variant="secondary" onClick={() => create.mutate("live")}>New live key</Button>
      </div>
      {keys.isLoading ? <Spinner /> : !keys.data?.length ? <Empty title="No keys yet" /> : (
        <Table rows={keys.data} keyFn={(k) => k.id}
          columns={[
            { header: "Environment", cell: (k) => <Badge tone={k.environment === "sandbox" ? "sandbox" : "active"}>{k.environment}</Badge> },
            { header: "Secret key", cell: (k) => <span className="font-mono text-xs">{k.secret_prefix}…{k.last4}</span> },
            { header: "Public key", cell: (k) => <span className="font-mono text-xs">{k.public_key.slice(0, 18)}…</span>, hideOnMobile: true },
            { header: "Status", cell: (k) => <Badge>{k.status}</Badge> },
            { header: "Last used", cell: (k) => dateTime(k.last_used_at), hideOnMobile: true },
            { header: "", cell: (k) => k.status === "active" && (
              <div className="flex justify-end gap-1">
                <Button size="sm" variant="ghost" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => roll.mutate(k.id)}>Roll</Button>
                <Button size="sm" variant="ghost" onClick={() => revoke.mutate(k.id)}>Revoke</Button>
              </div>
            ) },
          ]} />
      )}
      <Modal open={!!secret} onClose={() => setSecret(null)} title="Your new secret key">
        <Alert tone="warning">Copy this key now. For your security it won't be shown again.</Alert>
        <CopyText text={secret ?? ""} className="mt-4 block w-full break-all p-3 text-left" />
      </Modal>
    </>
  );
}

function Webhooks({ appId }: { appId: string }) {
  const eps = useGet<any[]>(["webhooks", appId], `/developer/apps/${appId}/webhooks`);
  const events = useGet<{ events: string[] }>(["events"], "/developer/events");
  const [form, setForm] = useState({ url: "", environment: "sandbox", events: [] as string[] });
  const [secret, setSecret] = useState<string | null>(null);
  const create = useAction(() => api(`/developer/apps/${appId}/webhooks`, { body: form }), { invalidate: [["webhooks", appId]], onSuccess: (e: any) => { setSecret(e.secret); setForm({ ...form, url: "" }); } });
  const test = useAction((id: string) => api(`/developer/apps/${appId}/webhooks/${id}/test`, { method: "POST" }), { invalidate: [["deliveries", appId]], success: (d: any) => `Test event ${d.status} (HTTP ${d.last_response_code ?? "error"})` });
  const toggle = useAction((ep: any) => api(`/developer/apps/${appId}/webhooks/${ep.id}`, { method: "PATCH", body: { active: !ep.active } }), { invalidate: [["webhooks", appId]] });
  const del = useAction((id: string) => api(`/developer/apps/${appId}/webhooks/${id}`, { method: "DELETE" }), { invalidate: [["webhooks", appId]], success: "Endpoint deleted" });
  const reveal = useAction((id: string) => api(`/developer/apps/${appId}/webhooks/${id}/secret`), { onSuccess: (r: any) => setSecret(r.secret) });
  return (
    <>
      <form className="mb-6 grid gap-3 rounded-lg bg-slate-50 p-4 sm:grid-cols-4" onSubmit={(e) => { e.preventDefault(); create.mutate(undefined); }}>
        <div className="sm:col-span-2"><Input label="Endpoint URL" placeholder="https://example.com/fincore/webhooks" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} required /></div>
        <Select label="Environment" value={form.environment} onChange={(e) => setForm({ ...form, environment: e.target.value })}>
          <option value="sandbox">Sandbox</option><option value="live">Live</option>
        </Select>
        <div className="flex items-end"><Button type="submit" className="w-full" icon={<Webhook className="h-4 w-4" />} loading={create.isPending}>Add endpoint</Button></div>
        <div className="flex flex-wrap gap-3 sm:col-span-4">
          {events.data?.events.map((ev) => (
            <label key={ev} className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={form.events.includes(ev)} onChange={(e) => setForm({ ...form, events: e.target.checked ? [...form.events, ev] : form.events.filter((x) => x !== ev) })} />
              <code>{ev}</code>
            </label>
          ))}
          <span className="text-xs text-slate-500">(none selected = all events)</span>
        </div>
      </form>
      {eps.isLoading ? <Spinner /> : !eps.data?.length ? <Empty title="No webhook endpoints" /> : (
        <ul className="divide-y divide-slate-100">
          {eps.data.map((ep) => (
            <li key={ep.id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <p className="truncate font-mono text-sm">{ep.url}</p>
                <p className="text-xs text-slate-500"><Badge tone={ep.environment === "sandbox" ? "sandbox" : "active"}>{ep.environment}</Badge> {ep.events.length ? ep.events.join(", ") : "all events"} {!ep.active && "· disabled"}</p>
              </div>
              <div className="flex flex-wrap gap-1">
                <Button size="sm" variant="ghost" icon={<Send className="h-3.5 w-3.5" />} onClick={() => test.mutate(ep.id)}>Test</Button>
                <Button size="sm" variant="ghost" onClick={() => reveal.mutate(ep.id)}>Secret</Button>
                <Button size="sm" variant="ghost" onClick={() => toggle.mutate(ep)}>{ep.active ? "Disable" : "Enable"}</Button>
                <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => del.mutate(ep.id)} aria-label="Delete" />
              </div>
            </li>
          ))}
        </ul>
      )}
      <Modal open={!!secret} onClose={() => setSecret(null)} title="Signing secret">
        <p className="mb-3 text-sm text-slate-600">Verify the <code>X-FinCore-Signature</code> header with this secret.</p>
        <CopyText text={secret ?? ""} className="block w-full break-all p-3 text-left" />
      </Modal>
    </>
  );
}

function Deliveries({ appId }: { appId: string }) {
  const d = useGet<any[]>(["deliveries", appId], `/developer/apps/${appId}/deliveries`);
  const retry = useAction((id: string) => api(`/developer/apps/${appId}/deliveries/${id}/retry`, { method: "POST" }), { invalidate: [["deliveries", appId]], success: "Retried" });
  const [open, setOpen] = useState<any>(null);
  if (d.isLoading) return <Spinner />;
  if (!d.data?.length) return <Empty title="No events delivered yet" />;
  return (
    <>
      <Table rows={d.data} keyFn={(x) => x.id} onRowClick={setOpen}
        columns={[
          { header: "Event", cell: (x) => <code className="text-xs">{x.event_type}</code> },
          { header: "Status", cell: (x) => <Badge>{x.status}</Badge> },
          { header: "Attempts", cell: (x) => x.attempts, hideOnMobile: true },
          { header: "Response", cell: (x) => x.last_response_code ?? x.last_error ?? "—", hideOnMobile: true },
          { header: "Created", cell: (x) => dateTime(x.created_at) },
          { header: "", cell: (x) => x.status !== "succeeded" && <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); retry.mutate(x.id); }}>Retry</Button> },
        ]} />
      <Modal open={!!open} onClose={() => setOpen(null)} title={open?.event_type ?? ""} wide>
        <pre className="overflow-x-auto rounded-lg bg-ink-900 p-4 text-xs text-emerald-200">{JSON.stringify(open?.payload, null, 2)}</pre>
      </Modal>
    </>
  );
}

function Usage({ appId }: { appId: string }) {
  const u = useGet<any>(["usage", appId], `/developer/apps/${appId}/usage`);
  if (u.isLoading) return <Spinner />;
  if (!u.data) return null;
  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Requests (30d)" value={u.data.total_requests} />
        <Stat label="Errors" value={u.data.error_requests} />
        <Stat label="Error rate" value={`${(u.data.error_rate * 100).toFixed(1)}%`} />
      </div>
      {u.data.daily.length ? (
        <div className="h-56">
          <ResponsiveContainer>
            <BarChart data={u.data.daily}>
              <XAxis dataKey="day" tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="requests" fill="#047857" radius={[4, 4, 0, 0]} />
              <Bar dataKey="errors" fill="#e11d48" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : <Empty title="No API traffic yet" />}
      {u.data.top_endpoints.length > 0 && (
        <Table rows={u.data.top_endpoints} keyFn={(r: any) => r.method + r.path}
          columns={[{ header: "Endpoint", cell: (r: any) => <code className="text-xs">{r.method} {r.path}</code> }, { header: "Requests", cell: (r: any) => r.requests, className: "text-right" }]} />
      )}
    </div>
  );
}

const CODE_CHARGE = `curl -X POST https://api.fincore.example/api/v1/gateway/charges \\
  -H "Authorization: Bearer sk_test_..." \\
  -H "Idempotency-Key: order-1042" \\
  -H "Content-Type: application/json" \\
  -d '{"amount": "120.00", "currency": "GHS", "phone": "0241234567",
       "email": "customer@example.com", "reference": "order-1042"}'`;

const CODE_VERIFY = `import hmac, hashlib, time

def verify(secret: str, header: str, body: bytes) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    if abs(time.time() - int(parts["t"])) > 300:
        return False
    expected = hmac.new(secret.encode(), f"{parts['t']}.".encode() + body,
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])`;

export function DeveloperDocs() {
  return (
    <>
      <PageHeader title="API quick start" subtitle={<>Full reference: <a className="text-brand-700" href="/docs" target="_blank" rel="noreferrer">OpenAPI docs</a></>} />
      <div className="grid gap-6">
        <Card title="1. Get a sandbox key">
          <p className="text-sm text-slate-600">Create an app under <b>Apps &amp; keys</b> and generate a sandbox key (<code>sk_test_…</code>). Sandbox charges are simulated and never move money.</p>
        </Card>
        <Card title="2. Create a charge">
          <p className="mb-3 text-sm text-slate-600">With a <code>phone</code>, FinCore sends a mobile-money approval prompt. Without one, redirect the customer to the returned <code>checkout_url</code>.</p>
          <pre className="overflow-x-auto rounded-lg bg-ink-900 p-4 text-xs text-emerald-200">{CODE_CHARGE}</pre>
          <p className="mt-3 text-sm text-slate-600">Sandbox numbers: ending <code>0000</code> → failed, <code>1111</code> → pending (resolve with <code>POST /gateway/sandbox/charges/:ref/resolve</code>), anything else → successful.</p>
        </Card>
        <Card title="3. Verify the payment">
          <p className="text-sm text-slate-600"><code>GET /api/v1/gateway/charges/:reference</code> — always confirm server-side before giving value.</p>
        </Card>
        <Card title="4. Handle webhooks">
          <p className="mb-3 text-sm text-slate-600">Events: <code>charge.success</code>, <code>charge.failed</code>, <code>refund.processed</code>, <code>settlement.paid</code>… Each request is signed: <code>X-FinCore-Signature: t=&lt;unix&gt;,v1=&lt;hmac_sha256(secret, "t." + body)&gt;</code>. Failed deliveries retry with exponential backoff.</p>
          <pre className="overflow-x-auto rounded-lg bg-ink-900 p-4 text-xs text-emerald-200">{CODE_VERIFY}</pre>
        </Card>
        <Card title="Conventions">
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
            <li>Amounts are decimal strings in GHS with up to 2 decimals.</li>
            <li>Send an <code>Idempotency-Key</code> header on every POST; retries with the same key return the original result.</li>
            <li>Errors look like <code>{`{"error": {"code", "message", "details"}}`}</code>.</li>
            <li>Live keys are available after business approval and platform go-live.</li>
          </ul>
        </Card>
      </div>
    </>
  );
}
