"""One-time migration: add the profile-dashboard columns to the existing
users table (bio, title, education, language, avatar_url, session_length,
preferred_content, learning_pace, preferred_difficulty, created_at).

SQLAlchemy's Base.metadata.create_all() never alters an existing table's
columns, and `users` already exists — run this once:

    python scripts/add_profile_columns.py

Safe to re-run — checks for each column before adding it. Existing users'
created_at is backfilled to "now" since their real signup date was never
recorded before this column existed; new users get their real timestamp
going forward.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app.db.database import engine  # noqa: E402

NEW_COLUMNS = [
    ("bio", "TEXT"),
    ("title", "VARCHAR"),
    ("education", "VARCHAR"),
    ("language", "VARCHAR"),
    ("avatar_url", "VARCHAR"),
    ("session_length", "VARCHAR"),
    ("preferred_content", "VARCHAR"),
    ("learning_pace", "VARCHAR"),
    ("preferred_difficulty", "VARCHAR"),
    ("created_at", "DATETIME"),
]


def migrate():
    with engine.connect() as conn:
        existing_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}

        for name, sql_type in NEW_COLUMNS:
            if name not in existing_columns:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {sql_type}"))
                print(f"Added users.{name}")
            else:
                print(f"users.{name} already exists, skipping.")

        if "created_at" not in existing_columns:
            conn.execute(text("UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
            print("Backfilled created_at = now for existing users (real signup date wasn't tracked before).")

        conn.commit()
    print("Migration complete.")


if __name__ == "__main__":
    migrate()