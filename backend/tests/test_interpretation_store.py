from __future__ import annotations

from app.interpretation_store import public_interpretation


def test_public_interpretation_hides_jev_and_exposes_relation_check():
    raw = {
        "id": "ai-1",
        "coding_id": "coding-1",
        "status": "pending",
        "jev": {"relation": "SUPPORTS", "probability": 0.9, "classifier": "jev", "model": "jev-latest"},
        "jev_direct": {
            "relation": "SUPPORTS",
            "probability": 0.9,
            "confidence": 0.8,
            "probabilities": {"SUPPORTS": 0.9},
            "needs_review": False,
            "status": "ok",
            "classifier": "jev",
            "model": "jev-latest",
        },
        "intervention": {
            "type": "NUANCE",
            "reasons": ["jev_disagrees"],
            "message": "Jev agrees this supports 'heat the water'.",
        },
    }
    public = public_interpretation(raw)
    assert "jev" not in public
    assert "jev_direct" not in public
    assert public["relation_check"]["relation"] == "SUPPORTS"
    assert "classifier" not in public["relation_check"]
    assert public["intervention"]["message"].startswith("This evidence appears to support")
    assert public["intervention"]["reasons"] == ["classifier_disagrees"]
