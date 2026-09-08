"""The single resolved AI harness run contract.

One immutable value object describes everything that shapes a generation run
and its checkpoint compatibility: model identity, wire protocol, reasoning
effort, structured-output strategy, result schema, harness policy, run
budgets and the SDK versions that define message/checkpoint formats.

Ownership boundaries (deliberately narrow):

* resolved ONCE by the production assembly entrypoint
  (``DeepAgentRubricGenerator``) and shared by the model factory semantics,
  the deep-agent assembly, the run fingerprint and diagnostics;
* it does NOT build graphs, call providers or touch databases — resolution
  is pure configuration validation, so a broken configuration can never
  block model-free jobs and never leaves a half-initialized runtime;
* it contains NO secrets: endpoints appear only as fingerprints, never URLs;
  API keys, material bodies and private reasoning are out of scope by
  construction.

The fingerprint is the authoritative checkpoint-compatibility identity:
semantic changes (protocol, effort, schema, harness policy, budgets, tracked
SDK versions) produce a new fingerprint and trigger the service's existing
lock-protected purge-and-rebuild flow. Key rotation, log paths, PIDs and
attempt timings never enter the fingerprint.
"""

from __future__ import annotations

import hashlib
import importlib.metadata as importlib_metadata
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from app.lib.ai_runtime.deep_runtime import RuntimeBudget
from app.lib.ai_runtime.model import (
    OPENAI_PROTOCOL_CHAT_COMPLETIONS,
    OPENAI_PROTOCOL_RESPONSES,
    RuntimeModelIdentity,
    openai_protocol,
    runtime_model_identity,
    validated_reasoning_effort,
)

# Versioned identity of the restricted harness policy: material/workspace
# permissions, excluded tools (execute/task), disabled general-purpose
# subagent, prompt/material encapsulation, public-stream filtering and the
# validation/correction rules. Bump when ANY of those semantics change, so
# checkpoints written under an older policy are refused and rebuilt.
HARNESS_POLICY_VERSION = "m0-restricted-v2"

# Client-held Responses history policy: store=false, no
# previous_response_id, encrypted reasoning items round-trip inside the
# message history/checkpoint.
RESPONSES_HISTORY_POLICY = "client-held-encrypted-v1"

ANTHROPIC_MESSAGES_PROTOCOL = "anthropic_messages"

# SDK packages whose versions affect message shapes, checkpoint formats or
# protocol behavior; they are part of the fingerprint.
TRACKED_SDK_PACKAGES: tuple[str, ...] = (
    "deepagents",
    "langchain",
    "langchain-core",
    "langchain-openai",
    "langchain-anthropic",
    "langgraph",
    "langgraph-checkpoint-postgres",
    "openai",
)


def tracked_sdk_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in TRACKED_SDK_PACKAGES:
        try:
            versions[package] = importlib_metadata.version(package)
        except importlib_metadata.PackageNotFoundError:
            versions[package] = "missing"
    return versions


