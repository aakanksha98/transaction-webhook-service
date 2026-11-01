# Transaction webhook service

A Python service that accepts payment transaction webhooks, responds immediately, and finishes processing in the background.

## Endpoints

| Method | Path | Behavior |
|---|---|---|
| `GET` | `/` | Returns `HEALTHY` and the current UTC time |
| `POST` | `/v1/webhooks/transactions` | Stores the transaction and returns `202` |
| `GET` | `/v1/transactions/{transaction_id}` | Returns the stored transaction in a one-element array |

`POST` body:

```json
{
  "transaction_id": "txn_abc123def456",
  "source_account": "acc_user_789",
  "destination_account": "acc_merchant_456",
  "amount": 1500,
  "currency": "INR"
}
```

The same `transaction_id` can be posted again. The service still returns `202` and does not process that transaction a second time.

About 30 seconds after the first accepted webhook, the status becomes `PROCESSED` and `processed_at` is set. Until then the status is `PROCESSING` and `processed_at` is `null`.

## Technical choices

- FastAPI, deployed as one Vercel Python function.
- Postgres, reached through `DATABASE_URL`. The app creates the `transactions` table if it is missing. `transaction_id` is the primary key, so concurrent duplicate webhooks still produce one row.
- The 30-second wait runs in a FastAPI background task after the `202` is sent. `vercel.json` allows that invocation to run for 60 seconds.
- `DATABASE_URL` is read from the environment. It is not stored in this repository.

## Run locally

Use Python 3.12 or newer.

```bash
python -m venv .venv
```

Windows:

```powershell
.venv\Scripts\pip install -r requirements.txt
$env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DB?sslmode=require"
.venv\Scripts\uvicorn main:app --port 8000
```

macOS or Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql://USER:PASSWORD@HOST/DB?sslmode=require"
uvicorn main:app --port 8000
```

Use a hosted Postgres database. Copy `.env.example` to `.env` for local convenience. `.env` is gitignored.

## Test

```bash
curl http://127.0.0.1:8000/
```

```bash
curl -i -X POST http://127.0.0.1:8000/v1/webhooks/transactions \
  -H "Content-Type: application/json" \
  -d "{\"transaction_id\":\"txn_abc123def456\",\"source_account\":\"acc_user_789\",\"destination_account\":\"acc_merchant_456\",\"amount\":1500,\"currency\":\"INR\"}"
```

The response is `202` with an empty body. Repeat that request. It returns `202` again.

```bash
curl http://127.0.0.1:8000/v1/transactions/txn_abc123def456
```

Right away, `status` is `PROCESSING`. After about 30 seconds, the same request shows `PROCESSED`.

## Deploy

Connect this repository to a Vercel project. Set `DATABASE_URL` in the Vercel project environment, using the provider's pooled connection string with `sslmode=require`. Do not commit that value.

The function entry is `main.py`. Vercel detects FastAPI from `requirements.txt`.
