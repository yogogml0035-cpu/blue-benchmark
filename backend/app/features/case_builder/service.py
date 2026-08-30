from datetime import datetime, timezone
from uuid import uuid4

from fastapi import UploadFile

from app.features.auth.repository import UserRecord
from app.features.case_builder import repository
from app.features.case_builder.schemas import (
    AnswerRequest,
    Attachment,
    CandidateCase,
    Case,
    CaseDetail,
    CaseState,
    ConfirmationRequest,
    DraftContent,
    EvidenceRef,
    Fact,
    LastError,
    PendingQuestion,
    ProposedStandard,
    ReferenceOutcome,
    Scenario,
    TeacherJudgment,
    Unknown,
    Dimension,
    BuilderSnapshot,
)
from app.features.workspaces import service as workspace_service
from app.lib.errors import AppError
from app.lib.settings import settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _touch(case: repository.CaseRecord) -> None:
    case.updated_at = _now()


def _detail(case: repository.CaseRecord) -> CaseDetail:
    return CaseDetail(
        case=Case(
            id=case.id,
            workspace_id=case.workspace_id,
            title=case.title,
            task_description=case.task_description,
            state=case.state,
            attachment=case.attachment,
            builder=BuilderSnapshot(
                draft_revision=case.draft_revision,
                pending_question=case.pending_question,
                draft=case.draft,
                last_error=case.last_error,
            ),
            candidate_case=case.candidate_case,
            created_at=case.created_at,
            updated_at=case.updated_at,
        )
    )


def _authorized_case(workspace_id: str, case_id: str, user: UserRecord) -> repository.CaseRecord:
    workspace_service.assert_owner(workspace_id, user)
    case = repository.get(case_id)
    if case is None:
        raise AppError(404, "RESOURCE_NOT_FOUND", "案例不存在。")
    if case.workspace_id != workspace_id:
        raise AppError(403, "FORBIDDEN", "你无权访问这个案例。")
    return case


def _parse_error(code: str, message: str) -> LastError:
    return LastError(stage="parse", code=code, message=message, retryable=False)


def _ai_error(code: str, message: str) -> LastError:
    return LastError(stage="ai", code=code, message=message, retryable=True)


def _detect_mode(text: str) -> str:
    if "[stub:ai_failed]" in text:
        return "ai_failed_once"
    if "[stub:waiting_for_confirmation]" in text or "[stub:success]" in text:
        return "confirmation"
    return "question"


async def create_case(
    workspace_id: str,
    title: str,
    task_description: str | None,
    upload: UploadFile,
    user: UserRecord,
) -> CaseDetail:
    workspace_service.assert_owner(workspace_id, user)
    if not title.strip():
        raise AppError(422, "VALIDATION_ERROR", "案例标题不能为空。")
    filename = upload.filename or "unnamed"
    extension = filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
    if extension not in {"txt", "md"}:
        raise AppError(415, "UNSUPPORTED_FILE_TYPE", "只支持 .txt 或 .md 文件。")
    content_type = upload.content_type or "application/octet-stream"
    allowed_types = {"text/plain", "text/markdown", "text/x-markdown", "application/octet-stream"}
    if content_type not in allowed_types:
        raise AppError(415, "UNSUPPORTED_FILE_TYPE", "文件声明类型不是 TXT/Markdown。")
    raw = await upload.read(settings.upload_max_bytes + 1)
    if len(raw) > settings.upload_max_bytes:
        raise AppError(
            413,
            "FILE_TOO_LARGE",
            "文件超过当前大小限制。",
            {"max_bytes": settings.upload_max_bytes},
        )
    try:
        parsed_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        parsed_text = ""
        parse_error = _parse_error("TEXT_DECODE_FAILED", "文件不是可读取的 UTF-8 文本。")
    else:
        parse_error = (
            _parse_error("PARSED_CONTENT_EMPTY", "文件内容为空，不能进入 AI 分析。")
            if not parsed_text.strip()
            else None
        )

    now = _now()
    case = repository.CaseRecord(
        id=str(uuid4()),
        workspace_id=workspace_id,
        title=title.strip(),
        task_description=task_description.strip() if task_description else None,
        attachment=Attachment(
            id=str(uuid4()),
            original_name=filename,
            media_type=content_type,
            size_bytes=len(raw),
        ),
        parsed_text=parsed_text,
        state=CaseState.parse_failed if parse_error else CaseState.ready_for_ai,
        thread_id=str(uuid4()),
        created_at=now,
        updated_at=now,
        last_error=parse_error,
        mode=_detect_mode(parsed_text),
    )
    repository.add(case)
    return _detail(case)


