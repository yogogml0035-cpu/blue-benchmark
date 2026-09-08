"""Worker-side rubric generation: durable run, business validation, CAS commit.

One generation attempt owns: freeze/fencing checks, the immutable material
snapshot fingerprint, run-thread registration (durable runtime only), a
persist-before-send public event sink, the restricted deep-agent call through
the adapter registry, deterministic normalization of the COMPLETE criterion
contract, and the atomic CAS commit. Success is only reported after the
business save; a graph completion is recorded as a stage, never as the final
``run_completed`` event.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.lib.ai_runtime.adapters import (
    RubricGenerationFailure,
    RubricGenerationInput,
    RubricGenerationResult,
    RunContext,
    get_adapters,
)
from app.lib.database import session_scope
from app.lib.database.models import EvalQuestionRow, OperationJobRow

TARGET_TYPE = "eval_question"


def derived_command_id(prefix: str, *parts: str) -> str:
    """Build a bounded, collision-safe command id from unbounded inputs.

    ``operation_jobs.command_id`` is limited to 255 characters; the raw
    concatenation of an external command id (up to 255) and a client case id
    (up to 128) would overflow on PostgreSQL. Hashing keeps the id stable and
    short regardless of input length.
    """

    seed = "\u0000".join(parts)
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:40]
    return f"{prefix}:{digest}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_generation_input(row: EvalQuestionRow) -> RubricGenerationInput:
    return RubricGenerationInput(
        task_prompt=row.task_prompt,
        reference_examples=[
            {
                "source_name": item.get("source_name"),
                "content_text": item.get("content_text", ""),
            }
            for item in (row.reference_examples_json or [])
        ],
        bad_cases=[
            {
                "content_text": item.get("content_text", ""),
                "teacher_feedback_texts": list(item.get("teacher_feedback_texts") or []),
                "reason_summary": item.get("reason_summary"),
            }
            for item in (row.bad_cases_json or [])
        ],
        reference_answer=row.reference_answer,
        memory_materials=[
            {
                "source_label": item.get("source_label"),
                "content_text": item.get("content_text", ""),
            }
            for item in (row.memory_materials_json or [])
        ],
    )


def materials_fingerprint(materials: RubricGenerationInput) -> str:
    """Stable hash of the immutable material snapshot this run is bound to."""
    canonical = json.dumps(
        materials.model_dump(mode="json"), sort_keys=True, ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generator_runtime_fingerprint(generator: Any) -> str:
    """The authoritative run fingerprint: the ACTUAL generator's contract.

    The service never re-derives model or SDK identity itself and never
    degrades to a runtime-mode placeholder: a generator that cannot resolve
    its harness contract is a deterministic configuration failure (terminal,
    NON-retryable), not a best-effort identity. Injected test generators
    carry an explicit contract for exactly this reason.
    """

    from app.lib.ai_runtime.contract import ResolvedHarnessContract

    contract = getattr(generator, "harness_contract", None)
    if not isinstance(contract, ResolvedHarnessContract):
        raise RubricGenerationFailure(
            "AI_CONFIG_INVALID",
            "当前生成器没有可解析的 AI 运行合同，无法登记运行线程；请检查运行配置。",
            retryable=False,
        )
    return contract.fingerprint


class _CompletionGatedSink:
    """Persists public events; ``run_completed`` is gated on the business save.

    The deep runtime reports graph completion; teachers must only see
    completion after the criteria are atomically saved. This sink downgrades
    the primitive's ``run_completed`` to a ``graph_completed`` stage and the
    worker emits the authoritative terminal event itself.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def emit(self, event: Any) -> None:
        from app.lib.ai_runtime.deep_runtime import PublicEvent

        if event.kind == "run_completed":
            self._inner.emit(PublicEvent(kind="stage", stage="graph_completed"))
            return
        self._inner.emit(event)

    def emit_terminal(self, kind: str, detail: str | None = None) -> None:
        from app.lib.ai_runtime.deep_runtime import PublicEvent

        self._inner.emit(PublicEvent(kind=kind, detail=detail))

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if close is not None:
            close()


