"""
batch_writer.py — Asynchronous batch writer for search-count updates.

Problem:
  If we write to SQLite on every single POST /search request, the database
  becomes a bottleneck under high load (SQLite is single-writer).

Solution:
  Instead of writing immediately, POST /search pushes the query into an
  in-memory asyncio.Queue. A background coroutine wakes up every 5 seconds,
  drains the queue, aggregates duplicate queries, and writes them to SQLite
  in a single transaction. This reduces N individual writes to ~1 batch write.

Trade-off (important for viva):
  If the server crashes before a flush, the queries in the 5-second window
  are lost. This is acceptable for search frequency analytics (eventual
  consistency) — in production, you'd mitigate with a WAL or more
  frequent flushes.

Trending / Recency:
  Each flush also records search counts in hourly time buckets
  (recent_searches table). These buckets are used to calculate an
  exponentially decayed recency score, which is then pushed into the
  Trie to influence suggestion rankings.
"""

import asyncio
import math
from collections import defaultdict
from datetime import datetime, timedelta

from database import get_connection


class BatchWriter:
    """
    Collects search queries in an async queue and periodically
    flushes them to SQLite in batches.
    """

    # How often the background worker wakes up to flush (seconds).
    FLUSH_INTERVAL_SECONDS = 5

    # Exponential decay constant for recency scoring.
    # With 0.173, the weight halves roughly every 4 hours.
    DECAY_LAMBDA = 0.173

    # How many hours of recent data to consider for trending.
    RECENCY_WINDOW_HOURS = 24

    def __init__(self, trie=None):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.trie = trie  # reference to the in-memory Trie (set at startup)

    async def add(self, query: str):
        """
        Enqueue a search query for later batch processing.
        Called by POST /search — returns immediately (non-blocking).
        """
        await self.queue.put(query.lower())

    async def flush_loop(self):
        """
        Background coroutine that runs forever, flushing the queue
        every FLUSH_INTERVAL_SECONDS.
        """
        while True:
            await asyncio.sleep(self.FLUSH_INTERVAL_SECONDS)
            await self._flush()

    def _calculate_recency_score(self, cursor, query: str) -> float:
        """
        Calculate an exponentially decayed recency score by looking
        at hourly search buckets over the last 24 hours.

        Recent hours are weighted much more heavily than older ones:
          weight(hour_i) = e^(-λ * i)

        Example weights: hour 0 = 1.0, hour 4 ≈ 0.5, hour 8 ≈ 0.25
        """
        score = 0.0
        now = datetime.utcnow()

        for i in range(self.RECENCY_WINDOW_HOURS):
            bucket_time = now - timedelta(hours=i)
            bucket_str = bucket_time.strftime("%Y-%m-%d %H:00")

            cursor.execute(
                "SELECT count FROM recent_searches WHERE query = ? AND hour_bucket = ?",
                (query, bucket_str),
            )
            row = cursor.fetchone()

            if row:
                decay = math.exp(-self.DECAY_LAMBDA * i)
                score += row['count'] * decay

        return score

    async def _flush(self):
        """
        Drain the queue, aggregate duplicate queries, and write
        everything to SQLite in a single transaction.
        """
        if self.queue.empty():
            return

        # Drain all pending queries from the queue.
        queries_batch = []
        while not self.queue.empty():
            try:
                queries_batch.append(self.queue.get_nowait())
                self.queue.task_done()
            except asyncio.QueueEmpty:
                break

        # Aggregate: if "apple" was searched 10 times, store {"apple": 10}
        # instead of 10 individual writes.
        counts: dict = defaultdict(int)
        for q in queries_batch:
            counts[q] += 1

        hour_bucket = datetime.utcnow().strftime("%Y-%m-%d %H:00")

        conn = get_connection()
        cursor = conn.cursor()

        for query, count in counts.items():
            # --- Update all-time count in the 'queries' table ---
            cursor.execute("SELECT count FROM queries WHERE query = ?", (query,))
            row = cursor.fetchone()

            if row:
                new_count = row['count'] + count
                cursor.execute("UPDATE queries SET count = ? WHERE query = ?", (new_count, query))
            else:
                new_count = count
                cursor.execute("INSERT INTO queries (query, count) VALUES (?, ?)", (query, new_count))

            # --- Update hourly bucket in 'recent_searches' table ---
            cursor.execute(
                "SELECT count FROM recent_searches WHERE query = ? AND hour_bucket = ?",
                (query, hour_bucket),
            )
            recent_row = cursor.fetchone()

            if recent_row:
                new_recent = recent_row['count'] + count
                cursor.execute(
                    "UPDATE recent_searches SET count = ? WHERE query = ? AND hour_bucket = ?",
                    (new_recent, query, hour_bucket),
                )
            else:
                cursor.execute(
                    "INSERT INTO recent_searches (query, hour_bucket, count) VALUES (?, ?, ?)",
                    (query, hour_bucket, count),
                )

            # --- Update the in-memory Trie with the new count + recency ---
            if self.trie:
                recency_score = self._calculate_recency_score(cursor, query)
                self.trie.insert(query, new_count, recency_score)

        conn.commit()
        conn.close()

        print(f"[batch_writer] Flushed {len(queries_batch)} searches ({len(counts)} unique queries)")


# Module-level singleton (trie reference is set at app startup in main.py).
batch_writer = BatchWriter()
