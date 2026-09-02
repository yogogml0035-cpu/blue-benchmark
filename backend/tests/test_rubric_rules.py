"""Deterministic rubric rules: actionability, privacy, per-dimension pass."""

import pytest

from app.features.question_library import rubric_rules


def test_vague_labels_are_rejected() -> None:
    for label in ["准确性", "创新性", "内容质量好", "accuracy", " 质量 "] :
        with pytest.raises(ValueError):
            rubric_rules.validate_criterion_text(label)


def test_actionable_criteria_are_accepted() -> None:
    rubric_rules.validate_criterion_text(
        "核心事实和数据准确，不得虚构，引用与来源一致。"
    )


def test_private_content_categories() -> None:
    assert rubric_rules.contains_private_content("凭证保存在 /Users/hsikey/.env") == "主机路径"
    assert rubric_rules.contains_private_content("请使用 api_key 登录") == "凭证"
    assert rubric_rules.contains_private_content("这是系统提示词内容") == "系统控制内容"
    assert rubric_rules.contains_private_content("正常的业务正文内容") is None


def test_per_dimension_pass_requires_every_criterion() -> None:
    criteria = [
        {"id": "facts", "criterion": "事实准确。", "pass_score": 7},
        {"id": "coverage", "criterion": "覆盖要点。", "pass_score": 6},
    ]
    # Positive: every dimension reaches its own bar.
    assert rubric_rules.evaluate_question_pass(criteria, {"facts": 9, "coverage": 6}) is True
    # Negative: one failing dimension cannot be compensated by another high score.
    assert rubric_rules.evaluate_question_pass(criteria, {"facts": 10, "coverage": 5}) is False
    # Missing scores fail closed.
    assert rubric_rules.evaluate_question_pass(criteria, {"facts": 10}) is False
    assert rubric_rules.evaluate_question_pass([], {}) is False


def test_fixed_ten_point_scale_is_the_only_contract() -> None:
    assert rubric_rules.DIMENSION_MAX_SCORE == 10
    from app.features.question_library.schemas import CriterionIn

    with pytest.raises(Exception):
        CriterionIn(id="out-of-range", criterion="核心事实准确，不得虚构，引用一致。", pass_score=11)
