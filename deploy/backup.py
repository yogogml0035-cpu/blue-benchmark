#!/usr/bin/env python3
"""blue-benchmark 部署备份工具（仅 Python 3.10+ 标准库，零第三方依赖）。

唯一备份格式：blue-benchmark-backup/v1。一次成功备份产生一套完整恢复点，
单归档 backups/latest.tar.gz 包含四个成员：

  manifest.json    格式版本、备份 ID、导出时间、应用镜像标识、业务 schema
                   版本、各成员大小与 SHA-256，以及用原 LANGGRAPH_AES_KEY
                   计算的 HMAC-SHA256 校验值（密钥本身绝不写入归档）
  business.sql     业务库结构和数据（停写窗口内 pg_dump 导出）
  checkpoint.sql   checkpoint 库结构和数据（与业务库同一停写窗口导出）
  files.tar        appdata 卷中本项目文件（只读一次性容器导出）

子命令：

  run            服务器每日备份全流程：预检 -> 互斥锁 -> 停写 -> 导出两库
                 和文件 -> 立即恢复服务 -> 打包验证 -> 原子替换服务器
                 latest.tar.gz -> 恢复服务之后才更新 OSS（只留最新一套）
  verify         离线校验归档结构、成员摘要、格式版本和路径安全；不执行
                 归档中的任何命令或 SQL。提供 --aes-key-file 或环境变量
                 LANGGRAPH_AES_KEY 时额外核对 HMAC（argv 直接传密钥被拒绝）
  download       Mac 经 SSH 下载服务器 latest：临时文件 + 完整校验 +
                 原子覆盖；只需本机 Python 和 SSH
  restore-check  恢复预检（文档化人工恢复步骤的第一道门），拒绝旧格式

留存策略：服务器、OSS、Mac 三处均只保留最新成功的一套。任一阶段失败
都保留该处上次成功的归档，分别输出备份 ID、生成时间和各阶段结果，绝不
把局部成功说成完整备份成功。

安全边界：
- 所有输出、日志和异常信息不出现密码、DSN 凭证或 AES 密钥；
- 配置来自 `docker compose config --format json` 的解析结果（原始 JSON
  含凭证，只保留在内存），不 shell source .env；
- 数据库目标只接受本 Compose 的 postgres 服务上已核验的两个库；
- OSS 只操作专用前缀内本工具拥有的对象，不递归清空 Bucket，不改保护策略。
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import gzip
import hashlib
import hmac
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import unquote, urlsplit

# ---------------------------------------------------------------------------
# 常量与格式定义
# ---------------------------------------------------------------------------

FORMAT_NAME = "blue-benchmark-backup/v1"
MEMBER_MANIFEST = "manifest.json"
MEMBER_BUSINESS = "business.sql"
MEMBER_CHECKPOINT = "checkpoint.sql"
MEMBER_FILES = "files.tar"
REQUIRED_MEMBERS = (MEMBER_MANIFEST, MEMBER_BUSINESS, MEMBER_CHECKPOINT, MEMBER_FILES)

ARCHIVE_NAME = "latest.tar.gz"
LOCK_NAME = "backup.lock"
STATE_NAME = "backup-state.json"
HMAC_ALGORITHM = "hmac-sha256"
COPY_CHUNK = 1024 * 1024
PG_ADMIN_DATABASES = frozenset({"postgres", "template0", "template1"})
# LANGGRAPH_AES_KEY 由 `openssl rand -hex 16` 生成：32 个十六进制字符
AES_KEY_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")
# SSH 主机别名白名单，防止把危险参数或 shell 片段传给 ssh
HOST_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
COPY_ATTEMPTS = 3
STARTUP_WAIT_SECONDS = 120.0
# 可用磁盘至少为 pgdata 目录体积的 3 倍（导出 + 打包 + 候选共存）
DISK_SPACE_FACTOR = 3

WRITE_SERVICES = ("api", "worker")

# OSS 布局（专用前缀内，稳态一份归档加一个很小的指针文件）
OSS_BUNDLES_DIR = "bundles"
OSS_POINTER_NAME = "latest.json"

# ---------------------------------------------------------------------------
# 错误与输出（输出中绝不出现凭证）
# ---------------------------------------------------------------------------


class BackupError(Exception):
    """备份/校验/下载的可预期失败；message 不含任何凭证。"""


class ConfigError(BackupError):
    """部署配置不满足已确认拓扑。"""


class PreflightError(BackupError):
    """预检失败：必须先于停写发生。"""


class LockBusyError(BackupError):
    """已有备份（或人工恢复）持有本 Compose 范围的维护互斥锁。"""


class OssError(BackupError):
    """OSS 阶段失败；服务器副本不受影响。"""


class DownloadError(BackupError):
    """Mac 下载阶段失败；本机旧归档保持不变。"""


def now_utc() -> datetime:
    """统一 UTC 时间。"""
    return datetime.now(timezone.utc)


def log(message: str) -> None:
    print(f"[{now_utc().strftime('%Y-%m-%dT%H:%M:%SZ')}] {message}", flush=True)


def fail(message: str) -> None:
    print(f"[{now_utc().strftime('%Y-%m-%dT%H:%M:%SZ')}] 失败：{message}", file=sys.stderr, flush=True)


def new_backup_id() -> str:
    return f"{now_utc().strftime('%Y%m%dT%H%M%SZ')}-{os.urandom(4).hex()}"


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(COPY_CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def sha256_stream(stream: Any) -> tuple[str, int]:
    """流式计算 SHA-256，不把整个归档装进内存。"""
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(COPY_CHUNK):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def hmac_sha256(key: str, payload: bytes) -> str:
    return hmac.new(key.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def hmac_payload(members: dict[str, dict[str, Any]]) -> bytes:
    """HMAC 绑定全部成员摘要的规范化 JSON 编码。"""
    return json.dumps(members, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# 敏感环境变量名（只允许出现在解析后的内存配置里，绝不进入任何输出）
_SENSITIVE_ENV_KEYS = frozenset(
    {
        "POSTGRES_PASSWORD",
        "DATABASE_URL",
        "CHECKPOINT_DATABASE_URL",
        "LANGGRAPH_AES_KEY",
        "AI_API_KEY",
        "AI_BASE_URL",
    }
)
_SENSITIVE_URL_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@")


def redact(text: str) -> str:
    """抹掉文本中的 URL 凭证和敏感环境变量赋值，兜底防止泄漏。"""
    text = _SENSITIVE_URL_PATTERN.sub("<redacted-url>", text)
    for key in sorted(_SENSITIVE_ENV_KEYS):
        text = re.sub(rf"(?i)\b{key}\s*[=:]\s*\S+", f"{key}=<redacted>", text)
    return text


class _RedactedCompleted(subprocess.CompletedProcess):  # type: ignore[type-arg]
    """stdout/stderr 均已脱敏的 CompletedProcess。"""

    @property
    def safe_output(self) -> str:
        parts = []
        for name in ("stdout", "stderr"):
            value = getattr(self, name)
            if isinstance(value, bytes):
                value = value.decode("utf-8", "replace")
            if value:
                parts.append(f"{name}: {value.strip()}")
        return "; ".join(parts)


def run_cmd(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    capture: bool = True,
    check: bool = True,
    stdin_data: bytes | None = None,
    stdout_file: Any = None,
    timeout: float | None = None,
    redact_output: bool = True,
) -> _RedactedCompleted:
    """执行外部命令；argv 本身不含凭证，输出统一脱敏后返回/抛出。

    redact_output=False 只用于 `docker compose config` 这类“输出本身就是
    配置来源”的调用：原始 JSON 含凭证，只保留在内存，绝不打印；失败时
    抛出的错误信息仍然脱敏。
    """
    result = subprocess.run(  # noqa: S603 - argv 为程序内构造的固定命令
        list(argv),
        cwd=str(cwd) if cwd else None,
        input=stdin_data,
        stdout=subprocess.PIPE if capture and stdout_file is None else stdout_file,
        stderr=subprocess.PIPE if capture else None,
        timeout=timeout,
        check=False,
    )
    completed = _RedactedCompleted(argv, result.returncode, result.stdout, result.stderr)
    for name in ("stdout", "stderr"):
        value = getattr(completed, name)
        if isinstance(value, bytes):
            value = value.decode("utf-8", "replace")
            if redact_output:
                value = redact(value)
            setattr(completed, name, value)
    if check and completed.returncode != 0:
        display = " ".join(shlex.quote(str(part)) for part in argv)
        error_output = redact(completed.safe_output)
        raise BackupError(f"命令失败（退出码 {completed.returncode}）：{display} {error_output}".strip())
    return completed


def sh_quote(value: str) -> str:
    """POSIX shell 单引号转义；用于远端只读命令，绝不把未转义输入拼进 shell。"""
    return "'" + value.replace("'", "'\\''") + "'"


# ---------------------------------------------------------------------------
# DSN 结构化解析与部署配置
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DatabaseTarget:
    """一个已核验的数据库目标（只属于本 Compose 的 postgres 服务）。"""

    label: str
    user: str
    password: str
    host: str
    port: int
    dbname: str

    def __str__(self) -> str:  # 绝不输出密码
        return f"{self.label}: {self.user}@{self.host}:{self.port}/{self.dbname}"


_FORBIDDEN_QUERY_KEYS = frozenset({"host", "port", "dbname", "user", "password", "options"})


def parse_dsn(label: str, dsn: str) -> DatabaseTarget:
    """结构化解析 PostgreSQL DSN；禁止 query/host 覆盖绕过。"""
    if not dsn:
        raise ConfigError(f"{label} 为空")
    split = urlsplit(dsn.strip())
    if split.scheme.lower() not in {"postgresql", "postgresql+psycopg"}:
        raise ConfigError(f"{label} 的协议不是 postgresql/postgresql+psycopg，拒绝接受任意外部数据库目标")
    if split.query or split.fragment:
        raise ConfigError(f"{label} 的 DSN 带有 query/fragment 参数，可能覆盖 host/dbname，已拒绝")
    if not split.hostname or not split.username:
        raise ConfigError(f"{label} 的 DSN 缺少主机或用户名")
    host = split.hostname.lower()
    if host != "postgres":
        raise ConfigError(f"{label} 的数据库主机是 {host}，必须是本 Compose 的 postgres 服务")
    dbname = unquote(split.path.lstrip("/"))
    if not dbname or "/" in dbname:
        raise ConfigError(f"{label} 的 DSN 未指明合法数据库名")
    if dbname.lower() in PG_ADMIN_DATABASES:
        raise ConfigError(f"{label} 指向 PostgreSQL 默认管理库 {dbname}，已拒绝")
    return DatabaseTarget(
        label=label,
        user=unquote(split.username),
        password=unquote(split.password or ""),
        host=host,
        port=split.port or 5432,
        dbname=dbname,
    )


@dataclass(frozen=True)
class OssTarget:
    bucket: str
    prefix: str
    endpoint: str

    @property
    def root(self) -> str:
        return f"oss://{self.bucket}/{self.prefix.strip('/')}" if self.prefix.strip("/") else f"oss://{self.bucket}"

    @property
    def pointer_url(self) -> str:
        return f"{self.root}/{OSS_POINTER_NAME}"

    def bundle_url(self, backup_id: str) -> str:
        return f"{self.root}/{OSS_BUNDLES_DIR}/{backup_id}.tar.gz"


@dataclass(frozen=True)
class DeployConfig:
    """从已解析 Compose 配置核验出的备份目标；凭证只存在于内存对象。"""

    compose_dir: Path
    project_name: str
    business: DatabaseTarget
    checkpoint: DatabaseTarget
    aes_key: str
    appdata_volume: str
    business_schema_version: str | None
    api_image: str
    worker_image: str
    postgres_image: str
    oss: OssTarget | None
    oss_endpoint_args: tuple[str, ...] = ()

    def safe_summary(self) -> str:
        oss_text = self.oss.root if self.oss else "未配置（跳过 OSS）"
        return (
            f"project={self.project_name} business={self.business} checkpoint={self.checkpoint} "
            f"appdata卷={self.appdata_volume} OSS={oss_text}"
        )


def _service_env(config: dict[str, Any], name: str) -> dict[str, str]:
    services = config.get("services") or {}
    service = services.get(name)
    if not isinstance(service, dict):
        raise ConfigError(f"Compose 配置缺少服务 {name}")
    env = service.get("environment") or {}
    result: dict[str, str] = {}
    for key, value in env.items():
        result[key] = "" if value is None else str(value)
    return result


def _require_env(env: dict[str, str], service: str, key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"服务 {service} 的已解析环境缺少 {key}")
    return value


def _appdata_volume(config: dict[str, Any], service: str) -> str:
    for mount in config["services"][service].get("volumes") or []:
        if isinstance(mount, dict) and mount.get("type") == "volume":
            source = str(mount.get("source") or "")
            if source.split("/")[-1] == "appdata":
                return source
    raise ConfigError(f"服务 {service} 没有挂载 appdata 数据卷")


def load_deploy_config(compose_dir: Path) -> DeployConfig:
    """运行 `docker compose config --format json` 并核验备份目标。

    原始 JSON 含凭证，只保留在内存；不 shell source .env。
    """
    if not (compose_dir / "compose.yaml").is_file() and not (compose_dir / "docker-compose.yaml").is_file():
        raise ConfigError(f"{compose_dir} 不是 Compose 目录（没有 compose.yaml）")
    result = run_cmd(
        ["docker", "compose", "config", "--format", "json"], cwd=compose_dir, redact_output=False
    )
    try:
        config = json.loads(result.stdout or "")
    except json.JSONDecodeError as exc:
        raise ConfigError("无法解析 docker compose config 输出") from exc

    project_name = str(config.get("name") or "").strip()
    if not project_name:
        raise ConfigError("docker compose config 输出缺少项目名（Compose 版本过旧？）")

    api_env = _service_env(config, "api")
    worker_env = _service_env(config, "worker")
    postgres_env = _service_env(config, "postgres")

    for key in ("DATABASE_URL", "CHECKPOINT_DATABASE_URL", "LANGGRAPH_AES_KEY"):
        api_value = _require_env(api_env, "api", key)
        worker_value = _require_env(worker_env, "worker", key)
        if api_value != worker_value:
            raise ConfigError(f"api 与 worker 的 {key} 不一致，两库配置必须相同")

    business = parse_dsn("DATABASE_URL(业务库)", api_env["DATABASE_URL"])
    checkpoint = parse_dsn("CHECKPOINT_DATABASE_URL(checkpoint库)", api_env["CHECKPOINT_DATABASE_URL"])
    if business.dbname == checkpoint.dbname:
        raise ConfigError("业务库与 checkpoint 库同名，必须是两个不同的数据库")
    if business.user != checkpoint.user:
        raise ConfigError("业务库与 checkpoint 库的用户不一致")

    aes_key = api_env["LANGGRAPH_AES_KEY"]
    if not AES_KEY_PATTERN.match(aes_key):
        raise ConfigError("LANGGRAPH_AES_KEY 形状不正确（应为 openssl rand -hex 16 生成的 32 位十六进制）")

    api_volume = _appdata_volume(config, "api")
    worker_volume = _appdata_volume(config, "worker")
    if api_volume != worker_volume:
        raise ConfigError("api 与 worker 挂载的 appdata 卷不一致")

    postgres_user = postgres_env.get("POSTGRES_USER", "").strip() or "blue_benchmark"
    if business.user != postgres_user:
        raise ConfigError("DSN 用户与 postgres 服务的 POSTGRES_USER 不一致，两库必须同在本 Compose 的 postgres 服务")

    business_schema_version = _discover_schema_version(compose_dir)

    oss: OssTarget | None = None
    endpoint_args: tuple[str, ...] = ()
    bucket = api_env.get("OSS_BUCKET", "").strip()
    prefix = api_env.get("OSS_PREFIX", "").strip()
    endpoint = api_env.get("OSS_ENDPOINT", "").strip()
    if bucket or prefix or endpoint:
        missing = [name for name, value in (("OSS_BUCKET", bucket), ("OSS_PREFIX", prefix), ("OSS_ENDPOINT", endpoint)) if not value]
        if missing:
            raise ConfigError(f"OSS 备份配置不完整，缺少：{'、'.join(missing)}")
        if prefix.strip("/") in {"", "."}:
            raise ConfigError("OSS_PREFIX 不能是 Bucket 根目录，必须使用专用备份前缀")
        oss = OssTarget(bucket=bucket.removeprefix("oss://"), prefix=prefix, endpoint=endpoint)
        endpoint_args = ("-e", endpoint)

    return DeployConfig(
        compose_dir=compose_dir,
        project_name=project_name,
        business=business,
        checkpoint=checkpoint,
        aes_key=aes_key,
        appdata_volume=api_volume,
        business_schema_version=business_schema_version,
        api_image=str(config["services"]["api"].get("image") or ""),
        worker_image=str(config["services"]["worker"].get("image") or ""),
        postgres_image=str(config["services"]["postgres"].get("image") or ""),
        oss=oss,
        oss_endpoint_args=endpoint_args,
    )


def _discover_schema_version(compose_dir: Path) -> str | None:
    """从仓库的 alembic 版本目录发现业务 schema 版本（部署机上可能不存在）。"""
    versions_dir = compose_dir.parent / "backend" / "alembic" / "versions"
    heads: list[str] = []
    try:
        for path in sorted(versions_dir.glob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            revision = re.search(r"^revision(?::\s*str)?\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
            down = re.search(r"^down_revision(?::[^=]+)?\s*=\s*['\"]([^'\"]+)['\"]", text, re.M)
            if revision:
                heads.append(revision.group(1))
                if down:
                    value = down.group(1)
                    if value in heads:
                        heads.remove(value)
    except OSError:
        return None
    if len(heads) == 1:
        return heads[0]
    return None


# ---------------------------------------------------------------------------
# 互斥锁与维护恢复状态
# ---------------------------------------------------------------------------


@dataclass
class ServiceSnapshot:
    service: str
    container_id: str
    was_running: bool


@contextmanager
def maintenance_lock(backups_dir: Path) -> Iterator[None]:
    """本 Compose 范围的维护互斥锁；备份与人工恢复共用。"""
    backups_dir.mkdir(parents=True, exist_ok=True)
    lock_path = backups_dir / LOCK_NAME
    handle = lock_path.open("a+")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise LockBusyError(
                    "另一个备份或人工恢复正在使用维护互斥锁，本次拒绝并发执行"
                ) from exc
            raise
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()} {now_utc().isoformat()}\n")
        handle.flush()
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def write_recovery_state(path: Path, payload: dict[str, Any]) -> None:
    """维护恢复状态：不含任何凭证，支持 SIGKILL/断电后下次启动核查。"""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def check_residual_state(state_path: Path) -> None:
    """重入保护：上一次运行留下了未清理的维护状态时拒绝自动继续。"""
    if not state_path.exists():
        return
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        running = [item["service"] for item in state.get("stopped", []) if item.get("was_running")]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise PreflightError(
            f"发现无法解析的残留维护状态 {state_path.name}；请人工核查上一次备份/恢复是否遗留停机服务后删除该文件"
        ) from None
    raise PreflightError(
        f"发现残留维护状态 {state_path.name}（上一次运行记录了停止的服务：{'、'.join(running) or '无'}）；"
        "请先用 docker compose ps 人工核查服务状态，确认无遗留停机后删除该文件再重跑"
    )


# ---------------------------------------------------------------------------
# 归档打包与校验
# ---------------------------------------------------------------------------


@dataclass
class VerifiedArchive:
    path: Path
    manifest: dict[str, Any]
    member_digests: dict[str, str]
    member_sizes: dict[str, int]

    @property
    def backup_id(self) -> str:
        return str(self.manifest["backup_id"])

    @property
    def created_at(self) -> str:
        return str(self.manifest["created_at"])


def build_manifest(
    backup_id: str,
    created_at: str,
    member_digests: dict[str, str],
    member_sizes: dict[str, int],
    aes_key: str,
    *,
    api_image: str,
    business_schema_version: str | None,
) -> dict[str, Any]:
    members = {
        name: {"size": member_sizes[name], "sha256": member_digests[name]}
        for name in (MEMBER_BUSINESS, MEMBER_CHECKPOINT, MEMBER_FILES)
    }
    return {
        "format": FORMAT_NAME,
        "backup_id": backup_id,
        "created_at": created_at,
        "api_image": api_image,
        "business_schema_version": business_schema_version,
        "members": members,
        "hmac": {"algorithm": HMAC_ALGORITHM, "value": hmac_sha256(aes_key, hmac_payload(members))},
    }


def _safe_member_path(name: str) -> str:
    """拒绝绝对路径、盘符和任何 ../ 越界。"""
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise BackupError(f"归档成员使用绝对路径：{name}")
    parts = Path(name).parts
    if any(part in {"..", ""} or "\\" in part for part in parts):
        raise BackupError(f"归档成员路径越界或含非法分隔符：{name}")
    return str(Path(*parts))


def validate_archive(stream: Any, *, aes_key: str | None = None, source: str = "归档") -> VerifiedArchive:
    """离线校验归档：结构、成员摘要、格式版本、路径安全、危险链接。

    只做只读校验，不执行归档中的任何命令或 SQL。提供 aes_key 时核对
    HMAC（证明持有原密钥）；不提供时跳过 HMAC（Mac 日常下载不要求每天
    输入密钥）。
    """
    member_digests: dict[str, str] = {}
    member_sizes: dict[str, int] = {}
    manifest_raw: bytes | None = None
    seen: set[str] = set()

    try:
        with tarfile.open(fileobj=stream, mode="r|*") as archive:
            for member in archive:
                if member.name in seen:
                    raise BackupError(f"{source} 含重复成员：{member.name}")
                seen.add(member.name)
                safe_name = _safe_member_path(member.name)
                if member.issym() or member.islnk():
                    raise BackupError(f"{source} 含符号链接/硬链接成员（危险链接，已拒绝）：{member.name}")
                if not member.isfile():
                    raise BackupError(f"{source} 含非普通文件成员：{member.name}（type={member.type!r}）")
                handle = archive.extractfile(member)
                if handle is None:
                    raise BackupError(f"{source} 成员不可读：{member.name}")
                with handle:
                    data = handle.read()
                digest = hashlib.sha256(data).hexdigest()
                if len(data) != member.size:
                    raise BackupError(f"{source} 成员 {member.name} 实际大小与 tar 头不一致（归档损坏）")
                if safe_name == MEMBER_MANIFEST:
                    if manifest_raw is not None:
                        raise BackupError(f"{source} 含重复成员：{MEMBER_MANIFEST}")
                    manifest_raw = data
                else:
                    member_digests[safe_name] = digest
                    member_sizes[safe_name] = len(data)
    except tarfile.ReadError as exc:
        raise BackupError(f"{source} 不是合法的 tar/gzip 归档（已损坏或被截断）：{exc}") from exc
    except EOFError as exc:
        raise BackupError(f"{source} 数据不完整（传输被截断）") from exc

    missing = [name for name in REQUIRED_MEMBERS if name not in seen]
    if missing:
        raise BackupError(
            f"{source} 缺少成员：{'、'.join(missing)}。仅业务库加文件的旧格式松散备份不是 {FORMAT_NAME} 完整备份，已拒绝"
        )
    if manifest_raw is None:
        raise BackupError(f"{source} 缺少 {MEMBER_MANIFEST}")

    try:
        manifest = json.loads(manifest_raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BackupError(f"{source} 的 manifest.json 不是合法 JSON") from exc
    if not isinstance(manifest, dict):
        raise BackupError(f"{source} 的 manifest.json 不是对象")

    fmt = manifest.get("format")
    if fmt != FORMAT_NAME:
        raise BackupError(f"{source} 的格式版本是 {fmt!r}，本工具只接受 {FORMAT_NAME}")
    for key in ("backup_id", "created_at"):
        if not str(manifest.get(key) or "").strip():
            raise BackupError(f"{source} 的清单缺少 {key}")

    declared = manifest.get("members")
    if not isinstance(declared, dict):
        raise BackupError(f"{source} 的清单缺少 members 摘要表")
    for name in (MEMBER_BUSINESS, MEMBER_CHECKPOINT, MEMBER_FILES):
        entry = declared.get(name)
        if not isinstance(entry, dict):
            raise BackupError(f"{source} 的清单缺少成员 {name} 的摘要")
        if name not in member_digests:
            raise BackupError(f"{source} 的清单声明了 {name}，但归档中没有对应数据")
        expected_digest = str(entry.get("sha256") or "")
        expected_size = entry.get("size")
        if not hmac.compare_digest(expected_digest, member_digests[name]):
            raise BackupError(f"{source} 的成员 {name} SHA-256 与清单不一致（归档损坏）")
        if expected_size != member_sizes[name]:
            raise BackupError(f"{source} 的成员 {name} 大小与清单不一致（归档损坏）")

    hmac_info = manifest.get("hmac")
    if not isinstance(hmac_info, dict) or hmac_info.get("algorithm") != HMAC_ALGORITHM:
        raise BackupError(f"{source} 的清单缺少 {HMAC_ALGORITHM} 校验值")
    expected_hmac = str(hmac_info.get("value") or "")
    if aes_key is not None:
        if not AES_KEY_PATTERN.match(aes_key):
            raise BackupError("提供的 AES 密钥形状不正确（应为 32 位十六进制）")
        computed = hmac_sha256(aes_key, hmac_payload({k: declared[k] for k in (MEMBER_BUSINESS, MEMBER_CHECKPOINT, MEMBER_FILES)}))
        if not hmac.compare_digest(expected_hmac, computed):
            raise BackupError(f"{source} 的 HMAC 校验失败：密钥与生成该备份的原 LANGGRAPH_AES_KEY 不匹配，拒绝完整恢复")

    return VerifiedArchive(
        path=Path(str(getattr(stream, "name", "") or "")),
        manifest=manifest,
        member_digests=member_digests,
        member_sizes=member_sizes,
    )


def validate_archive_path(path: Path, *, aes_key: str | None = None) -> VerifiedArchive:
    if not path.is_file():
        raise BackupError(f"归档不存在：{path}")
    with path.open("rb") as handle:
        verified = validate_archive(handle, aes_key=aes_key, source=str(path))
    verified.path = path
    return verified


def check_existing_latest(path: Path) -> None:
    """覆盖目标保护：符号链接、未知文件或旧格式松散归档一律不自动覆盖。"""
    if path.is_symlink():
        raise BackupError(f"{path} 是符号链接，本工具拒绝跟随或覆盖；请人工核查后移除")
    if not path.exists():
        return
    try:
        validate_archive_path(path)
    except BackupError:
        raise BackupError(
            f"{path} 已存在但不是合法的 {FORMAT_NAME} 归档（未知文件或旧格式松散备份）；"
            "本工具不自动覆盖未知文件，请人工核查后移走再重跑"
        ) from None


def write_archive_atomic(
    destination_dir: Path,
    manifest: dict[str, Any],
    member_paths: dict[str, Path],
) -> Path:
    """打包候选归档并验证，flush/fsync 后在同一文件系统内 os.replace 整体替换。

    manifest 必须已包含最终成员摘要与 HMAC；本函数只负责打包、验证候选
    和原子替换。
    """
    destination_dir.mkdir(parents=True, exist_ok=True)
    latest = destination_dir / ARCHIVE_NAME
    check_existing_latest(latest)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{ARCHIVE_NAME}.candidate-", dir=destination_dir)
    os.close(fd)
    candidate = Path(tmp_name)
    try:
        with candidate.open("wb") as raw:
            with _GzipFileNoMtime(filename="", mode="wb", fileobj=raw) as gzip_stream:
                with tarfile.open(fileobj=gzip_stream, mode="w|") as tar:
                    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
                    _add_bytes(tar, MEMBER_MANIFEST, manifest_bytes)
                    for name in (MEMBER_BUSINESS, MEMBER_CHECKPOINT, MEMBER_FILES):
                        _add_file(tar, name, member_paths[name], manifest["members"][name]["size"])
            raw.flush()
            os.fsync(raw.fileno())
        candidate.chmod(0o600)
        with candidate.open("rb") as handle:
            validate_archive(handle, source=f"候选归档 {candidate.name}")
        os.replace(candidate, latest)
        latest.chmod(0o600)
        return latest
    except BaseException:
        candidate.unlink(missing_ok=True)
        raise


class _GzipFileNoMtime(gzip.GzipFile):
    """固定 mtime=0 的 gzip，保证归档字节可复现。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, mtime=0, **kwargs)


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = 0
    info.mode = 0o600
    info.type = tarfile.REGTYPE
    tar.addfile(info, io.BytesIO(data))


