"""
database.py — SQLite primary data store setup.

This module manages the durable primary store for the typeahead system.
SQLite is chosen because it's zero-ops, easy to inspect, and provides
durability that the in-memory Trie does not.

Tables:
  - queries: stores (query, count) pairs — the all-time search frequency data.
  - recent_searches: stores (query, hour_bucket, count) — hourly bucketed
    search counts used for trending/recency scoring.
"""

import sqlite3
import os

# Path to the SQLite database file, stored in the project's data/ directory.
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "database.db")


def get_connection() -> sqlite3.Connection:
    """
    Open and return a new SQLite connection.
    Uses Row factory so results can be accessed by column name (e.g., row['query']).
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Create the schema if it doesn't already exist.

    - queries: primary store for all-time query counts.
    - recent_searches: hourly buckets for recency-based trending calculations.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS queries (
            query TEXT PRIMARY KEY,
            count INTEGER NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recent_searches (
            query TEXT,
            hour_bucket TEXT,
            count INTEGER,
            PRIMARY KEY (query, hour_bucket)
        )
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
