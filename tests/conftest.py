import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}", environment="test")
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def make_account(client):
    counter = {"n": 0}

    def _make(balance: str | None = None, currency: str = "USD") -> int:
        counter["n"] += 1
        cust = client.post(
            "/customers",
            json={
                "full_name": f"Test User {counter['n']}",
                "email": f"u{counter['n']}@example.com",
            },
        ).json()
        acct = client.post(
            "/accounts", json={"customer_id": cust["id"], "currency": currency}
        ).json()
        if balance:
            r = client.post(
                "/transactions/deposit", json={"account_id": acct["id"], "amount": balance}
            )
            assert r.status_code == 201, r.text
        return acct["id"]

    return _make
