"""Minimal, explicit SQL migration runner.

Applies every .sql file in migrations/versions/ in filename order, exactly
once, inside a transaction, tracking applied files in schema_migrations.

Usage:
    python -m migrations.run_migrations          # apply pending migrations
    python -m migrations.run_migrations --check  # verify DB reaches + extension
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

from app.config import get_settings
from app.database import get_engine

MIGRATIONS_DIR = Path(__file__).parent / "versions"

TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def applied_migrations(engine) -> set[str]:
    with engine.connect() as conn:
        conn.execute(text(TRACKING_TABLE))
        conn.commit()
        rows = conn.execute(text("SELECT filename FROM schema_migrations")).fetchall()
    return {row[0] for row in rows}


def run_migrations(engine, embedding_dim: int | None = None) -> list[str]:
    from app.config import get_settings

    dim = embedding_dim or get_settings().embedding_dim
    applied = applied_migrations(engine)
    pending = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql") if p.name not in applied)
    for filename in pending:
        sql = (MIGRATIONS_DIR / filename).read_text(encoding="utf-8")
        # The vector column dimension follows the configured embedding model.
        sql = sql.replace("{EMBEDDING_DIM}", str(dim))
        with engine.begin() as conn:
            conn.execute(text(TRACKING_TABLE))
            conn.execute(text(sql))
            conn.execute(
                text("INSERT INTO schema_migrations (filename) VALUES (:f)"), {"f": filename}
            )
        print(f"applied: {filename} (embedding_dim={dim})")
    if not pending:
        print("migrations up to date")
    return pending


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply SQL migrations")
    parser.add_argument("--check", action="store_true", help="only verify connectivity + pgvector")
    args = parser.parse_args()

    settings = get_settings()
    engine = get_engine(settings)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            conn.execute(text("SELECT '[0,0]'::vector"))
    except Exception as exc:  # noqa: BLE001 — report a single clear blocker
        print(f"database check FAILED: {exc.__class__.__name__}", file=sys.stderr)
        # Show the real cause (host/port/auth) — psycopg messages never
        # include the password, so this is safe to print in CI/PAAS logs.
        print(f"detail: {exc}", file=sys.stderr)
        print(
            "Ensure PostgreSQL with the pgvector extension is running and DATABASE_URL is correct\n"
            "(docker compose up -d db).",
            file=sys.stderr,
        )
        return 1

    if args.check:
        print("database OK (pgvector available)")
        return 0
    run_migrations(engine)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
