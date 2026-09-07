# Cutover Checklist:任务验收合并后由用户手动执行(D4/D5)

> 前提:`codex/rename-blue-benchmark` 已 ff 合并回 `main` 且 main 复验通过、任务 worktree 与分支已删除。
> 顺序不可颠倒:GitHub 改名 → 关会话 → mv 目录 → 记忆迁移 → 核验。

## 1. GitHub 仓库改名(D4)

1. 打开 https://github.com/yogogml0035-cpu/skill-eval-platform → Settings → General → Repository name 改为 `blue-benchmark` → Rename。
2. 本地更新 remote:
   ```bash
   git remote set-url origin https://github.com/yogogml0035-cpu/blue-benchmark.git
   git fetch origin
   git remote -v
   ```
   (GitHub 会为旧 URL 保留一段时间的重定向,但应立即切换,不依赖重定向。)

## 2. 关闭所有会话与终端

- 关闭所有 ZCode/编辑器会话、终端标签,确保没有任何进程的 cwd 停留在 `/Users/hsikey/Company/skill-eval-platform` 或其子目录内。
- `git worktree list` 确认除主工作区外无残留 worktree;`../skill-eval-platform-wt/` 目录如仍存在且为空,可一并删除。

## 3. mv 本地目录(D5)

```bash
mv /Users/hsikey/Company/skill-eval-platform /Users/hsikey/Company/blue-benchmark
```

- `.env`(gitignored)随目录一起迁移,无需重建;迁移后核对其中连接串已是 `blue_benchmark*`(本任务已改好,只需确认)。
- `backend/storage/` 下如有旧 `skill-eval.db`(2026-08-30 的 sqlite 遗留,已废弃且被 Postgres 取代),可直接删除;新默认名是 `blue-benchmark.db`,仅在无 Postgres 的降级开发时才会生成。

## 4. 迁移 ZCode 记忆目录

1. 在新目录 `/Users/hsikey/Company/blue-benchmark` 打开一次 ZCode 会话,让平台生成新的项目记忆目录(形如 `~/.zcode/cli/memories/projects/blue-benchmark-<新哈希>/`)。
2. 将旧目录 `~/.zcode/cli/memories/projects/skill-eval-platform-712f74b96f571042/memory/` 下所有 `.md` 复制到新目录的 `memory/`。
3. 更新 `MEMORY.md` 及各记忆文件中涉及旧路径/旧名/旧容器名/旧库名的行文(如 `skill-eval-platform-postgres` → `blue-benchmark-postgres`、`skill_eval` 库 → `blue_benchmark`);更新完成后删除旧项目记忆目录。

## 5. Docker/本地环境核验

```bash
docker ps -a          # blue-benchmark-postgres 应存在且 Up
docker compose ls     # 如有旧项目名残留,在新目录重新 up
```

- DBeaver:更新连接为 host `127.0.0.1:5432`、database `blue_benchmark`、user `blue_benchmark`(密码不变);checkpoint 库为 `blue_benchmark_checkpoint`(user `blue_benchmark_checkpoint`)。
- 本机部署版 ai-eval-push skill(`~/.agents/skills/ai-eval-push/`)仍含旧平台称呼与旧绑定值;从仓库 `skills/ai-eval-push/` 重新同步占位符副本后再绑定,或直接更新其中称呼(仓库外资产,不在本任务范围)。

## 6. 收尾确认

- `cd /Users/hsikey/Company/blue-benchmark && make test && make build` 全绿。
- 起本地服务,注册/登录首个管理员(业务库当前为 0 用户属预期,见任务 evidence.md),确认 Cookie 名为 `blue_benchmark_session`。
- 服务器发版实操:按新版 `deploy/README.md`、`deploy/server-setup.md` 继续(镜像 `blue-benchmark-web/api`、服务器目录 `/opt/blue-benchmark/`、库 `blue_benchmark*`、备份格式 `blue-benchmark-backup/v1`、Mac 下载目录 `~/blue-benchmark-backups/`、环境变量 `BLUE_BENCHMARK_BACKUP_AES_KEY`);发版顺序沿用既有计划:补 env → 建 checkpoint 库 → 0021 迁移先行。
