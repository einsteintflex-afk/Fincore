from datetime import date

from tests.conftest import fund


def upload(admin, csv_text: str, provider="sandbox", name="mtn-statement.csv"):
    return admin.client.post("/api/v1/admin/reconciliation/providers/upload", headers=admin.h,
                             data={"provider": provider}, files={"file": (name, csv_text.encode(), "text/csv")})


def _deposits(make_user, *amounts):
    u = make_user(kyc_tier=3)
    return [fund(u, a) for a in amounts]


def test_clean_file_balances(make_user, admin):
    a, b = _deposits(make_user, "100.00", "250.50")
    today = date.today().isoformat()
    csv_text = ("Transaction ID,Amount,Status,Date\n"
                f"{a['provider_reference']},100.00,SUCCESS,{today}T00:00:00\n"
                f"{b['provider_reference']},\"250.50\",Completed,{today}T23:59:00\n")
    r = upload(admin, csv_text)
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] == "balanced" and run["summary"]["matched"] == 2
    assert run["summary"]["file_name"] == "mtn-statement.csv" and run["summary"]["rows"] == 2


def test_discrepancies_detected(make_user, admin):
    a, b, c = _deposits(make_user, "100.00", "50.00", "20.00")
    today = date.today().isoformat()
    csv_text = ("provider_reference,amount,status,date\n"
                f"{a['provider_reference']},99.00,successful,{today}T00:00:00\n"     # amount mismatch
                f"{b['provider_reference']},50.00,failed,{today}T00:00:01\n"         # status mismatch
                f"SBX-UNKNOWN-1,5.00,successful,{today}T23:59:59\n")                # unknown to FinCore
    run = upload(admin, csv_text).json()
    kinds = sorted(d["type"] for d in run["discrepancies"])
    # c is successful internally but absent from the provider's file for the same period
    assert kinds == ["amount_mismatch", "missing_in_provider_file", "missing_internal", "status_mismatch"]
    missing = next(d for d in run["discrepancies"] if d["type"] == "missing_in_provider_file")
    assert missing["reference"] == c["reference"]


def test_match_by_internal_reference(make_user, admin):
    (a,) = _deposits(make_user, "10.00")
    r = upload(admin, f"reference,amount,status\n{a['reference']},10.00,paid\n")
    assert r.json()["summary"]["matched"] == 1


def test_malformed_files_rejected(admin):
    assert upload(admin, "").status_code == 422
    r = upload(admin, "foo,bar\n1,2\n")
    assert r.status_code == 422 and "amount, status" in r.json()["error"]["message"]
    r = upload(admin, "provider_reference,amount,status\nX1,abc,successful\n")
    assert r.status_code == 422 and "Line 2" in r.json()["error"]["message"]
    r = upload(admin, "provider_reference,amount,status\nX1,1.00,weird\n")
    assert r.status_code == 422 and "unknown status" in r.json()["error"]["message"]
    assert upload(admin, "provider_reference,amount,status\nX1,1,ok\n", provider="nope").status_code == 422


def test_only_finance_can_upload(make_user):
    support = make_user(role="support")
    assert upload(support, "provider_reference,amount,status\nX,1,successful\n").status_code == 403
