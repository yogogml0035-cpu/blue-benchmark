"""Deterministic tests for the M0 real-sample extraction module.

These tests use small SYNTHETIC corpora that mimic the structure of the two
real session exports. They never read the real corpus (that is the opt-in
rebuild flow) and never call any rubric generator.
"""

from __future__ import annotations

import json

import pytest

from scripts import m0_samples as m0


# ---------------------------------------------------------------------------
# Synthetic corpus builders
# ---------------------------------------------------------------------------

def _f_events() -> list[dict]:
    draft_v1 = (
        "# 测试初稿标题\n\n第一段正文，包含被否定的小节。"
        "填充句，让合成初稿正文足够长以通过元信息占比守卫。" * 3 + "\n\n"
        "## 被否定小节\n\n问题内容在这里。"
        "填充句，继续加长被否定小节的正文内容。" * 3 + "\n\n"
        "## 结语\n\n初稿收尾句。填充句，让结语段也有足够长度。\n\n"
        "---\n\n核对结论：可进入人工初审。字数约 100 字。\n\n"
        "核对卡：[delivery-check.md](.test/runs/x/delivery-check.md)"
    )
    final = (
        f"{m0.F_FINAL_LEAD}\n\n《测试终稿标题》\n\n"
        "终稿第一段，观点鲜明。\n\n终稿收尾段，节奏检验直到下一个交卷时间。"
    )
    ref_read_1 = "D:\\知识库\\媒体深度稿件\\参考样例一.md"
    ref_read_2 = "D:\\知识库\\媒体深度稿件\\参考样例二.md"
    return [
        {"type": "queue-operation", "operation": "enqueue"},
        {
            "type": "user",
            "uuid": "u-command",
            "origin": {"kind": "human"},
            "message": {"role": "user", "content": "<command-message>test-suite</command-message>"},
        },
        {
            "type": "user",
            "uuid": "u-skill",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Base directory for this skill: D:\\skills\\test"}],
            },
        },
        {
            "type": "assistant",
            "uuid": "a-read-1",
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t1", "name": "Read",
                             "input": {"file_path": ref_read_1}}],
            },
        },
        {
            "type": "user",
            "uuid": "u-read-1",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1",
                             "content": "1\t参考样例一第一行。\n2\t参考样例一第二行。"}],
            },
        },
        {
            "type": "assistant",
            "uuid": "a-read-2",
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t2", "name": "Read",
                             "input": {"file_path": ref_read_2}}],
            },
        },
        {
            "type": "user",
            "uuid": "u-read-2",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t2",
                             "content": "1\t参考样例二正文。\n2\t结尾行。"}],
            },
        },
        {
            "type": "assistant",
            "uuid": m0.F_UUID_DRAFT_V1,
            "message": {"role": "assistant",
                        "content": [{"type": "text", "text": draft_v1}]},
        },
        {
            "type": "user",
            "uuid": m0.F_UUID_FEEDBACK_V1,
            "origin": {"kind": "human"},
            "message": {
                "role": "user",
                "content": [{"type": "text",
                             "text": "“被否定小节”内容有问题：观点不鲜明，像罗列事实。"}],
            },
        },
        {
            "type": "assistant",
            "uuid": "a-draft-v2",
            "message": {"role": "assistant",
                        "content": [{"type": "text",
                                     "text": "# 二稿\n\n正文。\n\n核对结论：待确认。"}]},
        },
        {
            "type": "user",
            "uuid": m0.F_UUID_FINAL,
            "origin": {"kind": "human"},
            "message": {"role": "user", "content": [{"type": "text", "text": final}]},
        },
        {
            "type": "user",
            "uuid": "u-export",
            "origin": {"kind": "human"},
            "message": {"role": "user",
                        "content": [{"type": "text", "text": "一字不差地完整导出此次对话上下文。"}]},
        },
    ]


