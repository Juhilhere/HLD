# Search Typeahead System

A distributed search typeahead (autocomplete) system built with Python (FastAPI), SQLite, Redis, and React. Suggests popular search queries as the user types, with sub-millisecond latency.

## Architecture

```
┌─────────────┐      GET /suggest       ┌──────────────────────────┐
│   React UI  │ ──────────────────────► │     FastAPI Backend      │
│  (Vite)     │ ◄────────────────────── │                          │
│             │      POST /search       │  ┌──────────────────┐   │
└─────────────┘                         │  │  In-Memory Trie  │   │
                                        │  │  (prefix index)  │   │
                                        │  └────────┬─────────┘   │
                                        │           │              │
                                        │  ┌────────▼─────────┐   │
                                        │  │ Consistent Hash  │   │
                                        │  │     Ring         │   │
                                        │  └──┬─────┬─────┬───┘   │
                                        └─────┼─────┼─────┼───────┘
                                              │     │     │
                                        ┌─────▼┐ ┌──▼──┐ ┌▼─────┐
                                        │Redis │ │Redis│ │Redis │
                                        │:6379 │ │:6380│ │:6381 │
                                        └──────┘ └─────┘ └──────┘
                                              │     │     │
                                        ┌─────▼─────▼─────▼──────┐
                                        │    SQLite Database      │
                                        │  (durable primary store)│
                                        └─────────────────────────┘
```

## Components

| Component | File | Purpose |
|---|---|---|
| **Data Ingestion** | `backend/ingest.py` | Parses `count_1w.txt` (333k words) into SQLite |
| **Database** | `backend/database.py` | SQLite schema and connection management |
| **Trie Index** | `backend/trie.py` | In-memory prefix tree for O(prefix) lookups |
| **Cache Layer** | `backend/cache.py` | Consistent hashing ring with 150 virtual nodes per Redis instance |
| **Batch Writer** | `backend/batch_writer.py` | Async queue + 5-second flush cycle for search submissions |
| **API Server** | `backend/main.py` | FastAPI server with all endpoints |
| **Frontend** | `frontend/src/App.tsx` | React UI with debounced typeahead |

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/suggest?q=<prefix>` | Returns top 10 suggestions sorted by blended score |
| `POST` | `/search` | Submits a search query (batched writes) |
| `GET` | `/cache/debug?prefix=<x>` | Shows which Redis node owns the prefix (HIT/MISS) |
| `GET` | `/health` | Health check with word count |

## Setup & Run

### Prerequisites
- Python 3.11+
- Node.js 18+
- Docker (for Redis)

### 1. Start Redis Cache Nodes
```bash
docker-compose up -d
```

### 2. Ingest Dataset
```bash
cd backend
python -m venv venv
source venv/bin/activate   # or .\venv\Scripts\activate on Windows
pip install -r requirements.txt
python ingest.py
```

### 3. Start Backend
```bash
cd backend
source venv/bin/activate
uvicorn main:app --port 8000
```

### 4. Start Frontend
```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser.

## Design Choices & Trade-offs

### Why Trie over sorted array + binary search?
A sorted array finds the start position in O(log N), but still needs to walk forward to collect all prefix matches. A Trie walks directly to the prefix node in O(|prefix|) and collects only the relevant subtree — optimal for typeahead where we need ALL words matching a prefix.

### Why Consistent Hashing over modular hashing?
With modular hashing (`key % N`), adding or removing a node remaps nearly ALL keys, causing a massive cache stampede. Consistent hashing maps keys and nodes onto a ring — when a node is added/removed, only ~1/N of keys get remapped.

### Why Batch Writes?
Writing to SQLite on every search request would bottleneck the server (SQLite is single-writer). Instead, searches are queued in memory and flushed every 5 seconds in a single transaction. Trade-off: if the server crashes, up to 5 seconds of search data is lost — acceptable for frequency analytics (eventual consistency).

### Trending Ranking Formula
```
score = α * log(total_count + 1) + β * recency_score
```
- `α = 1.0`: weight for historical popularity (log-scaled to prevent domination)
- `β = 0.5`: weight for recent activity (exponentially decayed over 24h)
- Decay: `weight(hour_i) = e^(-0.173 * i)` — halves every ~4 hours

This ensures historically popular words stay relevant while recent spikes get a temporary boost.

### Cache Invalidation
When the batch writer flushes new search data and updates the Trie, the updated suggestions will be served on the next cache miss (after the 60-second TTL expires). For an assignment scope, this staleness window is acceptable.

## Dataset

**Google Web Corpus (count_1w.txt)** — 333,333 English word unigrams with frequency counts from Google's web crawl data. Each line contains a word and its occurrence count, tab-separated.
