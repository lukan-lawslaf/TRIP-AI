import pytest

from app.config import Settings
from app.rag import retrieval


@pytest.mark.asyncio
async def test_lexical_runtime_retrieves_guides_without_loading_model(monkeypatch):
    monkeypatch.setattr(retrieval, "get_settings", lambda: Settings(rag_mode="lexical"))
    index = retrieval.HybridIndex()
    results = await index.query("Kyoto temple etiquette shoes", destination="Kyoto", limit=2)
    assert results
    assert results[0]["id"] == "japan-kyoto-etiquette"
    assert all("Kyoto" in row["destination"] for row in results)
    assert index._embedder is None
    assert index._collection is None
