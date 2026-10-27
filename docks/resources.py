"""Free resources, searchable offline: free tiers for developers (free-for-dev), apps you can host yourself (awesome-selfhosted),
and free programming books and courses (free-programming-books). Built from those community lists; see data/free_resources.json.gz."""

import gzip
import json
import re
from functools import lru_cache
from pathlib import Path

SOURCES = {"free-for-dev": "Free tiers for developers", "awesome-selfhosted": "Apps to host yourself",
           "free-programming-books": "Free books and courses"}


@lru_cache(maxsize=1)
def _rows() -> list[dict]:
    with gzip.open(Path(__file__).parent / "data" / "free_resources.json.gz") as f:
        return json.load(f)


def count() -> int:
    return len(_rows())


def search(query: str, source: str = "", limit: int = 60) -> list[dict]:
    """Best matches first: every word must appear; a hit in the name counts most, then the category, then the description."""
    words = [w for w in re.split(r"\W+", query.lower()) if w]
    scored = []
    for r in _rows():
        if source and r["s"] != source:
            continue
        name, cat, desc = r["n"].lower(), r["c"].lower(), r["d"].lower()
        if not words:
            scored.append((0, r))
            continue
        if not all(w in name or w in cat or w in desc for w in words):
            continue
        score = sum(6 if w in name else 3 if w in cat else 1 for w in words) + (5 if " ".join(words) == name else 0)
        scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    return [{"name": r["n"], "url": r["u"], "description": r["d"].lstrip("⚠ -").strip(), "category": r["c"], "source": r["s"]}
            for _, r in scored[:limit]]
