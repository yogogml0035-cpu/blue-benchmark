# C1 完成证据（真实会话样本与独立回归基线）

日期：2026-09-06。执行 worktree：/Users/hsikey/Company/skill-eval-platform-wt/m0-rubric-real-samples（分支 codex/m0-rubric-real-samples，基线 main@768a6bb）。

## 交付物

- `backend/scripts/m0_samples.py`：可重建的真实样本提取模块与 CLI。
  - 六源文件 sha256/size 双校验 + 未知文件拒绝 + JSONL 全量可解析校验；提取前后各复验一次 hash。
  - F 组（JSONL）：按 uuid 锚点提取 bad case（line 141 稿件正文，剥离核对结论尾部）、老师反馈（line 146 全文）、终版供稿（line 247 全文 2339 字符，剥离引导句、无截断）、两个参考样例（Read tool_result 按 tool_use_id 配对、剥离行号前缀）、两个附件全文为记忆材料。
  - M 组（markdown 导出）：段落 4 老师任务原话（剔除思考/工具注记、host path 仅替换为文件名）、段落 6 初稿+段落 7 反馈、段落 19 粘贴稿+同段指令（标记句切分）、段落 43 官网通发终稿全文 4336 字符（与区域简讯任务及 i6 样例分离）；讲稿 v2 与拍摄指引附件全文。
  - 6 个派生反例（单点变异、标注 parent+mutation）：截断终稿、反馈脱绑、v2 冒充 v6、思考注记冒充老师、host path 泄露、跨题答案污染。
  - 15 条独立预期检查（expectations），全部在运行任何生成器之前固定，basis 指向老师原话/材料锚点。
- `backend/tests/test_m0_samples.py`：26 个确定性测试（合成语料，不读真实语料、不调生成器），覆盖 hash 校验失败模式、角色隔离、注记剔除、剥离边界、锚点漂移、截断终稿、反馈配对、派生反例标注、生产 BatchUploadRequest 合同校验、manifest 无正文泄露、提取中途源消失。

## 私有 fixture（不进 Git，已验证被 .gitignore:9 backend/storage/ 覆盖）

- `backend/storage/acceptance/m0-real-samples/{batch.json,manifest.json,expectations.json,derived_cases.json}`
- 重建命令（任何 worktree，从 main 检出后）：

```bash
cd backend && uv run python -m scripts.m0_samples \
  --source-root /Users/hsikey/Company/skill-eval-platform/.local-samples/m0 \
  --out storage/acceptance/m0-real-samples
```

- 仅校验 hash：`uv run python -m scripts.m0_samples --verify-only`

## 真实语料覆盖

- F 组与 M 组各 1 个证据完整 case；六个业务源文件 hash 与 research/real-sample-validation.md 登记一致，提取前后复验不变，源目录零写入。
- 真实批次通过生产 `BatchUploadRequest` pydantic 合同校验；`rubric_rules.contains_private_content` 对 batch 全文零命中；派生 D5（host path）确认被生产扫描器以「主机路径」拒绝。
- 限定与缺口（单列，不伪造）：F title/task_prompt 为上下文提炼（derived 标记）；M 语料仅 v2 讲稿正文，v3-v6 缺失，不断言 v6 全文一致性；M 三篇 2026 参考新闻稿仅有工具读取路径、正文未导出，reference_examples 为空；区域简讯、i6 样例、政府邀请函为同会话其他任务，不混入。

## 质量门

- `git diff --check`：通过。
- `make test`：backend 110 passed（含新增 26）+ frontend 70 passed，EXIT=0。
- 本子任务未跑真实模型、未重置任何数据库（按任务边界）。

## 对抗式审查

双审查代理（正确性/可追溯性逐字节复核 + 泄露/边界安全）结论：无 Critical；核心断言（逐字一致、无截断、配对正确、hash 不变、隐私清洗、派生单点变异）经独立重实现复核全部成立。发现并已在合入前修复：

- 泄露-M1：M task_prompt 残留无盘符相对路径 `理想汽车知识库\新闻稿\2026文件夹`（生产扫描器不拦截该形态）→ `strip_host_paths` 新增 drive-relative 反斜杠路径归一化（保留末段名），真实批次重生成后 task_prompt 790→774 字符，全批次隐私扫描零命中，新增单测覆盖。
- 泄露-M2：D5 负例在将提交代码中使用了老师真实主机路径前缀 → 改为明显虚构的 `D:\示例工作区\示例知识库\示例讲稿.md`，测试断言不变。
- 正确性-M1：`strip_delivery_meta` 首现 marker 即切可能静默截断正文 → 新增“切除不得超过全文 1/3”守卫，正文含 marker 词或尾部异常膨胀时 CorpusError；真实两稿尾部占比 ~10%/~18% 不受影响，新增 2 个负例单测。
- 正确性-M2：完整性哨兵仅存在性检查 → `split_at_marker` 新增 marker 唯一性断言；manifest provenance 新增 `content_sha256`（内容级 hash），下游可校验内容而非仅文件。
- 正确性-M3：`F_UUID_DRAFT_V2` 死常量、v2 反馈链缺口未声明 → 实查 line 243-246 无老师反馈事件（老师以直接提供终版回应），删除死常量并在 F limitations 中记录该决定。
- 加固（泄露-m4 + 正确性-m4）：`run_extraction` 拒绝 out_dir 位于只读语料内；`find_read_tool_results` 对同一参考样例多次 Read 报“版本歧义”而非静默取旧版。
- 其余 Minor（reason_summary 标注、导出分隔线移除记录）已在 bundle notes 中补充声明；短句级结构锚点经审查判定为允许的非敏感取样元数据，逐条清单见审查记录。

修复后测试 32 passed；真实批次重生成并通过生产合同与隐私复验。

## 提交与合并

- 代码提交 SHA：97a595b（feat(scripts): rebuild real M0 session samples into traceable test inputs），基线 main@768a6bb。
- 合并方式：主工作区 `git merge --ff-only codex/m0-rubric-real-samples`，`git log main..codex/m0-rubric-real-samples` 为空。
- main 复验（合并后在主工作区执行）：`git diff --check` 通过；`make test` backend 116 passed + frontend 70 passed，EXIT=0（/tmp/c1-main-reverify.log）。
- 规格同步：`.trellis/spec/backend/core/structure-and-boundaries.md` 已登记 m0_samples 脚本与真实语料提取纪律（收尾提交）。