def normalize_criteria(
    result: RubricGenerationResult, materials: RubricGenerationInput | None = None
) -> list[dict[str, Any]]:
    """Assign stable ids and apply deterministic business validation.

    Enforces the COMPLETE contract: actionable criterion text, privacy
    backstop on every public string, the generation-side rule that the
    suggested pass score has its own anchor and its basis explains exactly
    that score, and — when the material snapshot is provided — citation
    existence at the WORKER layer, so the gate survives any future generator
    implementation instead of living only inside one adapter.
    """

    from app.features.question_library import rubric_rules
    from app.features.question_library.schemas import assert_public_material_text
    from app.lib.ai_runtime.adapters import build_locator_texts, validate_result_citations

    if materials is not None:
        validate_result_citations(result, build_locator_texts(materials))

    criteria: list[dict[str, Any]] = []
    for index, item in enumerate(result.criteria):
        criterion = item.criterion.strip()
        rubric_rules.validate_criterion_text(criterion)
        scores = [anchor.score for anchor in item.score_anchors]
        if len(scores) != len(set(scores)):
            raise ValueError("分数锚点必须唯一。")
        if item.pass_score not in scores:
            raise ValueError("初始生成必须为建议通过分提供对应的表现描述锚点。")
        if item.pass_score_basis.explained_score != item.pass_score:
            raise ValueError("通过分依据必须解释所建议的通过分。")
        for anchor in item.score_anchors:
            assert_public_material_text(anchor.description, field_label="分数锚点说明")
        for basis in (item.criterion_basis, item.pass_score_basis):
            assert_public_material_text(basis.explanation, field_label="依据说明")
            for claim in basis.claims:
                assert_public_material_text(claim.claim, field_label="依据主张")
                if claim.citation is not None:
                    assert_public_material_text(claim.citation.quote, field_label="依据引用")
        criteria.append(
            {
                "id": f"criterion-{index + 1}",
                **item.model_dump(mode="json"),
            }
        )
    return criteria


