# HLD101 Assignment: Search Typeahead

Hey, this is my submission for the Search Typeahead assignment for HLD101. I built a full-stack typeahead system using React for the frontend and FastAPI for the backend. It's designed to suggest search queries as you type, and it handles caching, trending searches, and batch database writes.

## How it works (Architecture)

I used a React frontend that talks to a Python FastAPI backend.
Instead of querying a database for every letter typed, the backend loads all the words into an in-memory **Trie** (Prefix Tree) when it starts up. This makes finding suggestions crazy fast.

For caching, I set up 3 Redis nodes running in Docker. The backend uses a **Consistent Hashing Ring** to figure out which Redis node should cache which prefix. This way, if we add or remove a node, it doesn't break the whole cache.

When you submit a search, it doesn't write to the SQLite database right away (which would cause a bottleneck). Instead, an async batch writer queues up the queries and flushes them to the DB every 5 seconds in one single transaction.

## Setup Instructions

Make sure you have Docker installed. Then just run:
```bash
docker-compose up -d --build
```
This will automatically build and start the React frontend, FastAPI backend, and all 3 Redis cache nodes at once!

Then just open `http://localhost:5173` in your browser.

## API Endpoints

- `GET /suggest?q=<prefix>`: Returns the top 10 suggestions for whatever you're typing.
- `POST /search`: Submits a search (queues it for the batch writer).
- `GET /cache/debug?prefix=<x>`: A debugging endpoint to check which Redis node is caching a specific prefix.
- `GET /health`: Health check that also returns the total number of words loaded in the Trie.

## Design Choices & Trade-offs

- **Trie vs Binary Search**: I went with a Trie because it's way faster to grab all words matching a prefix compared to doing a binary search and then linearly scanning an array. The downside is that the Trie uses more memory.
- **Consistent Hashing**: Used this for the Redis cache so that we don't have a massive cache miss storm if a node goes down, which would happen if I just used normal modulo hashing.
- **Batch Writes**: SQLite is single-writer, so writing on every search request would kill performance. Batching every 5 seconds solves this. The trade-off is if the server crashes, we lose up to 5 seconds of analytics data, but for trending searches, that's fine.
- **Trending Searches**: I used a formula that combines all-time popularity (using a log function so it doesn't dominate) and recent popularity (using an exponential decay so older searches lose weight).

## Dataset

I used the **Google Web Corpus (`count_1w.txt`)**. It has about 333,333 English words with their frequencies.
