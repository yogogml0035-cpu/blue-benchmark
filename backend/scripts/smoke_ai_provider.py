"""Run a minimal, real-provider ToolStrategy smoke without printing model data."""

from __future__ import annotations

import sys

from app.features.case_builder.cocreation_schemas import CoverageReview
from app.lib.ai_runtime.adapters import DeepAgentsCoverageReviewer
from app.lib.ai_runtime.model import ModelConfigurationError, build_runtime_model
from app.lib.ai_runtime.profile import GRAPH_SCHEMA_VERSION, get_ai_profile
from app.lib.ai_runtime.context import AgentRunContext
from app.lib.settings import settings


def main() -> int:
    try:
        if settings.ai_runtime_mode != "production":
            raise ModelConfigurationError("AI_RUNTIME_MODE=production is required for ai-smoke")
        model, identity = build_runtime_model()
        reviewer = DeepAgentsCoverageReviewer(model=model, model_spec=identity.registration_key)
        context = AgentRunContext(
            user_id="provider-smoke",
            workspace_id="provider-smoke",
            target_type="coverage",
            target_id="provider-smoke",
            thread_key="provider-smoke",
            business_revision=0,
            evidence_file_ids=(),
            evidence_scope="/evidence/none",
            ai_profile_version=get_ai_profile().version,
            graph_schema_version=GRAPH_SCHEMA_VERSION,
        )
        result = reviewer.review(
            context,
            {
                "capabilities": ["tool-calling"],
                "dimensions": ["structured-output"],
                "failure_modes": [],
            },
        )
        if not isinstance(result.result, CoverageReview):
            raise RuntimeError("unexpected structured output")
    except Exception as exc:  # noqa: BLE001 - CLI output must stay secret-safe.
        provider = getattr(settings, "ai_provider", "configured") or "configured"
        model = getattr(settings, "ai_model", "configured") or "configured"
        print(
            f"AI_PROVIDER_SMOKE=FAIL provider={provider} model={model} error={type(exc).__name__}",
            file=sys.stderr,
        )
        return 1

    print(f"AI_PROVIDER_SMOKE=PASS provider={identity.provider} model={identity.model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
