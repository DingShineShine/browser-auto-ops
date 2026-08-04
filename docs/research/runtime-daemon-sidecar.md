# Runtime Daemon 与 ADS Sidecar 调研

## 结论

`browser-auto-ops` 需要从“每条 CLI 命令独立 attach”升级为“长驻 runtime + CLI thin client”。

这同时解决两个问题：

- `chrome-direct` 反复授权弹窗。
- network/download/trace 跨命令不持久。

并为 ADS/VPS 场景提供统一基础：

```text
Desktop Agent
  -> bao CLI
  -> local bao daemon
  -> chrome-direct live connection

Desktop Agent
  -> bao CLI
  -> VPS bao sidecar
  -> AdsPower Local API
  -> ws.puppeteer
```

参考：

- Steel Browser: https://github.com/steel-dev/steel-browser
- BrowserAct browser/session model
- Playwright remote browser/session model
- Chrome DevTools Protocol Target/Network/Browser/Storage domains

## Steel Browser 借鉴

Steel Browser 的核心价值：

- Browser session API。
- 长驻浏览器生命周期。
- 可通过 Puppeteer / Playwright / Selenium 连接。
- 内置 session 状态、cookies、localStorage。
- request logging 和调试 UI。
- 截图、PDF、scrape 等 quick actions。

适合 `browser-auto-ops` 借鉴：

- `/sessions` 管理模型。
- API server + browser runtime 分离。
- session 作为长驻对象。
- UI/trace/debug evidence。
- remote browser 以 API 形式暴露，而不是暴露裸 CDP。

## 当前问题

当前 CLI 模式：

```text
bao state
  -> create SessionManager
  -> attach stored session
  -> connect CDP
  -> execute
  -> disconnect
```

问题：

- `chrome-direct` 每条命令重连，触发授权弹窗。
- `NetworkRecorder` 每条命令重新创建，无法回看上一条命令的请求。
- download event 无法跨命令跟踪。
- trace 不包含连续 live runtime 事件。
- raw CDP target/page state 每次恢复成本高。

## 目标架构

### Local daemon

```text
bao daemon start
  -> FastAPI/IPC server
  -> SessionManager lives in process
  -> BrowserConnection stays open
```

CLI：

```text
bao --session s state
  -> call local daemon /sessions/s/state
```

### VPS sidecar

```text
bao sidecar start --ads-base-url http://127.0.0.1:50325
  -> authenticated API
  -> starts AdsPower profile
  -> connects ws.puppeteer locally
  -> returns session id to desktop
```

Desktop CLI never sees raw CDP URL unless in dev mode.

## API 设计

本地 daemon 和 VPS sidecar 使用同一 API：

```text
GET /health
GET /browsers
POST /browsers
POST /browsers/{id}/open
GET /sessions
GET /sessions/{id}/state
POST /sessions/{id}/actions
GET /sessions/{id}/network/requests
GET /sessions/{id}/downloads
POST /sessions/{id}/downloads/wait
DELETE /sessions/{id}
```

## CLI 设计

```bash
bao daemon start
bao daemon status
bao daemon stop

bao browser open local https://example.com --session task
bao --session task state
bao --session task click 3
```

默认行为：

- 如果 daemon 可用，CLI 走 daemon。
- 如果 daemon 不可用：
  - `ads` 提示需要 sidecar。
  - `chrome-direct` 提示 fallback reconnect 会触发授权弹窗。
  - 普通开发场景可允许 `--no-daemon`。

## Session 生命周期

```text
browser identity
  -> open session
  -> live BrowserConnection
  -> persistent NetworkRecorder
  -> persistent DownloadManager
  -> TraceRecorder
```

Session metadata：

```text
session_id
name
browser_id
runtime_url
provider
target_id
created_at
last_used_at
status
owner
```

## 安全设计

### Local daemon

- 默认只监听 `127.0.0.1`。
- 随机 token 写入 `.bao/daemon-token`。
- CLI 调用必须带 token。
- 不允许公网访问。

### VPS sidecar

- 必须配置 token。
- 可加 allowed IP。
- 只暴露业务 API，不暴露 CDP。
- trace 中脱敏 cookies、authorization、password、verification code。

## ADS sidecar

公开 browser type：

```text
ads
```

内部流程：

```text
POST /browsers/{ads_browser}/open
  -> AdsPower /api/v1/browser/start
  -> read data.ws.puppeteer
  -> connect locally
  -> keep BrowserConnection
```

关键原则：

- `ws.puppeteer` 不返回给员工桌面。
- 所有操作通过 sidecar API。
- sidecar 负责 network/download/trace。

## 与 BrowserAct 对齐

BrowserAct 模型：

```text
browser = persistent identity
session = task workspace
browser open = creates live runtime
state/click/input = reuse runtime
```

`bao` 应对齐：

```text
bao browser open = opens daemon-side session
bao --session s state = daemon operation
```

## 实施优先级

### P0

- 本地 daemon health/status。
- CLI 调用 daemon。
- `chrome-direct` live connection 不断开。

### P1

- NetworkRecorder 持久化。
- DownloadManager 持久化。
- Session trace 持续写入。

### P2

- VPS ADS sidecar token 鉴权。
- Desktop CLI remote runtime 配置。

### P3

- sidecar UI / trace viewer。
- session cleanup policy。

## 决策

必须实现 daemon。

否则：

- Chrome 授权弹窗无法根治。
- network/download 跨命令证据无法可靠追踪。
- 与 BrowserAct session 模型无法对齐。

`provider.connect` fallback 可以保留，但必须降级为诊断模式。
