# Stephen AI Hot Content Skill

这是 Stephen 的个人 AI 选题系统。它持续发现简体中文材料，检查全文、时效、历史与并发状态，再通过证据化编辑终审生成可审核批次。文章写作不在本项目范围内。

多渠道选题优先由三个独立任务分渠道寻找，其中一个兼任统筹。各自先读全文筛选，统筹再复核，最终只交付一份筛好的审核页；不会把淘汰记录和搜索线索交给用户二次筛选。渠道分工可以调整，Ego Browser 卡顿时减少空间与标签，不追求窗口数量。

## 判断系统

系统明确区分三类职责：

- **确定性程序**：抓取、语言、完整性、时效、GitHub 状态、去重、批次归属和交付顺序。
- **风险发现**：提示技术门槛、新闻腔、宣传、AI 加工、私人素材依赖等需要核实的问题。
- **人工终审**：依据完整正文判断选题吸引力、读者改变、材料增量、二创独立性和长期价值。

关键词和自动分数只用于发现排序，不能替代最终编辑判断。正式发布的每条候选必须记录五维证据、最强反对理由和决定性证据。

## 反馈如何进入系统

原始反馈保存在本地 `.local/editorial_feedback.jsonl`。新反馈会被区分为稳定原则、有条件偏好、执行规范、精确主题状态、单案例判断、无解释结果或待验证假设。

单一标题、产品名、作者名或技术词不会直接升级为普遍禁令。任何新原则都要先检查历史反例，并通过正反成对测试。

详细规则：

- [编辑判断模型](references/editorial-judgment.md)
- [正反校准案例](references/editorial-calibration-cases.md)
- [反馈学习协议](references/feedback-learning-protocol.md)

## 快速开始

```bash
python3 -m pip install -r scripts/requirements.txt
python3 scripts/agent_reach_runtime.py install
python3 scripts/add_source.py "内容链接" --platform wechat --creator "作者"
python3 scripts/scrape_aihot.py
```

需要一次性补齐 Exa、B站等系统渠道时，只有在明确允许用户级和全局安装后运行：

```bash
python3 scripts/agent_reach_runtime.py install --system --channels all
```

输出位于 `topics/<时间戳>/`。内部草稿允许暂时不足 5 条，但正式交付必须至少 5 条，其中至少 4 条文章型材料、GitHub 最多 1 条。

人工终审完成后发布：

```bash
python3 scripts/publish_batch.py topics/<批次ID> --owner 主力
```

用户在审核页导出反馈后导入：

```bash
python3 scripts/import_feedback.py /path/to/selection_feedback.json --expected-batch <批次ID> --owner 主力
```

导入会核验批次、任务归属、候选顺序和持久化结果；成功后默认删除下载目录中的临时 JSON，失败则保留。

## 目录职责

- `SKILL.md`：Agent 执行契约与门槛。
- `references/`：稳定判断、校准案例和外部能力说明。
- `resources/editorial_profile.json`：可执行配置与风险信号词典。
- `resources/editorial_profile.schema.json`：配置结构契约。
- `scripts/editorial_judgment.py`：资格、风险与人工证据契约。
- `scripts/feedback_audit.py`：反馈覆盖、空备注、重复判断和冲突候选审计，不导出备注原文。
- `scripts/quality_audit.py`：按公开的 100 分结构质量标准检查反馈保真、泛化、可靠性、可维护性、安全与测试。
- `resources/source_portfolio.json`：将目标求解空间拆成 12 个加权来源族。
- `scripts/source_coverage.py`：区分真实连通、已配置自动化和近 7 天实际探索覆盖率。
- `scripts/discovery_ledger.py`：私有记录每次检索的结果、全文、合格和入选收益。
- `scripts/curator.py`：确定性发现排序。
- `scripts/publish_batch.py`：终审证据、归属、去重和发布门禁。
- `tests/fixtures/editorial_boundary_cases.json`：可供不同模型回放的匿名正反边界集。
- `.local/`、`.config/`、`topics/`：私有状态与运行产物，不提交。

## 浏览器与隐私

本项目不使用 OpenCLI，避免 Browser Bridge 调试或抢占用户的 Google Chrome。动态网页和登录态页面使用 Ego Browser 隔离任务空间。

API Key、Cookie、登录态、审核反馈和完整候选正文都不得进入公开仓库。Agent Reach 与朱雀均为可选辅助能力；工具不可用或检测失败时不得伪造结论。

可选模型复排读取 `OPENROUTER_API_KEY` 或忽略目录中的 `.config/openrouter_api_key.txt`。朱雀读取 `ZHUQUE_GATEWAY`、`ZHUQUE_API_KEY` 或 `.config/zhuque.json`，具体协议见 [朱雀说明](references/zhuque-aigc.md)。

离线演示：

```bash
python3 scripts/scrape_aihot.py --fixture tests/fixtures/sample_items.json --no-ai
```

## 验证

`quality_audit.py` 只检查文件和结构，满分不代表选题达到用户标准。实际效果须用保留的人工反馈、未参与改规则的材料、误放/误杀记录和新批次用户采纳结果评估。`source_coverage.py` 只报告已声明来源组合的操作验证覆盖；不能推断全网份额。

运行 `python3 scripts/editorial_outcomes.py` 查看真实审核结果。该报告单列入选但已写的记录，未知召回率保持为空；不能凭持续出现少量入选推断市场供给充足或已经枯竭。

```bash
.venv/bin/python3 -m unittest discover -s tests -v
uv run --with pyyaml python /Users/a1-6/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
git diff --check
python3 scripts/quality_audit.py
```