def _m_export_text() -> str:
    return "\n".join([
        "# 测试导出",
        "",
        "## 1. 【系统 / 技能载入】　`2026-08-27T00:00:00.000Z`",
        "",
        "Base directory for this skill: D:\\skills\\test",
        "",
        "## 4. 【老师提问 / 输入】　`2026-08-27T02:57:52.105Z`",
        "",
        "你需要为“新一代理想MEGA正式发布”撰写一篇新闻稿，篇幅不严格限制。",
        "",
        "1、参考讲稿（\"D:\\Agent工作区\\知识库\\讲稿-v2.md\"）和拍摄指引的信息。",
        "3、价格、配置用占位符替代。",
        "",
        "---",
        "",
        "> 【思考过程 · 未落盘】 `2026-08-27T02:57:59.958Z` — 思考正文未落盘。",
        "",
        "> 【工具调用】 `2026-08-27T02:58:20.060Z` — Read  file_path=D:\\Agent工作区\\知识库\\讲稿-v2.md",
        "",
        "## 6. 【馒头回复】　`2026-08-27T03:10:00.000Z`",
        "",
        "# **测试MEGA新闻稿初稿，零售价【XX】万元**",
        "",
        "打开侧滑门，迎宾光毯亮起。初稿正文段落。" + "填充句，让合成初稿正文足够长。" * 6,
        "",
        "收尾句。" + "收尾填充句，继续加长正文。" * 4,
        "",
        "**核对结论：有待确认项**",
        "",
        "两处需老师裁决：略。核对卡：[delivery-check.md](.test/runs/m/delivery-check.md)",
        "",
        "## 7. 【老师提问 / 输入】　`2026-08-27T03:20:00.000Z`",
        "",
        "修改意见：",
        "1、结构重新调整，主体分为四个板块，整体和讲稿保持一致。",
        "5、不要用“打开侧滑门”这种口语化表达。",
        "",
        "---",
        "",
        "> 【工具调用】 `2026-08-27T03:21:00.000Z` — Bash  command=echo test",
        "",
        "## 19. 【老师提问 / 输入】　`2026-08-28T01:00:00.000Z`",
        "",
        "D:\\Agent工作区\\知识库\\讲稿-v2.md",
        "根据最新讲稿修改新闻稿，请添加重要信息：170座超充站升级为全5C超充站。",
        "另外，结尾我不满意，重新调整。",
        "以下是当前版本的新闻稿：",
        "",
        "测试MEGA新闻稿二稿，零售价XX万元",
        "",
        "二稿正文，旧结尾贴靠5C超充。",
        "",
        "## 43. 【老师提问 / 输入】　`2026-09-03T01:00:00.000Z`",
        "",
        "以下新闻稿是挂在理想汽车官网并且作为公司总部通发媒体的新闻稿，",
        "现在要基于这一版变形成为区域简讯。可以参考理想i6的简讯。",
        "",
        "以下是新一代理想MEGA新闻稿。",
        "测试MEGA新闻稿终稿，零售价XX万元",
        "",
        "终稿正文段落。" + "终稿填充句，用于让合成终稿超过八百字符。" * 45,
        "",
        "结尾：持续为用户创造超越需求的产品与服务，给车和家赋予生命。",
        "",
        "## 44. 【馒头回复】　`2026-09-03T02:00:00.000Z`",
        "",
        "区域简讯回复（不属于新闻稿 case）。",
    ])


def _build_synthetic_corpus(root) -> None:
    f_dir = root / m0.F_DIR
    m_dir = root / m0.M_DIR
    f_dir.mkdir(parents=True)
    m_dir.mkdir(parents=True)
    (f_dir / "理想汽车供稿-对话上下文-原始记录-2026-08-27.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in _f_events()) + "\n",
        encoding="utf-8")
    (f_dir / "【新闻稿】理想汽车公布2026年第二季度财报.md").write_text(
        "**测试新闻稿附件**\n\n交付100辆，营收200亿元。\n", encoding="utf-8")
    (f_dir / "理想汽车2026年第二季度财报-媒体沟通文档.md").write_text(
        "# 测试媒体沟通文档\n\n沟通要点。\n", encoding="utf-8")
    (m_dir / "新一代理想MEGA新闻稿-完整对话导出（含思考）-20260903.md").write_text(
        _m_export_text(), encoding="utf-8")
    (m_dir / "新一代理想MEGA讲稿-v2.md").write_text("# 测试讲稿v2\n\n讲稿正文。\n", encoding="utf-8")
    (m_dir / "新一代理想MEGA拍摄指引.md").write_text("# 测试拍摄指引\n\n指引正文。\n", encoding="utf-8")


