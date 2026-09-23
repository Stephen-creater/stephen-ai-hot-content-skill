#!/bin/sh
# 把上线前检查装进本机的 git 提交流程（每个 worktree 共用同一份 hooks）。
HOOKS="$(git rev-parse --path-format=absolute --git-common-dir)/hooks"
cp "$(git rev-parse --show-toplevel)/scripts/hooks/pre-commit" "$HOOKS/pre-commit" && chmod +x "$HOOKS/pre-commit" && echo "已安装：$HOOKS/pre-commit"
