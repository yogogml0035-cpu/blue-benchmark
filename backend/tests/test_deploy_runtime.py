"""部署运行时专项测试：Nginx 依赖重启（AC5/AC6）与备份恢复真实 Docker 证据（AC1-AC3）。

两层结构：

1. 默认层（make test 内运行，无外部副作用）：compose.yaml / nginx.conf /
   push-images.sh 的静态断言，以及 docker compose config 校验（本机没有
   docker 时显式 skip）。
2. 集成层（DEPLOY_INTEGRATION_REQUIRED=1 时运行，否则显式 skip；开启后
   Docker/工具缺失直接 fail，不允许用 skip 冒充验收）：
   - 自建唯一项目名（sedbrt-<uuid8>）、隔离网络与静态 IP 两阶段分配，
     强制上游容器在受支持的 `docker compose up -d` 更新后获得不同 IP，
     核对 nginx 容器确实被重启，且请求经 nginx 到达新标记实例；
   - 经 nginx 的代理回归：URI/查询参数透传、X-Forwarded-*/Cookie 转发、
     登录限流 429、SSE 增量分批抵达（不是一次 HTTP 200 就算过）；
   - 真实 postgres:16-alpine 上的 pg_dump 导出/打包/verify/隔离恢复，
     错误密钥、缺 checkpoint、损坏归档在开放写入前失败。
   只绑定本地随机端口，不占用 80/3000/8000；结束只删除本次创建且项目名
   前缀核验的资源；断言消息全部经过脱敏。
"""

from __future__ import annotations

import io
import json
import os
import shutil
import socket
import gzip
import hashlib
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import time
import uuid
from pathlib import Path
from typing import Any, Sequence
from urllib import error as urlerror
from urllib import request as urlrequest

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_ROOT / "deploy"
if str(DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOY_DIR))

import backup  # noqa: E402  复用归档/清单工具与合成数据构造（不新增第二套格式）

from tests.test_deploy_backup import (  # noqa: E402  复用默认层 fake ossutil 与合成配置
    BUSINESS_DSN,
    CHECKPOINT_DSN,
    FAKE_OSSUTIL,
    PASSWORD,
    TEST_AES_KEY,
    WRONG_AES_KEY,
    compose_config_json,
)

INTEGRATION_REQUIRED = os.environ.get("DEPLOY_INTEGRATION_REQUIRED") == "1"
PROJECT_PREFIX = "sedbrt-"

integration_only = pytest.mark.skipif(
    not INTEGRATION_REQUIRED,
    reason="集成层默认关闭：DEPLOY_INTEGRATION_REQUIRED=1 才运行（需要真实 Docker，不允许自动跳过当通过）",
)

FORBIDDEN_HOST_PORTS = {80, 3000, 8000}


# ---------------------------------------------------------------------------
# 通用工具（输出统一脱敏后才进入断言消息/日志）
# ---------------------------------------------------------------------------


