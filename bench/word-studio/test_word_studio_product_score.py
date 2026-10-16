import json

from word_studio_product_score import score_product_output, score_stream_depth


def test_product_score_preserves_parser_diagnostics_and_gate():
    raw = json.dumps({"options": ["clear wording", "clear wording", "direct language"]})
    result = score_product_output(raw, requested=3)
    assert result["usableUniqueCount"] == 2
    assert result["depth"] == {"first1": 1, "first3": 2, "first10": 2}
    assert result["duplicateTaxonomy"]["normalizedExactDuplicateCount"] == 1
    assert result["accepted"] is False
    assert "word_studio_too_few_candidates" in result["statuses"]


def test_product_score_rejects_protected_corruption():
    raw = json.dumps({"options": ["Pay the $5 invoice"]})
    result = score_product_output(raw, source="Pay the $4 invoice", protected=["$4"])
    assert result["protectedContentCorruptionCount"] == 1
    assert result["accepted"] is False
    assert "word_studio_protected_corruption" in result["statuses"]


def test_stream_depth_uses_only_completed_usable_candidates():
    raw = '{"options":["one","two","three"]}'
    assert score_stream_depth(raw) == {"usableUniqueCount": 3, "first1": 1, "first3": 3, "first10": 3}