@pytest.fixture()
def synthetic_corpus(tmp_path, monkeypatch):
    root = tmp_path / "m0"
    _build_synthetic_corpus(root)
    sources = []
    for group, rel, _sha, _size in m0.CORPUS_SOURCES:
        path = root / rel
        sources.append((group, rel, m0.sha256_file(path), path.stat().st_size))
    monkeypatch.setattr(m0, "CORPUS_SOURCES", tuple(sources))
    # Synthetic reference-example basenames differ from the real corpus.
    monkeypatch.setattr(m0, "F_REF_EXAMPLE_BASENAMES", ("参考样例一.md", "参考样例二.md"))
    # The synthetic bad-case sentinel phrases.
    monkeypatch.setattr(m0, "F_CLOSING_SENTINEL", "下一个交卷时间")
    monkeypatch.setattr(m0, "F_DRAFT_V1_SENTINEL", "被否定小节")
    return root


# ---------------------------------------------------------------------------
# Corpus verification
# ---------------------------------------------------------------------------

def test_verify_sources_ok(synthetic_corpus):
    records = m0.verify_sources(synthetic_corpus)
    assert len(records) == 6
    assert {rec.group for rec in records.values()} == {"F", "M"}


def test_verify_sources_missing_root(tmp_path):
    with pytest.raises(m0.CorpusError, match="corpus root not found"):
        m0.verify_sources(tmp_path / "nope")


def test_verify_sources_missing_file(synthetic_corpus):
    (synthetic_corpus / m0.CORPUS_SOURCES[0][1]).unlink()
    with pytest.raises(m0.CorpusError, match="missing"):
        m0.verify_sources(synthetic_corpus)


def test_verify_sources_hash_mismatch(synthetic_corpus):
    path = synthetic_corpus / m0.CORPUS_SOURCES[1][1]
    path.write_text(path.read_text(encoding="utf-8") + "篡改", encoding="utf-8")
    with pytest.raises(m0.CorpusError, match="size mismatch|hash mismatch"):
        m0.verify_sources(synthetic_corpus)


def test_verify_sources_unexpected_file(synthetic_corpus):
    (synthetic_corpus / m0.F_DIR / "多余文件.md").write_text("x", encoding="utf-8")
    with pytest.raises(m0.CorpusError, match="unexpected corpus file"):
        m0.verify_sources(synthetic_corpus)


def test_verify_sources_bad_jsonl(synthetic_corpus, monkeypatch):
    path = synthetic_corpus / m0.CORPUS_SOURCES[0][1]
    path.write_text("{not json}\n", encoding="utf-8")
    # Re-register hashes so size/hash gates pass and the parse gate is reached.
    sources = tuple(
        (g, rel, m0.sha256_file(synthetic_corpus / rel),
         (synthetic_corpus / rel).stat().st_size)
        for g, rel, _sha, _size in m0.CORPUS_SOURCES
    )
    monkeypatch.setattr(m0, "CORPUS_SOURCES", sources)
    with pytest.raises(m0.CorpusError, match="unparseable"):
        m0.verify_sources(synthetic_corpus)


def test_verify_sources_ignores_ds_store(synthetic_corpus):
    (synthetic_corpus / ".DS_Store").write_bytes(b"\x00")
    assert len(m0.verify_sources(synthetic_corpus)) == 6


# ---------------------------------------------------------------------------
# Sanitizers
# ---------------------------------------------------------------------------

