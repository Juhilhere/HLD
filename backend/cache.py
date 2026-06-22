"""
cache.py — Distributed cache layer using Consistent Hashing.

This module implements a consistent hashing ring that distributes
cache keys across 3 independent Redis nodes. This is the core
"distributed cache with consistent hashing" requirement from the rubric.

Why Consistent Hashing?
  - Simple modular hashing (key % N) breaks when nodes are added/removed:
    nearly ALL keys get remapped, causing a cache stampede.
  - Consistent hashing maps both keys and nodes onto a circular ring.
    When a node is added/removed, only ~1/N of the keys get remapped.

Virtual Nodes:
  - Without virtual nodes, 3 physical nodes could get very uneven
    key distribution (one node might own 60% of the ring by chance).
  - We create 150 virtual nodes per physical node, spreading each
    node's responsibility evenly around the ring.
  - This ensures near-uniform key distribution across all 3 nodes.

Architecture:
  - 3 Redis containers run via Docker Compose on ports 6379, 6380, 6381.
  - When /suggest receives a prefix, we hash it, walk the ring clockwise,
    and route the cache read/write to the responsible Redis node.
"""

import hashlib
import bisect
from typing import Dict, List, Optional

import redis


class ConsistentHashingRing:
    """
    A consistent hashing ring with virtual nodes for even key distribution.
    """

    def __init__(self, nodes: List[dict], virtual_nodes: int = 150):
        """
        Args:
            nodes: List of {"host": str, "port": int} dicts for each Redis node.
            virtual_nodes: Number of virtual nodes per physical node.
                           Higher = more even distribution, but more memory.
                           150 is a good balance for 3 nodes.
        """
        self.virtual_nodes = virtual_nodes
        self.ring: Dict[int, str] = {}          # hash_value -> node_name
        self.sorted_keys: List[int] = []        # sorted ring positions
        self.clients: Dict[str, redis.Redis] = {}  # node_name -> Redis client

        for node in nodes:
            self.add_node(node)

    def _hash(self, key: str) -> int:
        """
        Hash a string to a position on the ring using MD5.
        Returns a large integer suitable for ring placement.
        """
        return int(hashlib.md5(key.encode('utf-8')).hexdigest(), 16)

    def add_node(self, node: dict):
        """
        Add a physical node to the ring by creating `virtual_nodes`
        positions for it. Each virtual node maps to the same Redis client.
        """
        node_name = f"{node['host']}:{node['port']}"
        client = redis.Redis(
            host=node['host'],
            port=node['port'],
            decode_responses=True,
        )
        self.clients[node_name] = client

        # Create virtual nodes spread around the ring.
        for i in range(self.virtual_nodes):
            virtual_key = f"{node_name}-vn-{i}"
            hashed = self._hash(virtual_key)
            self.ring[hashed] = node_name
            bisect.insort(self.sorted_keys, hashed)

    def get_node_name(self, key: str) -> Optional[str]:
        """
        Given a cache key, find which node is responsible for it.
        Walks clockwise from the key's hash position on the ring.
        """
        if not self.ring:
            return None

        hashed = self._hash(key)

        # Find the first ring position >= the key's hash (clockwise walk).
        idx = bisect.bisect_right(self.sorted_keys, hashed)

        # Wrap around to the start of the ring if we've passed the end.
        if idx == len(self.sorted_keys):
            idx = 0

        return self.ring[self.sorted_keys[idx]]

    def get_client(self, key: str) -> Optional[redis.Redis]:
        """
        Return the Redis client responsible for the given key.
        """
        node_name = self.get_node_name(key)
        return self.clients[node_name] if node_name else None


# ---------------------------------------------------------------------------
# Module-level singleton: the cache ring used by the rest of the application.
# ---------------------------------------------------------------------------
import os

# Read from environment variables if running in Docker, otherwise fallback to localhost
REDIS_HOST_1 = os.environ.get("REDIS_HOST_1", "localhost")
REDIS_HOST_2 = os.environ.get("REDIS_HOST_2", "localhost")
REDIS_HOST_3 = os.environ.get("REDIS_HOST_3", "localhost")

# If running in Docker (host != localhost), internal port is always 6379 for all containers
REDIS_PORT_1 = 6379
REDIS_PORT_2 = 6379 if REDIS_HOST_2 != "localhost" else 6380
REDIS_PORT_3 = 6379 if REDIS_HOST_3 != "localhost" else 6381

REDIS_NODES = [
    {"host": REDIS_HOST_1, "port": REDIS_PORT_1},
    {"host": REDIS_HOST_2, "port": REDIS_PORT_2},
    {"host": REDIS_HOST_3, "port": REDIS_PORT_3},
]

cache_ring = ConsistentHashingRing(REDIS_NODES)
