"""Deterministic rubric and privacy rules shared by API validation and AI output checks.

These functions are pure: they raise ``ValueError`` with stable messages and
never depend on HTTP or database layers, so the worker can reuse them when
validating AI-generated criteria.
"""

from __future__ import annotations

import re
import unicodedata

# Minimum actionable length for a criterion. Shared by the admin patch schema
# and the AI output normalizer so both paths enforce the same floor.
MIN_CRITERION_LENGTH = 8

_VAGUE_CRITERION_LABELS = {
    "准确性",
    "准确性高",
    "内容准确",
    "创新性",
    "创新",
    "内容质量好",
    "质量好",
    "完整性",
    "完整性高",
    "可读性",
    "逻辑性",
    "专业性",
    "实用性",
    "规范性",
    "一致性",
    "及时性",
    "安全性",
    "合规性",
    "内容完整",
    "表达流畅",
    "逻辑清晰",
    "符合要求",
    "满足要求",
    "高质量",
    "质量",
    "accuracy",
    "creativity",
    "quality",
    "completeness",
    "relevance",
    "coherence",
    "professionalism",
}

_PRIVATE_TEXT_TERMS: tuple[tuple[str, str], ...] = (
    ("api_key", "凭证"),
    ("apikey", "凭证"),
    ("api key", "凭证"),
    ("access_token", "凭证"),
    ("access token", "凭证"),
    ("secret_key", "凭证"),
    ("private_key", "凭证"),
    ("-----begin", "凭证"),
    ("bearer ", "凭证"),
    ("password", "凭证"),
    ("passwd", "凭证"),
    ("密码", "凭证"),
    ("access key", "凭证"),
    ("secret key", "凭证"),
    ("private key", "凭证"),
    ("file://", "主机路径"),
    ("/users/", "主机路径"),
    ("/home/", "主机路径"),
    ("c:\\", "主机路径"),
    ("~/", "主机路径"),
    ("系统提示词", "系统控制内容"),
    ("系统指令", "系统控制内容"),
    ("system prompt", "系统控制内容"),
    ("<|im_start|>", "系统控制内容"),
    ("私有推理", "内部运行信息"),
)

_HOME_PATH_PATTERN = re.compile(r"(?:^|[\s\"'`])(/Users/|/home/|~/|C:\\)", re.IGNORECASE)

# Windows drive letters and UNC shares, plus high-signal secret value shapes.
_DRIVE_OR_UNC_PATTERN = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\\S)", re.ASCII)
_SECRET_VALUE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "凭证"),
    (re.compile(r"sep_[A-Za-z0-9_\-]{16,}"), "凭证"),
    (re.compile(r"AKIA[0-9A-Z]{12,}"), "凭证"),
    (re.compile(r"LTAI[0-9A-Za-z]{12,}"), "凭证"),
    (re.compile(r"ssh-(?:rsa|ed25519|dss)\s+[A-Za-z0-9+/=]{32,}"), "凭证"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"), "凭证"),
)

# Zero-width and bidi/format characters that can split a keyword to dodge the
# substring scan. They carry no business meaning in uploaded material.
_INVISIBLE_CHARS = re.compile(
    "[\u200b\u200c\u200d\u2060\u2061\u2062\u2063\u2064\ufeff"
    "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u00ad]"
)


def _canonical_for_scan(text: str) -> str:
    """Normalize text before secret/path scanning.

    Applies NFKC (folds full-width homoglyphs), drops zero-width and bidi
    formatting characters, and casefolds. This is a detection aid only; the
    stored text is never rewritten.
    """

    folded = unicodedata.normalize("NFKC", text)
    folded = _INVISIBLE_CHARS.sub("", folded)
    return folded.casefold()


def contains_private_content(text: str) -> str | None:
    """Return the risk category when text contains obvious leaks, else None."""

    canonical = _canonical_for_scan(text)
    for term, category in _PRIVATE_TEXT_TERMS:
        if term in canonical:
            return category
    if _DRIVE_OR_UNC_PATTERN.search(text):
        return "主机路径"
    if _HOME_PATH_PATTERN.search(text):
        return "主机路径"
    for pattern, category in _SECRET_VALUE_PATTERNS:
        if pattern.search(text):
            return category
    return None


def validate_public_text(text: str, *, field_label: str) -> None:
    category = contains_private_content(text)
    if category is not None:
        raise ValueError(f"{field_label}包含不应上传的{category}。")


_VAGUE_WRAPPER_PATTERN = re.compile(
    r"[\s。.！!？?；;，,、：:·…—\-~～*#@\"'`“”‘’「」『』【】《》〈〉（）()\[\]{}<>]+"
)
_VAGUE_LIST_SPLIT = re.compile(r"[、，,;；/|&＆]+")


def _strip_label_wrapping(text: str) -> str:
    """Remove punctuation, brackets and quotes that can wrap an isolated label."""

    normalized = unicodedata.normalize("NFKC", text)
    return _VAGUE_WRAPPER_PATTERN.sub("", normalized).casefold()


def is_vague_criterion(criterion: str) -> bool:
    normalized = unicodedata.normalize("NFKC", criterion).casefold()
    # A bare list of vague labels ("准确性、创新性") is still vague.
    tokens = [token for token in _VAGUE_LIST_SPLIT.split(normalized) if token.strip()]
    if tokens and all(
        _strip_label_wrapping(token) in _VAGUE_CRITERION_LABELS for token in tokens
    ):
        return True
    return _strip_label_wrapping(criterion) in _VAGUE_CRITERION_LABELS


def validate_criterion_text(criterion: str) -> None:
    """Ensure a criterion is an actionable standard, not an isolated label."""

    stripped = criterion.strip()
    if not stripped:
        raise ValueError("评分标准不能为空白。")
    if len(stripped) < MIN_CRITERION_LENGTH:
        raise ValueError("评分标准过短，必须写明判断对象、合格表现和主要问题。")
    if is_vague_criterion(stripped):
        raise ValueError("评分标准不能只是孤立标签，必须写明判断对象、合格表现和主要问题。")
    validate_public_text(stripped, field_label="评分标准")


DIMENSION_MAX_SCORE = 10


def evaluate_question_pass(
    criteria: list[dict], scores: dict[str, int]
) -> bool:
    """Future scoring semantics: per-dimension AND, no cross-compensation.

    Every dimension is scored 0..10 and must reach its own ``pass_score``;
    any failing dimension fails the whole question regardless of other high
    scores. M0 stores the contract only — this function is the executable
    definition that future scoring must apply.
    """

    if not criteria:
        return False
    for item in criteria:
        criterion_id = item.get("id")
        pass_score = int(item.get("pass_score", 0))
        if not 0 <= pass_score <= DIMENSION_MAX_SCORE:
            return False
        raw_score = scores.get(criterion_id)
        if raw_score is None:
            return False
        score = int(raw_score)
        if not 0 <= score <= DIMENSION_MAX_SCORE:
            return False
        if score < pass_score:
            return False
    return True