def test_strip_delivery_meta_variants():
    body1 = "正文开始，这是一段足够长的正文内容用于模拟真实稿件的主体部分。"
    body2 = "正文结束，这是第二段足够长的正文，保证正文远长于交付元信息尾部。"
    text = f"{body1}\n\n{body2}\n\n---\n\n核对结论：ok\n核对卡：[x](y)"
    assert m0.strip_delivery_meta(text) == f"{body1}\n\n{body2}"
    text2 = (
        f"{body1}\n\n{body2}\n\n"
        "**核对结论：有待确认项**\n\n裁决项。"
    )
    assert m0.strip_delivery_meta(text2) == f"{body1}\n\n{body2}"
    with pytest.raises(m0.CorpusError, match="meta marker not found"):
        m0.strip_delivery_meta("没有元信息的正文")


def test_strip_delivery_meta_rejects_midbody_marker():
    # A marker phrase quoted early inside the article must not silently
    # truncate it: the cut would remove more than a third of the text.
    text = (
        "正文开头就顺带提到了核对结论这个流程词，但这并不是交付元信息。\n\n"
        "后续正文段落继续展开，还有更多内容，第一段。\n\n"
        "第二段正文继续。\n\n再一段正文收尾。"
    )
    with pytest.raises(m0.CorpusError, match="more than a third"):
        m0.strip_delivery_meta(text)


def test_strip_delivery_meta_rejects_oversized_tail():
    text = "短。\n\n核对结论：非常长的元信息尾部\n" + "元信息填充。" * 20
    with pytest.raises(m0.CorpusError, match="more than a third"):
        m0.strip_delivery_meta(text)


def test_strip_line_number_prefixes():
    assert m0.strip_line_number_prefixes("1\t第一行\n2\t第二行\n") == "第一行\n第二行\n"
    # Content lines that merely start with digits are untouched.
    assert m0.strip_line_number_prefixes("2026年发布") == "2026年发布"


def test_strip_host_paths():
    text = '参考（"D:\\Agent工作区\\知识库\\讲稿-v2.md"）和 C:\\Users\\x\\文件.md 以及 /Users/me/notes.md'
    cleaned = m0.strip_host_paths(text)
    assert "D:\\" not in cleaned and "C:\\" not in cleaned and "/Users/" not in cleaned
    assert "讲稿-v2.md" in cleaned  # business meaning (file name) preserved


def test_strip_host_paths_drive_relative():
    text = "参考理想汽车知识库\\新闻稿\\2026文件夹中的三款产品新闻稿风格"
    cleaned = m0.strip_host_paths(text)
    assert "\\" not in cleaned
    assert "2026文件夹" in cleaned
    assert "知识库" not in cleaned


def test_assert_public_text_rejects_secrets():
    with pytest.raises(m0.CorpusError, match="private content"):
        m0.assert_public_text("access_token=abc123", label="test")
    with pytest.raises(m0.CorpusError, match="empty"):
        m0.assert_public_text("   ", label="test")


# ---------------------------------------------------------------------------
# Markdown export parsing
# ---------------------------------------------------------------------------

def test_export_sections_roles_and_annotations(synthetic_corpus):
    path = synthetic_corpus / m0.CORPUS_SOURCES[3][1]
    sections = m0.load_export_sections(path)
    by_no = {s.number: s for s in sections}
    assert "老师" in by_no[4].role
    assert "馒头" in by_no[6].role
    # Annotations excluded from teacher_text.
    assert "【思考过程" not in by_no[4].teacher_text
    assert "【工具调用】" not in by_no[4].teacher_text
    # But the raw annotation lines are retained for auditability.
    assert any("思考过程" in line for line in by_no[4].annotation_lines)
    # Separators removed.
    assert "---" not in by_no[4].teacher_text


def test_export_sections_reject_broken_numbering(tmp_path):
    path = tmp_path / "bad.md"
    path.write_text("## 2. 【老师提问 / 输入】\n\n正文\n\n## 2. 【馒头回复】\n\n回复\n", encoding="utf-8")
    with pytest.raises(m0.CorpusError, match="not strictly increasing"):
        m0.load_export_sections(path)


