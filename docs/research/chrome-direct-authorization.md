# Chrome Direct 授权机制调研

## 结论

`bao` 每次操作都弹出 Chrome 远程调试授权框，核心原因不是单纯的按钮识别问题，而是当前 CLI 的运行模型会在每条命令中重新连接真实 Chrome：

```text
bao state/click/input
  -> SessionStore 读取 session
  -> provider.connect
  -> raw CDP websocket connect
  -> execute
  -> disconnect
```

现代 Chrome 的 remote debugging approval mode 会对新的调试连接请求弹出授权提示。BrowserAct 在重启后不反复弹窗，关键差异大概率是它在 `browser open` 后维持长驻 session runtime，后续 `state/click/input` 复用同一连接。

因此，长期正确方案是实现 `bao daemon` / 本地长驻 runtime，而不是仅靠 `cdp_auto_allow_helper` 自动点击“允许”。

## 证据

Chrome 官方文档说明，AI agent 通过 auto-connect 连接当前 Chrome 时，Chrome 会显示对话框要求用户允许远程调试连接。这是保护真实浏览器会话的安全机制。

参考：

- Chrome DevTools MCP auto-connect: https://developer.chrome.com/blog/chrome-devtools-mcp-debug-your-browser-session
- Chrome remote debugging port security changes: https://developer.chrome.com/blog/remote-debugging-port
- ChromeDevTools MCP popup stacking issue: https://github.com/ChromeDevTools/chrome-devtools-mcp/issues/1794

Chromium 代码和公开 issue 也显示：

- remote debugging approval mode 由 Chrome 本地状态/策略控制。
- 多个或重复连接会导致 “Allow remote debugging?” 弹窗反复出现或堆叠。
- 使用独立 `--user-data-dir` 可以减少弹窗，但会失去真实员工 Chrome profile 的登录态。

## 与 BrowserAct 的差异

BrowserAct 的实测表现：

- 重启前，旧 `chrome-direct` browser health check failed。
- 删除并重建后仍失败。
- 电脑重启后，BrowserAct `chrome-direct` 成功打开。
- 成功后，后续 `state/click/input/wait` 没有每步弹授权。

这说明 BrowserAct 至少具备两个机制：

- `browser open` 阶段有严格 health check。
- session 成功建立后，后续命令复用同一 runtime，而不是每条命令重新 attach。

`bao` 当前表现：

- `bao chrome-direct authorize` 能证明一次连接成功。
- 但每个 CLI 命令都会断开并重新连接。
- 因此 Chrome 可以把每次操作都视为新的 remote debugging request。

## 方案

### P0：本地长驻 runtime

新增本地 `bao daemon`：

```text
bao daemon start
bao browser open local --session task
bao --session task state
bao --session task click 3
```

运行模型：

```text
CLI
  -> local daemon HTTP/IPC
  -> live SessionManager
  -> live BrowserConnection
  -> raw CDP websocket
```

要求：

- `browser open` 后 daemon 保持 `BrowserConnection`。
- `state/click/input/eval/network` 都通过 daemon 执行。
- CLI fallback reconnect 只用于非 `chrome-direct` 或诊断场景。
- 如果 fallback reconnect 用在 `chrome-direct`，必须输出警告。

### P1：增强授权命令

`bao chrome-direct authorize` 不应只检查一次连接成功，而应执行：

```text
connect
state
disconnect? no, keep runtime
state again through same runtime
```

如果 daemon 模式中连续操作不再弹窗，才算授权成功。

### P2：授权恢复策略

如果 Chrome 重启后弹窗再次出现：

- 暂停动作。
- 告诉 Agent 等待用户点击允许。
- 点击后自动 retry 当前命令。
- 记录到 trace。

## 不推荐方案

### 只靠自动点击弹窗

缺点：

- Windows UIA 不稳定。
- Chrome 弹窗文案/结构会变。
- 多个连接堆叠时仍会失败。
- 安全上容易掩盖真实授权边界。

### 使用独立 `--user-data-dir`

优点：

- 更少授权弹窗。
- 更符合 Chrome 136+ remote debugging 安全模型。

缺点：

- 失去员工真实 Chrome cookies、SSO、插件和证书。
- 不满足 `chrome-direct` 业务需求。

适合 `local-chrome`，不适合作为真实 `chrome-direct` 主路径。

### Chrome extension + native messaging

这是长期替代方向。公开讨论中有人建议用 MV3 extension + native messaging 替代 CDP，这可以绕开 remote debugging prompt。

优点：

- 安装时一次授权。
- 后续无需 remote debugging prompt。
- 更适合员工真实浏览器助手。

缺点：

- 需要开发扩展和 native host。
- 权限审核和分发复杂。
- 需要重新设计 action/state 协议。

可作为长期 P3，不作为当前短期方案。

## 决策

短期必须做：

- `bao daemon` / 本地长驻 runtime。
- `chrome-direct` 命令优先走 daemon。
- `authorize` 改成验证连续操作不会重复授权。

中期补强：

- 自动检测 Chrome 重启导致的授权失效。
- 弹窗出现时暂停并提示用户手动允许。
- 失败重试和 trace。

长期可研：

- Chrome extension + native messaging。
