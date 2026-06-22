# Project Report: Search Typeahead System

**Course:** HLD101
**Assignment:** Search Typeahead

---

### 1. Architecture Explanation
For this assignment, I built a full-stack system using React for the frontend and FastAPI (Python) for the backend. 

When a user types in the search bar on the React frontend, it sends a GET request to the backend. But instead of sending a request on every single keystroke, I added a 300ms debounce so it doesn't overload the server. 

On the backend, the core data structure is an in-memory Trie (Prefix Tree). When the server starts, it loads all the words from a SQLite database into this Trie. I also added a caching layer using Redis. To simulate a distributed system, I'm running 3 separate Redis nodes using Docker Compose on different ports (6379, 6380, 6381). The backend uses Consistent Hashing (with 150 virtual nodes) to figure out which Redis instance should store the cached results for a specific prefix.

When you submit a search query via POST, it doesn't write to the database immediately. I implemented a batch writer that queues up the searches and flushes them to SQLite every 5 seconds. This prevents the database from locking up under heavy load.

### 2. Dataset Source and Loading Instructions
I used the Google Web Corpus dataset (`count_1w.txt`), which has about 333,333 common English words and their frequencies. 

**How to load it:**
1. Make sure the `count_1w.txt` file is inside the `data/raw/` folder.
2. Go into the `backend` folder and activate your virtual environment.
3. Run `python ingest.py`. 
This script reads the text file line by line and inserts everything into the SQLite database. It takes a couple of seconds to run. Once it's done, you can start the FastAPI server with `uvicorn main:app` and it will automatically load the data from the DB into the Trie.

### 3. API Documentation

Here are the endpoints I created:

- **`GET /suggest?q=<prefix>`**
  This is the main endpoint used for the typeahead. You pass what the user is typing as the `q` query parameter. If `q` is empty, it returns the top trending searches. It returns a JSON object with the suggestions, the time it took to process (`ms`), and whether it came from the `cache` or the `trie`.

- **`POST /search`**
  You send a JSON body like `{ "query": "apple" }` to this endpoint when the user actually submits a search. It just returns `{ "message": "Searched" }` instantly while queuing the query for the batch writer in the background.

- **`GET /cache/debug?prefix=<prefix>`**
  I made this endpoint so you can test if the consistent hashing is working. It tells you exactly which Redis node (e.g. localhost:6380) is responsible for caching that specific prefix and whether there's a cache hit or miss.

- **`GET /health`**
  Just a simple health check to make sure the server is up and the Trie is loaded. It returns something like `{ "ok": true, "words": 333333 }`.

### 4. Design Choices and Trade-offs

**Why a Trie?**
I chose to build a Trie instead of just sorting an array and using binary search. Binary search is fast to find the starting point, but you still have to scan linearly to get all the matches. A Trie goes straight to the prefix node and the subtree has exactly the words you need. The trade-off is that the Trie uses more RAM because of all the node objects and pointers.

**Consistent Hashing vs Normal Modulo**
I used consistent hashing for the Redis cache. If I just did `hash(prefix) % 3` and one of the Redis nodes went down, the modulo logic would change for almost every key, meaning a total cache miss storm. Consistent hashing fixes this by putting nodes on a hash ring, so adding or removing a node only moves a fraction of the keys. 

**Batching Writes**
Since SQLite only allows one writer at a time, calling `INSERT` on every search request would be a huge bottleneck. So I used an `asyncio.Queue`. Searches get aggregated in memory (e.g. 10 searches for "apple" become just one "+10" database update) and flushed every 5 seconds. The trade-off is data loss: if the server crashes, we lose up to 5 seconds of search analytics. But for a feature like trending searches, eventual consistency is totally fine.

**Trending Formula**
For the trending logic, I calculate the score like this: `Score = log(total_count) + (decay_factor * recency_count)`. I put the all-time count in a log function so that historically popular words don't permanently drown out new trends. The recency score uses exponential decay over 24 hours, so older searches lose their weight over time.

### 5. Performance Report
The performance is pretty solid. The primary store has 333,333 words. 
When testing the API:
- If there's a **Cache Hit**, the Redis node returns the suggestions in less than 5ms. 
- If there's a **Cache Miss**, the backend has to traverse the Trie. For very short prefixes (like 1 or 2 letters) it can take around 150-200ms because the subtree is massive. But for longer prefixes (4+ letters), it drops down to 10-20ms.

The 300ms debounce on the React frontend helps immensely, cutting down the number of requests hitting the server by a lot. The Redis caching also means that no matter how many users type the exact same thing, the Trie only has to do the heavy lifting once every 60 seconds (the TTL I set for the cache).
