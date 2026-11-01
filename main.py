import asyncio
import os
from datetime import datetime, timezone

import psycopg
from fastapi import BackgroundTasks, FastAPI, HTTPException, Response
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    source_account TEXT NOT NULL,
    destination_account TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ
)
"""


class TransactionIn(BaseModel):
    transaction_id: str = Field(min_length=1)
    source_account: str = Field(min_length=1)
    destination_account: str = Field(min_length=1)
    amount: float
    currency: str = Field(min_length=1)


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise HTTPException(status_code=500, detail="database unavailable")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


def connect():
    conn = psycopg.connect(database_url(), connect_timeout=5, row_factory=dict_row)
    try:
        conn.execute(SCHEMA)
        conn.commit()
    except Exception:
        conn.close()
        raise
    return conn


def iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def json_amount(value) -> int | float:
    number = float(value)
    if number.is_integer():
        return int(number)
    return number


def row_payload(row: dict) -> dict:
    return {
        "transaction_id": row["transaction_id"],
        "source_account": row["source_account"],
        "destination_account": row["destination_account"],
        "amount": json_amount(row["amount"]),
        "currency": row["currency"],
        "status": row["status"],
        "created_at": iso_z(row["created_at"]),
        "processed_at": iso_z(row["processed_at"]),
    }


def mark_processed(transaction_id: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE transactions
            SET status = 'PROCESSED', processed_at = %s
            WHERE transaction_id = %s AND status = 'PROCESSING'
            """,
            (datetime.now(timezone.utc), transaction_id),
        )
        conn.commit()


async def process_transaction(transaction_id: str) -> None:
    try:
        await asyncio.sleep(30)
        await asyncio.to_thread(mark_processed, transaction_id)
    except Exception as exc:
        print(f"processing failed for {transaction_id}: {type(exc).__name__}")


@app.get("/")
def health():
    return {
        "status": "HEALTHY",
        "current_time": iso_z(datetime.now(timezone.utc)),
    }


@app.post("/v1/webhooks/transactions", status_code=202)
def accept_webhook(body: TransactionIn, background_tasks: BackgroundTasks):
    try:
        with connect() as conn:
            inserted = conn.execute(
                """
                INSERT INTO transactions (
                    transaction_id,
                    source_account,
                    destination_account,
                    amount,
                    currency,
                    status,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, 'PROCESSING', %s)
                ON CONFLICT (transaction_id) DO NOTHING
                RETURNING transaction_id
                """,
                (
                    body.transaction_id,
                    body.source_account,
                    body.destination_account,
                    body.amount,
                    body.currency,
                    datetime.now(timezone.utc),
                ),
            ).fetchone()
            conn.commit()
    except psycopg.Error:
        raise HTTPException(status_code=500, detail="database unavailable") from None

    if inserted:
        background_tasks.add_task(process_transaction, body.transaction_id)
    return Response(status_code=202)


@app.get("/v1/transactions/{transaction_id}")
def get_transaction(transaction_id: str):
    try:
        with connect() as conn:
            row = conn.execute(
                """
                SELECT
                    transaction_id,
                    source_account,
                    destination_account,
                    amount,
                    currency,
                    status,
                    created_at,
                    processed_at
                FROM transactions
                WHERE transaction_id = %s
                """,
                (transaction_id,),
            ).fetchone()
    except psycopg.Error:
        raise HTTPException(status_code=500, detail="database unavailable") from None

    if row is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    return [row_payload(row)]
