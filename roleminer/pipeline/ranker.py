"""TF-IDF pre-ranker — orders jobs by keyword overlap with profile."""
import logging

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from roleminer.scrapers.base import Job

logger = logging.getLogger(__name__)


def rank_jobs(jobs: list[Job], profile: dict, resume_summary: str) -> tuple[list[Job], list[float]]:
    """
    Rank jobs by TF-IDF cosine similarity against (skills + resume_summary).

    Returns (sorted_jobs_desc, scores_aligned_with_sorted_jobs).
    """
    if not jobs:
        return [], []

    skills = profile.get("skills", []) or []
    query = " ".join(skills) + " " + (resume_summary or "")

    docs = [(j.title or "") + " " + (j.jd_text or "")[:500] for j in jobs]

    try:
        vec = TfidfVectorizer(stop_words="english", lowercase=True, max_features=2000)
        matrix = vec.fit_transform([query] + docs)
    except ValueError as exc:
        # Empty vocabulary
        logger.warning("TF-IDF failed (%s) — returning unranked", exc)
        return jobs, [0.0] * len(jobs)

    sims = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
    order = sorted(range(len(jobs)), key=lambda i: sims[i], reverse=True)
    sorted_jobs = [jobs[i] for i in order]
    sorted_scores = [float(sims[i]) for i in order]
    logger.info("rank_jobs: ranked %d jobs (top score %.3f)", len(jobs), sorted_scores[0] if sorted_scores else 0.0)
    return sorted_jobs, sorted_scores