def _add_file(tar: tarfile.TarFile, name: str, path: Path, size: int) -> None:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mtime = 0
    info.mode = 0o600
    info.type = tarfile.REGTYPE
    with path.open("rb") as handle:
        tar.addfile(info, handle)


def build_synthetic_archive(
    destination: Path,
    *,
    backup_id: str | None = None,
    aes_key: str = "0" * 32,
    business: bytes = b"-- synthetic business dump\n",
    checkpoint: bytes = b"-- synthetic checkpoint dump\n",
    files_tar: bytes | None = None,
    members: Sequence[str] = REQUIRED_MEMBERS,
    corrupt_member: str | None = None,
    extra_members: dict[str, bytes] | None = None,
    tamper_manifest: Any = None,
) -> Path:
    """生成合成归档（测试与演练用）；不接触任何真实数据。"""
    if files_tar is None:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as inner:
            _add_bytes(inner, "uploads/hello.txt", b"synthetic upload\n")
        files_tar = buffer.getvalue()
    payload = {
        MEMBER_BUSINESS: business,
        MEMBER_CHECKPOINT: checkpoint,
        MEMBER_FILES: files_tar,
    }
    # 先按原始数据计算清单摘要，再对 corrupt_member 截断：模拟“归档数据
    # 与清单不一致”的损坏（成员字节被改但清单仍是原摘要）
    digests = {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}
    sizes = {name: len(data) for name, data in payload.items()}
    if corrupt_member and corrupt_member in payload:
        payload = dict(payload)
        payload[corrupt_member] = payload[corrupt_member][: max(0, len(payload[corrupt_member]) // 2)]
    member_table = {name: {"size": sizes[name], "sha256": digests[name]} for name in payload}
    manifest: dict[str, Any] = {
        "format": FORMAT_NAME,
        "backup_id": backup_id or new_backup_id(),
        "created_at": now_utc().isoformat(),
        "api_image": "example.invalid/blue-benchmark-api:synthetic",
        "business_schema_version": "synthetic",
        "members": member_table,
        "hmac": {
            "algorithm": HMAC_ALGORITHM,
            "value": hmac_sha256(
                aes_key,
                hmac_payload({name: member_table[name] for name in (MEMBER_BUSINESS, MEMBER_CHECKPOINT, MEMBER_FILES)}),
            ),
        },
    }
    if tamper_manifest is not None:
        manifest = tamper_manifest(manifest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    raw = destination.open("wb")
    try:
        with _GzipFileNoMtime(filename="", mode="wb", fileobj=raw) as gzip_stream:
            with tarfile.open(fileobj=gzip_stream, mode="w|") as tar:
                if MEMBER_MANIFEST in members:
                    _add_bytes(tar, MEMBER_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
                for name in members:
                    if name == MEMBER_MANIFEST:
                        continue
                    if name in payload:
                        _add_bytes(tar, name, payload[name])
                for name, data in (extra_members or {}).items():
                    _add_bytes(tar, name, data)
        raw.flush()
        os.fsync(raw.fileno())
    finally:
        raw.close()
    return destination


# ---------------------------------------------------------------------------
# Docker 交互（预检、停写、导出、恢复）
# ---------------------------------------------------------------------------


@dataclass
class ContainerInfo:
    service: str
    container_id: str
    state: str


def compose_ps(compose_dir: Path) -> list[ContainerInfo]:
    result = run_cmd(["docker", "compose", "ps", "--format", "json"], cwd=compose_dir)
    text = (result.stdout or "").strip()
    if not text:
        return []
    rows: Any
    try:
        # 旧版 Compose 输出 JSON 数组；单行 NDJSON 也落在这一分支
        data = json.loads(text)
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict) and ("Service" in data or "service" in data):
            rows = [data]
        else:
            rows = data.get("containers", []) if isinstance(data, dict) else []
    except json.JSONDecodeError:
        # 新版 Compose（v2.21+/v5）输出 NDJSON：每行一个 JSON 对象
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise BackupError("无法解析 docker compose ps 输出") from exc
    infos: list[ContainerInfo] = []
    for row in rows or []:
        service = str(row.get("Service") or row.get("service") or "")
        container_id = str(row.get("ID") or row.get("Id") or row.get("id") or "")
        state = str(row.get("State") or row.get("state") or "").lower()
        if service:
            infos.append(ContainerInfo(service=service, container_id=container_id, state=state))
    return infos


def list_databases(compose_dir: Path, user: str) -> set[str]:
    result = run_cmd(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", user, "-d", "postgres",
         "-Atc", "SELECT datname FROM pg_database"],
        cwd=compose_dir,
    )
    return {line.strip() for line in (result.stdout or "").splitlines() if line.strip()}


def check_write_connections(compose_dir: Path, user: str, dbnames: Sequence[str]) -> None:
    """确认停写：目标库上没有其他未授权写入连接；不杀未知进程。"""
    quoted = ",".join("'" + name.replace("'", "''") + "'" for name in dbnames)
    query = (
        "SELECT count(*) FROM pg_stat_activity "
        f"WHERE datname IN ({quoted}) AND backend_type = 'client backend' "
        "AND pid <> pg_backend_pid()"
    )
    result = run_cmd(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", user, "-d", "postgres", "-Atc", query],
        cwd=compose_dir,
    )
    try:
        count = int((result.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise BackupError("无法确认数据库停写：pg_stat_activity 查询没有返回计数") from exc
    if count > 0:
        raise BackupError(
            f"停写边界不存在：目标库上仍有 {count} 个其他客户端连接；恢复本次停止的服务并失败，不杀未知进程"
        )


def pgdata_size_bytes(compose_dir: Path) -> int | None:
    result = run_cmd(
        ["docker", "compose", "exec", "-T", "postgres", "du", "-sb", "/var/lib/postgresql/data"],
        cwd=compose_dir,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return int((result.stdout or "").strip().split()[0])
    except (ValueError, IndexError):
        return None


def stop_services(compose_dir: Path, services: Sequence[str]) -> None:
    run_cmd(["docker", "compose", "stop", *services], cwd=compose_dir, timeout=180)


def start_services(compose_dir: Path, services: Sequence[str]) -> None:
    run_cmd(["docker", "compose", "start", *services], cwd=compose_dir, timeout=180)


def wait_services_running(compose_dir: Path, services: Sequence[str], timeout: float = STARTUP_WAIT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    pending = set(services)
    while pending and time.monotonic() < deadline:
        infos = {info.service: info for info in compose_ps(compose_dir)}
        pending = {name for name in pending if infos.get(name) is None or infos[name].state != "running"}
        if not pending:
            return
        time.sleep(2)
    if pending:
        raise BackupError(f"服务启动失败：{'、'.join(sorted(pending))} 在 {timeout:.0f} 秒内未回到 running 状态")


def find_ossutil() -> str:
    for name in ("ossutil", "ossutil64"):
        path = shutil.which(name)
        if path:
            return name
    raise PreflightError("找不到 ossutil（或 ossutil64）；请先按 server-setup.md 安装并配置凭证")


def pg_dump_to(compose_dir: Path, target: DatabaseTarget, destination: Path) -> None:
    """在 postgres 容器内 pg_dump，导出流式落到权限受控的本地文件。"""
    with destination.open("wb") as handle:
        result = subprocess.run(  # noqa: S603 - 固定命令；argv 不含密码（容器内信任 peer 认证）
            ["docker", "compose", "exec", "-T", "postgres",
             "pg_dump", "-U", target.user, "--no-owner", "--no-privileges", target.dbname],
            cwd=str(compose_dir),
            stdout=handle,
            stderr=subprocess.PIPE,
            check=False,
        )
    if result.returncode != 0:
        destination.unlink(missing_ok=True)
        stderr = redact((result.stderr or b"").decode("utf-8", "replace"))
        raise BackupError(f"导出 {target.label} 失败（pg_dump 退出码 {result.returncode}）：{stderr.strip()}")


def export_files_tar(compose_dir: Path, config: DeployConfig, destination: Path) -> None:
    """用只读挂载 appdata 卷的一次性容器导出文件；不能对已停止的 api 用 exec。"""
    volume = config.appdata_volume
    if "/" not in volume:
        volume = f"{config.project_name}_{volume}"
    with destination.open("wb") as handle:
        result = subprocess.run(  # noqa: S603 - 固定命令，卷名来自已核验配置
            ["docker", "compose", "run", "--rm", "-T", "--no-deps",
             "-v", f"{volume}:/backup-src:ro",
             "--entrypoint", "tar", "api", "-cf", "-", "-C", "/backup-src", "."],
            cwd=str(compose_dir),
            stdout=handle,
            stderr=subprocess.PIPE,
            check=False,
        )
    if result.returncode != 0:
        destination.unlink(missing_ok=True)
        stderr = redact((result.stderr or b"").decode("utf-8", "replace"))
        raise BackupError(f"导出 appdata 文件失败（一次性容器退出码 {result.returncode}）：{stderr.strip()}")


# ---------------------------------------------------------------------------
# OSS：候选上传 -> 回读核对 -> 指针切换 -> 精确清旧（只留最新一套）
# ---------------------------------------------------------------------------


def _ossutil_cmd(config: DeployConfig) -> list[str]:
    ossutil = find_ossutil()
    endpoint_args = list(config.oss_endpoint_args)
    return [ossutil, *endpoint_args]


def ossutil(
    config: DeployConfig,
    args: Sequence[str],
    *,
    capture: bool = True,
    timeout: float = 600,
    check: bool = True,
    stdin_data: bytes | None = None,
) -> _RedactedCompleted:
    if config.oss is None:
        raise OssError("未配置 OSS 备份目标")
    return run_cmd(
        [*_ossutil_cmd(config), *args],
        cwd=config.compose_dir,
        capture=capture,
        timeout=timeout,
        check=check,
        stdin_data=stdin_data,
    )


def ossutil_capture(config: DeployConfig, args: Sequence[str], *, timeout: float = 120) -> str:
    result = ossutil(config, args, capture=True, timeout=timeout)
    return result.stdout or ""


def ossutil_cp(config: DeployConfig, source: str, destination: str, *, timeout: float = 1800) -> None:
    ossutil(config, ["cp", "-f", source, destination], timeout=timeout)


def oss_check_prerequisites(config: DeployConfig) -> None:
    """OSS 写入前置：Bucket 可达、专用前缀没有意外的版本控制/保留锁配置。

    已有保护性配置不匹配时失败并要求人工处理，不由脚本静默关闭保护。
    """
    assert config.oss is not None
    # 两项检查都用 check=False：没有配置版本控制/保留锁时 ossutil api 可能
    # 返回非零（如 NoSuchWORMConfiguration），这本身就是“没有保护性配置”
    versioning_result = ossutil(
        config, ["api", "get-bucket-versioning", "--bucket", config.oss.bucket], capture=True, timeout=60, check=False
    )
    versioning = versioning_result.stdout or ""
    if versioning_result.returncode == 0 and (
        '"Enabled"' in versioning or "'Enabled'" in versioning or versioning.strip().lower().startswith("enabled")
    ):
        raise OssError(
            f"Bucket {config.oss.bucket} 已启用版本控制，旧对象会以历史版本隐藏累积；"
            "与只留最新一套的留存策略不匹配，请人工处理（换专用 Bucket 或人工管理版本）"
        )
    retention_result = ossutil(
        config, ["api", "get-bucket-worm", "--bucket", config.oss.bucket], capture=True, timeout=60, check=False,
    )
    retention = retention_result.stdout or ""
    if "InProgress" in retention or "Locked" in retention:
        raise OssError(
            f"Bucket {config.oss.bucket} 存在保留锁（WORM）策略，无法按本工具语义清理旧对象；请人工处理"
        )
    # Bucket 必须可写：上传一个小的写入探针并删除
    probe_url = f"{config.oss.root}/.write-probe"
    payload = json.dumps({"probe": True, "at": now_utc().isoformat()}).encode("utf-8")
    ossutil(config, ["cp", "-f", "-", probe_url], stdin_data=payload, timeout=60)
    ossutil(config, ["rm", "-f", probe_url], timeout=60)


def oss_cleanup_stale(config: DeployConfig) -> list[str]:
    """清理专用前缀内本工具拥有的未发布候选、旧对象和未完成分片。

    只删除 bundles/ 下不被 latest 指针引用的 .tar.gz 对象；不删除指针
    指向的对象，不递归清空 Bucket，不动其他业务内容。
    """
    assert config.oss is not None
    actions: list[str] = []
    protected: str | None = None
    pointer_text = _oss_read_pointer(config)
    if pointer_text is not None:
        try:
            pointer = json.loads(pointer_text)
            protected = str(pointer.get("object") or "") or None
        except json.JSONDecodeError:
            protected = None

    bundles_url = f"{config.oss.root}/{OSS_BUNDLES_DIR}/"
    protected_url = f"{config.oss.root}/{protected}" if protected else None
    listing = ossutil_capture(config, ["ls", bundles_url], timeout=120)
    for line in listing.splitlines():
        match = re.search(r"(oss://\S+/bundles/[^\s]+\.tar\.gz)\s*$", line.strip())
        if not match:
            continue
        url = match.group(1)
        if protected_url and url == protected_url:
            continue
        ossutil(config, ["rm", "-f", url], timeout=60)
        actions.append(f"已删除未发布/过期候选对象：{url}")

    # 终止/清理本工具前缀内未完成的分片上传
    multipart = ossutil_capture(config, ["ls", bundles_url, "--multipart"], timeout=120)
    upload_ids = re.findall(r"([0-9A-Z]{16,})", multipart)
    for upload_id in set(upload_ids):
        completed = ossutil(
            config, ["rm", "-f", "-m", "-r", bundles_url, "--upload-id", upload_id], timeout=120, check=False,
        )
        if completed.returncode == 0:
            actions.append(f"已终止未完成分片上传：{upload_id}")
        else:
            actions.append(f"分片清理失败（需人工核查）：{upload_id}")
    return actions


def _oss_read_pointer(config: DeployConfig) -> str | None:
    """回读 latest 指针；对象不存在返回 None，其他失败抛出。"""
    assert config.oss is not None
    result = ossutil(config, ["cat", config.oss.pointer_url], capture=True, timeout=60, check=False)
    if result.returncode == 0:
        return result.stdout or ""
    output = result.safe_output.lower()
    if "nosuchkey" in output or "not exist" in output or "404" in output:
        return None
    raise OssError(f"读取 OSS latest 指针失败：{result.safe_output}")


def _oss_read_bundle_digest(config: DeployConfig, object_name: str) -> tuple[str, int]:
    """同地域内网回读候选并流式核对整包 SHA-256。

    不把对象存在性或 ETag 当作整包摘要证明。
    """
    assert config.oss is not None
    url = f"{config.oss.root}/{object_name}"
    process = subprocess.Popen(  # noqa: S603 - 固定命令
        [*_ossutil_cmd(config), "cat", url],
        cwd=str(config.compose_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    try:
        digest, size = sha256_stream(process.stdout)
    finally:
        process.stdout.close()
    stderr_bytes = process.stderr.read() if process.stderr else b""
    if process.stderr:
        process.stderr.close()
    returncode = process.wait()
    if returncode != 0:
        raise OssError(f"回读 OSS 候选失败（退出码 {returncode}）：{redact(stderr_bytes.decode('utf-8', 'replace'))}")
    if size == 0:
        raise OssError("回读 OSS 候选得到空响应（响应丢失），拒绝发布")
    return digest, size


def _oss_write_pointer(config: DeployConfig, object_name: str, backup_id: str, size: int, digest: str) -> None:
    assert config.oss is not None
    pointer = {
        "object": object_name,
        "backup_id": backup_id,
        "size": size,
        "sha256": digest,
        "updated_at": now_utc().isoformat(),
    }
    payload = (json.dumps(pointer, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    try:
        ossutil(config, ["cp", "-f", "-", config.oss.pointer_url], stdin_data=payload, timeout=120)
    except (BackupError, subprocess.TimeoutExpired):
        # 指针更新结果不明：先回读确认，不猜测删除可能正在使用的对象
        text = _oss_read_pointer(config)
        if text is not None:
            try:
                current = json.loads(text)
                if str(current.get("object") or "") == object_name:
                    return
            except json.JSONDecodeError:
                pass
        raise OssError("写入 OSS latest 指针失败且回读无法确认，保留旧指针/旧对象，本次云端更新失败") from None
    text = _oss_read_pointer(config)
    if text is None:
        raise OssError("写入 OSS latest 指针后回读不到内容，保留旧对象，本次云端更新失败")
    try:
        current = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OssError("OSS latest 指针回读内容不是合法 JSON，保留旧对象，本次云端更新失败") from exc
    if str(current.get("object") or "") != object_name:
        raise OssError("OSS latest 指针回读后未指向新候选（可能存在并发更新），保留旧对象，本次云端更新失败")


def oss_publish(config: DeployConfig, archive_path: Path, verified: VerifiedArchive) -> str:
    """发布候选：上传 -> 回读核对整包摘要 -> 切换指针 -> 精确删除上一对象。

    候选失败保留旧指针/旧对象；清理失败返回可诊断状态。发布前不删除任何
    旧对象（绝不先删后传）。
    """
    assert config.oss is not None
    backup_id = verified.backup_id
    object_name = f"{OSS_BUNDLES_DIR}/{backup_id}.tar.gz"
    local_digest, local_size = sha256_file(archive_path)

    old_pointer_text = _oss_read_pointer(config)
    old_object: str | None = None
    if old_pointer_text is not None:
        try:
            old_pointer = json.loads(old_pointer_text)
            old_object = str(old_pointer.get("object") or "") or None
        except json.JSONDecodeError:
            old_object = None

    ossutil_cp(config, str(archive_path), f"{config.oss.root}/{object_name}")
    try:
        remote_digest, remote_size = _oss_read_bundle_digest(config, object_name)
    except OssError:
        # 回读失败（响应丢失/读错）：删除本次候选，保留旧指针/旧对象
        ossutil(config, ["rm", "-f", f"{config.oss.root}/{object_name}"], timeout=60, check=False)
        raise OssError("OSS 候选回读失败（响应丢失或读取错误），已删除本次候选，保留旧指针/旧对象") from None
    if remote_digest != local_digest or remote_size != local_size:
        # 候选校验失败：删除本次候选，保留旧指针/旧对象
        ossutil(config, ["rm", "-f", f"{config.oss.root}/{object_name}"], timeout=60, check=False)
        raise OssError(
            "OSS 候选回读摘要与本地不一致（上传损坏或响应丢失），已删除本次候选，保留旧指针/旧对象"
        )
    _oss_write_pointer(config, object_name, backup_id, local_size, local_digest)

    # 只有确认远端指针已指向新候选，才删除精确的上一对象
    if old_object and old_object != object_name:
        result = ossutil(config, ["rm", "-f", f"{config.oss.root}/{old_object}"], timeout=60, check=False)
        if result.returncode != 0:
            return (
                f"已发布 {backup_id}；但旧对象 {old_object} 清理失败（退出码 {result.returncode}），"
                f"专用前缀内暂时存在两套，下一轮会先处理：{result.safe_output}"
            )
    return f"已发布 {backup_id} 并删除上一对象" if old_object else f"已发布 {backup_id}（首个云端恢复点）"


# ---------------------------------------------------------------------------
# 服务器每日备份（run）
# ---------------------------------------------------------------------------


def preflight(config: DeployConfig, backups_dir: Path, ossutil_name: str | None) -> None:
    """全部预检失败先于停写发生。"""
    if sys.version_info < (3, 10):
        raise PreflightError("需要 Python 3.10+")
    run_cmd(["docker", "compose", "version"], cwd=config.compose_dir)

    infos = {info.service: info for info in compose_ps(config.compose_dir)}
    for service in ("api", "worker", "postgres"):
        if service not in infos:
            raise PreflightError(f"服务 {service} 没有对应容器；先执行 docker compose up -d")
    if infos["postgres"].state != "running":
        raise PreflightError("postgres 容器未在运行，无法导出")
    for service in WRITE_SERVICES:
        if infos[service].state != "running":
            log(f"注意：服务 {service} 当前状态为 {infos[service].state}，本轮不会停止/恢复它")
    log(f"容器身份：api={infos['api'].container_id[:12]} worker={infos['worker'].container_id[:12]} postgres={infos['postgres'].container_id[:12]}")

    databases = list_databases(config.compose_dir, config.business.user)
    for target in (config.business, config.checkpoint):
        if target.dbname not in databases:
            raise PreflightError(
                f"{target.label} 指向的数据库 {target.dbname} 不存在；新建库可暂无 checkpoint 表，但库不存在必须拒绝"
            )

    backups_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(backups_dir, 0o700)
    latest = backups_dir / ARCHIVE_NAME
    check_existing_latest(latest)

    pgdata = pgdata_size_bytes(config.compose_dir)
    usage = shutil.disk_usage(backups_dir)
    if pgdata is not None:
        required = pgdata * DISK_SPACE_FACTOR
        if usage.free < required:
            raise PreflightError(
                f"磁盘可用空间不足：需要约 {required // (1024 * 1024)} MiB（pgdata 的 {DISK_SPACE_FACTOR} 倍），"
                f"实际可用 {usage.free // (1024 * 1024)} MiB"
            )
    else:
        log("警告：无法测量 pgdata 体积，跳过按倍数的空间预检")

    if config.oss is not None:
        if ossutil_name is None:
            raise PreflightError("已配置 OSS_* 但找不到 ossutil；请安装或移除 OSS 配置")
        run_cmd([ossutil_name, "--version"], cwd=config.compose_dir, check=False)
        oss_check_prerequisites(config)
        log("OSS 前置检查通过（版本控制/保留锁/写入探针）")


def cmd_run(args: argparse.Namespace) -> int:
    compose_dir = Path(args.compose_dir).resolve()
    backups_dir = Path(args.backups_dir).resolve() if args.backups_dir else compose_dir / "backups"
    config = load_deploy_config(compose_dir)
    log(f"配置核验通过：{config.safe_summary()}")

    ossutil_name: str | None = None
    if config.oss is not None:
        try:
            ossutil_name = find_ossutil()
        except PreflightError as exc:
            raise PreflightError(str(exc)) from None

    preflight(config, backups_dir, ossutil_name)
    state_path = backups_dir / STATE_NAME
    check_residual_state(state_path)

    with maintenance_lock(backups_dir):
        return _run_locked(config, backups_dir, state_path, args)


def _run_locked(config: DeployConfig, backups_dir: Path, state_path: Path, args: argparse.Namespace) -> int:
    stopped: list[ServiceSnapshot] = []
    workdir: Path | None = None
    server_result: str | None = None
    oss_result: str | None = None
    oss_failed = False
    services_restored = False
    backup_id = new_backup_id()
    created_at = now_utc().isoformat()
    try:
        infos = {info.service: info for info in compose_ps(config.compose_dir)}
        for service in WRITE_SERVICES:
            info = infos.get(service)
            stopped.append(
                ServiceSnapshot(
                    service=service,
                    container_id=info.container_id if info else "",
                    was_running=bool(info and info.state == "running"),
                )
            )
        write_recovery_state(
            state_path,
            {
                "backup_id": backup_id,
                "started_at": created_at,
                "stopped": [
                    {"service": item.service, "container_id": item.container_id, "was_running": item.was_running}
                    for item in stopped
                ],
            },
        )

        # ---- 停写窗口开始 ----
        to_stop = [item.service for item in stopped if item.was_running]
        if to_stop:
            log(f"停止写入服务：{'、'.join(to_stop)}（停写窗口开始）")
            stop_services(config.compose_dir, to_stop)
        try:
            check_write_connections(config.compose_dir, config.business.user, (config.business.dbname, config.checkpoint.dbname))
            workdir = Path(tempfile.mkdtemp(prefix=f"blue-benchmark-backup-{backup_id}-"))
            os.chmod(workdir, 0o700)
            log("导出业务库（停写窗口内）")
            pg_dump_to(config.compose_dir, config.business, workdir / MEMBER_BUSINESS)
            log("导出 checkpoint 库（停写窗口内）")
            pg_dump_to(config.compose_dir, config.checkpoint, workdir / MEMBER_CHECKPOINT)
            log("用只读一次性容器导出 appdata 文件（停写窗口内）")
            export_files_tar(config.compose_dir, config, workdir / MEMBER_FILES)
        finally:
            # ---- 停写窗口结束：立即恢复此前运行且本轮停止的服务 ----
            if to_stop:
                try:
                    start_services(config.compose_dir, to_stop)
                    wait_services_running(config.compose_dir, to_stop)
                    services_restored = True
                    log(f"服务已恢复：{'、'.join(to_stop)}")
                except Exception as exc:  # noqa: BLE001 - 恢复失败必须显式报告并保留状态
                    fail(f"恢复服务失败：{redact(str(exc))}；维护恢复状态保留在 {state_path}，请人工核查 docker compose ps")
                    raise
            else:
                services_restored = True

        # ---- 恢复服务之后：打包、验证、原子替换（不占用停写窗口） ----
        member_digests: dict[str, str] = {}
        member_sizes: dict[str, int] = {}
        for name in (MEMBER_BUSINESS, MEMBER_CHECKPOINT, MEMBER_FILES):
            digest, size = sha256_file(workdir / name)
            member_digests[name] = digest
            member_sizes[name] = size
        manifest = build_manifest(
            backup_id,
            created_at,
            member_digests,
            member_sizes,
            config.aes_key,
            api_image=config.api_image,
            business_schema_version=config.business_schema_version,
        )

        latest = write_archive_atomic(
            backups_dir,
            manifest,
            {name: workdir / name for name in (MEMBER_BUSINESS, MEMBER_CHECKPOINT, MEMBER_FILES)},
        )
        verified = validate_archive_path(latest, aes_key=config.aes_key)
        server_result = f"服务器副本已更新：备份 ID {verified.backup_id}，生成时间 {verified.created_at}"
        log(server_result)

        state_path.unlink(missing_ok=True)
        shutil.rmtree(workdir, ignore_errors=True)
        workdir = None

        # ---- OSS 更新（服务恢复之后才上传；失败不回滚服务器副本） ----
        if config.oss is not None:
            try:
                stale_actions = oss_cleanup_stale(config)
                for action in stale_actions:
                    log(f"OSS 前置清理：{action}")
                oss_result = f"OSS 副本：{oss_publish(config, latest, verified)}"
            except (OssError, BackupError, subprocess.TimeoutExpired) as exc:
                oss_failed = True
                oss_result = f"OSS 副本：本次更新失败（{redact(str(exc))}）；服务器最新副本不受影响，云端仍指向上一次成功备份"
                fail(oss_result)
        else:
            oss_result = "OSS 副本：未配置 OSS_*，跳过"
            log(oss_result)

        log(f"备份结果汇总：{server_result}；{oss_result}")
        if oss_failed:
            log("服务器完整备份成功；OSS 本次更新失败，云端仍指向上一次成功备份")
        else:
            log("完整备份成功")
        return 0
    except BaseException as exc:
        # 普通失败与 SIGINT/SIGTERM：finally 语义保证不输出完整成功，
        # 本次停止的服务已在导出块的 finally 中恢复（或已报告恢复失败）。
        if server_result is None:
            fail(f"本次备份失败：{redact(str(exc)) if not isinstance(exc, KeyboardInterrupt) else '收到中断信号'}；保留原有 latest.tar.gz")
        if workdir is not None:
            shutil.rmtree(workdir, ignore_errors=True)
        if services_restored:
            # 服务已确认恢复（或本轮从未停止）：维护状态不再需要，删除以免
            # 阻塞下一次运行；恢复失败/进程被 SIGKILL 时状态文件保留供核查
            state_path.unlink(missing_ok=True)
        if isinstance(exc, KeyboardInterrupt):
            return 130
        return 1


# ---------------------------------------------------------------------------
# Mac 每日下载（download）
# ---------------------------------------------------------------------------


def _ssh_base(host: str) -> list[str]:
    if not HOST_PATTERN.match(host):
        raise DownloadError(f"非法 SSH 主机参数：{host!r}（只接受现有主机别名，不关闭 host-key 检查）")
    return ["ssh", "-o", "BatchMode=yes", host]


def _scp_base(host: str) -> list[str]:
    if not HOST_PATTERN.match(host):
        raise DownloadError(f"非法 SSH 主机参数：{host!r}")
    return ["scp", "-o", "BatchMode=yes"]


def _remote_stat(host: str, remote_path: str) -> tuple[str, int]:
    """远端只读查询 latest 归档的大小和摘要（固定命令 + 转义路径）。"""
    script = f"stat -c %s {sh_quote(remote_path)} && sha256sum {sh_quote(remote_path)}"
    result = run_cmd([*_ssh_base(host), script], timeout=300)
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    if len(lines) < 2:
        raise DownloadError(f"远端归档信息不完整（文件不存在或路径错误）：{remote_path}")
    try:
        size = int(lines[0])
    except ValueError as exc:
        raise DownloadError(f"远端 stat 输出无法解析：{remote_path}") from exc
    digest = lines[1].split()[0]
    if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        raise DownloadError("远端 sha256sum 输出无法解析")
    return digest.lower(), size


def cmd_download(args: argparse.Namespace) -> int:
    host = args.host
    remote_path = args.remote_path
    local_dir = Path(args.local_dir).resolve()
    local_latest = local_dir / ARCHIVE_NAME

    local_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(local_dir, 0o700)
    check_existing_latest(local_latest)

    with maintenance_lock(local_dir):
        check_existing_latest(local_latest)
        try:
            remote_digest, remote_size = _remote_stat(host, remote_path)
            existing_digest: str | None = None
            if local_latest.is_file():
                existing_digest, _ = sha256_file(local_latest)
            if existing_digest == remote_digest:
                verified = validate_archive_path(local_latest)
                log(
                    f"本机 latest 与服务器归档一致（同 ID 幂等，不重复下载）："
                    f"备份 ID {verified.backup_id}，服务器生成时间 {verified.created_at}"
                )
                log("这是服务器已生成的版本，不保证包含下载时刻之后新增的数据。")
                return 0

            usage = shutil.disk_usage(local_dir)
            if usage.free < remote_size * 2 + 64 * 1024 * 1024:
                raise DownloadError(
                    f"本机磁盘可用空间不足：需要约 {remote_size * 2 // (1024 * 1024)} MiB，"
                    f"实际可用 {usage.free // (1024 * 1024)} MiB"
                )

            fd, tmp_name = tempfile.mkstemp(prefix=f".{ARCHIVE_NAME}.download-", dir=local_dir)
            os.close(fd)
            tmp_path = Path(tmp_name)
            try:
                downloaded = False
                for attempt in range(1, COPY_ATTEMPTS + 1):
                    result = run_cmd(
                        [*_scp_base(host), "-q", f"{host}:{remote_path}", str(tmp_path)],
                        capture=True,
                        check=False,
                        timeout=7200,
                    )
                    if result.returncode != 0:
                        log(f"第 {attempt}/{COPY_ATTEMPTS} 次下载失败：{result.safe_output or '网络中断'}")
                        continue
                    local_digest, local_size = sha256_file(tmp_path)
                    if local_size != remote_size or local_digest != remote_digest:
                        log(f"第 {attempt}/{COPY_ATTEMPTS} 次下载校验不一致（传输被截断），重试")
                        continue
                    downloaded = True
                    break
                if not downloaded:
                    raise DownloadError(f"连续 {COPY_ATTEMPTS} 次下载/校验失败；本机旧 latest 保持不变")

                # 完整校验：结构、成员摘要、传输完成（不要求每天输入密钥）
                verified = validate_archive_path(tmp_path)
                tmp_path.chmod(0o600)
                os.replace(tmp_path, local_latest)
                local_latest.chmod(0o600)
                log(
                    f"下载完成并覆盖本机 latest：备份 ID {verified.backup_id}，"
                    f"服务器生成时间 {verified.created_at}（不含下载时刻后新增数据）"
                )
                return 0
            except BaseException:
                tmp_path.unlink(missing_ok=True)
                raise
        except DownloadError as exc:
            fail(str(exc))
            return 1
        except BackupError as exc:
            fail(redact(str(exc)))
            return 1


# ---------------------------------------------------------------------------
# verify / restore-check
# ---------------------------------------------------------------------------


def cmd_verify(args: argparse.Namespace) -> int:
    path = Path(args.archive).resolve()
    aes_key: str | None = None
    if args.aes_key:
        raise BackupError("不允许通过命令行参数传密钥（会进入 shell 历史/argv）；请使用 --aes-key-file 或环境变量")
    if args.aes_key_file:
        aes_key = Path(args.aes_key_file).read_text(encoding="utf-8").strip()
    elif os.environ.get("BLUE_BENCHMARK_BACKUP_AES_KEY"):
        aes_key = os.environ["BLUE_BENCHMARK_BACKUP_AES_KEY"].strip()
    try:
        verified = validate_archive_path(path, aes_key=aes_key)
    except BackupError as exc:
        fail(str(exc))
        return 1
    manifest = verified.manifest
    log(f"归档校验通过：{path}")
    log(f"  格式：{manifest['format']}")
    log(f"  备份 ID：{verified.backup_id}")
    log(f"  服务器生成时间：{verified.created_at}")
    log(f"  应用镜像：{manifest.get('api_image') or '未知'}")
    log(f"  业务 schema 版本：{manifest.get('business_schema_version') or '未知'}")
    for name in (MEMBER_BUSINESS, MEMBER_CHECKPOINT, MEMBER_FILES):
        log(f"  成员 {name}：{verified.member_sizes[name]} 字节，sha256={verified.member_digests[name]}")
    log(f"  HMAC：{'已用原密钥核对通过' if aes_key else '未提供密钥，跳过 HMAC 核对（真正恢复前必须核对）'}")
    return 0


def cmd_restore_check(args: argparse.Namespace) -> int:
    """恢复预检：真正的恢复是 restore.md 文档化的人工步骤。

    这里核对归档格式、完整性，以及（提供密钥文件时）原密钥 HMAC；
    任一项失败都必须停在重新开放写入之前。不执行归档中的任何命令或 SQL。
    """
    path = Path(args.archive).resolve()
    aes_key: str | None = None
    if args.aes_key_file:
        aes_key = Path(args.aes_key_file).read_text(encoding="utf-8").strip()
    try:
        verified = validate_archive_path(path, aes_key=aes_key)
    except BackupError as exc:
        fail(f"恢复预检失败：{exc}")
        fail("缺少 checkpoint、错误密钥或损坏备份时，恢复必须在重新开放写入前失败；不生成替代密钥。")
        return 1
    log(f"恢复预检通过：备份 ID {verified.backup_id}，生成时间 {verified.created_at}")
    log(f"应用镜像标识：{verified.manifest.get('api_image') or '未知'}（恢复环境需使用相容镜像）")
    if aes_key is None:
        log("未提供密钥文件：HMAC 未核对；实际恢复前必须用原 LANGGRAPH_AES_KEY 核对（--aes-key-file）")
    log("下一步按 deploy/restore.md 人工执行：暂停调度、取得维护互斥锁、停止写入、重建目标两库与文件卷。")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backup.py",
        description="blue-benchmark 部署备份工具（唯一格式 blue-benchmark-backup/v1，三处只留最新一套）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="服务器每日备份全流程（cron 经 backup.sh 调用）")
    run_parser.add_argument("--compose-dir", required=True, help="明确的 Compose 目录（如 /opt/blue-benchmark）")
    run_parser.add_argument("--backups-dir", default=None, help="归档目录（默认 <compose-dir>/backups，固定 latest.tar.gz）")
    run_parser.set_defaults(handler=cmd_run)

    verify_parser = sub.add_parser("verify", help="离线校验归档（不执行其中命令或 SQL）")
    verify_parser.add_argument("archive", help="归档路径（latest.tar.gz）")
    verify_parser.add_argument("--aes-key", default=None, help="占位：禁止 argv 传密钥，请用 --aes-key-file")
    verify_parser.add_argument("--aes-key-file", default=None, help="原 LANGGRAPH_AES_KEY 所在文件（600 权限，另行安全保管）")
    verify_parser.set_defaults(handler=cmd_verify)

    download_parser = sub.add_parser("download", help="Mac 经 SSH 下载服务器 latest 并原子覆盖本机副本")
    download_parser.add_argument("--host", required=True, help="SSH 主机别名（~/.ssh/config 中已有）")
    download_parser.add_argument(
        "--remote-path", default="/opt/blue-benchmark/backups/latest.tar.gz", help="服务器归档绝对路径（只读）"
    )
    download_parser.add_argument(
        "--local-dir", default=str(Path.home() / "blue-benchmark-backups"), help="本机专用目录（默认 ~/blue-benchmark-backups）"
    )
    download_parser.set_defaults(handler=cmd_download)

    restore_parser = sub.add_parser("restore-check", help="恢复预检（人工恢复步骤的第一道门）")
    restore_parser.add_argument("archive", help="归档路径")
    restore_parser.add_argument("--aes-key-file", default=None, help="原 LANGGRAPH_AES_KEY 所在文件")
    restore_parser.set_defaults(handler=cmd_restore_check)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except LockBusyError as exc:
        fail(str(exc))
        return 2
    except BackupError as exc:
        fail(str(exc))
        return 1
    except KeyboardInterrupt:
        fail("收到中断信号；本次停止的服务应已恢复，请按维护恢复状态核查")
        return 130


if __name__ == "__main__":
    sys.exit(main())
