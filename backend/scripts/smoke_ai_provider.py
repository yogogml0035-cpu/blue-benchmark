"""Smoke-test the configured AI provider through the rubric generation contract.

Prints only structural facts (counts, scores, latency); never material bodies.
"""

from __future__ import annotations

import argparse
import sys
import time

from app.lib.ai_runtime.adapters import (
    RubricGenerationFailure,
    RubricGenerationInput,
    production_adapters,
)
from app.lib.ai_runtime.model import build_runtime_model, runtime_model_identity


_SAMPLE = RubricGenerationInput(
    task_prompt="请把提供的新闻素材改写成一段正式新闻稿，保持事实准确。",
    reference_examples=[
        {"source_name": "新闻素材", "content_text": "某品牌发布新一代车型，续航提升明显。"}
    ],
    bad_cases=[
        {
            "content_text": "这车真牛，快买！",
            "teacher_feedback_texts": ["语气太随意，不像新闻稿。"],
            "reason_summary": "语体不符合新闻稿规范。",
        }
    ],
    reference_answer="某品牌今日发布新一代车型，官方称续航里程较上一代显著提升。",
    memory_materials=[
        {"source_label": "业务记忆", "content_text": "新闻稿需使用客观陈述语气。"}
    ],
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rubric generation provider smoke test")
    parser.add_argument("--attempts", type=int, default=1)
    args = parser.parse_args()

    identity = runtime_model_identity()
    print(f"AI_SMOKE_PROVIDER={identity.provider} model={identity.model}")
    model, _ = build_runtime_model()
    generator = production_adapters(model=model).rubric_generator

    for attempt in range(1, args.attempts + 1):
        started = time.monotonic()
        try:
            result = generator.generate(_SAMPLE)
        except RubricGenerationFailure as exc:
            print(f"AI_SMOKE=FAIL attempt={attempt} code={exc.code} message={exc.message}")
            return 1
        elapsed = time.monotonic() - started
        scores = ",".join(str(item.pass_score) for item in result.criteria)
        print(
            f"AI_SMOKE=OK attempt={attempt} criteria={len(result.criteria)} "
            f"pass_scores=[{scores}] elapsed_seconds={elapsed:.1f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
