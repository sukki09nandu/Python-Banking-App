# Banking API

A small FastAPI banking transaction service for the AWS Cloud Engineer / DevOps
lab assignment. It uses **synthetic data only**.

## How to run the application

You need **Docker** (for the PostgreSQL database) and **Python 3.12 or newer**.
Run all commands in a Linux/WSL terminal.

### First-time setup (do this once)

**1. Install Python's virtual-environment support** (Ubuntu/WSL only; skip it if already installed)

```bash
sudo apt install python3-venv
```

**2. Create the database container**

```bash
docker run -d --name bank-pg -p 5432:5432 \
  -e POSTGRES_PASSWORD=localdevonly -e POSTGRES_DB=banking \
  postgres:17-alpine
```

> `localdevonly` is a throwaway password for your laptop only. Never use it anywhere else.

**3. Create a Python environment and install the dependencies**

```bash
cd ~/Python-Banking-App
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Next, start the app as described in the following section.

### Start the app (every time)

**1. Start the database** (it is stopped after a reboot)

```bash
docker start bank-pg
```

**2. Go to the project and activate Python**

```bash
cd ~/Python-Banking-App
source .venv/bin/activate
```

**3. Start the app**

```bash
export DATABASE_URL=postgresql+psycopg://postgres:localdevonly@localhost:5432/banking
export SEED_DEMO_DATA=true
uvicorn app.main:app --reload
```

Wait until you see `Application startup complete`. **Keep this terminal open.**
Closing it stops the app.

**4. Open the browser**

| URL | What you get |
|---|---|
| http://127.0.0.1:8000 | **Banking Console** (web UI) |
| http://127.0.0.1:8000/docs | Interactive API docs |
| http://127.0.0.1:8000/health | Health check, which should show `"database":"ok"` |
| http://127.0.0.1:8000/customers | Raw list of all customers (JSON) |
| http://127.0.0.1:8000/accounts | Raw list of all accounts (JSON) |
| http://127.0.0.1:8000/accounts/1/transactions | History of account 1 (change the number) |

### Using the web UI

1. **Add a customer:** fill in *Full name* and *Email* on the left, then click **Add customer**.
2. **Open an account:** with the customer selected, pick a type and currency, then click **Open account**.
3. **Move money:** choose **Deposit**, **Withdraw**, or **Transfer**, enter an amount, then submit.
4. **Check the history:** the *Transactions* table shows every movement on the selected account.

The badge at the top should be green: **healthy · db ok**.

### Using the API docs (`/docs`)

1. Click an endpoint, e.g. **GET /customers**.
2. Click **Try it out**, then **Execute**.
3. Read the real data under **Server response**.

> The **Responses → Example Value** box further down is only a template that shows the
> response format (`"string"`, `0`, ...). It never shows your data.

### Stop the app

- Press **Ctrl + C** in the terminal that is running `uvicorn`.
- Optionally stop the database with `docker stop bank-pg`. Your data is kept, and `docker start bank-pg` brings it back.

### Start over with an empty database

This **deletes all customers, accounts, and transactions**:

```bash
docker rm -f bank-pg
```

Then repeat **First-time setup → step 2**. The next app start re-creates the 3 demo customers.

### Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| Browser says "can't reach this page" | The app isn't running | Do *Start the app*, steps 2–3 |
| Red **unhealthy** badge, or `/health` returns 503 | The database isn't running, or `DATABASE_URL` isn't set | `docker start bank-pg`, then restart the app with step 3 |
| `{"detail":"Not Found"}` | Wrong URL | Use one of the URLs in the table above |
| `uvicorn: command not found` | The Python environment isn't activated | `source .venv/bin/activate` |
| `address already in use` (port 8000) | The app is already running in another terminal | Use that one, or stop it with Ctrl + C |
| `port is already allocated` (5432) | Another PostgreSQL is using port 5432 | Stop it, or use `-p 5433:5432` and `localhost:5433` in `DATABASE_URL` |
| `Conflict. The container name "/bank-pg" is already in use` | The database was already created | Skip setup step 2 and just run `docker start bank-pg` |

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET  | `/health/live` | Liveness: the process is up. Does not touch the DB. |
| GET  | `/health/ready`, `/health` | Readiness: the DB is reachable and the schema is ready. Returns 503 otherwise. |
| POST | `/customers` | Create a customer `{full_name, email}` |
| GET  | `/customers`, `/customers/{id}` | List or get customers |
| POST | `/accounts` | Open an account `{customer_id, account_type?, currency?}` |
| GET  | `/accounts?customer_id=`, `/accounts/{id}` | List or get accounts |
| GET  | `/accounts/{id}/transactions` | Transaction history, newest first |
| POST | `/transactions/deposit` | `{account_id, amount, description?, idempotency_key?}` |
| POST | `/transactions/withdrawal` | same body as deposit |
| POST | `/transactions/transfer` | `{from_account_id, to_account_id, amount, description?, idempotency_key?}` |

Interactive docs are at `/docs`.

## Web UI

Open **http://127.0.0.1:8000/** in a browser; it redirects to `/ui`. The page is served
by the same FastAPI app and calls the JSON API above. It has no external scripts or
fonts. From the UI you can:

- add customers and open checking or savings accounts in USD, EUR, or GBP
- deposit, withdraw, and transfer between any two accounts in the same currency (each submit gets an idempotency key)
- view the transaction history and live balances
- see API errors such as insufficient funds or a duplicate email as red notifications
- check service health in the header; it polls `/health` every 15 seconds

## Safe transaction handling

- Amounts are `Decimal` values stored as `NUMERIC(18,2)`. Each amount must be greater than 0, have at most 2 decimal places, and be no more than 1,000,000.00.
- Rows are locked with `SELECT ... FOR UPDATE` in ascending id order. This prevents double-spending and deadlocks.
- Balances can never go negative. The app checks this, and a DB `CHECK` constraint enforces it too.
- A transfer commits both the debit and the credit, or neither.
- An `idempotency_key` makes retries safe. Replaying a key returns the original transaction.
- Requests with unknown fields are rejected (422). Duplicate emails, insufficient funds, and inactive accounts return 409.

## Configuration (environment variables)

| Variable | Use |
|---|---|
| `DATABASE_URL` | Local/dev only, e.g. `postgresql+psycopg://user:pass@localhost:5432/banking` |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_SSLMODE` | AWS: RDS endpoint (non-secret; from a ConfigMap) |
| `DB_SECRET_ARN`, `AWS_REGION` | AWS: Secrets Manager secret holding `{"username","password"}` (the RDS-managed secret format) |
| `SEED_DEMO_DATA` | `true` loads 3 synthetic customers |
| `LOG_LEVEL`, `ENVIRONMENT` | Logging and labels |