def run(argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(  # noqa: S603 - 测试内固定命令
        list(argv), capture_output=True, text=True, timeout=kwargs.pop("timeout", 300), check=False, **kwargs
    )
    return result


def run_ok(argv: Sequence[str], **kwargs: Any) -> str:
    result = run(argv, **kwargs)
    assert result.returncode == 0, backup.redact(f"命令失败：{' '.join(argv)}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def docker(args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return run(["docker", *args], **kwargs)


def docker_ok(args: Sequence[str], **kwargs: Any) -> str:
    return run_ok(["docker", *args], **kwargs)


def compose(project: str, file: Path, args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return docker(["compose", "-p", project, "-f", str(file), *args], **kwargs)


def compose_ok(project: str, file: Path, args: Sequence[str], **kwargs: Any) -> str:
    return docker_ok(["compose", "-p", project, "-f", str(file), *args], **kwargs)


def free_port() -> int:
    """本地随机空闲端口；绝不占用 80/3000/8000。"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    assert port not in FORBIDDEN_HOST_PORTS
    return port


def http_get(url: str, *, headers: dict[str, str] | None = None, timeout: float = 10) -> tuple[int, dict[str, str], bytes]:
    req = urlrequest.Request(url, headers=headers or {})
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 仅测试内 127.0.0.1
            return resp.status, dict(resp.headers), resp.read()
    except urlerror.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read()


def container_ip(name: str, network: str) -> str:
    # 网络名含连字符不能直接进 Go 模板字段路径；容器只挂一个网络，遍历取值
    result = docker(["inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", name])
    assert result.returncode == 0, backup.redact(result.stderr)
    ips = result.stdout.split()
    assert len(ips) == 1, f"容器 {name} 应只挂 {network} 一个网络，实际 IP：{ips}"
    return ips[0]


def container_started_at(name: str) -> str:
    return docker_ok(["inspect", "-f", "{{.State.StartedAt}}", name]).strip()


def container_id(name: str) -> str:
    return docker_ok(["inspect", "-f", "{{.Id}}", name]).strip()


def project_containers(project: str) -> list[str]:
    out = docker_ok(["ps", "-a", "--filter", f"label=com.docker.compose.project={project}", "--format", "{{.Names}}"])
    return [line for line in out.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# 默认层：静态断言与 compose config 校验
# ---------------------------------------------------------------------------


class TestComposeStatic:
    def test_nginx_depends_on_restart_and_health(self) -> None:
        config = yaml.safe_load((DEPLOY_DIR / "compose.yaml").read_text(encoding="utf-8"))
        depends = config["services"]["nginx"]["depends_on"]
        for upstream in ("api", "web"):
            assert depends[upstream]["condition"] == "service_healthy", f"nginx 对 {upstream} 必须保留健康依赖"
            assert depends[upstream]["restart"] is True, f"nginx 对 {upstream} 必须声明 restart: true（更新后重新解析上游地址）"
        # 不改路由结构：服务集合与 nginx 端口保持原样
        assert set(config["services"]) == {"nginx", "web", "api", "worker", "postgres"}
        assert "80:80" in config["services"]["nginx"]["ports"]

    def test_production_nginx_conf_directives_intact(self) -> None:
        conf = (DEPLOY_DIR / "nginx" / "nginx.conf").read_text(encoding="utf-8")
        # 关键指令未被本轮修改破坏：静态上游（启动时解析）、限流、路由、SSE 依赖的超时
        assert "server api:8000;" in conf
        assert "server web:3000;" in conf
        assert "limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;" in conf
        assert "limit_req zone=login burst=3 nodelay;" in conf
        assert "location /api/auth/login" in conf
        assert "location /api/" in conf
        assert "location = /healthz" in conf
        assert "client_max_body_size 256m;" in conf
        assert "proxy_read_timeout 300s;" in conf

    def test_compose_config_valid(self) -> None:
        if shutil.which("docker") is None:
            pytest.skip("本机没有 docker 命令；默认层允许跳过（集成层不允许）")
        probe = docker(["info"])
        if probe.returncode != 0:
            pytest.skip("本机 Docker 守护进程不可用；默认层允许跳过（集成层不允许）")
        env = dict(os.environ)
        env.update({"REGISTRY": "example.invalid/review", "TAG": "review", "POSTGRES_PASSWORD": "not-a-secret"})
        result = run(
            ["docker", "compose", "--env-file", "/dev/null", "-f", str(DEPLOY_DIR / "compose.yaml"),
             "config", "--no-env-resolution", "--quiet"],
            env=env,
        )
        assert result.returncode == 0, backup.redact(result.stdout + result.stderr)

    def test_push_images_matches_supported_update_flow(self) -> None:
        script_path = DEPLOY_DIR / "push-images.sh"
        syntax = run(["bash", "-n", str(script_path)])
        assert syntax.returncode == 0, syntax.stderr
        text = script_path.read_text(encoding="utf-8")
        # 按整个 Compose 服务图更新（依赖重启生效），不提供绕过入口
        assert "docker compose pull && docker compose up -d" in text
        assert "--no-deps" not in text, "发布说明不得出现绕过依赖重启的 --no-deps 用法"
        assert "绕过" in text and "nginx" in text.lower(), "必须说明绕过依赖重启会导致 nginx 滞留旧地址"
        # 更新后等待健康并检查 Nginx 请求
        assert "healthy" in text
        assert "/healthz" in text


# ---------------------------------------------------------------------------
# 集成层公共 fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def docker_ready() -> None:
    """集成层门禁：开启后 Docker/工具缺失直接 fail，不许 skip。"""
    if not INTEGRATION_REQUIRED:
        pytest.skip("集成层未开启")
    if shutil.which("docker") is None:
        pytest.fail("DEPLOY_INTEGRATION_REQUIRED=1 但找不到 docker 命令：集成验收不允许跳过")
    info = docker(["info"])
    if info.returncode != 0:
        pytest.fail(f"Docker 守护进程不可用：{backup.redact(info.stderr)}")
    compose_version = docker(["compose", "version"])
    if compose_version.returncode != 0:
        pytest.fail("docker compose 不可用：集成验收不允许跳过")


@pytest.fixture(scope="session")
def project_name(docker_ready: None) -> str:
    return f"{PROJECT_PREFIX}{uuid.uuid4().hex[:8]}"


MARKER_SERVER = textwrap.dedent(
    '''\
    """集成测试用合成上游：标记、头部回显、SSE 分批输出。仅测试内使用。"""
    import json
    import os
    import socket
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs

    MARKER = os.environ.get("MARKER", "marker-v1")
    PORT = int(os.environ.get("PORT", "8000"))


    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, code, body, ctype="application/json", extra_headers=None):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            parsed = urlparse(self.path)
            # 生产 nginx 的 proxy_pass 不带 URI：backend 收到的是 /api/... 原样路径
            path = parsed.path
            if path.startswith("/api/"):
                path = path[len("/api"):]
            if path == "/auth/login":
                self._send(200, json.dumps({"marker": MARKER, "login": True}))
                return
            if path == "/healthz":
                self._send(200, json.dumps({"status": "ok", "marker": MARKER}))
                return
            if path == "/echo":
                payload = {
                    "marker": MARKER,
                    "ip": socket.gethostbyname(socket.gethostname()),
                    "path": path,
                    "query": parse_qs(parsed.query),
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                }
                self._send(200, json.dumps(payload))
                return
            if path == "/sse":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                try:
                    for i in range(3):
                        chunk = f"data: {{\\"marker\\": \\"{MARKER}\\", \\"seq\\": {i}}}\\n\\n"
                        raw = chunk.encode("utf-8")
                        self.wfile.write(b"%x\\r\\n" % len(raw) + raw + b"\\r\\n")
                        self.wfile.flush()
                        time.sleep(0.6)
                    self.wfile.write(b"0\\r\\n\\r\\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            self._send(404, json.dumps({"error": "not found", "marker": MARKER}))

        def log_message(self, *args):
            pass


    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    '''
)


def equivalent_nginx_conf() -> str:
    """与 deploy/nginx/nginx.conf 同构的测试配置：静态上游 + 相同路由/限流/转发头。"""
    return textwrap.dedent(
        """\
        worker_processes 1;
        events { worker_connections 256; }
        http {
            limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;
            limit_req_status 429;
            upstream backend { server api:8000; }
            upstream console { server web:3000; }
            server {
                listen 80;
                server_name _;
                client_max_body_size 256m;
                location /api/auth/login {
                    limit_req zone=login burst=3 nodelay;
                    proxy_pass http://backend;
                    proxy_set_header Host $host;
                    proxy_set_header X-Real-IP $remote_addr;
                    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                    proxy_set_header X-Forwarded-Proto $scheme;
                }
                location /api/ {
                    proxy_pass http://backend;
                    proxy_set_header Host $host;
                    proxy_set_header X-Real-IP $remote_addr;
                    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                    proxy_set_header X-Forwarded-Proto $scheme;
                    proxy_read_timeout 300s;
                }
                location = /healthz {
                    proxy_pass http://backend;
                }
                location / {
                    proxy_pass http://console;
                    proxy_set_header Host $host;
                    proxy_set_header X-Real-IP $remote_addr;
                    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                    proxy_set_header X-Forwarded-Proto $scheme;
                }
            }
        }
        """
    )


def nginx_compose_file(project: str, host_port: int, api_ip: str, web_ip: str, marker: str) -> str:
    return textwrap.dedent(
        f"""\
        name: {project}
        networks:
          net:
            ipam:
              config:
                - subnet: 172.28.0.0/24
        services:
          api:
            image: python:3.11
            command: ["python", "/opt/marker/marker_server.py"]
            environment:
              MARKER: {marker}
              PORT: "8000"
            volumes:
              - ./marker_server.py:/opt/marker/marker_server.py:ro
            healthcheck:
              test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]
              interval: 5s
              timeout: 3s
              retries: 10
              start_period: 5s
            networks:
              net:
                ipv4_address: {api_ip}
          web:
            image: python:3.11
            command: ["python", "/opt/marker/marker_server.py"]
            environment:
              MARKER: {marker}
              PORT: "3000"
            volumes:
              - ./marker_server.py:/opt/marker/marker_server.py:ro
            healthcheck:
              test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/healthz', timeout=3)"]
              interval: 5s
              timeout: 3s
              retries: 10
              start_period: 5s
            networks:
              net:
                ipv4_address: {web_ip}
          nginx:
            image: nginx:1.27-alpine
            ports:
              - "127.0.0.1:{host_port}:80"
            volumes:
              - ./nginx.conf:/etc/nginx/nginx.conf:ro
            depends_on:
              web:
                condition: service_healthy
                restart: true
              api:
                condition: service_healthy
                restart: true
            networks:
              - net
        """
    )


@pytest.fixture(scope="session")
def nginx_stack(project_name: str) -> Any:
    """隔离 nginx + 两个合成上游；yield 一个带操作句柄的字典。"""
    stack_dir = Path(tempfile.mkdtemp(prefix=f"{PROJECT_PREFIX}nginx-"))
    host_port = free_port()
    (stack_dir / "marker_server.py").write_text(MARKER_SERVER, encoding="utf-8")
    (stack_dir / "nginx.conf").write_text(equivalent_nginx_conf(), encoding="utf-8")
    compose_path = stack_dir / "compose.yaml"
    compose_path.write_text(
        nginx_compose_file(project_name, host_port, "172.28.0.11", "172.28.0.12", "marker-v1"), encoding="utf-8"
    )
    api_container = f"{project_name}-api-1"
    web_container = f"{project_name}-web-1"
    nginx_container = f"{project_name}-nginx-1"
    try:
        compose_ok(project_name, compose_path, ["up", "-d", "--wait", "--timeout", "180"])

        def update(api_ip: str, web_ip: str, marker: str) -> None:
            compose_path.write_text(
                nginx_compose_file(project_name, host_port, api_ip, web_ip, marker), encoding="utf-8"
            )
            # 受支持的更新入口：整个 Compose 服务图 up -d，不用 --no-deps
            compose_ok(project_name, compose_path, ["up", "-d", "--wait", "--timeout", "180"])

        stack = {
            "project": project_name,
            "dir": stack_dir,
            "compose_file": compose_path,
            "host_port": host_port,
            "api_container": api_container,
            "web_container": web_container,
            "nginx_container": nginx_container,
            "update": update,
            "url": lambda path: f"http://127.0.0.1:{host_port}{path}",
        }
        yield stack
    finally:
        down = compose(project_name, compose_path, ["down", "-v", "--remove-orphans", "--timeout", "30"], timeout=180)
        leftover = project_containers(project_name) if down.returncode != 0 else []
        for name in leftover:
            # 身份核验：只清理本项目名前缀的容器
            if name.startswith(project_name):
                docker(["rm", "-f", name], timeout=60)
        network = docker(["network", "ls", "--filter", f"name={project_name}", "--format", "{{.Name}}"])
        for line in network.stdout.splitlines():
            if line.strip().startswith(project_name):
                docker(["network", "rm", line.strip()], timeout=60)
        shutil.rmtree(stack_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 集成层：Nginx 换 IP 刷新（AC5）+ 代理回归（AC6）
# ---------------------------------------------------------------------------


@integration_only
class TestNginxRefreshIntegration:
    def test_baseline_proxy_regression(self, nginx_stack: dict[str, Any]) -> None:
        """更新前：经 nginx 验证路由、转发头、限流、SSE 分批（不是一次 200 就算过）。"""
        base = nginx_stack["url"]

        # /api/* -> backend（合成 api 上游），/ -> console（合成 web 上游）
        status, _, body = http_get(base("/api/echo?x=1&y=%E4%B8%AD%E6%96%87"))
        assert status == 200
        payload = json.loads(body)
        assert payload["marker"] == "marker-v1"
        # URI 与查询参数原样透传
        assert payload["path"] == "/echo"
        assert payload["query"] == {"x": ["1"], "y": ["中文"]}
        # 认证转发头与 Cookie
        headers = payload["headers"]
        assert headers["x-forwarded-proto"] == "http"
        assert "x-forwarded-for" in headers and headers["x-forwarded-for"]
        assert headers.get("x-real-ip")
        status, _, body = http_get(base("/api/echo"), headers={"Cookie": "skill_eval_session=abc123"})
        assert json.loads(body)["headers"]["cookie"] == "skill_eval_session=abc123"
        # 根路径到 console 上游
        status, _, body = http_get(base("/echo"))
        assert status == 200 and json.loads(body)["marker"] == "marker-v1"
        # healthz 精确匹配到 backend
        status, _, body = http_get(base("/healthz"))
        assert status == 200 and json.loads(body)["status"] == "ok"

        # 登录限流：rate=5r/m burst=3 => 前 4 个放行，第 5、6 个必须 429
        codes = [http_get(base("/api/auth/login"))[0] for _ in range(6)]
        assert codes[:4] == [200, 200, 200, 200], f"限流前 4 个请求应放行：{codes}"
        assert codes[4] == 429 and codes[5] == 429, f"超出 burst 后应 429：{codes}"

        # SSE 增量分批抵达（间隔 >= 1.2s 证明不是一次性缓冲）
        started = time.monotonic()
        status, headers, body = http_get(base("/api/sse"), timeout=30)
        elapsed = time.monotonic() - started
        assert status == 200
        assert headers.get("Content-Type", "").startswith("text/event-stream")
        events = [line for line in body.decode("utf-8").splitlines() if line.startswith("data:")]
        assert len(events) == 3, f"应有 3 个 SSE 事件：{events}"
        assert elapsed >= 1.2, f"SSE 应分批抵达（上游每 0.6s 一个事件），实际耗时 {elapsed:.2f}s"

    def test_update_changes_upstream_ip_and_refreshes_nginx(self, nginx_stack: dict[str, Any]) -> None:
        """AC5：强制上游换 IP 后执行受支持的 compose 更新，nginx 必须重启并解析到新实例。"""
        project = nginx_stack["project"]
        api_container = nginx_stack["api_container"]
        web_container = nginx_stack["web_container"]
        nginx_container = nginx_stack["nginx_container"]
        network = f"{project}_net"

        old_api_ip = container_ip(api_container, network)
        old_web_ip = container_ip(web_container, network)
        old_nginx_started = container_started_at(nginx_container)
        old_nginx_id = container_id(nginx_container)
        assert old_api_ip == "172.28.0.11" and old_web_ip == "172.28.0.12"

        # 两阶段静态 IP 分配 + 新标记：重建后上游必然拿到不同 IP
        nginx_stack["update"]("172.28.0.21", "172.28.0.22", "marker-v2")

        new_api_ip = container_ip(api_container, network)
        new_web_ip = container_ip(web_container, network)
        assert new_api_ip == "172.28.0.21" and new_web_ip == "172.28.0.22"
        assert new_api_ip != old_api_ip, "仅重启后恰好复用旧 IP 不算通过：API 上游 IP 必须确实变化"
        assert new_web_ip != old_web_ip, "Web 上游 IP 必须确实变化"

        # nginx 确实被重启：容器 ID 变化或 StartedAt 前进
        new_nginx_started = container_started_at(nginx_container)
        new_nginx_id = container_id(nginx_container)
        nginx_restarted = new_nginx_id != old_nginx_id or new_nginx_started > old_nginx_started
        assert nginx_restarted, (
            f"nginx 未随依赖更新重启：id {old_nginx_id[:12]}->{new_nginx_id[:12]}，"
            f"StartedAt {old_nginx_started}->{new_nginx_started}"
        )

        # 请求经 nginx 到达新标记、新 IP 实例（静态解析若滞留旧地址会连接失败）
        status, _, body = http_get(nginx_stack["url"]("/api/echo"))
        assert status == 200
        payload = json.loads(body)
        assert payload["marker"] == "marker-v2", "nginx 必须把请求代理到更新后的 API 实例"
        assert payload["ip"] == new_api_ip, "响应必须来自新 IP 的实例"
        status, _, body = http_get(nginx_stack["url"]("/echo"))
        assert status == 200
        web_payload = json.loads(body)
        assert web_payload["marker"] == "marker-v2"
        assert web_payload["ip"] == new_web_ip

        # 更新后代理行为回归不降级：转发头、查询参数、SSE 仍然正确
        status, _, body = http_get(nginx_stack["url"]("/api/echo?after=update"))
        after = json.loads(body)
        assert after["query"] == {"after": ["update"]}
        assert after["headers"]["x-forwarded-proto"] == "http"
        started = time.monotonic()
        status, _, body = http_get(nginx_stack["url"]("/api/sse"), timeout=30)
        assert status == 200
        assert len([l for l in body.decode().splitlines() if l.startswith("data:")]) == 3
        assert time.monotonic() - started >= 1.2


# ---------------------------------------------------------------------------
# 集成层：真实 PostgreSQL 备份/恢复证据（AC1-AC3）
# ---------------------------------------------------------------------------

BUSINESS_FIXTURE_SQL = """
CREATE TABLE questions (id serial PRIMARY KEY, title text NOT NULL);
INSERT INTO questions (title) VALUES ('合成题目一'), ('合成题目二');
"""
CHECKPOINT_FIXTURE_SQL = """
CREATE TABLE checkpoints (thread_id text PRIMARY KEY, checkpoint bytea NOT NULL);
INSERT INTO checkpoints VALUES ('thread-1', decode('deadbeef', 'hex'));
"""


def psql_exec(container: str, dbname: str, sql: str) -> str:
    result = docker(
        ["exec", "-i", container, "psql", "-v", "ON_ERROR_STOP=1", "-U", "skill_eval", "-d", dbname],
        input=sql,
    )
    assert result.returncode == 0, backup.redact(f"psql 失败：{result.stdout}\n{result.stderr}")
    return result.stdout


def psql_query(container: str, dbname: str, sql: str) -> str:
    return psql_exec(container, dbname, sql)


@pytest.fixture(scope="session")
def backup_stack(project_name: str) -> Any:
    """隔离 postgres:16-alpine + 合成两库 + fake ossutil；导出走真实 Docker。"""
    stack_dir = Path(tempfile.mkdtemp(prefix=f"{PROJECT_PREFIX}backup-"))
    oss_local = stack_dir / "oss"
    oss_local.mkdir()
    bin_dir = stack_dir / "bin"
    bin_dir.mkdir()
    fake_ossutil = bin_dir / "ossutil"
    fake_ossutil.write_text(FAKE_OSSUTIL, encoding="utf-8")
    fake_ossutil.chmod(0o755)
    events = stack_dir / "events.log"
    events.write_text("", encoding="utf-8")

    compose_dir = stack_dir / "compose"
    compose_dir.mkdir()
    compose_path = compose_dir / "compose.yaml"
    compose_path.write_text("services: {}\n", encoding="utf-8")
    cfg_path = stack_dir / "compose-config.json"
    cfg = compose_config_json()
    # 项目名必须与真实 compose 项目一致：appdata 卷按 <project>_appdata 解析
    cfg["name"] = project_name
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    pg_container = f"{project_name}-postgres-1"
    saved_env = {
        key: os.environ.get(key)
        for key in ("EVENTS", "OSS_LOCAL", "PATH", "FAKE_COMPOSE_CONFIG")
    }
    try:
        compose_path.write_text(
            textwrap.dedent(
                f"""\
                name: {project_name}
                services:
                  postgres:
                    image: postgres:16-alpine
                    environment:
                      POSTGRES_USER: skill_eval
                      POSTGRES_PASSWORD: {PASSWORD}
                      POSTGRES_DB: skill_eval
                    healthcheck:
                      test: ["CMD-SHELL", "pg_isready -U skill_eval -d skill_eval"]
                      interval: 3s
                      timeout: 3s
                      retries: 20
                      start_period: 5s
                  api:
                    image: python:3.11
                    command: ["python", "-c", "import time; time.sleep(7200)"]
                  worker:
                    image: python:3.11
                    command: ["python", "-c", "import time; time.sleep(7200)"]
                """
            ),
            encoding="utf-8",
        )
        compose_ok(project_name, compose_path, ["up", "-d", "--wait", "--timeout", "180"])
        docker_ok(["exec", pg_container, "createdb", "-U", "skill_eval", "skill_eval_checkpoint"])
        psql_exec(pg_container, "skill_eval", BUSINESS_FIXTURE_SQL)
        psql_exec(pg_container, "skill_eval_checkpoint", CHECKPOINT_FIXTURE_SQL)

        os.environ["EVENTS"] = str(events)
        os.environ["OSS_LOCAL"] = str(oss_local)
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"

        # 唯一测试替身：compose config 来自预生成 JSON（与 test_deploy_backup
        # 相同合同，提供两库 DSN/密钥/OSS 配置）。compose ps/stop/start、
        # pg_dump、文件导出、ossutil 之外的全部命令走真实 Docker；
        # load_deploy_config 必须在替身生效后调用（见 run_backup_tool）。
        real_run_cmd = backup.run_cmd

        def fake_run_cmd(argv: Any, **kwargs: Any) -> Any:
            argv = list(argv)
            if argv[:3] == ["docker", "compose", "config"]:
                return backup._RedactedCompleted(argv, 0, cfg_path.read_text(encoding="utf-8"), "")
            return real_run_cmd(argv, **kwargs)

        yield {
            "project": project_name,
            "dir": stack_dir,
            "compose_dir": compose_dir,
            "pg_container": pg_container,
            "oss_local": oss_local,
            "events": events,
            "patches": [(backup, "run_cmd", fake_run_cmd)],
        }
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        compose(project_name, compose_path, ["down", "-v", "--remove-orphans", "--timeout", "30"], timeout=180)
        for name in project_containers(project_name):
            # 身份核验：只清理本项目名前缀的容器
            if name.startswith(project_name):
                docker(["rm", "-f", name], timeout=60)
        # appdata 卷不在本 stack 的 compose 声明中，down -v 不会删它；按项目名精确清理
        appdata_volume = f"{project_name}_appdata"
        exists = docker(["volume", "ls", "--filter", f"name=^{appdata_volume}$", "--format", "{{.Name}}"])
        if appdata_volume in exists.stdout.split():
            docker(["volume", "rm", appdata_volume], timeout=60)
        shutil.rmtree(stack_dir, ignore_errors=True)


def run_backup_tool(stack: dict[str, Any], monkeypatch: pytest.MonkeyPatch, backups_dir: Path) -> int:
    """在替身环境下调用 backup.cmd_run 等价入口；返回退出码。"""
    for obj, name, value in stack["patches"]:
        monkeypatch.setattr(obj, name, value)
    argv = ["run", "--compose-dir", str(stack["compose_dir"]), "--backups-dir", str(backups_dir)]
    parser = backup.build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except backup.BackupError as exc:
        print(f"[test] BackupError: {backup.redact(str(exc))}")
        return 1


def make_files_tar(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def extract_member(archive: Path, member: str) -> bytes:
    with gzip.open(archive, "rb") as raw:
        with tarfile.open(fileobj=raw, mode="r|") as tar:
            for info in tar:
                if info.name == member:
                    handle = tar.extractfile(info)
                    assert handle is not None
                    return handle.read()
    raise AssertionError(f"归档缺少成员 {member}")


@integration_only
class TestBackupRestoreIntegration:
    def test_real_pg_dump_export_verify_restore_roundtrip(
        self, backup_stack: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        stack = backup_stack
        project = stack["project"]
        pg_container = stack["pg_container"]
        backups_dir = tmp_path / "backups"

        # 只读一次性容器（python:3.11，非 compose 项目成员）导出合成 appdata 文件
        file_entries = {
            "uploads/a.txt": b"synthetic upload A\n",
            "evidence/b.bin": bytes(range(256)),
        }
        files_tar = make_files_tar(file_entries)
        volume = f"{project}_appdata"
        docker_ok(["volume", "create", volume])
        # 把合成文件按目录结构种进 appdata 卷（导出应得到这些文件本身）
        seed_dir = tmp_path / "seed"
        for name, data in file_entries.items():
            target = seed_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        try:
            load = docker(
                ["run", "--rm", "-v", f"{volume}:/src", "-v", f"{seed_dir}:/seed:ro", "python:3.11",
                 "python", "-c", "import shutil; shutil.copytree('/seed', '/src', dirs_exist_ok=True)"],
            )
            assert load.returncode == 0, backup.redact(load.stderr)

            code = run_backup_tool(stack, monkeypatch, backups_dir)
            captured = capsys.readouterr()
            output = captured.out + captured.err
            assert code == 0, backup.redact(output)
            assert "完整备份成功" in output

            latest = backups_dir / "latest.tar.gz"
            verified = backup.validate_archive_path(latest, aes_key=TEST_AES_KEY)
            assert verified.manifest["format"] == backup.FORMAT_NAME

            # 真实 pg_dump 产物包含合成数据
            business_sql = extract_member(latest, backup.MEMBER_BUSINESS).decode("utf-8")
            assert "合成题目一" in business_sql and "合成题目二" in business_sql
            checkpoint_sql = extract_member(latest, backup.MEMBER_CHECKPOINT).decode("utf-8")
            assert "thread-1" in checkpoint_sql and "deadbeef" in checkpoint_sql
            # files.tar 是只读一次性容器 `tar -cf - -C /backup-src .` 的产物：
            # 成员带 ./ 前缀，按内容（名字规范化 + 摘要）核对而不是字节相等
            files_member = extract_member(latest, backup.MEMBER_FILES)
            with tarfile.open(fileobj=io.BytesIO(files_member), mode="r:") as exported:
                exported_entries = {
                    Path(info.name).as_posix().removeprefix("./"): hashlib.sha256(
                        (exported.extractfile(info) or io.BytesIO(b"")).read()
                    ).hexdigest()
                    for info in exported
                    if info.isfile()
                }
            assert exported_entries == {
                name: hashlib.sha256(data).hexdigest() for name, data in file_entries.items()
            }, "文件成员应与只读一次性容器导出的卷内容一致"

            # 恢复目标：同一 postgres 实例上的全新隔离库（受控输入、SQL 错误即停）
            docker_ok(["exec", pg_container, "createdb", "-U", "skill_eval", "restore_biz"])
            docker_ok(["exec", pg_container, "createdb", "-U", "skill_eval", "restore_ckpt"])
            restore_dir = tmp_path / "restore"
            restore_dir.mkdir()
            (restore_dir / "business.sql").write_bytes(extract_member(latest, backup.MEMBER_BUSINESS))
            (restore_dir / "checkpoint.sql").write_bytes(extract_member(latest, backup.MEMBER_CHECKPOINT))
            for name in ("business", "checkpoint"):
                load = docker(
                    ["cp", str(restore_dir / f"{name}.sql"), f"{pg_container}:/tmp/{name}.sql"]
                )
                assert load.returncode == 0, load.stderr
            psql_exec(pg_container, "restore_biz", "\\i /tmp/business.sql")
            psql_exec(pg_container, "restore_ckpt", "\\i /tmp/checkpoint.sql")
            titles = psql_query(
                pg_container, "restore_biz", "SELECT string_agg(title, ',' ORDER BY id) FROM questions;"
            )
            assert "合成题目一" in titles and "合成题目二" in titles
            thread = psql_query(pg_container, "restore_ckpt", "SELECT thread_id FROM checkpoints;")
            assert "thread-1" in thread
            # 文件解包路径严格校验（data filter）+ 摘要核对
            extract_dir = tmp_path / "files"
            extract_dir.mkdir()
            with tarfile.open(fileobj=io.BytesIO(files_member), mode="r:") as tar:
                tar.extractall(extract_dir, filter="data")
            for name, data in file_entries.items():
                restored = extract_dir / name
                assert restored.is_file(), f"恢复缺少文件 {name}"
                assert hashlib.sha256(restored.read_bytes()).digest() == hashlib.sha256(data).digest()
            # HMAC 用原密钥验证通过（validate_archive_path 已核对），错误密钥失败见下一测试
            assert_no_secret_output(output)
        finally:
            docker(["volume", "rm", volume], timeout=60)
            for dbname in ("restore_biz", "restore_ckpt"):
                docker(["exec", pg_container, "dropdb", "-U", "skill_eval", "--if-exists", dbname], timeout=60)

    def test_restore_fails_closed_on_wrong_key_missing_member_corruption(
        self, backup_stack: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        stack = backup_stack
        backups_dir = tmp_path / "backups"
        code = run_backup_tool(stack, monkeypatch, backups_dir)
        captured = capsys.readouterr()
        assert code == 0, backup.redact(captured.out + captured.err)
        latest = backups_dir / "latest.tar.gz"

        # 错误密钥：开放写入前失败，不生成替代密钥
        with pytest.raises(backup.BackupError, match="HMAC"):
            backup.validate_archive_path(latest, aes_key=WRONG_AES_KEY)
        # 缺 checkpoint 成员：不是完整恢复点
        partial = tmp_path / "partial.tar.gz"
        backup.build_synthetic_archive(
            partial, members=(backup.MEMBER_MANIFEST, backup.MEMBER_BUSINESS, backup.MEMBER_FILES)
        )
        with pytest.raises(backup.BackupError, match="缺少成员"):
            backup.validate_archive_path(partial, aes_key=TEST_AES_KEY)
        # 损坏归档（成员与清单摘要不一致）
        corrupt = tmp_path / "corrupt.tar.gz"
        backup.build_synthetic_archive(corrupt, corrupt_member=backup.MEMBER_CHECKPOINT)
        with pytest.raises(backup.BackupError, match="不一致"):
            backup.validate_archive_path(corrupt, aes_key=TEST_AES_KEY)
        # restore-check 入口对错误密钥失败关闭
        key_file = tmp_path / "wrong-key"
        key_file.write_text(WRONG_AES_KEY, encoding="utf-8")
        rc = backup.main(["restore-check", str(latest), "--aes-key-file", str(key_file)])
        captured2 = capsys.readouterr()
        assert rc == 1
        assert "重新开放写入前失败" in captured2.out + captured2.err
        assert_no_secret_output(captured2.out + captured2.err)

    def test_oss_publish_via_real_archive(
        self, backup_stack: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """run 全流程含 fake ossutil 发布：真实归档上 OSS 只留一套（bundle+指针）。"""
        stack = backup_stack
        backups_dir = tmp_path / "backups"
        code = run_backup_tool(stack, monkeypatch, backups_dir)
        captured = capsys.readouterr()
        assert code == 0, backup.redact(captured.out + captured.err)
        oss_root: Path = stack["oss_local"] / "skill-eval-backup-bucket" / "skill-eval-backups"
        bundles = sorted((oss_root / "bundles").glob("*.tar.gz"))
        assert len(bundles) == 1
        pointer = json.loads((oss_root / "latest.json").read_text(encoding="utf-8"))
        assert pointer["object"] == f"bundles/{bundles[0].name}"
        # 指针摘要 = 服务器 latest 的整包 SHA-256
        digest = hashlib.sha256((backups_dir / "latest.tar.gz").read_bytes()).hexdigest()
        assert pointer["sha256"] == digest
        assert_no_secret_output(captured.out + captured.err)


def assert_no_secret_output(text: str) -> None:
    assert PASSWORD not in text, "输出泄漏了数据库密码"
    assert TEST_AES_KEY not in text, "输出泄漏了 AES 密钥"