def process_rubric_generation(job: Any) -> dict[str, Any]:
    from sqlalchemy import select

    from app.features.question_library import run_streams
    from app.lib.database.models import OperationJobRow

    # Fencing check before the (expensive) AI call: a job that is no longer
    # queued/running was superseded while waiting and must not spend a call.
    _precheck_terminal = lambda detail: _record_precheck_terminal(job, detail)  # noqa: E731
    with session_scope() as session:
        job_row = session.execute(
            select(OperationJobRow).where(OperationJobRow.id == job.id)
        ).scalar_one_or_none()
        if job_row is None or job_row.status not in ("queued", "running"):
            from app.lib.operations.worker import SupersededOperation

            _precheck_terminal("superseded")
            raise SupersededOperation("任务已经被取代。")
        row = session.get(EvalQuestionRow, job.target_id)
        if row is None or row.active_operation_id != job.id:
            from app.lib.operations.worker import SupersededOperation

            _precheck_terminal("superseded")
            raise SupersededOperation("题目已经更新或删除。")
        if row.status == "deleting":
            from app.lib.operations.worker import SupersededOperation

            _precheck_terminal("superseded")
            raise SupersededOperation("题目已进入删除冻结，停止生成。")
        materials = build_generation_input(row)
        materials_fp = materials_fingerprint(materials)
        revision = row.content_revision
        question_id = row.id

    thread_id = run_streams.generation_thread_id(question_id, revision)
    generator = get_adapters().rubric_generator
    if getattr(generator, "uses_durable_runtime", False):
        # Resolve the authoritative contract fingerprint BEFORE any
        # checkpoint interaction: contract resolution failure is terminal
        # for this attempt, leaves a visible failure event and never a
        # dangling ``generating`` state.
        try:
            runtime_fp = generator_runtime_fingerprint(generator)
        except RubricGenerationFailure:
            _record_precheck_terminal(job, "contract_invalid")
            raise
        try:
            run_streams.register_thread(
                run_streams.ThreadRegistration(
                    thread_id=thread_id,
                    question_id=question_id,
                    operation_id=job.id,
                    materials_revision=revision,
                    materials_fingerprint=materials_fp,
                    runtime_fingerprint=runtime_fp,
                )
            )
        except ValueError as exc:
            code = str(exc)
            if code in ("THREAD_RUNTIME_MISMATCH", "THREAD_MATERIALS_MISMATCH"):
                # The persisted thread no longer matches what a fresh run on
                # the SAME revision would see. Runtime mismatch means the
                # harness contract moved (protocol, effort, schema, policy,
                # budgets or tracked SDK versions); materials mismatch means
                # the teacher edited materials through the free autosave path
                # (which intentionally never bumps content_revision). Either
                # way the old checkpoint is incompatible garbage: purge it
                # and start a fresh run on the CURRENT materials, so a
                # teacher retry actually recovers instead of dead-ending.
                # Old messages are NEVER converted across contracts.
                try:
                    _purge_incompatible_thread(thread_id)
                    run_streams.register_thread(
                        run_streams.ThreadRegistration(
                            thread_id=thread_id,
                            question_id=question_id,
                            operation_id=job.id,
                            materials_revision=revision,
                            materials_fingerprint=materials_fp,
                            runtime_fingerprint=runtime_fp,
                        )
                    )
                except RubricGenerationFailure:
                    # Purge failed: the incompatible checkpoint still exists;
                    # never continue writing new state on top of it. Leave a
                    # visible terminal event for this attempt.
                    _record_precheck_terminal(job, "purge_failed")
                    raise
                except ValueError:
                    _record_precheck_terminal(job, "registration_refused")
                    raise
            else:
                # Registration refused for a non-mismatch reason: terminal for
                # this attempt BEFORE any checkpoint write; leave a visible
                # failure event so the public log never trails off silently.
                _record_precheck_terminal(job, "registration_refused")
                raise RubricGenerationFailure(
                    code, "材料与已保存的线程快照不一致，本轮拒绝续跑。", retryable=False
                ) from exc

    context = RunContext(
        thread_id=thread_id,
        operation_id=job.id,
        attempt_number=job.attempts,
        question_id=question_id,
        materials_revision=revision,
        materials_fingerprint=materials_fp,
    )
    store_sink = run_streams.PersistentEventSink(
        question_id=question_id,
        operation_id=job.id,
        attempt_number=job.attempts,
        thread_id=thread_id,
    )
    sink = _CompletionGatedSink(store_sink)
    try:
        try:
            result = generator.generate(materials, context=context, sink=sink)
        except RubricGenerationFailure as exc:
            _record_failure_diagnostics(
                "generate", exc, generator, job, question_id, thread_id
            )
            sink.emit_terminal("run_failed")
            raise
        except Exception as exc:
            # Lazy model construction and contract-adjacent configuration
            # errors surface here (before or between checkpoint writes):
            # deterministic, administrator-correctable, NON-retryable — the
            # job still ends terminal with a visible failure event.
            from app.lib.ai_runtime.model import ModelConfigurationError

            _record_failure_diagnostics(
                "model_init", exc, generator, job, question_id, thread_id
            )
            sink.emit_terminal("run_failed")
            if isinstance(exc, ModelConfigurationError):
                raise RubricGenerationFailure(
                    "AI_CONFIG_INVALID",
                    "AI 运行配置无效，本轮生成已终止；请修正配置后显式重试。",
                    retryable=False,
                ) from exc
            raise
        try:
            criteria = normalize_criteria(result, materials)
        except ValueError as exc:
            sink.emit_terminal("run_failed")
            raise RubricGenerationFailure(
                "AI_OUTPUT_INVALID", f"AI 输出的评分标准不可执行：{exc}", retryable=True
            ) from exc
        except Exception as exc:
            sink.emit_terminal("run_failed")
            raise RubricGenerationFailure(
                "AI_OUTPUT_INVALID", f"AI 输出校验失败：{type(exc).__name__}", retryable=True
            ) from exc

        outcome = commit_generation_result(job, criteria)
        if outcome == "superseded":
            # The business row moved on (materials edited mid-run, or the
            # question was delete-frozen). The old round must end visibly as
            # failed/superseded in its own event log — NEVER as a completion.
            from app.lib.operations.worker import SupersededOperation

            sink.emit_terminal("run_failed", "superseded")
            raise SupersededOperation("题目材料已经更新，本轮生成作废。")
        if outcome is not True:
            # Ownership lost to a lease-expired duplicate: the current owner
            # decides the terminal events; this writer stays silent.
            from app.lib.operations.worker import SupersededOperation

            raise SupersededOperation("任务所有权已经失效。")
        # Authoritative completion: emitted only after the atomic business save.
        sink.emit_terminal("run_completed")
    finally:
        sink.close()
    return {"criteria_count": len(criteria)}