def get_case(workspace_id: str, case_id: str, user: UserRecord) -> CaseDetail:
    return _detail(_authorized_case(workspace_id, case_id, user))


def _stub_draft(case: repository.CaseRecord, answer: str | None = None) -> DraftContent:
    source_id = case.attachment.id
    quote = case.parsed_text.strip().replace("\n", " ")[:180]
    attachment_ref = EvidenceRef(
        kind="attachment_excerpt",
        source_id=source_id,
        locator="lines 1-5",
        quote=quote or "上传文本摘录",
    )
    task_ref = EvidenceRef(
        kind="task_description",
        source_id=case.id,
        locator=None,
        quote=case.task_description or "上传案例任务说明",
    )
    teacher_ref = (
        EvidenceRef(
            kind="teacher_answer",
            source_id=next(iter(case.answered_questions)),
            locator=None,
            quote=answer,
        )
        if answer and case.answered_questions
        else task_ref
    )
    accepted_result = answer or "基于输入材料形成可交付、可核验的结果。"
    return DraftContent(
        scenario=Scenario(summary="上传案例对应的业务任务场景（Stub 草案）", evidence_refs=[attachment_ref]),
        task_goal="完成案例中描述的真实任务，并保留输入材料中的事实边界。",
        input_summary="使用上传的 TXT/Markdown 案例和任务说明。",
        output_requirements=["输出与任务目标一致且可人工核验的结果。"],
        prohibited_errors=["不得编造输入材料中没有依据的事实。"],
        reference_outcome=ReferenceOutcome(
            accepted_result=accepted_result,
            rationale="由案例材料或老师回答提供依据，仍需人工确认。",
            evidence_refs=[teacher_ref],
        ),
        facts=[Fact(id="fact-1", text="案例包含一份待整理的真实业务任务。", evidence_refs=[attachment_ref])],
        teacher_judgments=(
            [TeacherJudgment(id="judgment-1", text=answer, evidence_refs=[teacher_ref])]
            if answer
            else []
        ),
        proposed_standards=[
            ProposedStandard(
                id="proposal-1",
                text="结果应同时满足任务要求和事实可追溯性。",
                evidence_refs=[attachment_ref],
            )
        ],
        unknowns=[Unknown(id="gap-1", text="具体业务偏好仍以老师确认稿为准。", blocking=False)],
        primary_capability="从真实业务案例中整理可验证标准。",
        dimensions=[
            Dimension(
                id="dimension-1",
                name="事实准确性",
                kind="hard_gate",
                criterion="所有关键结论都能在输入材料或老师回答中找到依据。",
                evidence_refs=[attachment_ref],
            )
        ],
        tags=["stub", "case-builder"],
    )


def _run_stub_generation(case: repository.CaseRecord) -> None:
    case.generation_attempts += 1
    case.last_error = None
    case.pending_question = None
    if case.mode == "ai_failed_once" and case.generation_attempts == 1:
        case.state = CaseState.ai_failed
        case.last_error = _ai_error("MODEL_UNAVAILABLE", "Stub 模型暂时不可用，请重试 AI。")
        _touch(case)
        return
    if case.mode == "question" and not case.answered_questions:
        question = PendingQuestion(
            id=str(uuid4()),
            text="这份案例里，哪一个结果是老师最终认可的？",
            reason="缺少参考结果，无法形成可验证的通过条件。",
        )
        case.pending_question = question
        case.state = CaseState.waiting_for_input
        _touch(case)
        return
    case.draft = _stub_draft(case, next(reversed(case.answered_questions.values()), None))
    case.draft_revision = max(case.draft_revision, 1)
    case.state = CaseState.waiting_for_confirmation
    _touch(case)


def generate_draft(workspace_id: str, case_id: str, user: UserRecord) -> CaseDetail:
    case = _authorized_case(workspace_id, case_id, user)
    if case.state == CaseState.generating:
        return _detail(case)
    if case.state not in {CaseState.ready_for_ai, CaseState.ai_failed}:
        conflict = {
            CaseState.waiting_for_input: ("ANSWER_REQUIRED", "请先回答当前问题。"),
            CaseState.waiting_for_confirmation: ("CONFIRMATION_REQUIRED", "请先确认当前草案。"),
            CaseState.parse_failed: ("CASE_NOT_READY_FOR_AI", "解析失败的案例不能进入 AI。"),
            CaseState.confirmed: ("CASE_ALREADY_CONFIRMED", "案例已经确认。"),
            CaseState.parsing: ("CASE_NOT_READY_FOR_AI", "案例仍在解析。"),
        }
        code, message = conflict.get(
            case.state, ("INVALID_STATE", "当前状态不能生成草案。")
        )
        raise AppError(409, code, message)
    case.state = CaseState.generating
    _touch(case)
    _run_stub_generation(case)
    repository.save(case)
    return _detail(case)