In AWS no credentials are passed to the app. It receives only the secret ARN and
reads the secret with its IAM role. Credentials are re-read for each new connection
(cached for 5 minutes), so RDS secret rotation does not need a restart. If
Secrets Manager or the DB is unavailable, the pod stays live but reports
**not ready**, and it logs the cause (for example `AccessDeniedException`).

Logs are JSON lines on stdout with `request_id`, `path`, `status`, and `duration_ms`.
Request bodies are never logged.

## Test

```bash
pytest -q          # 26 tests, uses a temporary SQLite DB
ruff check . && ruff format --check .
```

Browser (end-to-end) tests drive the UI in headless Chromium. They need only Docker:

```bash
./e2e/run.sh       # fresh Postgres + app + Playwright; 11 UI tests; screenshots in e2e/screenshots/
```

They cover page load and health, creating a customer, the duplicate-email error,
opening an account, deposit, withdrawal, overdraft rejection, invalid-amount
blocking, a transfer with the recipient's balance checked, and the mobile layout.

Sample calls:

```bash
curl localhost:8000/health
curl -X POST localhost:8000/customers -H 'content-type: application/json' \
     -d '{"full_name":"Test User","email":"test@example.com"}'
curl -X POST localhost:8000/accounts -H 'content-type: application/json' -d '{"customer_id":1}'
curl -X POST localhost:8000/transactions/deposit -H 'content-type: application/json' \
     -d '{"account_id":1,"amount":"100.00","idempotency_key":"dep-0001"}'
curl -X POST localhost:8000/transactions/transfer -H 'content-type: application/json' \
     -d '{"from_account_id":1,"to_account_id":2,"amount":"25.50"}'
```

## Layout

```
app/
  main.py          app factory, JSON logging, request-id/access-log middleware
  config.py        env-based settings
  db.py            engine, Secrets Manager credential injection, health ping
  models.py        Customer, Account, Transaction
  schemas.py       request/response validation
  services.py      business logic (locking, idempotency, atomic transfers)
  seed.py          synthetic demo data
  routers/         health, customers, accounts, transactions
tests/test_api.py
```

Schema creation uses `create_all` on startup, which is fine for this lab. A production
service would use Alembic migrations.
