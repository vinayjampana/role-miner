"""Pre-ranker: NVIDIA embeddings when key set, TF-IDF fallback."""
import logging

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from roleminer.pipeline import embedder
from roleminer.scrapers.base import Job

logger = logging.getLogger(__name__)


def _cosine(a: list[float], b: list[list[float]]) -> list[float]:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = np.linalg.norm(va) * np.linalg.norm(vb, axis=1)
    denom = np.where(denom == 0, 1e-9, denom)
    return (vb @ va / denom).tolist()


def _rank_tfidf(jobs: list[Job], query: str) -> tuple[list[Job], list[float]]:
    docs = [(j.title or "") + " " + (j.jd_text or "")[:500] for j in jobs]
    try:
        vec = TfidfVectorizer(stop_words="english", lowercase=True, max_features=2000)
        matrix = vec.fit_transform([query] + docs)
    except ValueError as exc:
        logger.warning("TF-IDF failed (%s) — returning unranked", exc)
        return jobs, [0.0] * len(jobs)
    sims = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
    order = sorted(range(len(jobs)), key=lambda i: sims[i], reverse=True)
    return [jobs[i] for i in order], [float(sims[i]) for i in order]


def _rank_nvidia(jobs: list[Job], query: str) -> tuple[list[Job], list[float]]:
    docs = [(j.title or "") + " " + (j.jd_text or "")[:500] for j in jobs]
    query_vec = embedder.embed([query], input_type="query")[0]
    doc_vecs = embedder.embed(docs, input_type="passage")
    sims = _cosine(query_vec, doc_vecs)
    order = sorted(range(len(jobs)), key=lambda i: sims[i], reverse=True)
    return [jobs[i] for i in order], [float(sims[i]) for i in order]


def rank_jobs(jobs: list[Job], profile: dict, resume_summary: str) -> tuple[list[Job], list[float]]:
    """Rank jobs by similarity to profile. Uses NVIDIA embeddings if key set, else TF-IDF."""
    if not jobs:
        return [], []

    skills = profile.get("skills", []) or []
    query = " ".join(skills) + " " + (resume_summary or "")

    if embedder.is_available():
        logger.info("rank_jobs: using embeddings (%s)", __import__("config").EMBED_MODEL)
        try:
            sorted_jobs, sorted_scores = _rank_nvidia(jobs, query)
            logger.info("rank_jobs: ranked %d jobs via embeddings (top %.3f)", len(jobs), sorted_scores[0] if sorted_scores else 0.0)
            return sorted_jobs, sorted_scores
        except Exception as exc:
            logger.warning("NVIDIA embed failed (%s), falling back to TF-IDF", exc)

    sorted_jobs, sorted_scores = _rank_tfidf(jobs, query)
    logger.info("rank_jobs: ranked %d jobs via TF-IDF (top score %.3f)", len(jobs), sorted_scores[0] if sorted_scores else 0.0)
    return sorted_jobs, sorted_scores
