import re
from dataclasses import dataclass
from typing import Any

from pymongo.database import Database


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9\\s]+", " ", (text or "").lower()).strip()


def _tokens(text: str) -> list[str]:
    parts = [p for p in _norm(text).split() if len(p) >= 3]
    # de-dup while keeping order
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


@dataclass(frozen=True)
class FaqMatch:
    question: str
    answer: str
    score: float


def search_faq(db: Database, query: str, limit: int = 8) -> FaqMatch | None:
    q = (query or "").strip()
    if not q:
        return None

    toks = _tokens(q)[:6]
    if not toks:
        return None

    # Candidate fetch: try $text if index exists, otherwise regex OR.
    candidates: list[dict[str, Any]] = []
    try:
        candidates = list(
            db["faqs"]
            .find({"$text": {"$search": " ".join(toks)}, "enabled": {"$ne": False}})
            .limit(limit)
        )
    except Exception:
        pattern = re.compile("|".join(re.escape(t) for t in toks), re.IGNORECASE)
        candidates = list(
            db["faqs"]
            .find(
                {
                    "enabled": {"$ne": False},
                    "$or": [{"question": pattern}, {"answer": pattern}],
                }
            )
            .limit(limit)
        )

    if not candidates:
        return None

    best: FaqMatch | None = None
    qset = set(toks)

    for c in candidates:
        question = str(c.get("question") or "")
        answer = str(c.get("answer") or "")
        if not question or not answer:
            continue

        cset = set(_tokens(question + " " + answer))
        overlap = len(qset & cset)
        score = overlap / max(1, len(qset))
        if best is None or score > best.score:
            best = FaqMatch(question=question, answer=answer, score=score)

    if not best:
        return None

    # threshold: require at least half token overlap
    if best.score < 0.5:
        return None

    return best

