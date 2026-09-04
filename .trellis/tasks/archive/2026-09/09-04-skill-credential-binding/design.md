# Design：ai-eval-push 技能凭证硬编码绑定机制

## 一次性切换边界

本任务以新语义（脚本内硬编码常量）整体替代旧语义（环境变量 / 配置文件读取），一次性切换，不保留兼容层。

## 数据结构变更

`push_eval_cases.py` 模块顶部新增两个常量（紧随 `SCHEMA_VERSION` 等常量区）：

```python
# Scene binding slot — replaced by the real values during credential binding.
# Keep the placeholders ("***") in the repository copy; bind only deployed copies.
BASE_URL = "***"
ACCESS_TOKEN = "sep_***"
```

- 判定未绑定：`"***" in BASE_URL or "***" in ACCESS_TOKEN`（两个都替换才算绑定完成；任一残留占位符都报未绑定）。
- 不做格式校验（如强制 `sep_` 前缀）：占位符本身已含 `sep_`，真实凭证形态由服务端校验，脚本只做“是否还是占位符”的判断，保持确定性。

## 需要删除的接口与数据结构

| 删除项 | 位置 |
|---|---|
| `AI_EVAL_BASE_URL` / `AI_EVAL_ACCESS_TOKEN` / `AI_EVAL_CONFIG` 读取逻辑 | `load_config()`（现 `push_eval_cases.py:343-369`） |
| docstring 中 `Environment:` 一节 | 模块 docstring |
| SKILL.md「配置」节环境变量说明与 `connection` 前的“确认绑定关系”措辞 | `SKILL.md:89-101` |
| SKILL.md 失败处理中 `config-error` 的环境变量提示 | `SKILL.md:81` |
| 测试中全部 `monkeypatch.setenv / delenv` 配置注入 | `tests/test_push_eval_cases.py` |
| 验收 harness 通过环境变量给子进程注入凭证 | `backend/scripts/accept_skill_push_evaldata.py` 的 `_run_client`（改为绑定临时副本后运行） |
| 绑定提示词中“写入私有配置文件 + 设置 AI_EVAL_CONFIG”的指引 | `frontend/src/features/evaluation-sets/prompt.ts` 及其断言 `logic.test.ts`（提示词是绑定合同的一部分，随本任务切换） |

## 新接口形态

```python
def load_config() -> tuple[str, str]:
    if _PLACEHOLDER in BASE_URL or _PLACEHOLDER in ACCESS_TOKEN:
        _usage_error(
            "credential not bound: replace BASE_URL and ACCESS_TOKEN at the top "
            "of scripts/push_eval_cases.py with the real platform address and "
            "scene credential (ask your agent to bind them)"
        )
    scheme = urllib.parse.urlsplit(BASE_URL).scheme
    if scheme not in ("http", "https"):
        _usage_error(f"BASE_URL must use http or https (got '{scheme or 'no scheme'}')")
    return BASE_URL.rstrip("/"), ACCESS_TOKEN
```

- `_PLACEHOLDER = "***"` 模块常量，测试与脚本共用判定口径。
- `_usage_error` 行为不变（打印 `config-error: ...` 到 stderr，exit 2）。
- `connection` / `push` 继续经 `load_config()` 拿配置，签名不变；`validate` 不需要网络与凭证，**不加载配置**（与现状一致：`cmd_validate` 不调用 `load_config`）。

## 测试 seam 变更

配置注入从 `monkeypatch.setenv` 改为 `monkeypatch.setattr(pec, "BASE_URL", ...)` / `monkeypatch.setattr(pec, "ACCESS_TOKEN", ...)`（`pec` 为被测模块别名）。新增用例：

1. 占位符状态下 `load_config()` 抛 `SystemExit(2)`（`connection`/`push` 同）。
2. 仅替换一个常量仍视为未绑定。
3. 绑定后 `connection` / `push` 正常走 HTTP（沿用现有 FakePlatform fixture）。
4. `BASE_URL` 非 http/https 仍被拒绝。

## SKILL.md 变更

「配置」节重写为「绑定凭证」：

- 说明两个硬编码常量的位置与占位符含义；
- 绑定流程：老师发送平台地址 + 场景凭证 → agent 替换脚本内常量 → `connection` 验证；
- 未绑定报错（`config-error`）的处理指引；
- 警示：仓库中的脚本必须保持占位符，绝不提交绑定后的脚本；
- 分发说明：绑定的是部署副本，打包分发给同事后对方零配置可用。

「失败处理」节 `config-error` 条目改为“凭证未绑定或 BASE_URL 非法；按绑定流程处理。不要打印 token”。

## 回滚方式

纯文件级改动，回滚 = `git revert` 本任务提交；无数据库、无外部状态。

## 风险

- 仓库副本被误绑定后提交：以验收标准 3/5 的定向检索与合并前检查兜底。
- 占位符 `***` 恰好出现在真实 base URL 中：实际不可能（http/https URL 不含 `***`），且 scheme 校验会在其之前通过与否给出信号。
