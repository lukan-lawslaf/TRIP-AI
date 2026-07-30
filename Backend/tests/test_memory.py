from app.memory.models import ItemStatus, TripState


def test_trip_state_merge_is_conservative_and_accumulative():
    state = TripState(
        origin="Delhi",
        party_size=2,
        preferences={"interests": ["food"], "dietary": ["vegetarian"]},
    )

    merged = state.merge(
        {
            "origin": None,
            "party_size": 3,
            "preferences": {"interests": ["temples", "food"]},
            "plan_items": [
                {
                    "kind": "activity",
                    "title": "Fushimi Inari",
                    "status": ItemStatus.CONFIRMED,
                    "day": 1,
                }
            ],
        }
    )

    assert merged.origin == "Delhi"
    assert merged.party_size == 3
    assert merged.preferences.interests == ["food", "temples"]
    assert len(merged.confirmed_items) == 1
    assert merged.confirmed_items[0].title == "Fushimi Inari"


def test_compact_drops_empty_values():
    compact = TripState(origin="Delhi").compact()

    assert compact == {"origin": "Delhi"}
    assert "preferences" not in compact
    assert "plan_items" not in compact


def test_plannability_reports_missing_requirements():
    state = TripState()

    ok, missing = state.is_plannable()

    assert not ok
    assert missing == ["destination", "travel dates or trip length", "number of travellers"]
