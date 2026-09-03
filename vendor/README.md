# Vendored runtime

`agent_reach-1.5.0-py3-none-any.whl` 来自 MIT 许可的
[`Panniantong/Agent-Reach`](https://github.com/Panniantong/Agent-Reach)，固定到提交：

`da5044d26fc6adddb6554d5679c94ac22e76e428`

构建前已运行上游完整测试。wheel 由该提交使用下面的命令生成：

```bash
uv build --wheel
```

SHA-256：

`07ecabccdf2ecd1217a13f30f8348f7b7bb0d290729406e291807f66014cf658`

运行时安装位置不在仓库中，而是用户自己的
`~/.agent-reach/stephen-hot-content-runtime`。Cookie、Token 和登录态不会打包进 wheel，也不得提交到本仓库。
