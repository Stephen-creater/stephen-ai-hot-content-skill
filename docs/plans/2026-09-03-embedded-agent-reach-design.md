# Agent Reach 内置能力设计

## 目标

用户只安装并调用 `stephen-ai-hot-content-skill`，即可获得 Agent Reach 的多平台检索能力。Agent Reach 对用户表现为内部能力层，而不是另一个需要单独理解的产品。

## 方案

不复制 Agent Reach 全仓库。热点选题仓库保存经过审计的固定版本 wheel、运行时清单、安装与体检脚本，以及选题专用路由参考。首次运行时，脚本优先复用机器上已有的 `agent-reach`；不存在时，在 `~/.agent-reach/stephen-hot-content-runtime` 创建隔离环境。安装优先使用仓库内经过 SHA-256 校验的 wheel，缺失时再尝试固定 commit 的 ZIP 和 Git 源。

系统级工具、浏览器扩展与登录态不适合静默安装。私有 Python 运行时可以自动准备；全局工具安装必须由用户明确允许；Cookie、Token 和登录态始终留在用户本机且不得进入公开仓库。

## 数据流

`SKILL.md` 触发选题任务 → 内置脚本检查运行时和渠道 → Agent Reach doctor 提供路由状态 → Exa 与中文平台发现材料 → 社区平台只提供线索 → 完整中文正文、字幕或逐字稿进入 inbox → 原有评分、历史去重和人工审核流程继续工作。

## 验收

- 没有全局 Agent Reach 时，私有运行时可以独立安装。
- 已安装时优先复用，不重复安装。
- 上游来源固定到 40 位 commit。
- 默认安装不触发全局系统修改。
- 系统级安装必须显式传入 `--system`。
- 运行时状态以结构化 JSON 返回，供 Skill 决定后续渠道。
- 原有热点筛选、反馈库与 Git 工作流不受影响。
