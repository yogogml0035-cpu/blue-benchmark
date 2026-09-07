"""deploy/backup.py 的默认回归测试：无外部副作用。

全部使用 fake docker/ossutil/ssh/scp（PATH 假脚本）、tmp_path 与合成数据：
不连接真实服务器/OSS，不接触本机 Docker，不读写业务数据库。真实 Docker
集成入口属于 backend/tests/test_deploy_runtime.py（DEPLOY_INTEGRATION_REQUIRED），
不在本文件。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import textwrap
from pathlib import Path
from typing import Any, Callable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_ROOT / "deploy"
if str(DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOY_DIR))

import backup  # noqa: E402

TEST_AES_KEY = "ab" * 16
OSS_BUCKET_DIR = "blue-benchmark-backup-bucket"
# fake ossutil 的本地对象布局为 <OSS_LOCAL>/<bucket>/<prefix>/...
OSS_BASE = f"{OSS_BUCKET_DIR}/blue-benchmark-backups"
WRONG_AES_KEY = "cd" * 16
PASSWORD = "super-secret-pass"
BUSINESS_DSN = f"postgresql+psycopg://blue_benchmark:{PASSWORD}@postgres:5432/blue_benchmark"
CHECKPOINT_DSN = f"postgresql://blue_benchmark:{PASSWORD}@postgres:5432/blue_benchmark_checkpoint"

# ---------------------------------------------------------------------------
# fake docker / ossutil / ssh / scp 脚本
# ---------------------------------------------------------------------------

FAKE_DOCKER = r"""#!/usr/bin/env bash
set -u
echo "$@" >> "$EVENTS"
if [ "$1" != "compose" ]; then echo "unexpected docker $1" >&2; exit 90; fi
shift
sub="$1"; shift
state_file="${SERVICE_STATE:?}"
get_state() { sed -n "s/^$1=//p" "$state_file"; }
set_state() { sed -i.bak "s/^$1=.*/$1=$2/" "$state_file" && rm -f "$state_file.bak"; }
case "$sub" in
  version) echo "Docker Compose version v2.29.0"; exit 0 ;;
  config) cat "${FAKE_COMPOSE_CONFIG:?}"; exit 0 ;;
  ps)
    printf '[{"ID":"api0000000001","Service":"api","State":"%s"},{"ID":"worker0000002","Service":"worker","State":"%s"},{"ID":"pg00000000003","Service":"postgres","State":"%s"}]\n' \
      "$(get_state api)" "$(get_state worker)" "$(get_state postgres)"
    exit 0 ;;
  stop)
    for svc in "$@"; do set_state "$svc" "exited"; done
    exit 0 ;;
  start)
    if [ "${FAIL_START:-0}" = "1" ]; then echo "failed to start: injected failure" >&2; exit 1; fi
    for svc in "$@"; do set_state "$svc" "running"; done
    exit 0 ;;
  exec)
    # exec -T postgres <cmd...>
    shift  # -T
    shift  # postgres
    tool="$1"; shift
    case "$tool" in
      psql)
        args="$*"
        case "$args" in
          *pg_database*) cat "${FAKE_DATABASES:?}"; exit 0 ;;
          *pg_stat_activity*) echo "${FAKE_CONN_COUNT:-0}"; exit 0 ;;
          *) echo "unexpected psql query" >&2; exit 91 ;;
        esac ;;
      du) echo "${FAKE_PGDATA_SIZE:-1048576}	/var/lib/postgresql/data"; exit 0 ;;
      pg_dump)
        dbname=""
        prev=""
        for a in "$@"; do
          if [ "$prev" = "--no-privileges" ]; then dbname="$a"; fi
          prev="$a"
        done
        if [ -n "${FAIL_DUMP_DB:-}" ] && [ "$dbname" = "$FAIL_DUMP_DB" ]; then
          echo "pg_dump: error: could not connect to database" >&2; exit 1
        fi
        if [ "$dbname" = "blue_benchmark" ]; then cat "${FAKE_DUMP_BUSINESS:?}";
        elif [ "$dbname" = "blue_benchmark_checkpoint" ]; then cat "${FAKE_DUMP_CHECKPOINT:?}";
        else echo "pg_dump: unknown database $dbname" >&2; exit 1; fi
        exit 0 ;;
      *) echo "unexpected exec tool $tool" >&2; exit 92 ;;
    esac ;;
  run)
    if [ "${FAIL_FILES:-0}" = "1" ]; then echo "tar: read error: injected" >&2; exit 1; fi
    cat "${FAKE_FILES_TAR:?}"
    exit 0 ;;
  *) echo "unexpected compose subcommand $sub" >&2; exit 93 ;;
