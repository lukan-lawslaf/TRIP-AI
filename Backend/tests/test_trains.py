import pytest

from app.tools.trains import train_lookup


@pytest.mark.asyncio
async def test_train_lookup_is_static_and_unavailable():
    result = await train_lookup("Delhi", "Jaipur", "2026-08-20")

    assert result.status == "unavailable"
    assert "Train data is not available right now" in (result.error or "")
    assert result.meta["provider_calls"] == 0
