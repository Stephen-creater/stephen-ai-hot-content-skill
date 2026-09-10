# 知乎 CLI 与 Ego Browser 路由

本路由只用于知乎只读扩源。它把 OpenCLI 的结构化知乎适配器能力与 Ego Browser 的隔离登录态配合使用，不导出 Cookie，不操作用户 Chrome，也不执行回答、评论、点赞、收藏、关注等写操作。

## 已验证能力与真实边界

2026-09-10 本机 OpenCLI 1.8.7 的 `zhihu` 适配器提供：

- `hot`：热榜，只作线索；
- `search`：按 `all / answer / article / question` 搜索，支持分页；
- `question`、`answer-detail`：问题与完整回答；
- `user`、`user-answers`、`user-articles`：作者资料及其回答、专栏文章；
- `download`：导出文章为 Markdown。

其中搜索使用 `/api/v4/search_v3`，完整回答使用 `/api/v4/answers/<answer_id>`。可用 `opencli zhihu --help -f yaml` 读取静态命令契约；帮助命令不需要打开浏览器。

当前 OpenCLI Browser Bridge 与 Ego Browser 是两套隔离会话。本轮 `opencli zhihu whoami` 和搜索数据命令因其 Chrome 会话缺少 `z_c0` 返回 `AUTH_REQUIRED`，而 Ego 中的知乎登录态可正常读取。这个结果不能表述成“知乎 CLI 已登录”或“CLI 已直接抓到数据”。

## 运行方式

1. 只在知乎是明确的高价值缺口、用户指定知乎，或常规来源不足时启用；它不是每批必跑渠道。
2. 先用静态帮助确认当前安装版本仍包含所需只读命令。适配器升级后若字段或端点变化，以当前帮助和本机适配器实现为准，不沿用旧假设。
3. 若 OpenCLI 数据命令没有现成、不会干扰用户 Chrome 的已授权会话，不运行 `login`，不要求用户复制 Cookie，也不反复重试。进入 Ego 独立 Task Space，在 `https://www.zhihu.com` 同源页面内用 `browserFetch` 或页面 `fetch(..., {credentials: 'include'})` 执行适配器等价的只读请求。
4. 搜索结果先保留原题、类型、作者、赞同数、URL 和分页信息。热榜、问题页与搜索列表都只算线索；逐条打开回答或专栏原文，核对标题、作者、日期、正文起止和结尾。
5. 对命中作者继续读取 `user-articles` / `user-answers` 对应作者页或接口，优先找围绕同一产品问题持续展开的完整访谈与产品决策材料。
6. 完成后关闭 Ego Task Space；在探索台账中分别记录 `search`、`read`、`author` 的非空结果和证据 URL。渠道名写成 `zhihu-cli-contract+ego-browser`，不得记成已验证的 OpenCLI 直连。

## 选题判断

本轮用户从 20 条知乎候选中保留了两条：一条手机 AI Memory 产品负责人访谈，一条 AI 社交产品创始人访谈。当前可复用的条件偏好是：知乎优先寻找完整的创始人、产品负责人或核心团队对话，且正文必须给出具体产品决策、用户任务、限制条件与取舍。

这不是“人物访谈自动入选”的白名单。宏观趋势、创业经历、品牌宣传、松散 QA、单点观点、技术实现细节或只能依赖作者身份成立的访谈仍按五维终审淘汰。单篇回答只有在自身形成连续因果链、读者改变明确、去掉作者专属资产后仍能二创时才进入审核页。

## Ego 只读请求示例

示例只展示请求形状。实际运行必须遵守 Ego Skill 的 Task Space、加载验证与关闭要求，并对返回结构做非空检查与分页去重。

```javascript
const task = await useOrCreateTaskSpace('stephen zhihu research')
await openOrReuseTab('https://www.zhihu.com', { wait: true, timeout: 30 })

const query = encodeURIComponent('AI 产品负责人 对话')
const search = await browserFetch(
  `https://www.zhihu.com/api/v4/search_v3?q=${query}&t=general&offset=0&limit=20`,
  { credentials: 'include' }
)
cliLog(search)
```

不要把列表摘要、站内 AI 总结、评论区总结或搜索高赞当成完整材料。专栏文章正文优先从公开原页面核验；回答可按适配器契约读取完整内容，但最终仍要检查页面是否公开可访问、正文是否截断，以及材料能否独立二创。
