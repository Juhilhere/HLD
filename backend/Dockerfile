FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy backend and data (needed for ingest.py)
COPY backend/ ./backend/
COPY data/ ./data/

WORKDIR /app/backend

# Ingest data to create SQLite DB, then start the server
CMD ["sh", "-c", "python ingest.py && uvicorn main:app --host 0.0.0.0 --port 8000"]
