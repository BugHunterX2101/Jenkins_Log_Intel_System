"""
Pattern Matching Engine — TF-IDF cosine similarity against historical failures.
"""

import hashlib
import logging
import re
from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PatternRecord

logger = logging.getLogger(__name__)

_THRESHOLD = 0.75
_VOLATILE  = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\s]*|\d{10,13}|[0-9a-f]{7,40}|/[^\s]+)\b",
    re.IGNORECASE,
)


def _normalise(text: str) -> str:
    return _VOLATILE.sub("TOKEN", text).lower()


def _hash(norm: str) -> str:
    return hashlib.sha256(norm.encode()).hexdigest()


@dataclass
class PatternMatch:
    signature_hash:  str
    failure_type:    str
    similarity_score: float
    resolution_text: str | None


async def find_similar(session: AsyncSession, error_text: str, top_k: int = 3) -> list[PatternMatch]:
    result  = await session.execute(select(PatternRecord))
    records = list(result.scalars().all())
    if not records:
        return []

    q_norm = _normalise(error_text)
    corpus = [_normalise(r.raw_sample) for r in records]

    try:
        vec    = TfidfVectorizer()
        matrix = vec.fit_transform(corpus + [q_norm])
        scores = cosine_similarity(matrix[-1], matrix[:-1])[0]
    except ValueError:
        return []

    matches = [
        PatternMatch(r.signature_hash, r.failure_type, float(s), r.resolution_text)
        for r, s in zip(records, scores) if s >= _THRESHOLD
    ]
    matches.sort(key=lambda m: m.similarity_score, reverse=True)
    return matches[:top_k]


async def upsert_pattern(session: AsyncSession, failure_type: str, raw_sample: str) -> PatternRecord:
    norm = _normalise(raw_sample)
    sig  = _hash(norm)
    result = await session.execute(select(PatternRecord).where(PatternRecord.signature_hash == sig))
    record = result.scalar_one_or_none()

    if record is None:
        record = PatternRecord(signature_hash=sig, failure_type=failure_type, raw_sample=raw_sample)
        session.add(record)
    else:
        record.occurrence_count += 1
        record.failure_type = failure_type

    await session.commit()
    await session.refresh(record)
    return record
