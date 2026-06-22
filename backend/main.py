"""
main.py — FastAPI application entry point.

This is the main server file for the Search Typeahead System.
It wires together:
  - The SQLite primary store (database.py)
  - The in-memory Trie index (trie.py)
  - The distributed Redis cache with consistent hashing (cache.py)
  - The async batch writer for search submissions (batch_writer.py)

API Endpoints:
  GET  /suggest?q=<prefix>       — returns top-10 typeahead suggestions
  POST /search                    — submits a search query (batched writes)
  GET  /cache/debug?prefix=<x>   — shows which Redis node owns a prefix
  GET  /health                    — health check with word count
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import time
import json

from trie import Trie
from cache import cache_ring
from batch_writer import batch_writer
from database import get_connection


# ---------------------------------------------------------------------------
# Application Lifespan — load data on startup, clean up on shutdown
# ---------------------------------------------------------------------------

trie = Trie()
batch_writer.trie = trie  # give the batch writer a reference to the Trie


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    On startup: load the Trie from SQLite and start the batch writer.
    On shutdown: (nothing special needed for an assignment).
    """
    # --- Load the Trie from the SQLite primary store ---
    print("[startup] Loading Trie from SQLite...")
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT query, count FROM queries")
    for row in cursor.fetchall():
        trie.insert(row['query'], row['count'], 0.0)

    # Load any existing recency data.
    cursor.execute(
        "SELECT query, SUM(count) as recent_count FROM recent_searches GROUP BY query"
    )
    for row in cursor.fetchall():
        trie.update_recency(row['query'], float(row['recent_count']))

    conn.close()
    print(f"[startup] Loaded {trie.size} words into Trie.")

    # --- Start the background batch writer loop ---
    flush_task = asyncio.create_task(batch_writer.flush_loop())
    print("[startup] Batch writer started (flushes every 5 seconds).")

    yield  # App is now running and serving requests.

    # --- Shutdown cleanup ---
    flush_task.cancel()


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Search Typeahead API",
    description="Distributed typeahead system with Trie, Redis consistent hashing, and batch writes.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# GET /suggest — Typeahead Suggestions
# ---------------------------------------------------------------------------

@app.get("/suggest")
async def suggest(q: str = ""):
    """
    Return up to 10 typeahead suggestions for the given prefix.

    Flow:
      1. Normalize the prefix (lowercase, strip whitespace).
      2. If prefix is empty, return top trending results from the Trie directly
         (used for the "Trending Searches" UI section).
      3. Otherwise, check the distributed Redis cache (cache-aside pattern):
         a. Hash the prefix → pick the responsible Redis node.
         b. On cache HIT: return cached results.
         c. On cache MISS: compute from Trie, cache with 60s TTL, return.
    """
    start_time = time.perf_counter()
    prefix = q.lower().strip()

    # Empty prefix: return globally top-scored words (trending).
    # We skip the cache for empty prefix since it changes frequently.
    if not prefix:
        results = trie.suggest("", limit=10)
        ms = round((time.perf_counter() - start_time) * 1000, 3)
        return {"q": prefix, "ms": ms, "results": results, "source": "trie"}

    # --- Cache-aside pattern with consistent hashing ---
    cache_client = cache_ring.get_client(prefix)
    cache_key = f"suggest:{prefix}"

    # Try to read from the assigned Redis node.
    if cache_client:
        try:
            cached = cache_client.get(cache_key)
            if cached:
                results = json.loads(cached)
                ms = round((time.perf_counter() - start_time) * 1000, 3)
                return {"q": prefix, "ms": ms, "results": results, "source": "cache"}
        except Exception:
            pass  # Redis down — fall through to Trie (graceful degradation).

    # Cache miss — compute from Trie.
    results = trie.suggest(prefix, limit=10)

    # Write back to the assigned Redis node with a 60-second TTL.
    if cache_client:
        try:
            cache_client.setex(cache_key, 60, json.dumps(results))
        except Exception:
            pass  # Redis down — still return results from Trie.

    ms = round((time.perf_counter() - start_time) * 1000, 3)
    return {"q": prefix, "ms": ms, "results": results, "source": "trie"}


# ---------------------------------------------------------------------------
# POST /search — Search Submission (with batch writes)
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str


@app.post("/search")
async def search(req: SearchRequest):
    """
    Submit a search query. Returns a dummy response immediately.

    The query is NOT written to SQLite synchronously — instead it's
    pushed onto an async queue. The batch writer background task
    aggregates and flushes these every 5 seconds (see batch_writer.py).
    """
    query = req.query.strip().lower()
    if query:
        await batch_writer.add(query)
    return {"message": "Searched"}


# ---------------------------------------------------------------------------
# GET /cache/debug — Cache Routing Debug Endpoint
# ---------------------------------------------------------------------------

@app.get("/cache/debug")
async def cache_debug(prefix: str):
    """
    Debug endpoint that shows which Redis node is responsible for a prefix
    and whether the cached entry currently exists (HIT) or not (MISS).

    Useful for demonstrating that consistent hashing distributes keys
    across different nodes.
    """
    prefix = prefix.lower().strip()
    node_name = cache_ring.get_node_name(prefix)
    cache_client = cache_ring.get_client(prefix)

    status = "MISS"
    if cache_client:
        try:
            if cache_client.exists(f"suggest:{prefix}"):
                status = "HIT"
        except Exception as e:
            status = f"ERROR: {e}"

    return {
        "prefix": prefix,
        "node": node_name,
        "status": status,
    }


# ---------------------------------------------------------------------------
# GET /health — Health Check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Health check endpoint returning the number of words in the Trie."""
    return {"ok": True, "words": trie.size}
