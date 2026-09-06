"""OpenAPI contract: two-field rubric only, no legacy routes or fields."""

import json
from pathlib import Path

from app.main import app


def test_openapi_matches_checked_in_contract() -> None:
    checked_in = json.loads(
        (Path(__file__).resolve().parents[1] / "openapi.json").read_text(encoding="utf-8")
    )
    assert checked_in == app.openapi()


def test_openapi_exposes_complete_criterion_contract() -> None:
    spec = app.openapi()
    expected = {
        "id", "criterion", "pass_score",
        "score_anchors", "criterion_basis", "pass_score_basis",
    }
    for schema_name in ("CriterionView", "CriterionIn"):
        schema = spec["components"]["schemas"][schema_name]
        assert set(schema["properties"].keys()) == expected, schema_name
    # The edit contract must NOT turn anchors into a pass_score whitelist:
    # pass_score keeps the plain 0-10 integer bound with no anchor coupling.
    pass_score = spec["components"]["schemas"]["CriterionIn"]["properties"]["pass_score"]
    assert pass_score.get("minimum") == 0 and pass_score.get("maximum") == 10
    assert "enum" not in pass_score
    # Deletion is an accepted operation, not a bare 204.
    delete_op = spec["paths"]["/api/questions/{question_id}"]["delete"]
    assert "202" in delete_op["responses"]
    assert "204" not in delete_op["responses"]
    # Run event surfaces exist (snapshot + SSE).
    assert "/api/questions/{question_id}/runs/{operation_id}/events" in spec["paths"]
    assert "/api/questions/{question_id}/runs/{operation_id}/events/stream" in spec["paths"]
    for legacy_field in [
        "name", "description", "purpose", "max_score", "award_points",
        "deduction_points", "critical", "hard_fail_conditions", "pass_threshold",
    ]:
        assert legacy_field not in spec["components"]["schemas"]["CriterionView"]["properties"]
    rendered = json.dumps(spec, ensure_ascii=False)
    assert "pass_threshold" not in rendered
    assert "critical_mode" not in rendered


def test_openapi_contains_no_legacy_paths() -> None:
    spec = app.openapi()
    for path in spec["paths"]:
        for legacy in [
            "workspaces",
            "upload-batches",
            "co-creation",
            "authoring",
            "evaluation-sets",
            "submissions",
            "scores",
            "question-revisions",
        ]:
            assert legacy not in path, path
    expected = {
        "/api/external/question-batches",
        "/api/questions",
        "/api/scenes",
    }
    assert expected.issubset(set(spec["paths"].keys()))


def test_openapi_documents_question_library_actions() -> None:
    spec = app.openapi()
    paths = set(spec["paths"].keys())
    assert "/api/questions/{question_id}/save-regenerate" in paths
    assert "/api/questions/{question_id}/criteria" in paths
    assert "/api/questions/{question_id}/generation-retry" in paths
    assert "/api/questions/{question_id}/publication" in paths
    assert "/api/questions/{question_id}/title" in paths


def test_openapi_requires_scene_id_on_question_list() -> None:
    spec = app.openapi()
    list_operation = spec["paths"]["/api/questions"]["get"]
    params = {param["name"]: param for param in list_operation["parameters"]}
    assert params["scene_id"]["required"] is True
    assert params["scene_id"]["schema"]["type"] == "string"
    assert params["status"].get("required", False) is False
    assert set(list_operation["responses"].keys()) == {"200", "401", "404", "422"}