def commit_generation_result(
    job: Any, criteria: list[dict[str, Any]]
) -> Any:
    """Atomically commit criteria and complete the job in ONE transaction.

    The fencing predicate requires the job to still be ``running`` under the
    current worker AND the question to still point at this job with the same
    content revision and NOT be delete-frozen, so a lease-expired duplicate or
    a stale generation can never overwrite committed criteria or later admin
    edits, and a late writer can never resurrect a frozen question.

    Returns ``True`` when THIS writer committed the result, ``"superseded"``
    when the business row moved on and the job was marked superseded (the
    caller must record a visible failure in the event log — never a
    completion), and ``False`` when ownership was lost to another worker
    (that owner decides the terminal events).
    """

    from sqlalchemy import select

    from app.lib.database.models import AgentRunAttemptRow, OperationJobRow

    def _mark_attempt(session, job_row: OperationJobRow, status: str) -> None:
        attempt = session.scalar(
            select(AgentRunAttemptRow).where(
                AgentRunAttemptRow.operation_job_id == job_row.id,
                AgentRunAttemptRow.attempt_number == job_row.attempts,
            )
        )
        if attempt is not None:
            attempt.status = status

    now = _utc_now()
    with session_scope() as session:
        job_row = session.execute(
            select(OperationJobRow)
            .where(OperationJobRow.id == job.id)
            .with_for_update()
        ).scalar_one_or_none()
        if (
            job_row is None
            or job_row.status != repository_status_running()
            or job_row.worker_id != job.worker_id
            or job_row.business_revision != job.business_revision
        ):
            return False
        row = session.get(EvalQuestionRow, job.target_id, with_for_update=True)
        if (
            row is None
            or row.status == "deleting"
            or row.content_revision != job.business_revision
            or row.active_operation_id != job.id
        ):
            job_row.status = "superseded"
            job_row.last_error_json = {"code": "SUPERSEDED", "message": "业务版本已经更新。"}
            job_row.lease_until = None
            job_row.worker_id = None
            job_row.finished_at = now
            job_row.updated_at = now
            _mark_attempt(session, job_row, "superseded")
            return "superseded"
        row.criteria_json = criteria
        row.criteria_confirmed = False
        row.status = "pending_review"
        row.last_error_json = None
        row.active_operation_id = None
        row.updated_at = now
        job_row.status = "succeeded"
        job_row.result_json = {
            "criteria_count": len(criteria),
            "__worker_runtime_mode": _runtime_mode_marker(),
        }
        job_row.lease_until = None
        job_row.worker_id = None
        job_row.finished_at = now
        job_row.updated_at = now
        _mark_attempt(session, job_row, "succeeded")
    return True


def _record_failure_diagnostics(
    stage: str,
    exc: BaseException,
    generator: Any,
    job: Any,
    question_id: str,
    thread_id: str,
) -> None:
    """Best-effort whitelisted diagnostics for one generation failure.

    Never raises and never changes the failure semantics; the contract is
    read safely (an unresolvable contract is recorded as unavailable).
    """

    try:
        from app.lib.ai_runtime.diagnostics import record_ai_failure

        try:
            contract = getattr(generator, "harness_contract", None)
        except Exception:  # noqa: BLE001
            contract = None
        record_ai_failure(
            stage=stage,
            exception=exc,
            contract=contract,
            operation_id=job.id,
            question_id=question_id,
            attempt=getattr(job, "attempts", None),
            thread_id=thread_id,
        )
    except Exception:  # noqa: BLE001
        pass


def _purge_incompatible_thread(thread_id: str) -> None:
    """Delete a runtime-incompatible thread's checkpoint and registration.

    Checkpoint unavailability is retryable (the purge must complete before a
    fresh run may start); a missing checkpoint configuration is terminal for
    this attempt and surfaces honestly.
    """
    from app.features.question_library import run_streams
    from app.lib.ai_runtime import deep_runtime

    try:
        session = deep_runtime.open_session(thread_id)
        try:
            deep_runtime.delete_thread_data(session)
        finally:
            session.close()
    except deep_runtime.DeepRuntimeError as exc:
        raise RubricGenerationFailure(exc.code, exc.message, retryable=exc.retryable) from exc
    except Exception as exc:
        raise RubricGenerationFailure(
            "CHECKPOINT_UNAVAILABLE",
            f"清理不兼容运行线程失败：{type(exc).__name__}",
            retryable=True,
        ) from exc
    run_streams.delete_thread_registration(thread_id)


