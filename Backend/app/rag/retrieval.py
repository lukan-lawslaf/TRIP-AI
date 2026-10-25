"""Persistent hybrid RAG over local curated travel guides.

Chroma supplies the semantic half with all-MiniLM-L6-v2 embeddings. rank-bm25 supplies
the lexical half so exact place names and etiquette terms remain easy to retrieve. The
retriever is lazy: importing the backend does not download a model or open Chroma.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable

from app.config import get_settings
from app.tools.base import ToolResult
from app.rag.corpus import DEFAULT_DOCUMENTS, GuideDocument

logger = logging.getLogger(__name__)

_TOKEN = re.compile(r"[\wÀ-ÿ]+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN.findall(text)]


@dataclass
class _StoredDocument:
    id: str
    text: str
    metadata: dict[str, Any]


class HybridIndex:
    def __init__(self) -> None:
        self._collection: Any = None
        self._embedder: Any = None
        self._bm25: Any = None
        self._documents: list[_StoredDocument] = []
        self._lock = asyncio.Lock()

    async def _ensure_ready(self) -> None:
        if self._bm25 is not None:
            return
        async with self._lock:
            if self._bm25 is not None:
                return
            await asyncio.to_thread(self._load_sync)

    def _load_sync(self) -> None:
        from rank_bm25 import BM25Okapi

        if get_settings().rag_mode == "lexical":
            self._documents = [
                _StoredDocument(row["id"], row["text"], {
                    "title": row["title"], "destination": row["destination"],
                    "source": row["source"],
                }) for row in DEFAULT_DOCUMENTS
            ]
            self._bm25 = BM25Okapi([
                _tokens(f"{doc.metadata['title']} {doc.text}") for doc in self._documents
            ])
            return
        try:
            import chromadb
            from rank_bm25 import BM25Okapi
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("RAG dependencies are not installed") from exc

        settings = get_settings()
        client = chromadb.PersistentClient(path=str(settings.chroma_dir))
        collection = client.get_or_create_collection(
            name="tripai_guides",
            metadata={"hnsw:space": "cosine"},
        )
        embedder = SentenceTransformer(settings.embedding_model)
        existing = collection.get(include=["documents", "metadatas"])
        documents = self._stored_documents(existing)
        if not documents:
            seed_rows = list(DEFAULT_DOCUMENTS)
            embeddings = embedder.encode(
                [row["text"] for row in seed_rows],
                normalize_embeddings=True,
            ).tolist()
            self._upsert_sync(collection, seed_rows, embeddings=embeddings)
            existing = collection.get(include=["documents", "metadatas"])
            documents = self._stored_documents(existing)

        self._collection = collection
        self._documents = documents
        self._bm25 = BM25Okapi([_tokens(document.text) for document in documents])
        self._embedder = embedder

    @staticmethod
    def _stored_documents(payload: dict[str, Any]) -> list[_StoredDocument]:
        ids = payload.get("ids") or []
        texts = payload.get("documents") or []
        metadata = payload.get("metadatas") or []
        return [
            _StoredDocument(
                id=str(doc_id),
                text=str(text),
                metadata=dict(metadata[index] or {}) if index < len(metadata) else {},
            )
            for index, (doc_id, text) in enumerate(zip(ids, texts))
        ]

    @staticmethod
    def _upsert_sync(collection: Any, documents: Iterable[GuideDocument], *, embeddings: list[list[float]] | None = None) -> None:
        rows = list(documents)
        payload: dict[str, Any] = {
            "ids": [row["id"] for row in rows],
            "documents": [row["text"] for row in rows],
            "metadatas": [
                {"title": row["title"], "destination": row["destination"], "source": row["source"]}
                for row in rows
            ],
        }
        if embeddings is not None:
            payload["embeddings"] = embeddings
        collection.upsert(**payload)

    async def query(self, query: str, *, destination: str | None, limit: int) -> list[dict[str, Any]]:
        await self._ensure_ready()
        if not query.strip():
            return []
        return await asyncio.to_thread(self._query_sync, query, destination, limit)

    def _query_sync(self, query: str, destination: str | None, limit: int) -> list[dict[str, Any]]:
        assert self._bm25 is not None
        limit = max(1, min(limit, 10))
        lexical_scores = list(self._bm25.get_scores(_tokens(query)))
        lexical_max = max(lexical_scores, default=0.0) or 1.0
        lexical = {document.id: score / lexical_max for document, score in zip(self._documents, lexical_scores)}

        semantic: dict[str, float] = {}
        if self._embedder is not None and self._collection is not None:
            vector = self._embedder.encode(query, normalize_embeddings=True).tolist()
            semantic_payload = self._collection.query(
                query_embeddings=[vector],
                n_results=min(max(limit * 3, 10), len(self._documents)),
                include=["documents", "metadatas", "distances"],
            )
            semantic_ids = (semantic_payload.get("ids") or [[]])[0]
            semantic_distances = (semantic_payload.get("distances") or [[]])[0]
            semantic = {str(doc_id): max(0.0, 1.0 - float(distance)) for doc_id, distance in zip(semantic_ids, semantic_distances)}

        ranked: list[tuple[float, _StoredDocument]] = []
        destination_lower = destination.lower() if destination else None
        for document in self._documents:
            doc_destination = str(document.metadata.get("destination", "")).lower()
            if destination_lower and destination_lower not in doc_destination and destination_lower not in document.text.lower():
                continue
            score = 0.55 * semantic.get(document.id, 0.0) + 0.45 * lexical.get(document.id, 0.0)
            if score > 0:
                ranked.append((score, document))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "id": document.id,
                "title": document.metadata.get("title", document.id),
                "destination": document.metadata.get("destination"),
                "text": document.text,
                "source": document.metadata.get("source", "tripai-curated-guide"),
                "score": round(score, 4),
            }
            for score, document in ranked[:limit]
        ]


_INDEX = HybridIndex()


async def rag_query(query: str, *, destination: str | None = None, limit: int = 5) -> ToolResult:
    try:
        results = await _INDEX.query(query, destination=destination, limit=limit)
    except Exception as exc:
        logger.exception("rag.query_failed")
        return ToolResult(
            source="rag",
            status="unavailable",
            error=f"Knowledge base unavailable: {exc}",
            meta={"query": query},
        )
    return ToolResult(
        source="rag",
        status="ok",
        data={"query": query, "destination": destination, "results": results},
        meta={"retrieval": "bm25" if get_settings().rag_mode == "lexical" else "hybrid_bm25_embedding", "count": len(results)},
    )