def answer_question(
    workspace_id: str, case_id: str, payload: AnswerRequest, user: UserRecord
) -> CaseDetail:
    case = _authorized_case(workspace_id, case_id, user)
    if payload.question_id in case.answered_questions:
        if case.answered_questions[payload.question_id] == payload.answer:
            return _detail(case)
        raise AppError(409, "QUESTION_ALREADY_ANSWERED", "这个问题已经用不同答案回答过。")
    if case.state != CaseState.waiting_for_input or not case.pending_question:
        raise AppError(409, "QUESTION_NOT_PENDING", "当前没有待回答的问题。")
    if payload.question_id != case.pending_question.id:
        raise AppError(409, "STALE_QUESTION", "问题已经更新，请重新读取案例。")
    question_id = case.pending_question.id
    case.answered_questions[question_id] = payload.answer
    case.pending_question = None
    case.state = CaseState.generating
    _touch(case)
    case.draft = _stub_draft(case, payload.answer)
    case.draft_revision = max(case.draft_revision, 1)
    case.state = CaseState.waiting_for_confirmation
    _touch(case)
    repository.save(case)
    return _detail(case)


def _validate_confirmation(case: repository.CaseRecord, content: DraftContent) -> None:
    if not content.scenario.summary.strip() or not content.task_goal.strip():
        raise AppError(422, "CANDIDATE_INCOMPLETE", "场景摘要和任务目标不能为空。")
    if not content.reference_outcome:
        raise AppError(422, "CANDIDATE_INCOMPLETE", "请补充老师认可的参考结果。")
    if not content.primary_capability.strip() or not content.output_requirements:
        raise AppError(422, "CANDIDATE_INCOMPLETE", "请补充主要能力和至少一条输出要求。")
    if not content.dimensions or any(not item.criterion.strip() for item in content.dimensions):
        raise AppError(422, "CANDIDATE_INCOMPLETE", "至少需要一个带判定标准的维度。")
    allowed_sources = {case.id, case.attachment.id, *case.answered_questions.keys()}
    refs = []
    refs.extend(content.scenario.evidence_refs)
    if content.reference_outcome:
        refs.extend(content.reference_outcome.evidence_refs)
    for item in [*content.facts, *content.teacher_judgments, *content.proposed_standards, *content.dimensions]:
        refs.extend(item.evidence_refs)
    if any(ref.source_id not in allowed_sources for ref in refs):
        raise AppError(422, "INVALID_EVIDENCE_REFERENCE", "草案中存在不属于当前案例的证据引用。")


def confirm(
    workspace_id: str, case_id: str, payload: ConfirmationRequest, user: UserRecord
) -> CaseDetail:
    case = _authorized_case(workspace_id, case_id, user)
    if case.state == CaseState.confirmed and case.candidate_case:
        if (
            payload.draft_revision == case.candidate_case.draft_revision
            and payload.content == case.candidate_case.content
        ):
            return _detail(case)
        raise AppError(409, "CASE_ALREADY_CONFIRMED", "案例已经确认，不能提交不同版本。")
    if case.state != CaseState.waiting_for_confirmation:
        raise AppError(409, "CONFIRMATION_NOT_PENDING", "当前没有待确认草案。")
    if payload.draft_revision != case.draft_revision:
        raise AppError(409, "STALE_DRAFT", "草案版本已经更新，请重新读取案例。")
    _validate_confirmation(case, payload.content)
    timestamp = _now()
    candidate = CandidateCase(
        id=str(uuid4()),
        source_case_id=case.id,
        draft_revision=payload.draft_revision,
        content=payload.content,
        confirmed_by=user.id,
        confirmed_by_username=user.username,
        confirmed_at=timestamp,
    )
    # Stub 没有数据库事务；单次内存提交同时替换候选快照和业务状态。
    case.candidate_case = candidate
    case.draft = payload.content
    case.state = CaseState.confirmed
    case.last_error = None
    _touch(case)
    repository.save(case)
    return _detail(case)
