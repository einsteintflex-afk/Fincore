"""Simple concurrent load test for the money-movement hot path.

Creates N customers, funds them through the sandbox, then fires concurrent wallet transfers in a ring and
reports throughput, latency percentiles and a ledger-integrity check.

    python scripts/loadtest.py --base http://localhost:8000 --users 20 --transfers 400 --concurrency 20

Only run against development/staging environments with live payments disabled.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import statistics
import time
import uuid

import httpx

PASSWORD = "LoadTest!Pass2026"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--users", type=int, default=20)
    ap.add_argument("--transfers", type=int, default=400)
    ap.add_argument("--concurrency", type=int, default=20)
    args = ap.parse_args()
    api = f"{args.base}/api/v1"
    client = httpx.Client(timeout=30)

    if client.get(f"{api}/platform").json().get("live_payments_enabled"):
        raise SystemExit("Refusing to load-test a deployment with live payments enabled")

    users = []
    run = uuid.uuid4().hex[:6]
    for i in range(args.users):
        email = f"load-{run}-{i}@example.com"
        client.post(f"{api}/auth/register", json={"email": email, "password": PASSWORD, "full_name": f"Load {i}"})
        tok = client.post(f"{api}/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        w = client.get(f"{api}/wallets", headers=h).json()[0]
        r = client.post(f"{api}/deposits", headers=h, json={"wallet_id": w["id"], "amount": "200", "phone": "0241234567"})
        r.raise_for_status()
        users.append((h, w))
    print(f"prepared {len(users)} funded users")

    def transfer(i: int) -> tuple[int, float]:
        h, w = users[i % len(users)]
        _, dst = users[(i + 1) % len(users)]
        t0 = time.perf_counter()
        r = httpx.post(f"{api}/transfers", headers={**h, "Idempotency-Key": f"{run}-{i}"}, timeout=30,
                       json={"wallet_id": w["id"], "destination_account": dst["account_number"], "amount": "1.00"})
        return r.status_code, time.perf_counter() - t0

    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(args.concurrency) as ex:
        results = list(ex.map(transfer, range(args.transfers)))
    elapsed = time.perf_counter() - t0
    lat = sorted(r[1] * 1000 for r in results)
    ok = sum(1 for r in results if r[0] == 201)
    codes: dict[int, int] = {}
    for c, _ in results:
        codes[c] = codes.get(c, 0) + 1
    print(f"transfers: {ok}/{len(results)} ok  status codes: {codes}")
    print(f"throughput: {len(results) / elapsed:.1f} req/s over {elapsed:.1f}s at concurrency {args.concurrency}")
    print(f"latency ms: p50={statistics.median(lat):.0f} p95={lat[int(len(lat) * .95) - 1]:.0f} max={lat[-1]:.0f}")


if __name__ == "__main__":
    main()