def test_export_sections_reject_no_sections(tmp_path):
    path = tmp_path / "empty.md"
    path.write_text("没有任何编号段落\n", encoding="utf-8")
    with pytest.raises(m0.CorpusError, match="no numbered sections"):
        m0.load_export_sections(path)


def test_split_at_marker_missing():
    with pytest.raises(m0.CorpusError, match="marker not found"):
        m0.split_at_marker("没有标记的文本", "标记：", label="test")


def test_split_at_marker_rejects_ambiguous():
    with pytest.raises(m0.CorpusError, match="expected exactly 1"):
        m0.split_at_marker("标记：甲\n正文\n标记：乙", "标记：", label="test")


# ---------------------------------------------------------------------------
# JSONL role isolation
# ---------------------------------------------------------------------------

def test_jsonl_tool_results_are_not_teacher_text(synthetic_corpus):
    events = m0.load_jsonl_events(
        synthetic_corpus / m0.CORPUS_SOURCES[0][1])
    human_texts = []
    for event in events:
        if event.get("type") != "user":
            continue
        if (event.get("origin") or {}).get("kind") != "human":
            continue
        human_texts.extend(m0._event_text_blocks(event))
    joined = "\n".join(human_texts)
    assert "参考样例一第一行" not in joined  # tool_result content excluded
    assert "Base directory" not in joined    # skill loading excluded (no human origin)
    assert "被否定小节" in joined             # real teacher feedback kept


def test_find_event_by_uuid_type_guard(synthetic_corpus):
    events = m0.load_jsonl_events(synthetic_corpus / m0.CORPUS_SOURCES[0][1])
    with pytest.raises(m0.CorpusError, match="expected"):
        m0.find_event_by_uuid(events, m0.F_UUID_FEEDBACK_V1, expected_type="assistant")
    with pytest.raises(m0.CorpusError, match="not found"):
        m0.find_event_by_uuid(events, "no-such-uuid", expected_type="user")


def test_find_read_tool_results_requires_pairing(synthetic_corpus, monkeypatch):
    events = m0.load_jsonl_events(synthetic_corpus / m0.CORPUS_SOURCES[0][1])
    found = m0.find_read_tool_results(events, ("参考样例一.md",))
    assert "参考样例一.md" in found
    with pytest.raises(m0.CorpusError, match="not found"):
        m0.find_read_tool_results(events, ("不存在的样例.md",))


def test_find_read_tool_results_rejects_ambiguous_reread(synthetic_corpus):
    events = m0.load_jsonl_events(synthetic_corpus / m0.CORPUS_SOURCES[0][1])
    # Duplicate the Read call + result for 参考样例一: version becomes ambiguous.
    dup_use = {"type": "assistant", "uuid": "a-read-1-dup",
               "message": {"role": "assistant", "content": [
                   {"type": "tool_use", "id": "t1dup", "name": "Read",
                    "input": {"file_path": "D:\\知识库\\参考样例一.md"}}]}}
    dup_result = {"type": "user", "uuid": "u-read-1-dup",
                  "message": {"role": "user", "content": [
                      {"type": "tool_result", "tool_use_id": "t1dup", "content": "1\t修订后的样例。"}]}}
    events.extend([dup_use, dup_result])
    with pytest.raises(m0.CorpusError, match="version ambiguous"):
        m0.find_read_tool_results(events, ("参考样例一.md",))


def test_run_extraction_rejects_out_inside_source(synthetic_corpus):
    with pytest.raises(m0.CorpusError, match="read-only corpus root"):
        m0.run_extraction(synthetic_corpus, synthetic_corpus / "out", "cmd")


# ---------------------------------------------------------------------------
# Case builders on the synthetic corpus
# ---------------------------------------------------------------------------