def result_schema_hash(result_schema: Any) -> str:
    """Deterministic hash of the structured-output contract."""

    canonical = json.dumps(
        result_schema.model_json_schema(), sort_keys=True, ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def prompt_identity_hash(*texts: str) -> str:
    """Mechanical prompt identity: ANY change to the instruction texts that
    shape a run (system prompt, revision instruction) moves the contract
    fingerprint — the policy version constant is no longer the only guard."""

    joined = "\u0000".join(texts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ResolvedHarnessContract:
    """Everything one generation run's identity and recovery depend on."""

    provider: str
    model: str
    endpoint_fingerprint: str
    protocol: str
    reasoning_effort: str  # "" = unspecified (model default); "none" = explicit
    output_strategy: str
    result_schema_hash: str
    harness_policy_version: str
    prompt_identity: str
    responses_history_policy: str
    max_model_calls: int
    max_tool_calls: int
    max_total_seconds: float
    max_citation_revisions: int
    sdk_versions: Mapping[str, str] = MappingProxyType({})

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "endpoint_fingerprint": self.endpoint_fingerprint,
            "protocol": self.protocol,
            "reasoning_effort": self.reasoning_effort,
            "output_strategy": self.output_strategy,
            "result_schema_hash": self.result_schema_hash,
            "harness_policy_version": self.harness_policy_version,
            "prompt_identity": self.prompt_identity,
            "responses_history_policy": self.responses_history_policy,
            "budget": {
                "max_model_calls": self.max_model_calls,
                "max_tool_calls": self.max_tool_calls,
                "max_total_seconds": self.max_total_seconds,
            },
            "max_citation_revisions": self.max_citation_revisions,
            "sdk_versions": dict(sorted(self.sdk_versions.items())),
        }

    @property
    def fingerprint(self) -> str:
        """Deterministic canonical-JSON hash; stable across processes."""

        canonical = json.dumps(
            self.canonical_dict(), sort_keys=True, ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def diagnostics_identity(self) -> dict[str, Any]:
        """Whitelisted, non-secret identity fields for structured logging."""

        return {
            "contract_fingerprint": self.fingerprint,
            "provider": self.provider,
            "model": self.model,
            "endpoint_fingerprint": self.endpoint_fingerprint,
            "protocol": self.protocol,
            "reasoning_effort": self.reasoning_effort or "unspecified",
            "output_strategy": self.output_strategy,
            "harness_policy_version": self.harness_policy_version,
        }


def resolve_harness_contract(
    config: Any,
    *,
    result_schema: Any,
    budget: RuntimeBudget | None = None,
    max_revisions: int = 1,
    prompt_texts: tuple[str, ...] | None = None,
) -> ResolvedHarnessContract:
    """Resolve the contract from a configuration snapshot.

    Pure and side-effect free: no model construction, no network, no
    database. Credentials are NOT required here (the model factory keeps the
    fail-closed credential gate at build time), so a missing key never
    produces a wrong identity — it fails later, at the actual model build,
    with the contract fingerprint already recorded for diagnostics.
    """

    identity: RuntimeModelIdentity = runtime_model_identity(config, require_credentials=False)
    effort = validated_reasoning_effort(config)
    if identity.provider == "openai":
        protocol = openai_protocol(config)
        # Native structured output (ProviderStrategy: json_schema on the wire)
        # is the declared capability for current OpenAI reasoning models on
        # both protocols; the C1 capability gate verified it against the
        # current gateway together with the file tools.
        output_strategy = "provider_strategy_json_schema"
        responses_history = (
            RESPONSES_HISTORY_POLICY
            if protocol == OPENAI_PROTOCOL_RESPONSES
            else "not_applicable"
        )
    else:
        protocol = ANTHROPIC_MESSAGES_PROTOCOL
        # Anthropic keeps its existing profile-resolved strategy; this task
        # adds no Anthropic thinking support and re-verifies nothing there.
        output_strategy = "model_profile_default"
        responses_history = "not_applicable"
    effective_budget = budget if budget is not None else RuntimeBudget()
    if prompt_texts is None:
        # Production default: the actual instruction texts of the rubric
        # generator (imported lazily; adapters never imports this module at
        # module scope, so there is no cycle).
        from app.lib.ai_runtime.adapters import _REVISION_PROMPT_PREFIX, _SYSTEM_PROMPT

        prompt_texts = (_SYSTEM_PROMPT, _REVISION_PROMPT_PREFIX)
    return ResolvedHarnessContract(
        provider=identity.provider,
        model=identity.model,
        endpoint_fingerprint=identity.endpoint_fingerprint,
        protocol=protocol,
        reasoning_effort=effort,
        output_strategy=output_strategy,
        result_schema_hash=result_schema_hash(result_schema),
        harness_policy_version=HARNESS_POLICY_VERSION,
        prompt_identity=prompt_identity_hash(*prompt_texts),
        responses_history_policy=responses_history,
        max_model_calls=effective_budget.max_model_calls,
        max_tool_calls=effective_budget.max_tool_calls,
        max_total_seconds=effective_budget.max_total_seconds,
        max_citation_revisions=max_revisions,
        sdk_versions=MappingProxyType(tracked_sdk_versions()),
    )


def protocol_uses_responses(protocol: str) -> bool:
    return protocol == OPENAI_PROTOCOL_RESPONSES


def protocol_uses_chat_completions(protocol: str) -> bool:
    return protocol == OPENAI_PROTOCOL_CHAT_COMPLETIONS


__all__ = [
    "ANTHROPIC_MESSAGES_PROTOCOL",
    "HARNESS_POLICY_VERSION",
    "RESPONSES_HISTORY_POLICY",
    "TRACKED_SDK_PACKAGES",
    "ResolvedHarnessContract",
    "prompt_identity_hash",
    "protocol_uses_chat_completions",
    "protocol_uses_responses",
    "resolve_harness_contract",
    "result_schema_hash",
    "tracked_sdk_versions",
]
