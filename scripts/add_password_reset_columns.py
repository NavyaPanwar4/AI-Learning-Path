"""One-time migration: add reset_token / reset_token_expires columns to the
existing users table for the forgot-password feature.

Run once:  python scripts/add_password_reset_columns.py
Safe to re-run.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402
from app.db.database import engine  # noqa: E402


def migrate():
    with engine.connect() as conn:
        existing_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}

        if "reset_token" not in existing_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN reset_token VARCHAR"))
            print("Added users.reset_token")
        else:
            print("users.reset_token already exists, skipping.")

        if "reset_token_expires" not in existing_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN reset_token_expires DATETIME"))
            print("Added users.reset_token_expires")
        else:
            print("users.reset_token_expires already exists, skipping.")

        conn.commit()
    print("Migration complete.")


if __name__ == "__main__":
    migrate()