# 协作规则

## 范围

- 选题批次的数量、停止条件与缺口报告以 `SKILL.md`「完成契约与停止条件」为唯一准则：不足时持续扩源，不降标凑数；达到停止条件仍不足时交付缺口报告，由用户决定下一步。

- 本仓库只负责 Stephen 的 AI 热点选题，不负责文章正文。
- 中文二手内容是默认候选池，英文一手来源只用于核验。
- 选题方向与筛选标准由用户决定，技术实现可自主完成。
- 不修改仓库外的文件。

## 安全

- API Key、Token、Cookie、登录态和本地反馈禁止提交。
- `.config/`、`.local/`、缓存和运行结果保持在 `.gitignore` 中。
- 提交前扫描敏感信息和大文件：
  `git diff --cached | grep -nE '(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|z_c0=|Bearer [A-Za-z0-9._-]{20,})'` 应无输出；`git diff --cached --stat` 中不应出现 `.local`、`topics`、`.config` 或单个超过 1MB 的文件。

## 验证

- 修改评分、抓取或报告逻辑后，运行 `.venv/bin/python3 -m unittest discover -s tests -v`（worktree 内使用权威仓库的 `.venv`）。
- 修改来源后，至少运行一次离线夹具；条件允许时再运行联网抓取。
- 声称完成前，回读远程仓库最新提交。

## 版本管理

- 每次修改完成本地 commit 并发布到 Public 远程 `origin` 的 `main`：单任务可直接在 `main` 提交；有并发会话时在各自 worktree 分支提交，再按下方流程 `git push origin HEAD:main`。
- 不提交 `topics/` 运行结果，除非用户明确要求保留某次样例。
- 不改写已公开历史，不 force push。

## 并发任务

- “主力”与“主力2”等并发会话必须使用各自独立 Git worktree 和分支，不得同时修改同一个工作树。
- 并发 worktree 可以将 `.local/`、`.config/`、`topics/` 链接到权威仓库对应目录，以共享反馈、私有配置和审核产物；这些路径仍然禁止提交。
- `scripts/add_source.py` 与 `scripts/import_feedback.py` 的共享写入必须保留文件锁，禁止绕过脚本直接并发改 JSON/JSONL。
- 每个任务开始先 `git fetch origin main` 并同步自己的分支；提交前再次同步 `origin/main`、解决冲突、重跑相关测试，再用 `git push origin HEAD:main` 发布。推送被拒绝时重新同步和验证，禁止 force push。
