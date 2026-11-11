from decimal import Decimal

import pytest


def balance(client, account_id) -> Decimal:
    return Decimal(client.get(f"/accounts/{account_id}").json()["balance"])


# ---- health ---------------------------------------------------------------
def test_health_endpoints(client):
    assert client.get("/health/live").json()["status"] == "ok"
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["database"] == "ok"
    assert client.get("/health").status_code == 200


def test_ready_returns_503_without_database_config(tmp_path):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    with TestClient(create_app(Settings(database_url=None, db_host=None))) as c:
        assert c.get("/health/live").status_code == 200
        r = c.get("/health/ready")
        assert r.status_code == 503
        assert r.json()["detail"] == "DatabaseConfigError"


# ---- customers ------------------------------------------------------------
def test_create_and_get_customer(client):
    r = client.post("/customers", json={"full_name": "Jane Test", "email": "JANE@Example.com"})
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "jane@example.com"
    assert client.get(f"/customers/{body['id']}").json()["full_name"] == "Jane Test"
    assert len(client.get("/customers").json()) == 1


def test_duplicate_email_rejected(client):
    payload = {"full_name": "A", "email": "a@example.com"}
    assert client.post("/customers", json=payload).status_code == 201
    assert client.post("/customers", json=payload).status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"full_name": "", "email": "x@example.com"},
        {"full_name": "X", "email": "not-an-email"},
        {"full_name": "X", "email": "x@example.com", "is_admin": True},  # extra field
    ],
)
def test_customer_validation(client, payload):
    assert client.post("/customers", json=payload).status_code == 422


def test_missing_customer_404(client):
    assert client.get("/customers/999").status_code == 404


# ---- accounts -------------------------------------------------------------
def test_create_account(client, make_account):
    acct_id = make_account()
    acct = client.get(f"/accounts/{acct_id}").json()
    assert acct["balance"] == "0.00"
    assert len(acct["account_number"]) == 12
    assert acct["status"] == "active"


def test_account_for_unknown_customer_404(client):
    assert client.post("/accounts", json={"customer_id": 42}).status_code == 404


# ---- deposits / withdrawals -----------------------------------------------
def test_deposit_and_withdraw(client, make_account):
    acct = make_account("100.00")
    r = client.post("/transactions/withdrawal", json={"account_id": acct, "amount": "40.25"})
    assert r.status_code == 201
    assert r.json()["balance_after"] == "59.75"
    assert balance(client, acct) == Decimal("59.75")


def test_withdraw_insufficient_funds(client, make_account):
    acct = make_account("10.00")
    r = client.post("/transactions/withdrawal", json={"account_id": acct, "amount": "10.01"})
    assert r.status_code == 409
    assert balance(client, acct) == Decimal("10.00")


@pytest.mark.parametrize("amount", ["0", "-5", "1.001", "1000000.01", "abc"])
def test_invalid_amounts_rejected(client, make_account, amount):
    acct = make_account()
    r = client.post("/transactions/deposit", json={"account_id": acct, "amount": amount})
    assert r.status_code == 422


def test_deposit_unknown_account_404(client):
    r = client.post("/transactions/deposit", json={"account_id": 999, "amount": "1.00"})
    assert r.status_code == 404


def test_idempotent_deposit(client, make_account):
    acct = make_account()
    body = {"account_id": acct, "amount": "25.00", "idempotency_key": "dep-abc-123"}
    first = client.post("/transactions/deposit", json=body).json()
    second = client.post("/transactions/deposit", json=body).json()
    assert first["id"] == second["id"]
    assert balance(client, acct) == Decimal("25.00")


# ---- transfers ------------------------------------------------------------
def test_transfer(client, make_account):
    a, b = make_account("500.00"), make_account("10.00")
    r = client.post(
        "/transactions/transfer", json={"from_account_id": a, "to_account_id": b, "amount": "200"}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["debit"]["type"] == "transfer_out"
    assert body["credit"]["type"] == "transfer_in"
    assert body["debit"]["transfer_id"] == body["credit"]["transfer_id"] == body["transfer_id"]
    assert balance(client, a) == Decimal("300.00")
    assert balance(client, b) == Decimal("210.00")


def test_transfer_insufficient_funds_is_atomic(client, make_account):
    a, b = make_account("5.00"), make_account()
    r = client.post(
        "/transactions/transfer", json={"from_account_id": a, "to_account_id": b, "amount": "6"}
    )
    assert r.status_code == 409
    assert balance(client, a) == Decimal("5.00")
    assert balance(client, b) == Decimal("0.00")
    assert client.get(f"/accounts/{b}/transactions").json() == []


def test_transfer_to_same_account_rejected(client, make_account):
    a = make_account("5.00")
    r = client.post(
        "/transactions/transfer", json={"from_account_id": a, "to_account_id": a, "amount": "1"}
    )
    assert r.status_code == 422


def test_cross_currency_transfer_rejected(client, make_account):
    a, b = make_account("50.00", "USD"), make_account(None, "EUR")
    r = client.post(
        "/transactions/transfer", json={"from_account_id": a, "to_account_id": b, "amount": "1"}
    )
    assert r.status_code == 400


def test_idempotent_transfer(client, make_account):
    a, b = make_account("100.00"), make_account()
    body = {
        "from_account_id": a,
        "to_account_id": b,
        "amount": "30",
        "idempotency_key": "xfer-0001",
    }
    first = client.post("/transactions/transfer", json=body).json()
    second = client.post("/transactions/transfer", json=body).json()
    assert first["transfer_id"] == second["transfer_id"]
    assert balance(client, a) == Decimal("70.00")
    assert balance(client, b) == Decimal("30.00")


def test_transaction_history(client, make_account):
    a = make_account("100.00")
    client.post("/transactions/withdrawal", json={"account_id": a, "amount": "1"})
    history = client.get(f"/accounts/{a}/transactions").json()
    assert [t["type"] for t in history] == ["withdrawal", "deposit"]  # newest first


def test_root_redirects_to_ui(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/ui"


def test_ui_page_served(client):
    r = client.get("/ui")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Banking Console" in r.text


def test_request_id_header(client):
    r = client.get("/health/live", headers={"x-request-id": "trace-123"})
    assert r.headers["x-request-id"] == "trace-123"
