"""确认这次跑批用的是最新的 Skill。

2026-09-20 有一批是用旧版规则跑的，跑到一半才发现。所以不靠记性：抓取时把当时的 commit
记进 run.json，发布前再和远程 main 对一次，本地落后就不让发。取不到远程（断网）时不拦。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args: str, root: Path = ROOT, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=timeout)


def output(*args: str, root: Path = ROOT) -> str:
    result = git(*args, root=root)
    return result.stdout.strip() if result.returncode == 0 else ""


def current_commit(root: Path = ROOT) -> str:
    return output("rev-parse", "--short", "HEAD", root=root)


def behind_remote(root: Path = ROOT) -> str:
    """远程比本地新时返回缺的那几条提交，否则返回空字符串。"""
    git("fetch", "origin", "main", root=root)
    local, remote = output("rev-parse", "HEAD", root=root), output("rev-parse", "origin/main", root=root)
    if not local or not remote or local == remote:
        return ""
    if git("merge-base", "--is-ancestor", local, remote, root=root).returncode != 0:
        return ""  # 本地有未推送的改动，不算落后
    return output("log", "--oneline", f"{local}..{remote}", root=root) or "本地落后于 origin/main"
