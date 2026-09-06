"""Rebuild real M0 test inputs from the two confirmed session corpora.

Source root (read-only, never modified)::

    /Users/hsikey/Company/skill-eval-platform/.local-samples/m0

The module extracts two evidence-complete cases — one per corpus group — into
the existing six-material batch upload contract, plus derived counter-examples
with explicit mutation notes. Every extracted fragment keeps a machine-readable
provenance record (source file, sha256, message uuid / section number / line
range) so downstream tasks (C2-C5) can re-verify origin without re-reading the
raw corpora into Git.

Hard rules implemented here:

* the six source files must exist with the registered sha256; anything else is
  a loud ``CorpusError``, never a silent fallback or placeholder;
* teacher text is separated from assistant text, tool results, exporter
  annotations (思考过程/工具调用 blockquotes) and system summaries;
* delivery drafts are stripped of agent meta (核对结论/核对卡/链接尾巴) so bad
  cases contain only the article the teacher actually commented on;
* host paths (``D:\\...`` etc.) are reduced to bare file names and every public
  text is checked with the production ``rubric_rules`` privacy scanner;
* reference answers keep the FULL teacher-approved draft — no truncation;
* the M-group regional-brief task, the i6 brief sample and the export commands
  are separated out and never mixed into the MEGA press-release case;
* missing material versions (v3-v6 讲稿, three 2026 reference press releases)
  are recorded as limitations instead of being faked.

Usage (private fixtures stay in the gitignored storage/acceptance tree)::

    cd backend && uv run python -m scripts.m0_samples \
        --source-root /Users/hsikey/Company/skill-eval-platform/.local-samples/m0 \
        --out storage/acceptance/m0-real-samples

Console output is a redacted summary only: ids, counts, character lengths and
hashes — never material bodies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.features.question_library import rubric_rules  # noqa: E402


class CorpusError(RuntimeError):
    """Raised when the corpus is missing, altered, or cannot support a case."""


# ---------------------------------------------------------------------------
# Registered corpus (non-sensitive metadata; safe to commit)
# ---------------------------------------------------------------------------

F_DIR = "理想汽车供稿-对话上下文-原始记录-2026-08-27"
M_DIR = "新一代理想MEGA新闻稿-对话上下文完整导出-20260828"

CORPUS_SOURCES: tuple[tuple[str, str, str, int], ...] = (
    # (group, relative path, sha256, size bytes)
    ("F", f"{F_DIR}/理想汽车供稿-对话上下文-原始记录-2026-08-27.jsonl",
     "bb85c5a468d126bd6940fdf1da9f99fdf7ee156c5f72a800f3ba83cf3d54e57f", 736805),
    ("F", f"{F_DIR}/【新闻稿】理想汽车公布2026年第二季度财报.md",
     "a650051d2d937f6555d814c8d23d3f3a455d4aa2099181b644c4a797f236fbcb", 9554),
    ("F", f"{F_DIR}/理想汽车2026年第二季度财报-媒体沟通文档.md",
     "0b25b54ab4fd14f9af2801ab7777417682ae021814a231a5ce790221dfde27d4", 34956),
    ("M", f"{M_DIR}/新一代理想MEGA新闻稿-完整对话导出（含思考）-20260903.md",
     "6f1bf1a0f2a0ae6ebf143e94209b6c3ad2bb9dce8b76a05747dda9d09327c9b2", 402110),
    ("M", f"{M_DIR}/新一代理想MEGA讲稿-v2.md",
     "90139599691aa873f1a579d4a2307d359045b286c3831455f1e303a91a8860ed", 25420),
    ("M", f"{M_DIR}/新一代理想MEGA拍摄指引.md",
     "b4bfb8127fe2b433f672ac2fb08ffeca75898e3468c34567f96f4c9128d7f982", 21121),
)

IGNORED_NAMES = {".DS_Store"}

# F group anchors (verified against the JSONL on 2026-09-06).
F_UUID_DRAFT_V1 = "c2da473e-12a3-45c1-b5ac-7b06ec61cb78"   # line 141: delivered draft v1
F_UUID_FEEDBACK_V1 = "715cfb28-7830-477b-9697-bcf0e3081973"  # line 146: teacher rejection of v1
F_UUID_FINAL = "1f353981-89e2-47cd-b49b-64c8cc303b3f"      # line 247: teacher-provided final
F_REF_EXAMPLE_BASENAMES = (
    "【优质供稿-盖世汽车】理想汽车：见山见海见自己.md",
    "【优质供稿】具身智能的上下半场：一家中国车企的全栈突围.md",
)
F_FINAL_LEAD = "以下是终版媒体供稿，供你学习。"
F_DRAFT_V1_SENTINEL = "先由纯电撑住基盘"

# M group anchors (section numbers in the export, verified on 2026-09-06).
M_SECTION_TASK = 4          # teacher's original 8-point task
M_SECTION_DRAFT_V1 = 6      # assistant draft v1 (commented on in section 7)
M_SECTION_FEEDBACK_V1 = 7   # teacher's 6-point structural rejection
M_SECTION_DRAFT_V2 = 19     # teacher instruction + pasted then-current draft
M_SECTION_FINAL = 43        # brief task + i6 sample + official published MEGA draft
M_FINAL_MARKER = "以下是新一代理想MEGA新闻稿。"
M_V2_INSTRUCTION_MARKER = "以下是当前版本的新闻稿："
M_TASK_OPENING = "你需要为“新一代理想MEGA正式发布”撰写一篇新闻稿"
M_DRAFT_V1_SENTINEL = "打开侧滑门"
M_FEEDBACK_V1_OPENING = "修改意见"
M_OFFICIAL_STATEMENT = "挂在理想汽车官网"
M_CLOSING_SENTINEL = "给车和家赋予生命"

F_CLOSING_SENTINEL = "下一个交卷时间"


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class SourceRecord:
    group: str
    rel_path: str
    sha256: str
    size_bytes: int

    def as_dict(self) -> dict:
        return {
            "group": self.group,
            "rel_path": self.rel_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


def verify_sources(root: Path) -> dict[str, SourceRecord]:
    """Verify the corpus root against the registered hashes.

    Fails loudly on missing files, hash mismatch, size mismatch, unreadable
    JSONL, or unexpected extra business files. Never falls back to defaults.
    """
    if not root.is_dir():
        raise CorpusError(f"corpus root not found: {root}")
    records: dict[str, SourceRecord] = {}
    for group, rel, expected_sha, expected_size in CORPUS_SOURCES:
        path = root / rel
        if not path.is_file():
            raise CorpusError(f"corpus file missing: {rel}")
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            raise CorpusError(
                f"corpus file size mismatch: {rel} expected {expected_size} got {actual_size}"
            )
        actual_sha = sha256_file(path)
        if actual_sha != expected_sha:
            raise CorpusError(f"corpus file hash mismatch: {rel} got {actual_sha}")
        records[rel] = SourceRecord(group, rel, actual_sha, actual_size)
    # Reject unknown business files so a swapped corpus can never pass silently.
    expected_paths = {rel for _, rel, _, _ in CORPUS_SOURCES}
    for path in sorted(root.rglob("*")):
        if path.is_dir() or path.name in IGNORED_NAMES:
            continue
        rel = path.relative_to(root).as_posix()
        if rel not in expected_paths:
            raise CorpusError(f"unexpected corpus file: {rel}")
    # JSONL must be fully parseable.
    jsonl_rel = next(rel for g, rel, _, _ in CORPUS_SOURCES if rel.endswith(".jsonl"))
    with open(root / jsonl_rel, encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                raise CorpusError(f"corpus JSONL line {lineno} unparseable: {exc}") from exc
    return records


_LINE_NUMBER_PREFIX = re.compile(r"^\s*\d+\t", re.M)


def strip_line_number_prefixes(text: str) -> str:
    """Remove Read-tool line number prefixes from captured file content."""
    return _LINE_NUMBER_PREFIX.sub("", text)


_DELIVERY_META_MARKERS = ("核对结论", "核对卡：", "可修改正文：", "上一稿保留在")


def strip_delivery_meta(text: str) -> str:
    """Cut the agent's delivery meta tail, keeping only the article body.

    The delivery messages end with a 核对结论/核对卡 block (sometimes behind a
    ``---`` separator). Bad cases must contain only the article the teacher
    actually commented on. Fails when no meta marker is found — the corpora
    always deliver with a check card, so its absence means the anchor moved.
    """
    cut = len(text)
    for marker in _DELIVERY_META_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            # Cut at the start of the marker's line so bold/quote prefixes and
            # separator lines before it never leak into the article body.
            line_start = text.rfind("\n", 0, idx) + 1
            cut = min(cut, line_start)
    if cut == len(text):
        raise CorpusError("delivery meta marker not found; draft anchor may have moved")
    body = text[:cut].rstrip()
    # A delivery check-card tail is always short relative to the article it
    # accompanies; if the cut would remove a third or more of the text, the
    # marker was hit inside the article body — fail instead of truncating.
    if len(text) - len(body) > len(text) / 3:
        raise CorpusError("delivery meta cut would remove more than a third of the text")
    body = re.sub(r"(?:\n-{3,}\s*)+$", "", body).rstrip()
    return body.strip()


_WINDOWS_PATH = re.compile(r"[A-Za-z]:[\\/][^\s\"'（()）\n]*")
# Drive-less relative Windows paths (e.g. 知识库\新闻稿\2026文件夹) also leak
# the teacher's workspace layout; the production scanner does not catch them.
_RELATIVE_BACKSLASH_PATH = re.compile(r"(?:[^\s\\/\"'（()）\n]{2,}\\){1,}[^\s\\/\"'（()）\n]{2,}")


def strip_host_paths(text: str) -> str:
    """Replace absolute and drive-relative host paths with their bare tail names.

    Business meaning is preserved (the material/folder name stays visible)
    while the teacher's workspace layout never enters public material.
    """
    def _basename(match: re.Match[str]) -> str:
        raw = match.group(0)
        tail = re.split(r"[\\/]", raw)[-1]
        return tail or raw

    cleaned = _WINDOWS_PATH.sub(_basename, text)
    cleaned = _RELATIVE_BACKSLASH_PATH.sub(_basename, cleaned)
    cleaned = re.sub(r"(?:^|[\s\"'`])(/Users/|/home/|~/)\S*", "", cleaned)
    return cleaned


def assert_public_text(text: str, *, label: str) -> str:
    """Run the production privacy scanner over a prepared public text."""
    category = rubric_rules.contains_private_content(text)
    if category is not None:
        raise CorpusError(f"{label} still contains private content ({category}) after sanitizing")
    if not text.strip():
        raise CorpusError(f"{label} is empty after sanitizing")
    return text.strip()


@dataclass
class Provenance:
    """Machine-readable origin record for one extracted fragment."""

    source_rel: str
    locator: str
    sha256: str
    chars: int
    extraction: str
    sanitization: list[str] = field(default_factory=list)
    content_sha256: str = ""

    def as_dict(self) -> dict:
        data = {
            "source_rel": self.source_rel,
            "locator": self.locator,
            "sha256": self.sha256,
            "chars": self.chars,
            "extraction": self.extraction,
        }
        if self.content_sha256:
            data["content_sha256"] = self.content_sha256
        if self.sanitization:
            data["sanitization"] = list(self.sanitization)
        return data


# ---------------------------------------------------------------------------
# JSONL parsing (F group)
# ---------------------------------------------------------------------------

def load_jsonl_events(path: Path) -> list[dict]:
    events = []
    with open(path, encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise CorpusError(f"{path.name} line {lineno} unparseable: {exc}") from exc
    return events


def _event_text_blocks(event: dict) -> list[str]:
    content = event.get("message", {}).get("content")
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return []


def find_event_by_uuid(events: list[dict], uuid: str, *, expected_type: str) -> tuple[int, dict]:
    for idx, event in enumerate(events, 1):
        if event.get("uuid") == uuid:
            if event.get("type") != expected_type:
                raise CorpusError(
                    f"event {uuid} has type {event.get('type')!r}, expected {expected_type!r}"
                )
            return idx, event
    raise CorpusError(f"event uuid not found in corpus: {uuid}")


def find_read_tool_results(events: list[dict], basenames: tuple[str, ...]) -> dict[str, tuple[int, dict, str]]:
    """Pair Read tool_use calls with their tool_result payloads by tool_use_id."""
    wanted = {name: None for name in basenames}
    use_by_id: dict[str, str] = {}
    for idx, event in enumerate(events, 1):
        if event.get("type") != "assistant":
            continue
        for block in event.get("message", {}).get("content", []):
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if block.get("name") != "Read":
                continue
            file_path = str(block.get("input", {}).get("file_path", ""))
            for name in basenames:
                if file_path.replace("\\", "/").endswith(name):
                    use_by_id[block.get("id")] = name
    results: dict[str, tuple[int, dict, str]] = {}
    duplicate: set[str] = set()
    for idx, event in enumerate(events, 1):
        if event.get("type") != "user":
            continue
        content = event.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            name = use_by_id.get(block.get("tool_use_id"))
            if name is None:
                continue
            if name in results:
                # A re-read after revision would make "which version" ambiguous;
                # fail loudly instead of silently keeping a stale copy.
                duplicate.add(name)
                continue
            payload = block.get("content")
            text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
            results[name] = (idx, event, text)
    if duplicate:
        raise CorpusError(f"reference examples were read more than once, version ambiguous: {sorted(duplicate)}")
    missing = [name for name in basenames if name not in results]
    if missing:
        raise CorpusError(f"Read tool results not found for reference examples: {missing}")
    return results


# ---------------------------------------------------------------------------
# Markdown export parsing (M group)
# ---------------------------------------------------------------------------

_SECTION_HEADER = re.compile(r"^## (\d+)\. 【(?P<role>[^】]+)】(?:\s*`(?P<ts>[^`]*)`)?")
_ANNOTATION_PREFIX = "> 【"


@dataclass(frozen=True)
class ExportSection:
    number: int
    role: str
    timestamp: str | None
    start_line: int
    body_lines: tuple[str, ...]
    annotation_lines: tuple[str, ...]

    @property
    def teacher_text(self) -> str:
        """Body text with exporter annotations and separators removed."""
        kept = [line for line in self.body_lines if line.strip() != "---"]
        return "\n".join(kept).strip()


def load_export_sections(path: Path) -> list[ExportSection]:
    lines = path.read_text(encoding="utf-8").splitlines()
    marks: list[tuple[int, int, str, str | None]] = []
    for idx, line in enumerate(lines):
        match = _SECTION_HEADER.match(line)
        if match:
            marks.append((idx, int(match.group(1)), match.group("role").strip(), match.group("ts")))
    if not marks:
        raise CorpusError(f"no numbered sections found in export: {path.name}")
    numbers = [m[1] for m in marks]
    if numbers != sorted(numbers) or len(set(numbers)) != len(numbers):
        raise CorpusError("export section numbers are not strictly increasing and unique")
    sections: list[ExportSection] = []
    for pos, (line_idx, number, role, ts) in enumerate(marks):
        end = marks[pos + 1][0] if pos + 1 < len(marks) else len(lines)
        chunk = lines[line_idx + 1 : end]
        body = tuple(l for l in chunk if not l.startswith(_ANNOTATION_PREFIX))
        notes = tuple(l for l in chunk if l.startswith(_ANNOTATION_PREFIX))
        sections.append(ExportSection(number, role, ts, line_idx + 1, body, notes))
    return sections


def get_section(sections: list[ExportSection], number: int) -> ExportSection:
    for section in sections:
        if section.number == number:
            return section
    raise CorpusError(f"export section {number} not found")


def require_role(section: ExportSection, keyword: str) -> None:
    if keyword not in section.role:
        raise CorpusError(
            f"section {section.number} role is {section.role!r}, expected to contain {keyword!r}"
        )


def split_at_marker(text: str, marker: str, *, label: str) -> tuple[str, str]:
    occurrences = text.count(marker)
    if occurrences == 0:
        raise CorpusError(f"{label}: marker not found: {marker!r}")
    if occurrences > 1:
        raise CorpusError(f"{label}: marker appears {occurrences} times, expected exactly 1: {marker!r}")
    idx = text.find(marker)
    return text[:idx].strip(), text[idx + len(marker) :].strip()


# ---------------------------------------------------------------------------
# Case bundle
# ---------------------------------------------------------------------------

@dataclass
class CaseBundle:
    case_id: str
    title: str
    group: str
    derived: bool
    case: dict                      # BatchUploadRequest CaseIn-compatible payload
    provenance: dict[str, Provenance | list[Provenance]]
    limitations: list[str]
    notes: list[str]
    parent_case_id: str | None = None
    mutation: str | None = None


def _prov(source: SourceRecord, locator: str, text: str, extraction: str,
          sanitization: list[str] | None = None) -> Provenance:
    return Provenance(source.rel_path, locator, source.sha256, len(text), extraction,
                      sanitization or [],
                      content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())


def _prepare(text: str, label: str, *, strip_paths: bool = True) -> tuple[str, list[str]]:
    applied: list[str] = []
    if strip_paths:
        new_text = strip_host_paths(text)
        if new_text != text:
            applied.append("host_paths_replaced_with_basenames")
        text = new_text
    text = assert_public_text(text, label=label)
    return text, applied


# ---------------------------------------------------------------------------
# F case: 财报媒体供稿
# ---------------------------------------------------------------------------

F_TITLE = "理想汽车2026年第二季度财报媒体供稿"
F_TASK_PROMPT = (
    "基于理想汽车2026年第二季度财报的官方新闻稿与媒体沟通文档，撰写一篇可直接发布的媒体供稿："
    "先立住鲜明的分析观点，再让每一个信息点都服务于文章主旨，形成媒体供稿风格的深度分析，"
    "而不是罗列事实。"
)


def build_f_case(records: dict[str, SourceRecord], root: Path) -> CaseBundle:
    jsonl_rel = f"{F_DIR}/理想汽车供稿-对话上下文-原始记录-2026-08-27.jsonl"
    jsonl_src = records[jsonl_rel]
    events = load_jsonl_events(root / jsonl_rel)

    # Teacher feedback rejecting draft v1.
    fb_line, fb_event = find_event_by_uuid(events, F_UUID_FEEDBACK_V1, expected_type="user")
    if (fb_event.get("origin") or {}).get("kind") != "human":
        raise CorpusError("F feedback event is not a human-origin message")
    feedback_text = "\n".join(_event_text_blocks(fb_event)).strip()
    if not feedback_text:
        raise CorpusError("F feedback event has no text")

    # Draft v1 (the article actually commented on).
    d1_line, d1_event = find_event_by_uuid(events, F_UUID_DRAFT_V1, expected_type="assistant")
    draft_v1_raw = "\n".join(_event_text_blocks(d1_event)).strip()
    draft_v1 = strip_delivery_meta(draft_v1_raw)
    if F_DRAFT_V1_SENTINEL not in draft_v1:
        raise CorpusError("F draft v1 does not contain the section the teacher rejected")

    # Teacher-provided final media piece (full text, no truncation).
    fin_line, fin_event = find_event_by_uuid(events, F_UUID_FINAL, expected_type="user")
    if (fin_event.get("origin") or {}).get("kind") != "human":
        raise CorpusError("F final-draft event is not a human-origin message")
    final_raw = "\n".join(_event_text_blocks(fin_event)).strip()
    if not final_raw.startswith(F_FINAL_LEAD):
        raise CorpusError("F final-draft lead sentence changed; extraction anchor invalid")
    final_body = final_raw[len(F_FINAL_LEAD) :].strip()
    if F_CLOSING_SENTINEL not in final_body[-400:]:
        raise CorpusError("F final draft looks truncated; closing sentence missing")

    # Reference examples read by the agent during the session.
    ref_results = find_read_tool_results(events, F_REF_EXAMPLE_BASENAMES)

    # Memory materials: the two teacher-supplied business documents.
    press_rel = f"{F_DIR}/【新闻稿】理想汽车公布2026年第二季度财报.md"
    doc_rel = f"{F_DIR}/理想汽车2026年第二季度财报-媒体沟通文档.md"
    press_text = (root / press_rel).read_text(encoding="utf-8")
    doc_text = (root / doc_rel).read_text(encoding="utf-8")

    provenance: dict[str, Provenance | list[Provenance]] = {}
    ref_examples = []
    for i, name in enumerate(F_REF_EXAMPLE_BASENAMES, 1):
        line_no, _event, raw = ref_results[name]
        body = strip_line_number_prefixes(raw).strip()
        body, san = _prepare(body, f"F reference example {name}")
        ref_examples.append({
            "client_ref_id": f"f-ref-example-{i}",
            "source_name": name,
            "content_text": body,
        })
        provenance.setdefault("reference_examples", []).append(
            _prov(jsonl_src, f"Read tool_result line {line_no} for {name}", body,
                  "tool_result paired to Read tool_use by tool_use_id",
                  san + ["line_number_prefixes_stripped"]))

    fb_clean, fb_san = _prepare(feedback_text, "F teacher feedback")
    d1_clean, d1_san = _prepare(draft_v1, "F draft v1")
    fin_clean, fin_san = _prepare(final_body, "F final draft")
    press_clean, press_san = _prepare(press_text, "F press release attachment")
    doc_clean, doc_san = _prepare(doc_text, "F media communication document")

    case = {
        "client_case_id": "m0-real-f-financial-report",
        "title": F_TITLE,
        "task_prompt": F_TASK_PROMPT,
        "reference_examples": ref_examples,
        "bad_cases": [
            {
                "content_text": d1_clean,
                "teacher_feedback_texts": [fb_clean],
                "reason_summary": (
                    "老师否定初稿：i8 上市时点与季度贡献关系错位、"
                    "“延展产品生命周期”表述有误导、缺少 25 年纯电上市为换代做准备的前置因果，"
                    "整体像罗列事实、缺乏深度分析与鲜明观点，不符合媒体供稿风格。"
                ),
            }
        ],
        "reference_answer": fin_clean,
        "memory_materials": [
            {
                "client_ref_id": "f-mem-press-release",
                "source_label": "【新闻稿】理想汽车公布2026年第二季度财报.md",
                "content_text": press_clean,
            },
            {
                "client_ref_id": "f-mem-media-doc",
                "source_label": "理想汽车2026年第二季度财报-媒体沟通文档.md",
                "content_text": doc_clean,
            },
        ],
    }

    provenance["title"] = _prov(jsonl_src, "derived", F_TITLE,
                                "从会话上下文提炼的任务标题，非老师逐字原话")
    provenance["task_prompt"] = _prov(jsonl_src, "derived", F_TASK_PROMPT,
                                      "从会话上下文（技能启动、所读材料与老师反馈）提炼的任务摘要，非老师逐字原话")
    provenance["bad_case_v1"] = _prov(jsonl_src, f"assistant uuid {F_UUID_DRAFT_V1} (line {d1_line})",
                                      d1_clean, "delivery 正文，已剥离核对结论/核对卡尾部元信息", d1_san)
    provenance["feedback_v1"] = _prov(jsonl_src, f"human uuid {F_UUID_FEEDBACK_V1} (line {fb_line})",
                                      fb_clean, "老师原话全文", fb_san)
    provenance["reference_answer"] = _prov(jsonl_src, f"human uuid {F_UUID_FINAL} (line {fin_line})",
                                           fin_clean,
                                           "老师提供的终版供稿全文（未截断），已剥离引导句“以下是终版媒体供稿，供你学习。”",
                                           fin_san)
    provenance["memory_press_release"] = _prov(records[press_rel], "whole file", press_clean,
                                               "附件全文", press_san)
    provenance["memory_media_doc"] = _prov(records[doc_rel], "whole file", doc_clean,
                                           "附件全文", doc_san)

    return CaseBundle(
        case_id=case["client_case_id"],
        title=F_TITLE,
        group="F",
        derived=False,
        case=case,
        provenance=provenance,
        limitations=[
            "会话中未读取到老师逐字下达的任务指令，title/task_prompt 为上下文提炼并已标记 derived。",
            "助手在反馈后交付过二稿（line 242），但 line 243-246 无任何老师反馈事件，"
            "老师以直接提供终版供稿（line 247）回应；二稿没有实际否定反馈可配对，不纳入 bad_cases。",
        ],
        notes=[
            "bad case 与反馈按 uuid 严格配对：反馈评论的正是 line 141 交付的初稿。",
            "终版供稿保留老师原文全文 2300+ 字符，未做前 800 字截断。",
            "reason_summary 为从配对反馈提炼的概括，非老师逐字原话；老师原话全文保留在 teacher_feedback_texts。",
        ],
    )


# ---------------------------------------------------------------------------
# M case: 新一代理想MEGA新闻稿
# ---------------------------------------------------------------------------

M_TITLE = "新一代理想MEGA正式发布新闻稿"


def build_m_case(records: dict[str, SourceRecord], root: Path) -> CaseBundle:
    export_rel = f"{M_DIR}/新一代理想MEGA新闻稿-完整对话导出（含思考）-20260903.md"
    export_src = records[export_rel]
    sections = load_export_sections(root / export_rel)

    # Task prompt: section 4, teacher role, annotations excluded.
    task_sec = get_section(sections, M_SECTION_TASK)
    require_role(task_sec, "老师")
    task_raw = task_sec.teacher_text
    if not task_raw.startswith(M_TASK_OPENING):
        raise CorpusError("M task section opening changed; extraction anchor invalid")
    task_text, task_san = _prepare(task_raw, "M task prompt")

    # Bad case v1: assistant draft in section 6, teacher rejection in section 7.
    draft_sec = get_section(sections, M_SECTION_DRAFT_V1)
    require_role(draft_sec, "馒头")
    draft_v1 = strip_delivery_meta(draft_sec.teacher_text)
    if M_DRAFT_V1_SENTINEL not in draft_v1:
        raise CorpusError("M draft v1 does not contain the phrasing the teacher rejected")
    fb1_sec = get_section(sections, M_SECTION_FEEDBACK_V1)
    require_role(fb1_sec, "老师")
    fb1_text, fb1_san = _prepare(fb1_sec.teacher_text, "M feedback v1")
    if not fb1_text.startswith(M_FEEDBACK_V1_OPENING):
        raise CorpusError("M feedback v1 opening changed; extraction anchor invalid")
    draft_v1_clean, d1_san = _prepare(draft_v1, "M draft v1")

    # Bad case v2: section 19 = teacher instruction + pasted then-current draft.
    v2_sec = get_section(sections, M_SECTION_DRAFT_V2)
    require_role(v2_sec, "老师")
    instruction_raw, pasted_raw = split_at_marker(
        v2_sec.teacher_text, M_V2_INSTRUCTION_MARKER, label="M section 19"
    )
    if not pasted_raw:
        raise CorpusError("M section 19 pasted draft is empty")
    fb2_text, fb2_san = _prepare(instruction_raw, "M feedback v2 instruction")
    draft_v2_clean, d2_san = _prepare(pasted_raw, "M draft v2 pasted")

    # Reference answer: official published MEGA draft inside section 43.
    final_sec = get_section(sections, M_SECTION_FINAL)
    require_role(final_sec, "老师")
    brief_part, mega_part = split_at_marker(
        final_sec.teacher_text, M_FINAL_MARKER, label="M section 43"
    )
    if M_OFFICIAL_STATEMENT not in brief_part:
        raise CorpusError("M section 43 does not carry the official-publication statement")
    if M_CLOSING_SENTINEL not in mega_part[-400:]:
        raise CorpusError("M final draft looks truncated; closing sentence missing")
    final_clean, fin_san = _prepare(mega_part, "M final draft")

    # Memory materials: the two attachments the teacher pointed the agent at.
    speech_rel = f"{M_DIR}/新一代理想MEGA讲稿-v2.md"
    guide_rel = f"{M_DIR}/新一代理想MEGA拍摄指引.md"
    speech_text, sp_san = _prepare(
        (root / speech_rel).read_text(encoding="utf-8"), "M speech v2 attachment")
    guide_text, gd_san = _prepare(
        (root / guide_rel).read_text(encoding="utf-8"), "M shooting guide attachment")

    case = {
        "client_case_id": "m0-real-m-mega-press-release",
        "title": M_TITLE,
        "task_prompt": task_text,
        "reference_examples": [],
        "bad_cases": [
            {
                "content_text": draft_v1_clean,
                "teacher_feedback_texts": [fb1_text],
                "reason_summary": (
                    "老师否定初稿结构与表达：要求按外观/座舱内饰/驾驶/智能与补能四板块重组、"
                    "信息与讲稿一致、认真构思每段总起和落点、去掉口语化表达和小标题。"
                ),
            },
            {
                "content_text": draft_v2_clean,
                "teacher_feedback_texts": [fb2_text],
                "reason_summary": (
                    "老师要求按 v2 讲稿刷新、在适当位置加入 170 座超充站升级为全 5C 超充站，"
                    "并明确对当时版本结尾不满意、结尾不再贴靠 5C 超充。"
                ),
            },
        ],
        "reference_answer": final_clean,
        "memory_materials": [
            {
                "client_ref_id": "m-mem-speech-v2",
                "source_label": "新一代理想MEGA讲稿-v2.md",
                "content_text": speech_text,
            },
            {
                "client_ref_id": "m-mem-shooting-guide",
                "source_label": "新一代理想MEGA拍摄指引.md",
                "content_text": guide_text,
            },
        ],
    }

    provenance: dict[str, Provenance | list[Provenance]] = {
        "title": _prov(export_src, "derived", M_TITLE,
                       "从段落 4 老师任务原文提炼的标题"),
        "task_prompt": _prov(export_src, f"section {M_SECTION_TASK} (line {task_sec.start_line})",
                             task_text, "老师原话全文（8 条要求），导出注记已剔除", task_san),
        "bad_case_v1": _prov(export_src, f"section {M_SECTION_DRAFT_V1} (line {draft_sec.start_line})",
                             draft_v1_clean, "馒头交付初稿正文，已剥离核对结论/核对卡尾部元信息", d1_san),
        "feedback_v1": _prov(export_src, f"section {M_SECTION_FEEDBACK_V1} (line {fb1_sec.start_line})",
                             fb1_text, "老师原话全文（6 条修改意见）", fb1_san),
        "bad_case_v2": _prov(export_src, f"section {M_SECTION_DRAFT_V2} (line {v2_sec.start_line})",
                             draft_v2_clean, "老师粘贴的当时版本新闻稿（按标记句切分）", d2_san),
        "feedback_v2": _prov(export_src, f"section {M_SECTION_DRAFT_V2} (line {v2_sec.start_line})",
                             fb2_text, "老师指令原文（v2 刷新 + 170 座全 5C + 结尾不满意）", fb2_san),
        "reference_answer": _prov(export_src, f"section {M_SECTION_FINAL} (line {final_sec.start_line})",
                                  final_clean,
                                  "老师声明为官网挂出、总部通发的 MEGA 新闻稿全文（未截断），"
                                  "与同段区域简讯任务及 i6 简讯样例分离", fin_san),
        "memory_speech_v2": _prov(records[speech_rel], "whole file", speech_text, "附件全文", sp_san),
        "memory_shooting_guide": _prov(records[guide_rel], "whole file", guide_text, "附件全文", gd_san),
    }

    return CaseBundle(
        case_id=case["client_case_id"],
        title=M_TITLE,
        group="M",
        derived=False,
        case=case,
        provenance=provenance,
        limitations=[
            "语料仅含 v2 讲稿；v3/v4/v5/v6 讲稿只在老师指令中被引用，正文缺失，"
            "不得声称已验证与 v6 全文一致，相关断言限定为“配置名称与所提供讲稿一致”。",
            "段落 4 引用的三篇 2026 新闻稿参考（全新L9/L8/i8后驱长续航）仅存在工具读取路径，"
            "正文未导出，故 reference_examples 为空，不伪造样例正文。",
            "区域简讯任务（段落 43 前半）与 i6 简讯样例属于同会话的另一个任务，"
            "其助手产出无老师认可证据，均不纳入本 case。",
            "政府邀请函任务（段落 25/27/29）为独立任务，不纳入本 case。",
        ],
        notes=[
            "两组 bad case 均与老师实际反馈按段落严格配对；反馈评论对象即所贴稿件。",
            "终稿以老师明确声明（官网挂出、总部通发）为认可证据。",
            "导出器插入的思考过程/工具注记与系统上下文摘要段落一律不进入老师要求；"
            "老师段落中独立成行的导出分隔线（---）在提取时移除。",
            "reason_summary 为从配对反馈提炼的概括，非老师逐字原话；老师原话全文保留在 teacher_feedback_texts。",
        ],
    )


# ---------------------------------------------------------------------------
# Derived counter-examples (single-point mutations, clearly labeled)
# ---------------------------------------------------------------------------

import copy  # noqa: E402


def build_derived_cases(f_case: CaseBundle, m_case: CaseBundle) -> list[CaseBundle]:
    """Single-point mutations of the real cases; never overwrite real cases."""
    derived: list[CaseBundle] = []

    # D1: truncated reference answer (the old 800-char shortcut must fail loudly).
    m_mut = copy.deepcopy(m_case.case)
    m_mut["client_case_id"] = "m0-derived-m-truncated-answer"
    m_mut["reference_answer"] = m_case.case["reference_answer"][:800]
    derived.append(CaseBundle(
        case_id=m_mut["client_case_id"],
        title=m_case.title,
        group="M",
        derived=True,
        case=m_mut,
        provenance={},
        limitations=[],
        notes=[],
        parent_case_id=m_case.case_id,
        mutation="reference_answer 截断为前 800 字符",
    ))

    # D2: feedback unbound from the draft it actually rejected (cross-binding).
    f_mut = copy.deepcopy(f_case.case)
    f_mut["client_case_id"] = "m0-derived-f-unbound-feedback"
    f_mut["bad_cases"][0]["teacher_feedback_texts"] = [
        "初稿不好，重写。"
    ]
    derived.append(CaseBundle(
        case_id=f_mut["client_case_id"],
        title=f_case.title,
        group="F",
        derived=True,
        case=f_mut,
        provenance={},
        limitations=[],
        notes=[],
        parent_case_id=f_case.case_id,
        mutation="bad case 反馈替换为无实义的编造句，脱离原稿件的具体否定理由",
    ))

    # D3: v2 material mislabeled as v6 (version-gap fabrication).
    m_mut3 = copy.deepcopy(m_case.case)
    m_mut3["client_case_id"] = "m0-derived-m-version-fabrication"
    m_mut3["memory_materials"][0]["source_label"] = "新一代理想MEGA讲稿-v6.md"
    derived.append(CaseBundle(
        case_id=m_mut3["client_case_id"],
        title=m_case.title,
        group="M",
        derived=True,
        case=m_mut3,
        provenance={},
        limitations=[],
        notes=[],
        parent_case_id=m_case.case_id,
        mutation="v2 讲稿被标注为 v6；语料中不存在 v6 正文，预期版本时点校验失败",
    ))

    # D4: assistant thinking/tool note smuggled into teacher feedback.
    f_mut4 = copy.deepcopy(f_case.case)
    f_mut4["client_case_id"] = "m0-derived-f-thinking-as-teacher"
    f_mut4["bad_cases"][0]["teacher_feedback_texts"] = [
        "> 【思考过程 · 未落盘】 — 本轮存在思考过程，但会话记录中该字段仅保留加密签名。"
    ]
    derived.append(CaseBundle(
        case_id=f_mut4["client_case_id"],
        title=f_case.title,
        group="F",
        derived=True,
        case=f_mut4,
        provenance={},
        limitations=[],
        notes=[],
        parent_case_id=f_case.case_id,
        mutation="导出器思考注记冒充老师反馈；预期角色隔离校验失败",
    ))

    # D5: host path left in public material (privacy scanner must reject).
    m_mut5 = copy.deepcopy(m_case.case)
    m_mut5["client_case_id"] = "m0-derived-m-host-path-leak"
    m_mut5["task_prompt"] = (
        "参考 D:\\示例工作区\\示例知识库\\示例讲稿.md 撰写新闻稿。"
    )
    derived.append(CaseBundle(
        case_id=m_mut5["client_case_id"],
        title=m_case.title,
        group="M",
        derived=True,
        case=m_mut5,
        provenance={},
        limitations=[],
        notes=[],
        parent_case_id=m_case.case_id,
        mutation="task_prompt 注入虚构 Windows 主机路径（D:\\示例工作区\\…，非真实语料路径）；"
                 "预期 rubric_rules 隐私校验拒绝",
    ))

    # D6: cross-question contamination (F answer swapped into M case).
    m_mut6 = copy.deepcopy(m_case.case)
    m_mut6["client_case_id"] = "m0-derived-m-cross-question-answer"
    m_mut6["reference_answer"] = f_case.case["reference_answer"]
    derived.append(CaseBundle(
        case_id=m_mut6["client_case_id"],
        title=m_case.title,
        group="M",
        derived=True,
        case=m_mut6,
        provenance={},
        limitations=[],
        notes=[],
        parent_case_id=m_case.case_id,
        mutation="reference_answer 替换为 F 题终稿；预期本题隔离/引用校验失败",
    ))

    return derived


# ---------------------------------------------------------------------------
# Independent expectations (fixed BEFORE any generator run)
# ---------------------------------------------------------------------------

def build_expectations(f_case: CaseBundle, m_case: CaseBundle,
                       derived: list[CaseBundle]) -> dict:
    return {
        "policy": "expectations 在运行任何待测生成器之前固定；生成器输出不得回写为 golden。",
        "real_cases": [
            {
                "case_id": f_case.case_id,
                "checks": [
                    {"id": "f-anchor-i8-timing",
                     "expect": "生成的维度或依据若涉及 i8 后驱长续航版，必须与老师反馈一致："
                               "8 月上市、不构成二季度销量支撑、应归入下半年纯电接棒；"
                               "把 i8 上市写成二季度支撑属于错误。",
                     "basis": "feedback_v1 原话（uuid 715cfb28）"},
                    {"id": "f-forbidden-phrase",
                     "expect": "“延展产品生命周期”被老师明确否定；生成结果不得将其作为正面表达建议。",
                     "basis": "feedback_v1 原话"},
                    {"id": "f-depth-over-listing",
                     "expect": "应存在体现“深度分析/鲜明观点/信息点服务主旨”的维度或依据，"
                               "来源归类为老师明确要求，而非 AI 推定。",
                     "basis": "feedback_v1 原话"},
                    {"id": "f-answer-completeness",
                     "expect": "reference_answer 为终版供稿全文（2300+ 字符），任何以截断版本为完整"
                               "答案的断言均失败。",
                     "basis": "reference_answer 来源 uuid 1f353981"},
                    {"id": "f-material-grounding",
                     "expect": "财报数字类依据（交付 98,330 辆、营收 257 亿元、毛利率 11.0% 等）"
                               "必须能在新闻稿/媒体沟通文档材料中定位，不得虚构来源。",
                     "basis": "memory_materials 两个附件"},
                ],
            },
            {
                "case_id": m_case.case_id,
                "checks": [
                    {"id": "m-four-section-structure",
                     "expect": "应存在体现四板块结构（外观/座舱内饰/驾驶/智能辅助驾驶+5C超充与网络）"
                               "且与讲稿一致的维度或依据，来源归类为老师明确要求。",
                     "basis": "feedback_v1（段落 7）与 task_prompt（段落 4）"},
                    {"id": "m-no-colloquial",
                     "expect": "“打开侧滑门”“客厅主灯”“后舱可以工作也可以聚餐”等被点名的口语化表达"
                               "不得作为正面建议；应有书面化/官方克制语言相关维度。",
                     "basis": "feedback_v1（段落 7）第 5、6 条与 task_prompt 第 4 条"},
                    {"id": "m-restrained-official-tone",
                     "expect": "官方新闻稿语言克制、不自吹自擂的要求应可追溯到老师原话。",
                     "basis": "task_prompt（段落 4）第 4 条"},
                    {"id": "m-speech-over-guide",
                     "expect": "讲稿与拍摄指引冲突时以讲稿为准的要求应被保留为老师明确要求。",
                     "basis": "task_prompt（段落 4）第 5 条"},
                    {"id": "m-placeholder-policy",
                     "expect": "价格、配置用占位符替代；终稿中 XX 占位符属于老师明确规则，"
                               "不得被判为缺陷，也不得被补写为具体数字。",
                     "basis": "task_prompt（段落 4）第 3 条与 reference_answer 原文"},
                    {"id": "m-ending-rework",
                     "expect": "结尾要求经历多次反馈（不贴靠5C、另起段落或放导语、调性学习 L8/L9），"
                               "最终终稿结尾不含“贴靠5C”的旧写法；引用结尾要求时必须使用有效时点。",
                     "basis": "feedback_v2（段落 19）、段落 23 老师原话、reference_answer"},
                    {"id": "m-170-5c-upgrade",
                     "expect": "“170 座超充站升级为全 5C 超充站”是老师明确要求加入的信息点。",
                     "basis": "feedback_v2（段落 19）"},
                    {"id": "m-v6-limitation",
                     "expect": "语料仅有 v2 讲稿正文；任何声称验证了 v6 全文一致性的断言失败，"
                               "配置名称一致性断言只能限定在所提供讲稿范围内。",
                     "basis": "limitations：v3-v6 正文缺失"},
                    {"id": "m-answer-completeness",
                     "expect": "reference_answer 为官网通发全文（4300+ 字符），以“给车和家赋予生命”"
                               "收尾；截断版本不得作为完整答案。",
                     "basis": "reference_answer（段落 43）"},
                    {"id": "m-no-cross-task-mixing",
                     "expect": "区域简讯任务、i6 简讯样例与政府邀请函要求不得混入 MEGA 新闻稿题的"
                               "维度或依据。",
                     "basis": "limitations：同会话多任务分离"},
                ],
            },
        ],
        "derived_cases": [
            {
                "case_id": d.case_id,
                "parent_case_id": d.parent_case_id,
                "mutation": d.mutation,
                "expect": _derived_expectation(d.case_id),
            }
            for d in derived
        ],
    }


def _derived_expectation(case_id: str) -> str:
    table = {
        "m0-derived-m-truncated-answer": "完整性校验必须失败：终稿缺少结尾句，不得作为 golden 使用。",
        "m0-derived-f-unbound-feedback": "反馈-稿件配对校验必须失败：反馈与具体稿件内容无可核查关联。",
        "m0-derived-m-version-fabrication": "版本时点校验必须失败：v6 正文不存在，标注即伪造。",
        "m0-derived-f-thinking-as-teacher": "角色隔离校验必须失败：思考/工具注记不得成为老师要求。",
        "m0-derived-m-host-path-leak": "隐私校验必须拒绝：主机路径不得进入公开材料。",
        "m0-derived-m-cross-question-answer": "本题隔离校验必须失败：F 题终稿不得充当 M 题标准答案。",
    }
    return table[case_id]


# ---------------------------------------------------------------------------
# Batch assembly and CLI
# ---------------------------------------------------------------------------

def build_manifest(bundles: list[CaseBundle], records: dict[str, SourceRecord]) -> dict:
    return {
        "corpus_root_policy": "read-only; sources verified by sha256 before and after extraction",
        "sources": [rec.as_dict() for rec in records.values()],
        "cases": [
            {
                "case_id": b.case_id,
                "group": b.group,
                "derived": b.derived,
                "parent_case_id": b.parent_case_id,
                "mutation": b.mutation,
                "title": b.title,
                "limitations": b.limitations,
                "notes": b.notes,
                "provenance": {
                    key: ([p.as_dict() for p in value] if isinstance(value, list) else value.as_dict())
                    for key, value in b.provenance.items()
                },
            }
            for b in bundles
        ],
    }


def build_batch(real_bundles: list[CaseBundle], command_id: str) -> dict:
    return {
        "schema_version": "1.0",
        "command_id": command_id,
        "cases": [b.case for b in real_bundles],
    }


def redacted_summary(bundles: list[CaseBundle]) -> list[dict]:
    out = []
    for b in bundles:
        case = b.case
        out.append({
            "case_id": b.case_id,
            "group": b.group,
            "derived": b.derived,
            "title_chars": len(case["title"]),
            "task_prompt_chars": len(case["task_prompt"]),
            "reference_examples": len(case["reference_examples"]),
            "bad_cases": len(case["bad_cases"]),
            "reference_answer_chars": len(case["reference_answer"]),
            "memory_materials": len(case["memory_materials"]),
        })
    return out


def run_extraction(source_root: Path, out_dir: Path, command_id: str) -> dict:
    source_root = source_root.resolve()
    out_dir = out_dir.resolve()
    if out_dir == source_root or source_root in out_dir.parents:
        raise CorpusError("output directory must not live inside the read-only corpus root")
    records = verify_sources(source_root)
    f_case = build_f_case(records, source_root)
    m_case = build_m_case(records, source_root)
    derived = build_derived_cases(f_case, m_case)
    real = [f_case, m_case]

    batch = build_batch(real, command_id)
    manifest = build_manifest(real + derived, records)
    expectations = build_expectations(f_case, m_case, derived)
    derived_payload = {
        "policy": "derived cases 是真实 case 的单点变异，只用于负例校验，不得上传为真实题目。",
        "cases": [d.case for d in derived],
    }

    # Sources must be untouched after extraction.
    after = verify_sources(source_root)
    if {k: v.sha256 for k, v in records.items()} != {k: v.sha256 for k, v in after.items()}:
        raise CorpusError("source hashes changed during extraction")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "batch.json").write_text(
        json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "expectations.json").write_text(
        json.dumps(expectations, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "derived_cases.json").write_text(
        json.dumps(derived_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "sources_verified": len(records),
        "batch_cases": len(batch["cases"]),
        "derived_cases": len(derived_payload["cases"]),
        "expectation_checks": sum(len(c["checks"]) for c in expectations["real_cases"]),
        "summary": redacted_summary(real + derived),
        "outputs": sorted(str(p.relative_to(out_dir)) for p in out_dir.iterdir()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source-root",
        default="/Users/hsikey/Company/skill-eval-platform/.local-samples/m0",
        help="read-only corpus root containing the two group directories",
    )
    parser.add_argument(
        "--out",
        default="storage/acceptance/m0-real-samples",
        help="output directory for private fixtures (gitignored)",
    )
    parser.add_argument(
        "--command-id",
        default="m0-real-samples-rebuild",
        help="batch command id (per-run values are allowed)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="only verify corpus hashes; do not extract",
    )
    args = parser.parse_args(argv)

    source_root = Path(args.source_root)
    try:
        if args.verify_only:
            records = verify_sources(source_root)
            print(f"M0_SAMPLES_VERIFY=OK sources={len(records)}")
            for rel, rec in sorted(records.items()):
                print(f"  {rec.group} {rel} sha256={rec.sha256[:16]}… bytes={rec.size_bytes}")
            return 0
        result = run_extraction(source_root, Path(args.out), args.command_id)
    except CorpusError as exc:
        print(f"M0_SAMPLES=FAIL {exc}", file=sys.stderr)
        return 1

    print(f"M0_SAMPLES=OK sources={result['sources_verified']} "
          f"batch_cases={result['batch_cases']} derived={result['derived_cases']} "
          f"expectation_checks={result['expectation_checks']}")
    for row in result["summary"]:
        print("  " + json.dumps(row, ensure_ascii=False))
    print("outputs:", ", ".join(result["outputs"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
