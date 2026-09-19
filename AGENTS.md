# 协作规则

## 范围

- 选题批次的数量、停止条件与缺口报告以 `SKILL.md`「交付规则」为唯一准则：不足时持续扩源，不降标凑数；达到停止条件仍不足时交付缺口报告，由用户决定下一步。

- 本仓库只负责 Stephen 的 AI 热点选题，不负责文章正文。
- 中文二手内容是默认候选池；英文一手来源只用于发现选题线索和事实核验，不直接作为候选。例外是主流 AI 厂商的重大发布：发布后 5 天内，官方英文原文（博客、官网、文档、官方账号）可以直接作候选。
- 选题方向与筛选标准由用户决定，技术实现可自主完成。
- 不修改仓库外的文件。

## 写作规范

Skill 里的文档、注释、报错和审核页文字是写给 Stephen 看的，要让他不问 AI 也能看懂。

- 说具体的事：写“命中就扣 10 分”，不写“施加降权约束”；写“至少 2 条原文引用”，不写“证据锚点契约”。
- 给东西起名用“做什么 + 对象”，例如“推荐理由格式检查”“搜索记录本”“收工检查”。不要用契约、词典、求解空间、口径、闭环、抓手、赋能、范式这类词命名，“门槛”只在说具体数字时用。
- 一个概念全仓库只用一个名字。第一次出现的英文字段名或工具名，紧跟一句中文说明它是干什么的。
- 少用破折号和引号，不写“第一招、三点启示”这种整齐套话，不堆小标题。能用一句话说清的不拆成清单。
- 数字、条数和阈值只在 `resources/editorial_profile.json` 写一次，文档里写“见口味档案”或直接引用字段名，避免改一处漏一处。
- 临时要求（某一批要几条、某次只看某个来源）不写进长期规则。

## 安全

- API Key、Token、Cookie、登录态和本地反馈禁止提交。
- `.config/`、`.local/`、缓存和运行结果保持在 `.gitignore` 中。
- 提交前扫描敏感信息和大文件：
  `git diff --cached | grep -nE '(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|z_c0=|Bearer [A-Za-z0-9._-]{20,})'` 应无输出；`git diff --cached --stat` 中不应出现 `.local`、`topics`、`.config` 或单个超过 1MB 的文件。

## 验证

- 修改评分、抓取或报告逻辑后，运行 `.venv/bin/python3 -m unittest discover -s tests -v`（worktree 内使用权威仓库的 `.venv`）。
- 修改口味档案、一票否决、打分或终审标准后，运行 `.venv/bin/python3 scripts/eval_replay.py machine`，报告退步时不提交；改终审标准时再按 `references/evaluation.md` 跑判断层评测。
- 修改来源后，至少运行一次离线夹具 `.venv/bin/python3 scripts/scrape_aihot.py --fixture tests/fixtures/sample_items.json --output-root .local/work/fixture`；条件允许时再运行联网抓取。
- 声称完成前，回读远程仓库最新提交。

## 版本管理

- 每次修改完成本地 commit 并发布到 Public 远程 `origin` 的 `main`：单任务可直接在 `main` 提交；有并发会话时在各自 worktree 分支提交，再按下方流程 `git push origin HEAD:main`。
- 不提交 `topics/` 运行结果，除非用户明确要求保留某次样例。
- 不改写已公开历史，不 force push。

## 并发任务

- 修改仓库代码或文档的并发会话必须使用各自独立 Git worktree 和分支，不得同时修改同一个工作树；只跑选题批次、不改仓库文件的会话在权威仓库根目录执行，工作文件放在各自的 `.local/work/<批次ID>/`。
- 并发 worktree 可以将 `.local/`、`.config/`、`topics/` 链接到权威仓库对应目录，以共享反馈、私有配置和审核产物；这些路径仍然禁止提交。
- `scripts/add_source.py` 与 `scripts/import_feedback.py` 的共享写入必须保留文件锁，禁止绕过脚本直接并发改 JSON/JSONL。
- 每个任务开始先 `git fetch origin main` 并同步自己的分支；提交前再次同步 `origin/main`、解决冲突、重跑相关测试，再用 `git push origin HEAD:main` 发布。推送被拒绝时重新同步和验证，禁止 force push。
