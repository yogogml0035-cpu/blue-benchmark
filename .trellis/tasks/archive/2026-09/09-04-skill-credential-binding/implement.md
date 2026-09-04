# Implement：ai-eval-push 技能凭证硬编码绑定机制

## 分支与门禁

- 分支：`codex/skill-credential-binding`，从 `main`（`8bb160c`，已验证干净）创建。
- 门禁：`git diff --check`、`make test`（后端套件不受影响，需全量过）、skill 测试 `python -m pytest skills/ai-eval-push/tests -q`；本任务不触及前端与生产构建，`make build` 可不做，但以任务文档为准。

## 执行顺序

1. **改脚本** `skills/ai-eval-push/scripts/push_eval_cases.py`：
   - 顶部常量区新增 `BASE_URL` / `ACCESS_TOKEN` 占位符常量与注释；
   - 重写 `load_config()`：占位符检测 → `config-error`；scheme 校验保留；删除全部 `os.environ` 读取与 `AI_EVAL_CONFIG` 文件读取；
   - 更新模块 docstring：删除 `Environment:` 一节，改写开头对脚本职责的描述（"reads the API base URL and scene credential from the environment" → 从脚本内绑定槽读取）；
   - `import os` 若不再被使用则删除（检查 `os.path` 是否还有其他引用——当前只在 `load_config` 用，删）。
2. **改测试** `skills/ai-eval-push/tests/test_push_eval_cases.py`：
   - `server` fixture 与所有用例：`monkeypatch.setenv/delenv` → `monkeypatch.setattr` 模块常量；
   - 新增未绑定态用例（见 design）；
   - 确认无 `AI_EVAL_*` 字符串残留。
3. **改 SKILL.md**：按 design 重写「配置」→「绑定凭证」节、「失败处理」`config-error` 条目、第 5/6 步命令说明中涉及配置的措辞。
4. **清除跨层旧语义**（实施中发现，已同步回 design.md 删除清单）：
   - `backend/scripts/accept_skill_push_evaldata.py` 的 `_run_client`：不再注入环境变量，改为把占位符替换进临时副本后运行该副本；
   - `frontend/src/features/evaluation-sets/prompt.ts`：绑定提示词改为“替换部署副本脚本内的 `BASE_URL` / `ACCESS_TOKEN` 占位符”，同步更新 `logic.test.ts` 断言。
5. **验证**（见下）。
6. **提交**：一个提交批次 `feat(skill): ai-eval-push 凭证改为脚本内硬编码绑定，移除环境变量链路`（措辞对齐仓库提交风格，`git log --oneline -5` 为准）。

## 检索范围（完成门禁，逐项确认无可执行旧路径）

```bash
git grep -n "AI_EVAL_BASE_URL\|AI_EVAL_ACCESS_TOKEN\|AI_EVAL_CONFIG" -- ':!.trellis'
git grep -n "load_config\|os.environ" -- skills/
grep -rn "setenv\|delenv" skills/ai-eval-push/
git diff --check
```

## 验证命令

```bash
python -m pytest skills/ai-eval-push/tests -q
make test
git diff --check
# 占位符状态行为抽查（应 config-error, exit 2）：
python skills/ai-eval-push/scripts/push_eval_cases.py connection; echo $?
```

## 回滚点

每步均可单独 `git checkout -- <file>` 回退；合并前整体回滚 = 删除任务分支。