def test_build_f_case(synthetic_corpus):
    records = m0.verify_sources(synthetic_corpus)
    bundle = m0.build_f_case(records, synthetic_corpus)
    case = bundle.case
    assert case["client_case_id"] == "m0-real-f-financial-report"
    # Bad case body must not carry delivery meta.
    assert "核对结论" not in case["bad_cases"][0]["content_text"]
    assert "被否定小节" in case["bad_cases"][0]["content_text"]
    # Feedback paired verbatim.
    assert case["bad_cases"][0]["teacher_feedback_texts"][0].startswith("“被否定小节”")
    # Reference answer keeps the FULL final draft minus the lead sentence.
    answer = case["reference_answer"]
    assert answer.startswith("《测试终稿标题》")
    assert m0.F_FINAL_LEAD not in answer
    assert "下一个交卷时间" in answer
    # Reference examples strip line-number prefixes from tool reads.
    refs = {r["source_name"]: r["content_text"] for r in case["reference_examples"]}
    assert refs["参考样例一.md"] == "参考样例一第一行。\n参考样例一第二行。"
    # Memory materials are the whole attachments.
    labels = {m["source_label"] for m in case["memory_materials"]}
    assert labels == {
        "【新闻稿】理想汽车公布2026年第二季度财报.md",
        "理想汽车2026年第二季度财报-媒体沟通文档.md",
    }
    # Provenance covers every material group.
    for key in ("title", "task_prompt", "bad_case_v1", "feedback_v1",
                "reference_answer", "memory_press_release", "memory_media_doc",
                "reference_examples"):
        assert key in bundle.provenance
    assert bundle.derived is False


def test_build_m_case(synthetic_corpus):
    records = m0.verify_sources(synthetic_corpus)
    bundle = m0.build_m_case(records, synthetic_corpus)
    case = bundle.case
    assert case["client_case_id"] == "m0-real-m-mega-press-release"
    # Task prompt: host paths sanitized, annotations excluded.
    assert "D:\\" not in case["task_prompt"]
    assert "讲稿-v2.md" in case["task_prompt"]
    assert "思考过程" not in case["task_prompt"]
    # Bad case v1: article only, no check-card meta.
    bc1 = case["bad_cases"][0]["content_text"]
    assert "核对结论" not in bc1 and "打开侧滑门" in bc1
    # Bad case v2: pasted draft separated from the instruction.
    bc2 = case["bad_cases"][1]
    assert bc2["content_text"].startswith("测试MEGA新闻稿二稿")
    assert "结尾我不满意" in bc2["teacher_feedback_texts"][0]
    assert "以下是当前版本" not in bc2["teacher_feedback_texts"][0]
    # Reference answer: official draft only — brief-task text excluded.
    answer = case["reference_answer"]
    assert answer.startswith("测试MEGA新闻稿终稿")
    assert "区域简讯" not in answer and "理想i6" not in answer
    assert "给车和家赋予生命" in answer
    # Version-gap limitation recorded, not faked.
    assert any("v6" in lim for lim in bundle.limitations)
    assert case["reference_examples"] == []


def test_builder_rejects_truncated_final(synthetic_corpus, monkeypatch):
    # Corrupt the final-draft tail: extraction must fail loudly, not proceed.
    records = m0.verify_sources(synthetic_corpus)
    path = synthetic_corpus / m0.CORPUS_SOURCES[0][1]
    events = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    for event in events:
        if event.get("uuid") == m0.F_UUID_FINAL:
            event["message"]["content"][0]["text"] = m0.F_FINAL_LEAD + "\n\n《测试终稿标题》\n\n被截断的正文"
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
                    encoding="utf-8")
    with pytest.raises(m0.CorpusError, match="truncated"):
        m0.build_f_case(records, synthetic_corpus)


def test_builder_rejects_unanchored_feedback(synthetic_corpus):
    records = m0.verify_sources(synthetic_corpus)
    path = synthetic_corpus / m0.CORPUS_SOURCES[3][1]
    text = path.read_text(encoding="utf-8").replace("修改意见：", "随便说说：")
    path.write_text(text, encoding="utf-8")
    with pytest.raises(m0.CorpusError, match="anchor invalid"):
        m0.build_m_case(records, synthetic_corpus)


