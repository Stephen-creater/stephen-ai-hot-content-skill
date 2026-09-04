# 朱雀 AIGC 文本检测接入

朱雀通过腾讯云 EdgeOne Makers Model Pro 的 AI 网关提供服务，仅企业版开放，会按 EIU 产生费用。热点选题 Skill 只把已经通过其他硬门槛、可能进入报告的完整正文送检，并按正文 SHA-256 缓存结果，避免重复调用。

截至 2026-09-04，腾讯云官方价格是 0.001 元/EIU；`zhuque-text` 每 1000 字符（向上取整）消耗 40 EIU，即约 0.04 元。2.2 万字符约 0.88 元。默认单次运行费用保护线为 5 元，预估超过后整批不调用并写入告警，可通过 `max_cost_yuan_per_run` 调整。

## 用户首次配置

1. 在 EdgeOne 控制台创建 Makers Model Pro 项目并开通朱雀能力。
2. 记录网关域名和 API Key。API Key 当前不能补发，遗失后需重新创建网关。
3. 复制 `resources/zhuque_config.example.json` 到 `.config/zhuque.json`，填入真实值；或设置 `ZHUQUE_GATEWAY` 与 `ZHUQUE_API_KEY` 环境变量。
4. 运行状态检查，再做一次会产生费用的真实测试：

```bash
python3 scripts/zhuque_aigc.py status
python3 scripts/zhuque_aigc.py test --text "待检测的一小段中文"
python3 scripts/zhuque_aigc.py test --file /path/to/article.txt
```

`.config/` 和 `.local/` 已被 Git 忽略。不得把真实 API Key 写进 README、`SKILL.md`、测试、报告或提交历史。

## 返回结构与标签

Skill 使用同步文本路由 `/v1/providers/zhuque-text/classify`，发送 `is_merge: false`，以取得逐段结果。原始标签含义：

- `0`：人工写作
- `1`：AI 写作
- `2`：疑似 AI 写作

适配器把 `labels_ratio` 规范化成 `human`、`ai`、`suspected_ai`，并保留每段的文字、标签、置信度、顺序和字符位置。异步模式不是当前默认路径；若以后批量规模显著增大，再增加任务提交和轮询。

## 当前筛选政策

- `ai >= 98%`：视为几乎全文由 AI 生成，硬淘汰。
- `ai > 50%` 或 `suspected_ai > 50%`：减 35 分并降低排序。
- 其他结果：保留检测证据，不额外加分。检测通过不等于文章一定由人写。
- API 未配置、鉴权失败、超时或服务异常：写入运行告警，不把未知结果当成人工内容，也不阻断其他确定性筛选。
- 预估费用超过本地 `max_cost_yuan_per_run`：不发起检测，避免无提示扣费。

阈值可在本地配置里调整。缓存位于 `.local/zhuque_aigc_cache.json`；只有正文变化时才会重新计费。腾讯云明确说明检测结果仅供辅助参考，因此“通过”不能当成原创证明。