def _record_precheck_terminal(job: Any, detail: str) -> None:
    """Best-effort terminal event for pre-check rejections.

    The sink does not exist yet at pre-check time; record directly so the
    public log of a superseded round still ends with a visible terminal
    marker instead of trailing off mid-stream. Never raises.
    """
    try:
        from app.features.question_library import run_streams

        with session_scope() as session:
            row = session.get(EvalQuestionRow, job.target_id)
            if row is None or row.status == "deleting":
                return
            revision = row.content_revision
        from app.lib.ai_runtime.deep_runtime import PublicEvent

        sink = run_streams.PersistentEventSink(
            question_id=job.target_id,
            operation_id=job.id,
            attempt_number=job.attempts,
            thread_id=run_streams.generation_thread_id(job.target_id, revision),
        )
        sink.emit(PublicEvent(kind="run_failed", detail=detail))
        sink.close()
    except Exception:
        pass


def repository_status_running() -> str:
    from app.lib.operations import repository

    return repository.OperationJobStatus.running.value


def _runtime_mode_marker() -> str:
    from app.lib.settings import settings

    return settings.ai_runtime_mode


def mark_generation_failed(
    job: Any, error: dict[str, Any], *, worker_id: str
) -> None:
    """Best-effort projection: flip the question to generation_failed.

    Only applies when the question still points at this exact job and content
    revision and is not delete-frozen, so a newer round or an accepted
    deletion is never overwritten by an older failure.
    """

    try:
        now = _utc_now()
        with session_scope() as session:
            row = session.get(EvalQuestionRow, job.target_id, with_for_update=True)
            if (
                row is None
                or row.status == "deleting"
                or row.active_operation_id != job.id
                or row.content_revision != job.business_revision
            ):
                return
            row.status = "generation_failed"
            row.last_error_json = {"code": error.get("code", "GENERATION_FAILED"), "message": error.get("message", "")}
            row.active_operation_id = None
            row.updated_at = now
    except Exception:
        # The OperationJob remains authoritative; projection cleanup is advisory.
        pass


def enqueue_generation(
    session, *, question_id: str, content_revision: int, command_id: str
) -> str:
    """Create (or revive) the idempotent generation job in the caller's transaction.

    The id is deterministic in (question, revision, command), so a replayed
    transaction produces the identical job identity. When a failed job with
    the same identity already exists (administrator retry with the same
    command), it is requeued with a fresh attempt budget instead of inserting
    a duplicate row.
    """

    from sqlalchemy import delete, select

    from app.lib.database.models import AgentRunAttemptRow, OperationJobRow

    seed = f"rubric-generation:{question_id}:{content_revision}:{command_id}"
    job_id = str(uuid.UUID(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]))
    now = _utc_now()
    existing = session.execute(
        select(OperationJobRow).where(OperationJobRow.id == job_id)
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status in ("failed", "superseded"):
            # A revived round starts from a clean attempt budget, so its
            # historical attempt rows must go: ``claim_next`` re-derives
            # attempt numbers from zero and the (job_id, attempt_number)
            # unique constraint would otherwise poison the queue.
            session.execute(
                delete(AgentRunAttemptRow).where(
                    AgentRunAttemptRow.operation_job_id == job_id
                )
            )
            existing.status = "queued"
            existing.attempts = 0
            existing.available_at = now
            existing.last_error_json = None
            existing.finished_at = None
            existing.updated_at = now
            session.flush()
            return job_id
        if existing.status in ("queued", "running"):
            return job_id
        raise ValueError("GENERATION_JOB_CONFLICT")
    row = OperationJobRow(
        id=job_id,
        kind="rubric_generation",
        target_type=TARGET_TYPE,
        target_id=question_id,
        command_id=command_id,
        business_revision=content_revision,
        status="queued",
        attempts=0,
        max_attempts=_max_attempts(),
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    return job_id


def _max_attempts() -> int:
    from app.lib.settings import settings

    return settings.operation_max_attempts