esac
"""

FAKE_OSSUTIL = r"""#!/usr/bin/env bash
set -u
printf '%s\n' "$*" >> "$EVENTS"
if [ "${1:-}" = "-e" ]; then shift 2; fi
cmd="$1"; shift
key_of() { echo "${1#oss://}"; }
case "$cmd" in
  --version) echo "ossutil version 2.1.1"; exit 0 ;;
  api)
    api="$1"; shift
    case "$api" in
      get-bucket-versioning) cat "${FAKE_VERSIONING:-/dev/null}"; exit 0 ;;
      get-bucket-worm) echo "NoSuchWORMConfiguration" >&2; exit 1 ;;
      *) echo "unexpected api $api" >&2; exit 94 ;;
    esac ;;
  cp)
    # cp -f <src> <dst>
    shift
    src="$1"; dst="$2"
    # 注入开关只作用于 bundle 候选上传，不影响预检探针与 latest 指针写入
    case "$dst" in
      */bundles/*)
        if [ "${FAIL_CP:-0}" = "1" ]; then echo "ossutil: injected cp failure" >&2; exit 1; fi
        ;;
    esac
    if [ "$src" = "-" ]; then
      out="$OSS_LOCAL/$(key_of "$dst")"
      mkdir -p "$(dirname "$out")"
      cat > "$out"
      exit 0
    fi
    out="$OSS_LOCAL/$(key_of "$dst")"
    mkdir -p "$(dirname "$out")"
    cp "$src" "$out"
    case "$dst" in
      */bundles/*)
        if [ "${CORRUPT_CP:-0}" = "1" ]; then echo "corrupted" >> "$out"; fi
        if [ "${DROP_CP:-0}" = "1" ]; then : > "$out"; fi
        ;;
    esac
    exit 0 ;;
  cat)
    key="$(key_of "$1")"
    if [ -n "${FAIL_CAT:-}" ] && [[ "$key" == *"${FAIL_CAT}"* ]]; then
      echo "ossutil: injected cat failure" >&2; exit 1
    fi
    if [ -f "$OSS_LOCAL/$key" ]; then cat "$OSS_LOCAL/$key"; exit 0; fi
    echo "ErrorCode=NoSuchKey" >&2; exit 1 ;;
  rm)
    shift
    if [ "${FAIL_RM:-0}" = "1" ]; then echo "ossutil: injected rm failure" >&2; exit 1; fi
    for target in "$@"; do
      case "$target" in oss://*) rm -f "$OSS_LOCAL/$(key_of "$target")" ;; esac
    done
    exit 0 ;;
  ls)
    target="$1"; shift || true
    multipart=0
    for a in "$@"; do [ "$a" = "--multipart" ] && multipart=1; done
    if [ "$multipart" = "1" ]; then cat "${FAKE_MULTIPART:-/dev/null}"; exit 0; fi
    base="$(key_of "$target")"
    find "$OSS_LOCAL/${base%/}" -type f 2>/dev/null | while read -r f; do
      echo "2026-09-07 03:00:00 +0000 UTC   1024   Standard   oss://${f#"$OSS_LOCAL/"}"
    done
    exit 0 ;;
  *) echo "unexpected ossutil command $cmd" >&2; exit 95 ;;
esac
"""

FAKE_SSH = r"""#!/usr/bin/env bash
set -u
echo "ssh $@" >> "$EVENTS"
case "$*" in *StrictHostKeyChecking=no*) echo "forbidden ssh option" >&2; exit 96 ;; esac
host_found=0
for a in "$@"; do
  case "$a" in -*) ;; *) host_found=1; break ;; esac
done
[ "$host_found" = "1" ] || { echo "no host" >&2; exit 97; }
script="${*: -1}"
case "$script" in
  stat\ -c*)
    path="$(printf '%s\n' "$script" | awk -F"'" '{print $2}')"
    [ -n "$path" ] || { echo "no path in remote script" >&2; exit 98; }
    if [ ! -f "$path" ]; then echo "stat: cannot stat: No such file" >&2; exit 1; fi
    wc -c < "$path" | tr -d ' \n'; echo
    shasum -a 256 "$path" | awk '{print $1}'
    exit 0 ;;
  *) echo "unexpected remote script" >&2; exit 99 ;;
esac
"""

FAKE_SCP = r"""#!/usr/bin/env bash
set -u
echo "scp $@" >> "$EVENTS"
if [ "${FAIL_SCP:-0}" = "1" ]; then echo "scp: injected network failure" >&2; exit 1; fi
src=""; dst=""
skip_next=0
for a in "$@"; do
  if [ "$skip_next" = "1" ]; then skip_next=0; continue; fi
  case "$a" in
    -o|-i|-F|-l|-P) skip_next=1; continue ;;
    -*) continue ;;
  esac
  if [ -z "$src" ]; then src="$a"; else dst="$a"; fi
done
remote="${src#*:}"
if [ "${DROP_TAIL:-0}" = "1" ]; then
  python3 -c 'import sys; data=open(sys.argv[1],"rb").read(); open(sys.argv[2],"wb").write(data[:max(0,len(data)-1000)])' "$remote" "$dst"
  exit 0
fi
cp "$remote" "$dst"
"""


@pytest.fixture()
def fake_bin(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 fake docker/ossutil/ssh/scp 放进 PATH 最前面。"""
    bin_dir = tmp_path_factory.mktemp("fakebin")
    for name, body in (
        ("docker", FAKE_DOCKER),
        ("ossutil", FAKE_OSSUTIL),
        ("ssh", FAKE_SSH),
        ("scp", FAKE_SCP),
    ):
        script = bin_dir / name
        script.write_text(body, encoding="utf-8")
        script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return bin_dir


# ---------------------------------------------------------------------------
# 合成部署环境（compose 配置 + 服务端归档 + OSS 本地映射）
# ---------------------------------------------------------------------------


def compose_config_json(*, checkpoint_db: str = "blue_benchmark_checkpoint", extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    env: dict[str, str] = {
        "DATABASE_URL": BUSINESS_DSN,
        "CHECKPOINT_DATABASE_URL": f"postgresql://blue_benchmark:{PASSWORD}@postgres:5432/{checkpoint_db}",
        "LANGGRAPH_AES_KEY": TEST_AES_KEY,
        "OSS_BUCKET": "blue-benchmark-backup-bucket",
        "OSS_PREFIX": "blue-benchmark-backups",
        "OSS_ENDPOINT": "oss-cn-beijing-internal.aliyuncs.com",
    }
    env.update(extra_env or {})
    return {
        "name": "blue-benchmark",
        "services": {
            "api": {
                "image": "registry.example.invalid/blue-benchmark-api:20260907-abc1234",
                "environment": dict(env),
                "volumes": [{"type": "volume", "source": "appdata", "target": "/app/storage"}],
            },
            "worker": {
                "image": "registry.example.invalid/blue-benchmark-api:20260907-abc1234",
                "environment": dict(env),
                "volumes": [{"type": "volume", "source": "appdata", "target": "/app/storage"}],
            },
            "postgres": {
                "image": "postgres:16-alpine",
                "environment": {
                    "POSTGRES_USER": "blue_benchmark",
                    "POSTGRES_PASSWORD": PASSWORD,
                    "POSTGRES_DB": "blue_benchmark",
                },
            },
        },
    }


@pytest.fixture()
def env(tmp_path: Path, fake_bin: Path) -> dict[str, Any]:
    """一个可用的合成部署环境；返回测试可控的开关字典。"""
    compose_dir = tmp_path / "opt" / "blue-benchmark"
    compose_dir.mkdir(parents=True)
    (compose_dir / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    backups_dir = compose_dir / "backups"
    backups_dir.mkdir()

    work = tmp_path / "fake"
    work.mkdir()
    events = work / "events.log"
    events.write_text("", encoding="utf-8")
    state = work / "services.state"
    state.write_text("api=running\nworker=running\npostgres=running\n", encoding="utf-8")
    (work / "compose-config.json").write_text(json.dumps(compose_config_json()), encoding="utf-8")
    (work / "databases.txt").write_text("blue_benchmark\nblue_benchmark_checkpoint\npostgres\n", encoding="utf-8")
    (work / "business.sql").write_bytes(b"-- synthetic business dump\nCREATE TABLE questions (id int);\n")
    (work / "checkpoint.sql").write_bytes(b"-- synthetic checkpoint dump\n")

    files_buf = io.BytesIO()
    with tarfile.open(fileobj=files_buf, mode="w") as files_tar:
        data = b"synthetic upload\n"
        info = tarfile.TarInfo("uploads/hello.txt")
        info.size = len(data)
        files_tar.addfile(info, io.BytesIO(data))
    (work / "files.tar").write_bytes(files_buf.getvalue())

    oss_local = tmp_path / "oss"
    oss_local.mkdir()

    # Mac 端：SSH 主机别名与专用下载目录
    ssh_dir = tmp_path / "sshhome" / ".ssh"
    ssh_dir.mkdir(parents=True)
    (ssh_dir / "config").write_text("Host evalserver\n  HostName 10.0.0.1\n", encoding="utf-8")

    switches = {
        "EVENTS": str(events),
        "SERVICE_STATE": str(state),
        "FAKE_COMPOSE_CONFIG": str(work / "compose-config.json"),
        "FAKE_DATABASES": str(work / "databases.txt"),
        "FAKE_DUMP_BUSINESS": str(work / "business.sql"),
        "FAKE_DUMP_CHECKPOINT": str(work / "checkpoint.sql"),
        "FAKE_FILES_TAR": str(work / "files.tar"),
        "FAKE_PGDATA_SIZE": "1048576",
        "FAKE_CONN_COUNT": "0",
        "OSS_LOCAL": str(oss_local),
        "HOME": str(tmp_path / "sshhome"),
    }
    os.environ.update(switches)
    return {
        "tmp_path": tmp_path,
        "compose_dir": compose_dir,
        "backups_dir": backups_dir,
        "work": work,
        "oss_local": oss_local,
        "events": events,
        "switches": switches,
    }


@pytest.fixture(autouse=True)
def _clean_env_keys():
    added = [
        "EVENTS", "SERVICE_STATE", "FAKE_COMPOSE_CONFIG", "FAKE_DATABASES",
        "FAKE_DUMP_BUSINESS", "FAKE_DUMP_CHECKPOINT", "FAKE_FILES_TAR",
        "FAKE_PGDATA_SIZE", "FAKE_CONN_COUNT", "FAIL_START", "FAIL_DUMP_DB",
        "FAIL_FILES", "FAIL_CP", "FAIL_RM", "FAIL_CAT", "FAIL_SCP", "DROP_TAIL",
        "CORRUPT_CP", "DROP_CP", "FAKE_VERSIONING", "FAKE_MULTIPART",
        "OSS_LOCAL", "HOME", "BLUE_BENCHMARK_BACKUP_AES_KEY",
    ]
    saved = {key: os.environ.get(key) for key in added}
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def event_lines(env: dict[str, Any]) -> list[str]:
    return [line for line in env["events"].read_text(encoding="utf-8").splitlines() if line.strip()]


def set_switch(key: str, value: str) -> None:
    os.environ[key] = value


def oss_objects(env: dict[str, Any]) -> set[str]:
    root: Path = env["oss_local"]
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


def run_cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = backup.main(argv)
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def run_subprocess(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(DEPLOY_DIR / "backup.py"), *argv],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def run_success(env: dict[str, Any], capsys: pytest.CaptureFixture[str], backups_dir: Path | None = None) -> str:
    code, output = run_cli(
        ["run", "--compose-dir", str(env["compose_dir"]), "--backups-dir", str(backups_dir or env["backups_dir"])],
        capsys,
    )
    assert code == 0, output
    assert "完整备份成功" in output
    return output


def run_success_all(env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> str:
    """要求服务器与 OSS 两处都成功的 run。"""
    output = run_success(env, capsys)
    assert "OSS 副本：本次更新失败" not in output, output
    return output


def assert_no_secrets(text: str) -> None:
    assert PASSWORD not in text, "输出泄漏了数据库密码"
    assert TEST_AES_KEY not in text, "输出泄漏了 AES 密钥"
    assert f"blue_benchmark:{PASSWORD}@" not in text, "输出泄漏了含凭证的 DSN"


def service_states(env: dict[str, Any]) -> dict[str, str]:
    states: dict[str, str] = {}
    for line in Path(os.environ["SERVICE_STATE"]).read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            states[key] = value
    return states


def backup_id_from_output(output: str) -> str:
    import re as re_mod

    match = re_mod.search(r"备份 ID (\S+?)，", output)
    assert match, f"输出中没有备份 ID：{output}"
    return match.group(1)


# ---------------------------------------------------------------------------
# 归档格式
# ---------------------------------------------------------------------------


class TestArchiveFormat:
    def test_valid_archive_passes_with_key(self, tmp_path: Path) -> None:
        archive = backup.build_synthetic_archive(tmp_path / "latest.tar.gz", aes_key=TEST_AES_KEY)
        verified = backup.validate_archive_path(archive, aes_key=TEST_AES_KEY)
        assert verified.manifest["format"] == backup.FORMAT_NAME
        assert set(verified.member_digests) == {backup.MEMBER_BUSINESS, backup.MEMBER_CHECKPOINT, backup.MEMBER_FILES}

    def test_missing_member_rejected(self, tmp_path: Path) -> None:
        archive = backup.build_synthetic_archive(
            tmp_path / "latest.tar.gz",
            members=(backup.MEMBER_MANIFEST, backup.MEMBER_BUSINESS, backup.MEMBER_FILES),
        )
        with pytest.raises(backup.BackupError, match="缺少成员"):
            backup.validate_archive_path(archive)

    def test_old_loose_format_rejected(self, tmp_path: Path) -> None:
        # 旧的两份松散文件不是完整恢复点
        import gzip as gzip_mod

        loose = tmp_path / "db-20260101-030000.sql.gz"
        loose.write_bytes(gzip_mod.compress(b"-- only business"))
        (tmp_path / "files-20260101-030000.tar.gz").write_bytes(gzip_mod.compress(b"files"))
        with pytest.raises(backup.BackupError):
            backup.validate_archive_path(loose)

    def test_truncated_archive_rejected(self, tmp_path: Path) -> None:
        archive = backup.build_synthetic_archive(tmp_path / "latest.tar.gz")
        data = archive.read_bytes()
        truncated = tmp_path / "truncated.tar.gz"
        truncated.write_bytes(data[: len(data) // 2])
        with pytest.raises(backup.BackupError, match="损坏|截断|不完整"):
            backup.validate_archive_path(truncated)

    def test_corrupted_member_rejected(self, tmp_path: Path) -> None:
        archive = backup.build_synthetic_archive(tmp_path / "latest.tar.gz", corrupt_member=backup.MEMBER_BUSINESS)
        with pytest.raises(backup.BackupError, match="不一致"):
            backup.validate_archive_path(archive)

    def test_wrong_key_hmac_rejected(self, tmp_path: Path) -> None:
        archive = backup.build_synthetic_archive(tmp_path / "latest.tar.gz", aes_key=TEST_AES_KEY)
        with pytest.raises(backup.BackupError, match="HMAC"):
            backup.validate_archive_path(archive, aes_key=WRONG_AES_KEY)

    def test_without_key_hmac_skipped(self, tmp_path: Path) -> None:
        # Mac 日常下载不要求每天输入密钥：结构+成员摘要仍必须通过
        archive = backup.build_synthetic_archive(tmp_path / "latest.tar.gz", aes_key=TEST_AES_KEY)
        verified = backup.validate_archive_path(archive)
        assert verified.backup_id

    def test_duplicate_member_rejected(self, tmp_path: Path) -> None:
        archive = backup.build_synthetic_archive(
            tmp_path / "latest.tar.gz", extra_members={backup.MEMBER_BUSINESS: b"duplicate"}
        )
        with pytest.raises(backup.BackupError, match="重复成员"):
            backup.validate_archive_path(archive)

    def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        archive = backup.build_synthetic_archive(tmp_path / "latest.tar.gz", extra_members={"../evil.sql": b"x"})
        with pytest.raises(backup.BackupError, match="越界|绝对路径"):
            backup.validate_archive_path(archive)
        absolute = backup.build_synthetic_archive(tmp_path / "abs.tar.gz", extra_members={"/tmp/evil.sql": b"x"})
        with pytest.raises(backup.BackupError, match="绝对路径"):
            backup.validate_archive_path(absolute)

    def test_symlink_member_rejected(self, tmp_path: Path) -> None:
        archive = tmp_path / "sym.tar.gz"
        manifest = {
            "format": backup.FORMAT_NAME,
            "backup_id": "x",
            "created_at": "2026-09-07T00:00:00+00:00",
            "members": {},
            "hmac": {"algorithm": backup.HMAC_ALGORITHM, "value": "0" * 64},
        }
        raw = archive.open("wb")
        with backup._GzipFileNoMtime(filename="", mode="wb", fileobj=raw) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                data = json.dumps(manifest).encode()
                info = tarfile.TarInfo(backup.MEMBER_MANIFEST)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
                link = tarfile.TarInfo("escape")
                link.type = tarfile.SYMTYPE
                link.linkname = "/etc/passwd"
                tar.addfile(link)
        raw.close()
        with pytest.raises(backup.BackupError, match="链接"):
            backup.validate_archive_path(archive)

    def test_unknown_format_version_rejected(self, tmp_path: Path) -> None:
        def tamper(manifest: dict[str, Any]) -> dict[str, Any]:
            manifest["format"] = "blue-benchmark-backup/v0"
            return manifest

        archive = backup.build_synthetic_archive(tmp_path / "latest.tar.gz", tamper_manifest=tamper)
        with pytest.raises(backup.BackupError, match="格式版本"):
            backup.validate_archive_path(archive)

    def test_unknown_latest_target_refused(self, tmp_path: Path) -> None:
        # 首次遇到未知文件不自动覆盖
        latest = tmp_path / "latest.tar.gz"
        latest.write_bytes(b"unknown junk")
        with pytest.raises(backup.BackupError, match="不自动覆盖"):
            backup.check_existing_latest(latest)
        # 符号链接不跟随
        latest.unlink()
        latest.symlink_to("/etc/passwd")
        with pytest.raises(backup.BackupError, match="符号链接"):
            backup.check_existing_latest(latest)
        # 本工具生成的合法归档允许替换
        latest.unlink()
        backup.build_synthetic_archive(latest)
        backup.check_existing_latest(latest)


# ---------------------------------------------------------------------------
# 配置解析
# ---------------------------------------------------------------------------


class TestConfigParsing:
    def write_config(self, env: dict[str, Any], config: dict[str, Any]) -> None:
        Path(os.environ["FAKE_COMPOSE_CONFIG"]).write_text(json.dumps(config), encoding="utf-8")

    def test_valid_config(self, env: dict[str, Any]) -> None:
        config = backup.load_deploy_config(env["compose_dir"])
        assert config.business.dbname == "blue_benchmark"
        assert config.checkpoint.dbname == "blue_benchmark_checkpoint"
        assert config.oss is not None and config.oss.prefix == "blue-benchmark-backups"
        assert_no_secrets(config.safe_summary())

    def test_api_worker_mismatch_rejected(self, env: dict[str, Any]) -> None:
        config = compose_config_json()
        config["services"]["worker"]["environment"]["CHECKPOINT_DATABASE_URL"] = (
            f"postgresql://blue_benchmark:{PASSWORD}@postgres:5432/other_checkpoint"
        )
        self.write_config(env, config)
        with pytest.raises(backup.ConfigError, match="不一致"):
            backup.load_deploy_config(env["compose_dir"])

    def test_same_database_name_rejected(self, env: dict[str, Any]) -> None:
        config = compose_config_json(checkpoint_db="blue_benchmark")
        self.write_config(env, config)
        with pytest.raises(backup.ConfigError, match="同名"):
            backup.load_deploy_config(env["compose_dir"])

    def test_admin_database_rejected(self, env: dict[str, Any]) -> None:
        for dbname in ("postgres", "template0", "template1"):
            config = compose_config_json(checkpoint_db=dbname)
            self.write_config(env, config)
            with pytest.raises(backup.ConfigError, match="默认管理库"):
                backup.load_deploy_config(env["compose_dir"])

    def test_dsn_query_override_rejected(self, env: dict[str, Any]) -> None:
        config = compose_config_json()
        config["services"]["api"]["environment"]["DATABASE_URL"] = (
            f"postgresql://blue_benchmark:{PASSWORD}@postgres:5432/blue_benchmark?host=evil.example.com"
        )
        config["services"]["worker"]["environment"]["DATABASE_URL"] = config["services"]["api"]["environment"]["DATABASE_URL"]
        self.write_config(env, config)
        with pytest.raises(backup.ConfigError, match="query"):
            backup.load_deploy_config(env["compose_dir"])

    def test_foreign_host_rejected(self, env: dict[str, Any]) -> None:
        config = compose_config_json()
        for service in ("api", "worker"):
            config["services"][service]["environment"]["DATABASE_URL"] = (
                f"postgresql://blue_benchmark:{PASSWORD}@evil.example.com:5432/blue_benchmark"
            )
        self.write_config(env, config)
        with pytest.raises(backup.ConfigError, match="postgres 服务"):
            backup.load_deploy_config(env["compose_dir"])

    def test_bad_key_shape_rejected(self, env: dict[str, Any]) -> None:
        config = compose_config_json()
        for service in ("api", "worker"):
            config["services"][service]["environment"]["LANGGRAPH_AES_KEY"] = "too-short"
        self.write_config(env, config)
        with pytest.raises(backup.ConfigError, match="形状"):
            backup.load_deploy_config(env["compose_dir"])

    def test_incomplete_oss_config_rejected(self, env: dict[str, Any]) -> None:
        config = compose_config_json(extra_env={"OSS_BUCKET": ""})
        self.write_config(env, config)
        with pytest.raises(backup.ConfigError, match="OSS"):
            backup.load_deploy_config(env["compose_dir"])

    def test_root_prefix_rejected(self, env: dict[str, Any]) -> None:
        config = compose_config_json(extra_env={"OSS_PREFIX": "/"})
        self.write_config(env, config)
        with pytest.raises(backup.ConfigError, match="根目录"):
            backup.load_deploy_config(env["compose_dir"])


# ---------------------------------------------------------------------------
# run：成功路径、原子替换、故障注入、互斥、残留状态
# ---------------------------------------------------------------------------


class TestRunFlow:
    def test_run_success_replaces_latest_and_reports(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        output = run_success(env, capsys)
        latest: Path = env["backups_dir"] / "latest.tar.gz"
        assert latest.is_file()
        verified = backup.validate_archive_path(latest, aes_key=TEST_AES_KEY)
        assert verified.backup_id in output
        assert verified.created_at in output
        assert_no_secrets(output)
        # 停写窗口顺序：stop 在 pg_dump/tar 之前；OSS 上传在服务恢复之后
        # （预检阶段的 OSS 检查在 stop 之前属正常，这里只看发布阶段）
        events = event_lines(env)
        stop_idx = next(i for i, e in enumerate(events) if e.startswith("compose stop"))
        dump_idx = next(i for i, e in enumerate(events) if "pg_dump" in e)
        start_idx = next(i for i, e in enumerate(events) if e.startswith("compose start"))
        oss_idx = next((i for i, e in enumerate(events) if i > start_idx and e.startswith("-e")), None)
        assert oss_idx is not None, f"没有 ossutil 发布事件；output={output} events={events}"
        assert stop_idx < dump_idx < start_idx < oss_idx        # 文件导出使用只读一次性容器，不对已停止的 api 用 exec
        run_event = next(e for e in events if e.startswith("compose run"))
        assert ":ro" in run_event and "--no-deps" in run_event
        # 维护恢复状态与临时候选已清理
        assert not (env["backups_dir"] / "backup-state.json").exists()
        assert list(env["backups_dir"].glob(".latest.tar.gz.candidate-*")) == []
        assert service_states(env)["api"] == "running"

    def test_run_updates_oss_latest_only(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        run_success_all(env, capsys)
        objects = oss_objects(env)
        bundles = [name for name in objects if name.startswith(OSS_BASE + "/bundles/")]
        assert len(bundles) == 1
        assert OSS_BASE + "/latest.json" in objects
        pointer = json.loads((env["oss_local"] / OSS_BUCKET_DIR / "blue-benchmark-backups" / "latest.json").read_text(encoding="utf-8"))
        assert OSS_BASE + "/" + pointer["object"] == bundles[0]
        assert pointer["backup_id"]
        assert pointer["sha256"]

    def test_two_rounds_leave_single_copy_everywhere(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        first = run_success_all(env, capsys)
        second = run_success_all(env, capsys)
        first_id = backup_id_from_output(first)
        second_id = backup_id_from_output(second)
        assert first_id != second_id
        # 服务器只有一个 latest；OSS 只有一个 bundle + 一个指针
        assert sorted(p.name for p in env["backups_dir"].iterdir()) == ["backup.lock", "latest.tar.gz"]
        objects = oss_objects(env)
        bundles = [name for name in objects if name.startswith(OSS_BASE + "/bundles/")]
        assert len(bundles) == 1
        assert OSS_BASE + "/latest.json" in objects
        pointer = json.loads((env["oss_local"] / OSS_BUCKET_DIR / "blue-benchmark-backups" / "latest.json").read_text(encoding="utf-8"))
        assert pointer["backup_id"] == second_id
        assert bundles[0] == f"{OSS_BASE}/bundles/{second_id}.tar.gz"
        # 第一轮对象已被精确删除：events 中有一次针对旧对象的 rm
        rm_events = [e for e in event_lines(env) if " rm -f oss://" in e and "bundles/" in e]
        assert any(first_id in e for e in rm_events), "应精确删除上一对象"
        assert_no_secrets(second)

    def test_second_dump_failure_restores_services_keeps_old_latest(
        self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]
    ) -> None:
        old = backup.build_synthetic_archive(env["backups_dir"] / "latest.tar.gz", backup_id="old-id-00000000")
        old_bytes = old.read_bytes()
        set_switch("FAIL_DUMP_DB", "blue_benchmark_checkpoint")
        code, output = run_cli(
            ["run", "--compose-dir", str(env["compose_dir"]), "--backups-dir", str(env["backups_dir"])], capsys
        )
        assert code == 1
        assert "完整备份成功" not in output
        assert service_states(env)["api"] == "running", "失败必须恢复本次停止的服务"
        assert service_states(env)["worker"] == "running"
        assert (env["backups_dir"] / "latest.tar.gz").read_bytes() == old_bytes, "失败保留旧 latest"
        assert not (env["backups_dir"] / "backup-state.json").exists(), "服务已恢复，普通失败不残留维护状态"
        assert_no_secrets(output)

    def test_stop_write_boundary_failure_aborts(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        set_switch("FAKE_CONN_COUNT", "2")
        code, output = run_cli(
            ["run", "--compose-dir", str(env["compose_dir"]), "--backups-dir", str(env["backups_dir"])], capsys
        )
        assert code == 1
        assert "停写边界不存在" in output
        assert "完整备份成功" not in output
        assert service_states(env)["api"] == "running"
        assert not (env["backups_dir"] / "latest.tar.gz").exists()

    def test_files_export_failure_aborts(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        set_switch("FAIL_FILES", "1")
        code, output = run_cli(
            ["run", "--compose-dir", str(env["compose_dir"]), "--backups-dir", str(env["backups_dir"])], capsys
        )
        assert code == 1
        assert "完整备份成功" not in output
        assert service_states(env)["api"] == "running"
        assert not (env["backups_dir"] / "latest.tar.gz").exists()

    def test_restore_failure_reported_and_state_kept(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        set_switch("FAIL_START", "1")
        code, output = run_cli(
            ["run", "--compose-dir", str(env["compose_dir"]), "--backups-dir", str(env["backups_dir"])], capsys
        )
        assert code == 1
        assert "恢复服务失败" in output
        assert "完整备份成功" not in output
        # 维护恢复状态保留，供人工/下次启动核查
        state_path = env["backups_dir"] / "backup-state.json"
        assert state_path.is_file()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert {item["service"] for item in state["stopped"]} == {"api", "worker"}
        assert_no_secrets(state_path.read_text(encoding="utf-8"))
        assert_no_secrets(output)

    def test_missing_checkpoint_database_refused_before_stop(
        self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]
    ) -> None:
        Path(os.environ["FAKE_DATABASES"]).write_text("blue_benchmark\npostgres\n", encoding="utf-8")
        code, output = run_cli(
            ["run", "--compose-dir", str(env["compose_dir"]), "--backups-dir", str(env["backups_dir"])], capsys
        )
        assert code == 1
        assert "不存在" in output
        events = event_lines(env)
        assert not any(e.startswith("compose stop") for e in events), "预检失败必须先于停写"

    def test_empty_checkpoint_database_allowed(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        # 新建库可暂无 checkpoint 表：库存在即可导出（空 dump 也合法）
        Path(os.environ["FAKE_DUMP_CHECKPOINT"]).write_bytes(b"-- empty checkpoint database\n")
        output = run_success(env, capsys)
        assert "完整备份成功" in output

    def test_disk_space_preflight_failure(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "disk_usage", lambda path: _FakeUsage(free=10))
        code, output = run_cli(
            ["run", "--compose-dir", str(env["compose_dir"]), "--backups-dir", str(env["backups_dir"])], capsys
        )
        assert code == 1
        assert "磁盘可用空间不足" in output
        assert not any(e.startswith("compose stop") for e in event_lines(env))

    def test_concurrent_run_rejected(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        with backup.maintenance_lock(env["backups_dir"]):
            code, output = run_cli(
                ["run", "--compose-dir", str(env["compose_dir"]), "--backups-dir", str(env["backups_dir"])], capsys
            )
        assert code == 2
        assert "互斥锁" in output
        assert not any(e.startswith("compose stop") for e in event_lines(env))

    def test_residual_state_blocks_reentry(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        state_path = env["backups_dir"] / "backup-state.json"
        state_path.write_text(
            json.dumps(
                {
                    "backup_id": "crashed-run",
                    "started_at": "2026-09-07T03:00:00+00:00",
                    "stopped": [
                        {"service": "api", "container_id": "api0000000001", "was_running": True},
                        {"service": "worker", "container_id": "worker0000002", "was_running": True},
                    ],
                }
            ),
            encoding="utf-8",
        )
        code, output = run_cli(
            ["run", "--compose-dir", str(env["compose_dir"]), "--backups-dir", str(env["backups_dir"])], capsys
        )
        assert code == 1
        assert "残留维护状态" in output
        assert not any(e.startswith("compose stop") for e in event_lines(env))

    def test_interrupt_restores_services(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        real_pg_dump = backup.pg_dump_to

        def interrupting_dump(compose_dir: Path, target: backup.DatabaseTarget, destination: Path) -> None:
            real_pg_dump(compose_dir, target, destination)
            if target.dbname == "blue_benchmark_checkpoint":
                raise KeyboardInterrupt

        env["backups_dir"].mkdir(parents=True, exist_ok=True)
        import unittest.mock as mock

        with mock.patch.object(backup, "pg_dump_to", side_effect=interrupting_dump):
            code = backup.main(
                ["run", "--compose-dir", str(env["compose_dir"]), "--backups-dir", str(env["backups_dir"])]
            )
        assert code == 130
        assert service_states(env)["api"] == "running", "SIGINT 也必须恢复本次停止的服务"
        assert service_states(env)["worker"] == "running"
        assert not (env["backups_dir"] / "latest.tar.gz").exists()

    def test_unknown_latest_refused(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        (env["backups_dir"] / "latest.tar.gz").write_bytes(b"unknown junk from before")
        code, output = run_cli(
            ["run", "--compose-dir", str(env["compose_dir"]), "--backups-dir", str(env["backups_dir"])], capsys
        )
        assert code == 1
        assert "不自动覆盖" in output
        assert (env["backups_dir"] / "latest.tar.gz").read_bytes() == b"unknown junk from before"

    def test_no_oss_config_skips_upload(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        config = compose_config_json(extra_env={"OSS_BUCKET": "", "OSS_PREFIX": "", "OSS_ENDPOINT": ""})
        Path(os.environ["FAKE_COMPOSE_CONFIG"]).write_text(json.dumps(config), encoding="utf-8")
        output = run_success(env, capsys)
        assert "跳过" in output
        assert oss_objects(env) == set()


class _FakeUsage:
    def __init__(self, free: int) -> None:
        self.free = free
        self.total = free
        self.used = 0


# ---------------------------------------------------------------------------
# OSS：失败保留旧副本、指针竞态、分片清理、版本控制拒绝
# ---------------------------------------------------------------------------


class TestOssFlow:
    def test_upload_failure_keeps_server_copy_and_old_pointer(
        self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]
    ) -> None:
        first = run_success_all(env, capsys)
        pointer_before = (env["oss_local"] / OSS_BUCKET_DIR / "blue-benchmark-backups" / "latest.json").read_bytes()
        set_switch("FAIL_CP", "1")
        output = run_success(env, capsys)  # 服务器副本仍然成功
        assert "服务器副本已更新" in output
        assert "OSS 副本：本次更新失败" in output
        # 服务器完整备份成立，云端失败单独如实报告，不伪称三处同步完成
        assert "服务器完整备份成功；OSS 本次更新失败" in output
        assert (env["oss_local"] / OSS_BUCKET_DIR / "blue-benchmark-backups" / "latest.json").read_bytes() == pointer_before
        assert first

    def test_readback_mismatch_rejects_candidate(
        self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]
    ) -> None:
        run_success_all(env, capsys)
        bundles_before = [name for name in oss_objects(env) if "bundles/" in name]
        set_switch("CORRUPT_CP", "1")
        output = run_success(env, capsys)
        assert "OSS 副本：本次更新失败" in output
        assert "回读摘要" in output
        bundles_after = [name for name in oss_objects(env) if "bundles/" in name]
        assert bundles_after == bundles_before, "候选失败保留旧对象，坏候选已删除"
        pointer = json.loads((env["oss_local"] / OSS_BUCKET_DIR / "blue-benchmark-backups" / "latest.json").read_text(encoding="utf-8"))
        assert OSS_BASE + "/" + pointer["object"] == bundles_before[0]

    def test_lost_readback_response_rejected(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        set_switch("DROP_CP", "1")
        output = run_success(env, capsys)
        assert "OSS 副本：本次更新失败" in output
        assert [name for name in oss_objects(env) if "bundles/" in name] == []
        assert not (env["oss_local"] / OSS_BUCKET_DIR / "blue-benchmark-backups" / "latest.json").exists()

    def test_old_object_cleanup_failure_is_diagnosable(
        self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]
    ) -> None:
        run_success_all(env, capsys)
        first_bundles = [name for name in oss_objects(env) if "bundles/" in name]

        # 第二轮：cp/ls/cat 正常，仅 rm 旧对象失败
        original_run_cmd = backup.run_cmd

        def selective_run_cmd(argv: Any, **kwargs: Any) -> Any:
            argv = list(argv)
            if (
                argv and Path(str(argv[0])).name == "ossutil"
                and "rm" in argv
                and any("bundles/" in str(a) for a in argv)
            ):
                if kwargs.get("check", True):
                    raise backup.BackupError("命令失败")
                return backup._RedactedCompleted(argv, 1, "", "ossutil: injected rm failure")
            return original_run_cmd(argv, **kwargs)

        import unittest.mock as mock

        with mock.patch.object(backup, "run_cmd", side_effect=selective_run_cmd):
            output = run_success(env, capsys)
        assert "清理失败" in output
        assert "完整备份成功" in output
        bundles = [name for name in oss_objects(env) if "bundles/" in name]
        assert len(bundles) == 2, "清理失败时两套短暂共存，必须如实报告而不是假称一套"
        assert first_bundles[0] in bundles
        pointer = json.loads((env["oss_local"] / OSS_BUCKET_DIR / "blue-benchmark-backups" / "latest.json").read_text(encoding="utf-8"))
        assert OSS_BASE + "/" + pointer["object"] != first_bundles[0], "指针必须已指向新候选"

        # 第三轮：先处理上一轮残留（未发布/过期候选被清理），指针对象保留
        output3 = run_success_all(env, capsys)
        assert "OSS 前置清理" in output3
        bundles3 = [name for name in oss_objects(env) if "bundles/" in name]
        assert len(bundles3) == 1, "下一轮必须先清掉残留旧对象"
        assert first_bundles[0] not in bundles3

    def test_pointer_write_uncertain_reread_before_delete(
        self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]
    ) -> None:
        run_success_all(env, capsys)
        pointer_before = json.loads((env["oss_local"] / OSS_BUCKET_DIR / "blue-benchmark-backups" / "latest.json").read_text(encoding="utf-8"))

        original_run_cmd = backup.run_cmd
        calls = {"pointer_cp_timed_out": False}

        def flaky_pointer(argv: Any, **kwargs: Any) -> Any:
            argv = list(argv)
            if (
                argv and Path(str(argv[0])).name == "ossutil"
                and "cp" in argv
                and any(str(a).endswith("latest.json") for a in argv)
                and not calls["pointer_cp_timed_out"]
            ):
                # 指针写入“结果不明”：实际已写入，但命令报超时
                original_run_cmd(argv, **kwargs)
                calls["pointer_cp_timed_out"] = True
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout") or 1)
            return original_run_cmd(argv, **kwargs)

        import unittest.mock as mock

        with mock.patch.object(backup, "run_cmd", side_effect=flaky_pointer):
            output = run_success_all(env, capsys)
        assert calls["pointer_cp_timed_out"]
        # 结果不明先回读：指针已指向新候选 => 发布成功并删除旧对象
        pointer_after = json.loads((env["oss_local"] / OSS_BUCKET_DIR / "blue-benchmark-backups" / "latest.json").read_text(encoding="utf-8"))
        assert pointer_after["object"] != pointer_before["object"]
        assert "已发布" in output
        bundles = [name for name in oss_objects(env) if "bundles/" in name]
        assert len(bundles) == 1
        assert OSS_BASE + "/" + pointer_after["object"] in bundles

    def test_versioned_bucket_refused(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        versioning = env["tmp_path"] / "versioning.json"
        versioning.write_text(json.dumps({"VersioningConfiguration": {"Status": "Enabled"}}), encoding="utf-8")
        set_switch("FAKE_VERSIONING", str(versioning))
        code, output = run_cli(
            ["run", "--compose-dir", str(env["compose_dir"]), "--backups-dir", str(env["backups_dir"])], capsys
        )
        assert code == 1
        assert "版本控制" in output
        assert not any(e.startswith("compose stop") for e in event_lines(env)), "OSS 前置失败必须先于停写"

    def test_multipart_residue_terminated(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        multipart = env["tmp_path"] / "multipart.txt"
        multipart.write_text(
            "oss://blue-benchmark-backup-bucket/blue-benchmark-backups/bundles/ 0004B999EF5FB185A015 uploadId\n",
            encoding="utf-8",
        )
        set_switch("FAKE_MULTIPART", str(multipart))
        output = run_success_all(env, capsys)
        assert "已终止未完成分片上传" in output
        assert any("rm -f -m -r" in e and "0004B999EF5FB185A015" in e for e in event_lines(env))

    def test_ossutil_timeout_reported(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
        import unittest.mock as mock

        original_run_cmd = backup.run_cmd

        def timeout_once(argv: Any, **kwargs: Any) -> Any:
            argv = list(argv)
            if argv and Path(str(argv[0])).name == "ossutil" and "cp" in argv and any("bundles/" in str(a) for a in argv):
                raise subprocess.TimeoutExpired(argv, kwargs.get("timeout") or 1)
            return original_run_cmd(argv, **kwargs)

        with mock.patch.object(backup, "run_cmd", side_effect=timeout_once):
            output = run_success(env, capsys)
        assert "OSS 副本：本次更新失败" in output
        assert "完整备份成功" in output  # 服务器副本不受影响


# ---------------------------------------------------------------------------
# download：SSH 下载、校验、原子覆盖、幂等、互斥
# ---------------------------------------------------------------------------


class TestDownload:
    def server_archive(self, env: dict[str, Any]) -> Path:
        archive = env["backups_dir"] / "latest.tar.gz"
        if not archive.exists():
            backup.build_synthetic_archive(archive, aes_key=TEST_AES_KEY)
        return archive

    def local_dir(self, env: dict[str, Any]) -> Path:
        path = env["tmp_path"] / "mac" / "blue-benchmark-backups"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def download(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str], local_dir: Path | None = None) -> tuple[int, str]:
        return run_cli(
            [
                "download",
                "--host", "evalserver",
                "--remote-path", str(env["backups_dir"] / "latest.tar.gz"),
                "--local-dir", str(local_dir or self.local_dir(env)),
            ],
            capsys,
        )

    def test_download_success_replaces_local(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        self.server_archive(env)
        local_dir = self.local_dir(env)
        code, output = self.download(env, capsys, local_dir)
        assert code == 0, output
        local_latest = local_dir / "latest.tar.gz"
        assert local_latest.is_file()
        verified = backup.validate_archive_path(local_latest, aes_key=TEST_AES_KEY)
        assert verified.backup_id in output
        assert verified.created_at in output
        assert "不含下载时刻后新增数据" in output
        assert_no_secrets(output)
        assert list(local_dir.glob(".latest.tar.gz.download-*")) == []

    def test_same_id_idempotent(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        self.server_archive(env)
        local_dir = self.local_dir(env)
        code, _ = self.download(env, capsys, local_dir)
        assert code == 0
        events_before = len(event_lines(env))
        code2, output2 = self.download(env, capsys, local_dir)
        assert code2 == 0
        assert "幂等" in output2
        new_events = event_lines(env)[events_before:]
        assert not any(e.startswith("scp") for e in new_events), "同 ID 不重复传输归档"

    def test_checksum_failure_keeps_old_local(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        self.server_archive(env)
        local_dir = self.local_dir(env)
        backup.build_synthetic_archive(local_dir / "latest.tar.gz", backup_id="old-local-id0", aes_key=TEST_AES_KEY)
        old_bytes = (local_dir / "latest.tar.gz").read_bytes()
        set_switch("DROP_TAIL", "1")
        code, output = self.download(env, capsys, local_dir)
        assert code == 1
        assert "校验" in output
        assert (local_dir / "latest.tar.gz").read_bytes() == old_bytes, "校验失败保持旧 latest"
        assert list(local_dir.glob(".latest.tar.gz.download-*")) == []

    def test_network_failure_keeps_old_local(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        self.server_archive(env)
        local_dir = self.local_dir(env)
        backup.build_synthetic_archive(local_dir / "latest.tar.gz", backup_id="old-local-id0", aes_key=TEST_AES_KEY)
        old_bytes = (local_dir / "latest.tar.gz").read_bytes()
        set_switch("FAIL_SCP", "1")
        code, output = self.download(env, capsys, local_dir)
        assert code == 1
        assert (local_dir / "latest.tar.gz").read_bytes() == old_bytes
        assert output.count("次下载失败") == backup.COPY_ATTEMPTS, "重试次数受限，不无限下载"

    def test_remote_missing_fails(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        local_dir = self.local_dir(env)
        code, output = self.download(env, capsys, local_dir)
        assert code == 1
        assert not (local_dir / "latest.tar.gz").exists()

    def test_unknown_local_latest_refused(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        self.server_archive(env)
        local_dir = self.local_dir(env)
        (local_dir / "latest.tar.gz").write_bytes(b"unknown junk")
        code, output = self.download(env, capsys, local_dir)
        assert code == 1
        assert "不自动覆盖" in output
        assert (local_dir / "latest.tar.gz").read_bytes() == b"unknown junk"

    def test_symlink_local_latest_refused(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        self.server_archive(env)
        local_dir = self.local_dir(env)
        (local_dir / "latest.tar.gz").symlink_to("/etc/hosts")
        code, output = self.download(env, capsys, local_dir)
        assert code == 1
        assert "符号链接" in output

    def test_concurrent_download_rejected(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        self.server_archive(env)
        local_dir = self.local_dir(env)
        with backup.maintenance_lock(local_dir):
            code, output = self.download(env, capsys, local_dir)
        assert code == 2
        assert "互斥锁" in output

    def test_bad_host_argument_rejected(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        self.server_archive(env)
        for host in ("evalserver; rm -rf /", "$(whoami)", "host with space"):
            code, output = self.download_with_host(env, capsys, host)
            assert code == 1
            assert "非法 SSH 主机参数" in output
        # 以 - 开头的主机参数会被 argparse 当作选项直接拒绝
        with pytest.raises(SystemExit):
            self.download_with_host(env, capsys, "-oProxyCommand=evil")

    def download_with_host(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str], host: str) -> tuple[int, str]:
        return run_cli(
            [
                "download",
                "--host", host,
                "--remote-path", str(env["backups_dir"] / "latest.tar.gz"),
                "--local-dir", str(self.local_dir(env)),
            ],
            capsys,
        )

    def test_no_date_directories_created(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        self.server_archive(env)
        local_dir = self.local_dir(env)
        code, _ = self.download(env, capsys, local_dir)
        assert code == 0
        names = {path.name for path in local_dir.iterdir()}
        assert names <= {"latest.tar.gz", "backup.lock"}, "不创建日期目录或后台调度产物"

    def test_ssh_host_key_check_not_disabled(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        self.server_archive(env)
        code, _ = self.download(env, capsys)
        assert code == 0
        ssh_events = [e for e in event_lines(env) if e.startswith("ssh ")]
        assert ssh_events
        for event in ssh_events:
            assert "StrictHostKeyChecking=no" not in event


# ---------------------------------------------------------------------------
# verify / restore-check / CLI 安全
# ---------------------------------------------------------------------------


class TestVerifyAndRestoreCheck:
    def test_verify_ok(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        archive = backup.build_synthetic_archive(tmp_path / "latest.tar.gz", aes_key=TEST_AES_KEY)
        code, output = run_cli(["verify", str(archive)], capsys)
        assert code == 0
        assert "归档校验通过" in output
        assert "跳过 HMAC" in output

    def test_verify_with_key_file(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        archive = backup.build_synthetic_archive(tmp_path / "latest.tar.gz", aes_key=TEST_AES_KEY)
        key_file = tmp_path / "key"
        key_file.write_text(TEST_AES_KEY + "\n", encoding="utf-8")
        code, output = run_cli(["verify", str(archive), "--aes-key-file", str(key_file)], capsys)
        assert code == 0
        assert "已用原密钥核对通过" in output

    def test_verify_broken(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        archive = tmp_path / "latest.tar.gz"
        archive.write_bytes(b"junk")
        code, output = run_cli(["verify", str(archive)], capsys)
        assert code == 1
        assert "不是合法的 tar/gzip 归档" in output

    def test_verify_rejects_key_in_argv(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        archive = backup.build_synthetic_archive(tmp_path / "latest.tar.gz")
        code, output = run_cli(["verify", str(archive), "--aes-key", TEST_AES_KEY], capsys)
        assert code == 1
        assert "argv" in output

    def test_restore_check_wrong_key_fails_closed(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        archive = backup.build_synthetic_archive(tmp_path / "latest.tar.gz", aes_key=TEST_AES_KEY)
        key_file = tmp_path / "wrong-key"
        key_file.write_text(WRONG_AES_KEY, encoding="utf-8")
        code, output = run_cli(["restore-check", str(archive), "--aes-key-file", str(key_file)], capsys)
        assert code == 1
        assert "重新开放写入前失败" in output
        assert "不生成替代密钥" in output

    def test_restore_check_missing_checkpoint_member(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        archive = backup.build_synthetic_archive(
            tmp_path / "latest.tar.gz",
            members=(backup.MEMBER_MANIFEST, backup.MEMBER_BUSINESS, backup.MEMBER_FILES),
        )
        code, output = run_cli(["restore-check", str(archive)], capsys)
        assert code == 1
        assert "缺少成员" in output

    def test_restore_check_ok(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        archive = backup.build_synthetic_archive(tmp_path / "latest.tar.gz", aes_key=TEST_AES_KEY)
        key_file = tmp_path / "key"
        key_file.write_text(TEST_AES_KEY, encoding="utf-8")
        code, output = run_cli(["restore-check", str(archive), "--aes-key-file", str(key_file)], capsys)
        assert code == 0
        assert "恢复预检通过" in output
        assert "restore.md" in output

    def test_cli_never_leaks_secrets_on_config_error(
        self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]
    ) -> None:
        # DSN 含密码；任何报错输出都必须脱敏
        config = compose_config_json(checkpoint_db="blue_benchmark")  # 两库同名 -> ConfigError
        Path(os.environ["FAKE_COMPOSE_CONFIG"]).write_text(json.dumps(config), encoding="utf-8")
        code, output = run_cli(
            ["run", "--compose-dir", str(env["compose_dir"]), "--backups-dir", str(env["backups_dir"])], capsys
        )
        assert code == 1
        assert_no_secrets(output)

    def test_subprocess_run_end_to_end(self, env: dict[str, Any]) -> None:
        # 独立进程验证脚本可执行入口与事件顺序（无密钥泄漏）
        completed = run_subprocess(
            ["run", "--compose-dir", str(env["compose_dir"]), "--backups-dir", str(env["backups_dir"])]
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert "完整备份成功" in completed.stdout
        combined = completed.stdout + completed.stderr
        assert_no_secrets(combined)
        assert (env["backups_dir"] / "latest.tar.gz").is_file()

    def test_state_and_lock_files_have_no_secrets(self, env: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
        run_success(env, capsys)
        for path in env["backups_dir"].iterdir():
            if path.is_file() and path.suffix in {".json", ".log", ""}:
                assert_no_secrets(path.read_text(encoding="utf-8", errors="replace"))