# ---------------------------------------------------------------------------
# Derived counter-examples
# ---------------------------------------------------------------------------

def test_derived_cases_are_labeled_mutations(synthetic_corpus):
    records = m0.verify_sources(synthetic_corpus)
    f_case = m0.build_f_case(records, synthetic_corpus)
    m_case = m0.build_m_case(records, synthetic_corpus)
    derived = m0.build_derived_cases(f_case, m_case)
    assert len(derived) == 6
    ids = {d.case_id for d in derived}
    assert f_case.case_id not in ids and m_case.case_id not in ids
    for d in derived:
        assert d.derived is True
        assert d.parent_case_id in {f_case.case_id, m_case.case_id}
        assert d.mutation
    # Real cases untouched by mutation (deepcopy isolation).
    truncated = next(d for d in derived if d.case_id == "m0-derived-m-truncated-answer")
    assert len(truncated.case["reference_answer"]) == 800
    assert len(m_case.case["reference_answer"]) > 800
    assert m_case.case["reference_answer"] != truncated.case["reference_answer"]
    # Host-path leak mutation must actually trip the production scanner.
    from app.features.question_library import rubric_rules
    leak = next(d for d in derived if d.case_id == "m0-derived-m-host-path-leak")
    assert rubric_rules.contains_private_content(leak.case["task_prompt"]) == "主机路径"


def test_expectations_fixed_before_generation(synthetic_corpus):
    records = m0.verify_sources(synthetic_corpus)
    f_case = m0.build_f_case(records, synthetic_corpus)
    m_case = m0.build_m_case(records, synthetic_corpus)
    derived = m0.build_derived_cases(f_case, m_case)
    expectations = m0.build_expectations(f_case, m_case, derived)
    assert expectations["policy"]
    real_ids = {c["case_id"] for c in expectations["real_cases"]}
    assert real_ids == {f_case.case_id, m_case.case_id}
    for case_block in expectations["real_cases"]:
        assert case_block["checks"]
        for check in case_block["checks"]:
            assert check["id"] and check["expect"] and check["basis"]
    assert len(expectations["derived_cases"]) == len(derived)
    for d in expectations["derived_cases"]:
        assert d["expect"]


# ---------------------------------------------------------------------------
# Full rebuild flow on the synthetic corpus
# ---------------------------------------------------------------------------

def test_run_extraction_end_to_end(synthetic_corpus, tmp_path):
    out = tmp_path / "out"
    result = m0.run_extraction(synthetic_corpus, out, "test-command")
    assert result["sources_verified"] == 6
    assert result["batch_cases"] == 2
    assert result["derived_cases"] == 6
    batch = json.loads((out / "batch.json").read_text(encoding="utf-8"))
    assert batch["command_id"] == "test-command"
    assert batch["schema_version"] == "1.0"
    # The batch must satisfy the production upload contract.
    from app.features.question_library.schemas import BatchUploadRequest
    BatchUploadRequest.model_validate(batch)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["sources"]) == 6
    # Manifest carries provenance metadata but never material bodies.
    manifest_text = json.dumps(manifest, ensure_ascii=False)
    assert "终稿第一段" not in manifest_text
    assert "打开侧滑门" not in manifest_text
    derived_payload = json.loads((out / "derived_cases.json").read_text(encoding="utf-8"))
    assert len(derived_payload["cases"]) == 6


def test_run_extraction_fails_when_source_vanishes_midway(synthetic_corpus, tmp_path, monkeypatch):
    # If a source disappears between the two verification passes, fail loudly.
    original = m0.verify_sources

    calls = {"n": 0}

    def flaky(root):
        calls["n"] += 1
        if calls["n"] == 2:
            (synthetic_corpus / m0.CORPUS_SOURCES[0][1]).unlink()
        return original(root)

    monkeypatch.setattr(m0, "verify_sources", flaky)
    with pytest.raises(m0.CorpusError):
        m0.run_extraction(synthetic_corpus, tmp_path / "out", "cmd")
