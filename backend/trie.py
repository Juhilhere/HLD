"""
trie.py — In-memory Trie (prefix tree) for typeahead suggestions.

Why a Trie instead of a flat key-value store or sorted array?
  - GET /suggest?q=<prefix> needs every word starting with that prefix.
  - A key-value store would require a full scan — O(N) for N total words.
  - A sorted array + binary search finds the start in O(log N), but still
    needs to walk forward to collect all matches.
  - A Trie walks only the subtree under the prefix node, so the cost is
    O(|prefix| + descendants), which is optimal for prefix matching.

Complexity:
  - insert(word):          O(|word|) — one dict lookup per character.
  - suggest(prefix, k):    O(|prefix| + M log M) — where M is the number
                           of descendants under the prefix node, and
                           M log M is the top-k sort.

Scoring (for Trending Searches):
  The basic version (60% marks) sorts by overall count descending.
  The trending version (bonus 20% marks) blends historical count with a
  recency score using exponential decay:

    score = α * log(total_count + 1) + β * recency_score

  This ensures historically popular terms stay high, but recent surges
  can temporarily boost a query's ranking.
"""

import math
from typing import List, Dict, Any


class TrieNode:
    """
    A single node in the Trie.
    Uses __slots__ for memory efficiency (333k+ nodes).
    """
    __slots__ = ['children', 'count', 'word', 'recency_score']

    def __init__(self):
        self.children: Dict[str, 'TrieNode'] = {}   # char -> child node
        self.count: int = 0                          # all-time search count
        self.word: str = ""                          # the full word ending here
        self.recency_score: float = 0.0              # recent activity score


class Trie:
    """
    Prefix tree that supports insertion and top-k prefix suggestions.
    """

    def __init__(self):
        self.root = TrieNode()
        self.size = 0         # total number of unique words inserted

        # Scoring weights (tunable).
        # α controls how much all-time popularity matters.
        # β controls how much recent activity matters.
        self.alpha = 1.0
        self.beta = 0.5

    def _get_score(self, node: TrieNode) -> float:
        """
        Calculate a blended ranking score for a word.
        Uses log scale on count to prevent extremely popular words
        from permanently dominating the results.
        """
        count_score = math.log(node.count + 1) if node.count > 0 else 0
        return (self.alpha * count_score) + (self.beta * node.recency_score)

    def insert(self, word: str, count: int, recency_score: float = 0.0):
        """
        Insert a word with its frequency count into the Trie.
        If the word already exists, the count is replaced (authoritative load).
        """
        node = self.root
        for ch in word:
            if ch not in node.children:
                node.children[ch] = TrieNode()
            node = node.children[ch]

        if node.count == 0:
            self.size += 1

        node.count = count
        node.word = word
        node.recency_score = recency_score

    def update_recency(self, word: str, recency_score: float):
        """
        Update only the recency score for an existing word.
        Used by the batch writer after flushing new search data.
        """
        node = self.root
        for ch in word:
            if ch not in node.children:
                return  # word not in Trie, nothing to update
            node = node.children[ch]
        node.recency_score = recency_score

    def suggest(self, prefix: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Return up to `limit` suggestions for the given prefix,
        sorted by blended score descending.

        An empty prefix returns the globally top-scored words (used for
        the "Trending Searches" UI section).
        """
        prefix = prefix.lower()

        # Walk to the prefix node.
        node = self.root
        for ch in prefix:
            if ch not in node.children:
                return []  # no words with this prefix exist
            node = node.children[ch]

        # Collect all terminal words in the subtree using iterative DFS
        # (avoids recursion depth issues on deep tries).
        collected: List[Dict[str, Any]] = []
        stack = [node]
        while stack:
            n = stack.pop()
            if n.count > 0:
                collected.append({
                    "q": n.word,
                    "c": n.count,
                    "score": round(self._get_score(n), 4),
                })
            for child in n.children.values():
                stack.append(child)

        # Sort by blended score descending, return top results.
        collected.sort(key=lambda x: x["score"], reverse=True)
        return collected[:limit]
