# Stephen AI Hot Content Skill

这是 Stephen 的个人 AI 选题系统。它持续发现简体中文材料，检查全文、时效、历史与并发状态，再通过证据化编辑终审生成可审核批次。文章写作不在本项目范围内。

来源按分层模型组织：BestBlogs 与觉醒AI 是中文主入口，访谈与文字稿公众号、有转录的播客是高命中层，英文一手来源只作雷达，资讯媒体不作候选入口。Ego Browser 只在常规路径不足时补充。执行契约、数量要求与停止条件以 [SKILL.md](SKILL.md) 为准。

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
python3 -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt
.venv/bin/python3 scripts/agent_reach_runtime.py install
.venv/bin/python3 scripts/add_source.py "内容链接" --platform wechat --creator "作者"
.venv/bin/python3 scripts/scrape_aihot.py --batch <批次ID> --round 1 --output-root .local/work/<批次ID>
```

本机 Homebrew Python 禁止直接 `pip install`（PEP 668），所以统一使用 `.venv`。

需要一次性补齐 Exa、B站等系统渠道时，只有在明确允许用户级和全局安装后运行：

```bash
.venv/bin/python3 scripts/agent_reach_runtime.py install --system --channels all
```

每轮输出位于 `.local/work/<批次ID>/<时间戳>/`，只是待终审材料；终审后组装到 `topics/<批次ID>/` 再发布。发布数量、构成与停止条件见 SKILL.md 的完成契约。

人工终审完成后发布：

```bash
.venv/bin/python3 scripts/publish_batch.py topics/<批次ID> --owner 主力
```

用户在审核页导出反馈后导入：

```bash
.venv/bin/python3 scripts/import_feedback.py /path/to/selection_feedback.json --expected-batch <批次ID> --owner 主力
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
- `resources/content_curator_sources.json`：自动抓取来源配置，按 `family` 与 `role` 标注来源族和用途。
- `references/source_discovery_playbook.md`：分层来源模型与扩源顺序。
- `resources/source_portfolio.json`：将目标求解空间拆成 12 个加权来源族。
- `scripts/source_coverage.py`：区分真实连通、已配置自动化和近 7 天实际探索覆盖率。
- `scripts/discovery_ledger.py`：私有记录每次检索的结果、全文、合格和入选收益；`stop-check` 判定是否达到停止条件。
- `scripts/curator.py`：确定性发现排序。
- `scripts/publish_batch.py`：终审证据、归属、去重和发布门禁；`--check-only` 只校验不登记。
- `scripts/history_check.py`：终审前按链接和正文重合检查历史重复。
- `tests/fixtures/editorial_boundary_cases.json`：可供不同模型回放的匿名正反边界集。
- `docs/plans/`：历史设计记录，不作为执行依据；现行规则以 `SKILL.md` 与 `references/` 为准。
- `.local/`、`.config/`、`topics/`：私有状态与运行产物，不提交。

## 浏览器与隐私

默认不使用 OpenCLI，避免 Browser Bridge 调试或抢占用户的 Google Chrome；唯一例外是知乎扩源时读取适配器的只读能力契约，见 [知乎路由](references/zhihu-cli-ego.md)。需要浏览器补充时使用 Ego Browser 隔离任务空间；常规检索不要求打开浏览器。

API Key、Cookie、登录态、审核反馈和完整候选正文都不得进入公开仓库。Agent Reach 与朱雀均为可选辅助能力；工具不可用或检测失败时不得伪造结论。

可选模型复排读取 `OPENROUTER_API_KEY` 或忽略目录中的 `.config/openrouter_api_key.txt`。朱雀读取 `ZHUQUE_GATEWAY`、`ZHUQUE_API_KEY` 或 `.config/zhuque.json`，具体协议见 [朱雀说明](references/zhuque-aigc.md)。

离线演示：

```bash
.venv/bin/python3 scripts/scrape_aihot.py --fixture tests/fixtures/sample_items.json --output-root .local/work/fixture
```

## 验证

`quality_audit.py` 只检查文件和结构，满分不代表选题达到用户标准。实际效果须用保留的人工反馈、未参与改规则的材料、误放/误杀记录和新批次用户采纳结果评估。`source_coverage.py` 只报告已声明来源组合的操作验证覆盖；不能推断全网份额。

运行 `.venv/bin/python3 scripts/editorial_outcomes.py` 查看真实审核结果。该报告单列入选但已写的记录，未知召回率保持为空；不能凭持续出现少量入选推断市场供给充足或已经枯竭。

```bash
.venv/bin/python3 -m unittest discover -s tests -v
uv run --with pyyaml python /Users/a1-6/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
git diff --check
.venv/bin/python3 scripts/quality_audit.py
```
