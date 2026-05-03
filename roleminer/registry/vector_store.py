"""ChromaDB vector store — companies + jobs collections."""
import logging
from pathlib import Path

import chromadb

import config

logger = logging.getLogger(__name__)


def get_client(chroma_path: Path | None = None) -> chromadb.PersistentClient:
    p = chroma_path if chroma_path is not None else config.CHROMA_PATH
    p.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(p))


def _companies_col(client: chromadb.PersistentClient) -> chromadb.Collection:
    return client.get_or_create_collection(
        "companies",
        metadata={"hnsw:space": "cosine"},
    )


def _jobs_col(client: chromadb.PersistentClient) -> chromadb.Collection:
    return client.get_or_create_collection(
        "jobs",
        metadata={"hnsw:space": "cosine"},
    )


def upsert_companies(
    client: chromadb.PersistentClient,
    companies: list[dict],
    embeddings: list[list[float]],
) -> None:
    """Upsert company embeddings. companies[i] must have 'id'."""
    if not companies:
        return
    col = _companies_col(client)
    col.upsert(
        ids=[str(c["id"]) for c in companies],
        embeddings=embeddings,
        documents=[_company_text(c) for c in companies],
        metadatas=[
            {
                "name": c.get("name", ""),
                "hq_city": c.get("hq_city") or "",
                "company_type": c.get("company_type") or "",
                "ats_type": c.get("ats_type") or "",
                "funding_stage": c.get("funding_stage") or "",
            }
            for c in companies
        ],
    )
    logger.info("vector_store: upserted %d companies", len(companies))


def upsert_jobs(
    client: chromadb.PersistentClient,
    jobs: list,  # list[Job] or list[ScoredJob]
    run_id: int,
    embeddings: list[list[float]],
) -> None:
    """Upsert job embeddings for a run. Job ID = run_id:url_hash."""
    if not jobs:
        return
    col = _jobs_col(client)
    ids = [f"{run_id}:{abs(hash(j.url))}" for j in jobs]
    col.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=[_job_text(j) for j in jobs],
        metadatas=[
            {
                "run_id": run_id,
                "title": j.title or "",
                "company": j.company or "",
                "url": j.url or "",
                "location": j.location or "",
                "work_mode": j.work_mode or "",
                "score": float(getattr(j, "score", -1)),
            }
            for j in jobs
        ],
    )
    logger.info("vector_store: upserted %d jobs for run %d", len(jobs), run_id)


def query_similar_jobs(
    client: chromadb.PersistentClient,
    query_embedding: list[float],
    n_results: int = 10,
    run_id: int | None = None,
) -> list[dict]:
    """Return top-n similar jobs. Optionally filter by run_id."""
    col = _jobs_col(client)
    where = {"run_id": run_id} if run_id is not None else None
    kwargs: dict = {"query_embeddings": [query_embedding], "n_results": n_results, "include": ["metadatas", "distances", "documents"]}
    if where:
        kwargs["where"] = where
    res = col.query(**kwargs)
    return _flatten_query_result(res)


def query_similar_companies(
    client: chromadb.PersistentClient,
    query_embedding: list[float],
    n_results: int = 10,
) -> list[dict]:
    col = _companies_col(client)
    res = col.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["metadatas", "distances", "documents"],
    )
    return _flatten_query_result(res)


def _flatten_query_result(res: dict) -> list[dict]:
    out = []
    metadatas = (res.get("metadatas") or [[]])[0]
    distances = (res.get("distances") or [[]])[0]
    documents = (res.get("documents") or [[]])[0]
    for meta, dist, doc in zip(metadatas, distances, documents):
        out.append({"distance": dist, "document": doc, **(meta or {})})
    return out


def _company_text(c: dict) -> str:
    parts = [c.get("name", ""), c.get("hq_city") or "", c.get("company_type") or "", c.get("funding_stage") or ""]
    tech = c.get("tech_stack")
    if tech:
        parts.append(str(tech))
    return ". ".join(p for p in parts if p)


def _job_text(j) -> str:
    return f"{j.title or ''} at {j.company or ''}. {j.location or ''}. {(j.jd_text or '')[:500]}"
