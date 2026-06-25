"""AI 简历求职助手一键启动器。

默认模式（推荐，单进程）：让后端在同一端口同时托管已构建的前端，
启动后自动打开浏览器，Ctrl+C 优雅关闭。

    python launch.py

开发模式（前后端分离，前端用 Vite 热更新，需要 Node/npm）：

    python launch.py --dev

该脚本同时兼容被 PyInstaller 打包成 exe 后运行：把生成的 exe 放在项目根目录
（与 app/、frontend/、.venv/ 同级）双击即可。
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

try:  # 让 Windows 控制台正常显示中文
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def project_root() -> Path:
    """定位项目根目录，兼容源码运行与 PyInstaller 打包后的 exe。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = project_root()

# 基础设施依赖：服务名 -> (host, port, 端口就绪等待秒数)。
# 这些服务在 docker-compose.yml 中属于 "infra" profile，默认 `docker compose up`
# 不会启动它们，改由本启动器在启动时按需用 Docker 拉起。
INFRA_SERVICES: dict[str, tuple[str, int, int]] = {
    "redis": ("127.0.0.1", 6379, 30),
    "mysql": ("127.0.0.1", 3306, 90),
}


def log(message: str) -> None:
    print(f"[启动器] {message}", flush=True)


def backend_python() -> str:
    """优先使用项目虚拟环境的 Python 运行后端。"""
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    venv_python_posix = ROOT / ".venv" / "bin" / "python"
    if venv_python_posix.exists():
        return str(venv_python_posix)
    if not getattr(sys, "frozen", False):
        return sys.executable
    raise SystemExit(
        "找不到虚拟环境 .venv，请先在项目目录创建并安装依赖："
        "python -m venv .venv && .venv\\Scripts\\pip install -r requirements.txt"
    )


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def wait_for_port(host: str, port: int, timeout_seconds: float = 60.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if port_in_use(host, port):
            return True
        time.sleep(1.0)
    return False


def docker_compose_cmd() -> list[str] | None:
    """返回可用的 docker compose 命令；找不到则返回 None。"""
    if shutil.which("docker") is not None:
        try:
            probe = subprocess.run(
                ["docker", "compose", "version"],
                capture_output=True,
                timeout=20,
            )
            if probe.returncode == 0:
                return ["docker", "compose"]
        except Exception:  # noqa: BLE001
            pass
    if shutil.which("docker-compose") is not None:
        return ["docker-compose"]
    return None


def docker_running() -> bool:
    """Docker 守护进程是否可用（Docker Desktop 是否已启动）。"""
    if shutil.which("docker") is None:
        return False
    try:
        probe = subprocess.run(["docker", "info"], capture_output=True, timeout=20)
        return probe.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def ensure_infra(args: argparse.Namespace) -> list[str]:
    """按需用 Docker 拉起 Redis / MySQL（仅启动未在运行的服务）。

    这些服务在 compose 中属于 ``infra`` profile，默认 ``docker compose up`` 不会
    启动；这里通过 ``docker compose --profile infra up -d <service>`` 显式拉起。
    端口已在监听（无论是 Docker 还是本地服务提供）则跳过，避免重复启动或冲突。

    返回本次实际由启动器拉起的服务名列表，便于退出时只停掉自己拉起的容器，
    不影响用户原本就在运行的 Redis / MySQL。
    """
    if getattr(args, "no_infra", False):
        log("已指定 --no-infra，跳过自动拉起 Redis / MySQL。")
        return []

    missing = [
        name
        for name, (host, port, _) in INFRA_SERVICES.items()
        if not port_in_use(host, port)
    ]
    if not missing:
        log("Redis / MySQL 已在运行，无需拉起。")
        return []

    compose = docker_compose_cmd()
    if compose is None or not docker_running():
        log(
            "检测到 "
            + "、".join(missing)
            + " 未运行，但 Docker 不可用。请启动 Docker Desktop 后重试，"
            "或手动启动 Redis / MySQL。"
        )
        return []

    compose_file = ROOT / "docker-compose.yml"
    log("通过 Docker 拉起基础设施：" + "、".join(missing) + " ……")
    subprocess.run(
        compose
        + ["-f", str(compose_file), "--profile", "infra", "up", "-d", *missing],
        cwd=str(ROOT),
        check=False,
    )
    for name in missing:
        host, port, wait_seconds = INFRA_SERVICES[name]
        if wait_for_port(host, port, wait_seconds):
            log(f"{name} 端口已就绪（{host}:{port}）。")
        else:
            log(f"{name} 等待超时，可执行 docker compose logs {name} 排查。")
    return missing


def stop_infra(services: list[str]) -> None:
    """停止由本启动器拉起的基础设施容器（退出时调用）。"""
    if not services:
        return
    compose = docker_compose_cmd()
    if compose is None:
        return
    compose_file = ROOT / "docker-compose.yml"
    log("停止启动器拉起的基础设施：" + "、".join(services) + " ……")
    subprocess.run(
        compose + ["-f", str(compose_file), "stop", *services],
        cwd=str(ROOT),
        check=False,
    )


def wait_for_health(url: str, timeout_seconds: float = 60.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(1.0)
    return False


def ensure_frontend_build(skip_build: bool) -> bool:
    """确保前端已构建（dist 存在）。必要时调用 npm run build。"""
    index_html = ROOT / "frontend" / "dist" / "index.html"
    if index_html.exists():
        return True
    if skip_build:
        log("未发现 frontend/dist，且已指定 --skip-build，将只启动后端 API。")
        return False
    npm = shutil.which("npm")
    if npm is None:
        log("未发现 frontend/dist，也没有检测到 npm，无法自动构建前端。")
        log("可先手动构建：cd frontend && npm install && npm run build")
        return False
    frontend_dir = ROOT / "frontend"
    if not (frontend_dir / "node_modules").exists():
        log("正在安装前端依赖（npm install），首次较慢……")
        subprocess.run([npm, "install"], cwd=frontend_dir, check=True, shell=False)
    log("正在构建前端（npm run build）……")
    subprocess.run([npm, "run", "build"], cwd=frontend_dir, check=True, shell=False)
    return index_html.exists()


def start_backend(host: str, port: int) -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [
        backend_python(),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    log(f"启动后端：{' '.join(cmd)}")
    return subprocess.Popen(cmd, cwd=str(ROOT), env=env)


def start_frontend_dev() -> subprocess.Popen | None:
    npm = shutil.which("npm")
    if npm is None:
        log("开发模式需要 npm，但未检测到，跳过前端热更新。")
        return None
    frontend_dir = ROOT / "frontend"
    if not (frontend_dir / "node_modules").exists():
        log("正在安装前端依赖（npm install），首次较慢……")
        subprocess.run([npm, "install"], cwd=frontend_dir, check=True, shell=False)
    log("启动前端开发服务器：npm run dev")
    return subprocess.Popen([npm, "run", "dev"], cwd=str(frontend_dir), shell=False)


def run(args: argparse.Namespace) -> int:
    host = args.host
    port = args.port

    started_infra = ensure_infra(args)
    if getattr(args, "infra_only", False):
        log("已完成基础设施启动（--infra-only），未启动后端 / 前端。")
        return 0

    if port_in_use(host, port):
        log(f"端口 {host}:{port} 已被占用，可能后端已在运行。")
        if not args.no_browser:
            webbrowser.open(f"http://{host}:{port}/")
        return 0

    processes: list[subprocess.Popen] = []
    frontend_url = f"http://{host}:{port}/"

    try:
        if args.dev:
            backend = start_backend(host, port)
            processes.append(backend)
            health_url = f"http://{host}:{port}{args.api_prefix}/health"
            log("等待后端就绪……")
            if not wait_for_health(health_url):
                log("后端健康检查超时，请查看上方日志排查。")
            frontend = start_frontend_dev()
            if frontend is not None:
                processes.append(frontend)
                frontend_url = f"http://{host}:{args.dev_port}/"
                time.sleep(2.0)
        else:
            built = ensure_frontend_build(args.skip_build)
            backend = start_backend(host, port)
            processes.append(backend)
            health_url = f"http://{host}:{port}{args.api_prefix}/health"
            log("等待后端就绪……")
            if not wait_for_health(health_url):
                log("后端健康检查超时，请查看上方日志排查。")
            if not built:
                frontend_url = f"http://{host}:{port}/docs"

        log("=" * 56)
        log(f"前端控制台：{frontend_url}")
        log(f"后端 API 文档：http://{host}:{port}/docs")
        log("按 Ctrl+C 关闭所有服务。")
        log("=" * 56)

        if not args.no_browser:
            webbrowser.open(frontend_url)

        backend.wait()
    except KeyboardInterrupt:
        log("收到退出信号，正在关闭服务……")
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        if started_infra and not getattr(args, "keep_infra", False):
            stop_infra(started_infra)
        elif started_infra:
            log("已保留启动器拉起的 Redis / MySQL（--keep-infra）。")
        log("已退出。")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI 简历求职助手一键启动器")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8025, help="后端端口，默认 8025")
    parser.add_argument(
        "--api-prefix", default="/api/v1", help="后端 API 前缀，默认 /api/v1"
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="开发模式：后端 + 前端 Vite 热更新（需要 Node/npm）",
    )
    parser.add_argument(
        "--dev-port", type=int, default=5173, help="开发模式前端端口，默认 5173"
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="默认模式下跳过自动构建前端（dist 不存在则只起后端）",
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="启动后不自动打开浏览器"
    )
    parser.add_argument(
        "--no-infra",
        action="store_true",
        help="不自动用 Docker 拉起 Redis / MySQL（自备时使用）",
    )
    parser.add_argument(
        "--infra-only",
        action="store_true",
        help="只用 Docker 拉起 Redis / MySQL，不启动后端 / 前端",
    )
    parser.add_argument(
        "--keep-infra",
        action="store_true",
        help="退出时保留启动器拉起的 Redis / MySQL（默认退出时会停掉它们）",
    )
    return parser.parse_args(argv)


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
