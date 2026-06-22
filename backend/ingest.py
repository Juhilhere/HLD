"""
ingest.py — One-off data ingestion script.

Reads the raw dataset (count_1w.txt) which contains tab-separated
(word, frequency) pairs and loads them into the SQLite primary store.

Dataset: Google's corpus of English word unigram frequencies.
Each line is:  word<TAB>count
Example:       the     23135851162

Only alphabetic words are kept; numbers, punctuation, and empty
entries are skipped. This gives us 333,333 unique words — well
above the assignment's 100,000 minimum requirement.

Usage:
    cd backend
    python ingest.py
"""

import os
from database import get_connection, init_db

# Path to the raw dataset file.
INPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "count_1w.txt")


def ingest():
    """
    Parse count_1w.txt and bulk-insert (query, count) rows into
    the SQLite 'queries' table. Uses batch inserts (10,000 rows at
    a time) for performance.
    """
    # Ensure the database schema exists before inserting.
    init_db()

    conn = get_connection()
    cursor = conn.cursor()

    print(f"Reading from: {INPUT_FILE}")

    batch_size = 10000
    batch = []
    skipped = 0
    total = 0

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            trimmed = line.strip()
            if not trimmed:
                continue

            # Each line is tab-separated: word<TAB>count
            parts = trimmed.split('\t')
            if len(parts) != 2:
                skipped += 1
                continue

            word = parts[0].strip().lower()
            try:
                count = int(parts[1].strip())
            except ValueError:
                skipped += 1
                continue

            # Only keep purely alphabetic words (no numbers, hyphens, etc.)
            if len(word) == 0 or not word.isalpha():
                skipped += 1
                continue

            batch.append((word, count))
            total += 1

            # Flush in batches for performance.
            if len(batch) >= batch_size:
                cursor.executemany(
                    "INSERT OR REPLACE INTO queries (query, count) VALUES (?, ?)",
                    batch,
                )
                batch = []

    # Flush any remaining rows.
    if batch:
        cursor.executemany(
            "INSERT OR REPLACE INTO queries (query, count) VALUES (?, ?)",
            batch,
        )

    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM queries")
    db_count = cursor.fetchone()[0]
    conn.close()

    print(f"Ingestion complete. Total parsed: {total}, Skipped: {skipped}. DB rows: {db_count}")


if __name__ == "__main__":
    ingest()
