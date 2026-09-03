from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "resources" / "agent_reach_runtime.json"
COMMIT_SOURCE_RE = re.compile(
    r"^git\+https://github\.com/Panniantong/Agent-Reach\.git@[0-9a-f]{40}$"
)
ARCHIVE_SOURCE_RE = re.compile(
    r"^https://github\.com/Panniantong/Agent-Reach/archive/[0-9a-f]{40}\.zip$"
)


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "package",
        "minimum_version",
        "bundled_wheel",
        "bundled_wheel_sha256",
        "archive_source",
        "source",
        "runtime_dir",
        "default_system_channels",
        "required_discovery_channels",
    }
    missing = required - manifest.keys()
    if missing:
        raise ValueError(f"Agent Reach manifest 缺少字段: {', '.join(sorted(missing))}")
    if manifest["package"] != "agent-reach":
        raise ValueError("Agent Reach manifest package 不正确")
    if not COMMIT_SOURCE_RE.fullmatch(str(manifest["source"])):
        raise ValueError("Agent Reach source 必须固定到官方仓库的 40 位 commit")
    if not ARCHIVE_SOURCE_RE.fullmatch(str(manifest["archive_source"])):
        raise ValueError("Agent Reach archive_source 必须固定到官方仓库的 40 位 commit")
    if not isinstance(manifest["required_discovery_channels"], list):
        raise ValueError("required_discovery_channels 必须是数组")
    wheel = ROOT / str(manifest["bundled_wheel"])
    try:
        wheel.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError("bundled_wheel 必须位于 Skill 仓库内") from exc
    if not re.fullmatch(r"[0-9a-f]{64}", str(manifest["bundled_wheel_sha256"])):
        raise ValueError("bundled_wheel_sha256 必须是 64 位十六进制 SHA-256")
    return manifest


def runtime_dir(manifest: dict) -> Path:
    return Path(os.path.expanduser(str(manifest["runtime_dir"])))


def private_executable(manifest: dict) -> Path:
    root = runtime_dir(manifest)
    if os.name == "nt":
        return root / "Scripts" / "agent-reach.exe"
    return root / "bin" / "agent-reach"


def find_agent_reach(manifest: dict) -> str | None:
    global_command = shutil.which("agent-reach")
    if global_command:
        return global_command
    local_command = private_executable(manifest)
    return str(local_command) if local_command.is_file() else None


def bundled_wheel(manifest: dict) -> Path | None:
    path = ROOT / str(manifest["bundled_wheel"])
    if not path.is_file():
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != manifest["bundled_wheel_sha256"]:
        raise RuntimeError("内置 Agent Reach wheel 校验失败，拒绝安装")
    return path


def run_checked(command: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def install_private_runtime(manifest: dict) -> str:
    target = runtime_dir(manifest)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not target.exists():
        run_checked([sys.executable, "-m", "venv", str(target)])
    pip_command = target / ("Scripts/pip.exe" if os.name == "nt" else "bin/pip")
    local_wheel = bundled_wheel(manifest)
    sources = [str(local_wheel)] if local_wheel else []
    sources.extend((manifest["archive_source"], manifest["source"]))
    errors = []
    for source in sources:
        try:
            run_checked(
                [
                    str(pip_command),
                    "install",
                    "--disable-pip-version-check",
                    "--upgrade",
                    str(source),
                ]
            )
            break
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"{source}: {exc}")
    else:
        raise RuntimeError("Agent Reach 固定版本下载失败；已尝试 ZIP 与 Git 两条路径")
    command = private_executable(manifest)
    if not command.is_file():
        detail = f"；安装错误: {' | '.join(errors)}" if errors else ""
        raise RuntimeError(f"Agent Reach 私有运行时安装后未找到可执行文件{detail}")
    return str(command)


def doctor(command: str) -> dict:
    result = subprocess.run(
        [command, "doctor", "--json"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise ValueError("Agent Reach doctor 返回格式不正确")
    return payload


def status_payload(manifest: dict) -> dict:
    command = find_agent_reach(manifest)
    if not command:
        return {
            "installed": False,
            "minimum_version": manifest["minimum_version"],
            "runtime_dir": str(runtime_dir(manifest)),
            "next_action": "install",
        }
    try:
        channels = doctor(command)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError) as exc:
        return {
            "installed": True,
            "command": command,
            "healthy": False,
            "error": str(exc),
            "next_action": "repair",
        }
    required = set(manifest["required_discovery_channels"])
    usable = {
        name
        for name, value in channels.items()
        if isinstance(value, dict) and value.get("status") == "ok"
    }
    return {
        "installed": True,
        "command": command,
        "healthy": True,
        "minimum_version": manifest["minimum_version"],
        "required_channels": sorted(required),
        "doctor_ok_channels": sorted(usable),
        "missing_or_unverified_channels": sorted(required - usable),
        "channels": channels,
    }


def install(manifest: dict, *, system: bool, channels: str) -> dict:
    command = find_agent_reach(manifest) or install_private_runtime(manifest)
    if system:
        run_checked(
            [
                command,
                "install",
                "--env=auto",
                "--system",
                f"--channels={channels}",
            ]
        )
    else:
        run_checked([command, "install", "--env=auto"])
    return status_payload(manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description="热点选题 Skill 内置 Agent Reach 运行时")
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("status", help="只读检查安装与渠道状态")
    install_parser = subparsers.add_parser("install", help="安装或修复内置运行时")
    install_parser.add_argument(
        "--system",
        action="store_true",
        help="允许 Agent Reach 安装全局上游工具并写入用户级配置",
    )
    install_parser.add_argument(
        "--channels",
        default=None,
        help="传给 Agent Reach 的渠道列表；默认读取 manifest",
    )
    args = parser.parse_args()

    manifest = load_manifest()
    if args.action == "status":
        payload = status_payload(manifest)
    else:
        channels = args.channels or manifest["default_system_channels"]
        payload = install(manifest, system=args.system, channels=channels)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
