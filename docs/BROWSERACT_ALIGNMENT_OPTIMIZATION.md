# BrowserAct 对齐优化文档

## 背景

`browser-auto-ops` 的目标不是复刻 BrowserAct 的内部实现，而是提供一个适合企业自动化办公的 BrowserAct-style 浏览器运行时。

对员工和桌面 Agent 来说，它应该像 BrowserAct 一样简单：

```bash
bao get-skills core
bao browser list
bao --session task browser open <browser> <url>
bao --session task state
bao --session task click 3
```

对企业场景来说，它必须比 BrowserAct 更贴合业务：

- 支持员工本机 Chrome：`chrome-direct`
- 支持 VPS/ADS/AdsPower 浏览器：`ads`
- 支持企业账号、权限、安全确认、审计和 trace
- 不暴露裸 CDP 端口

## 当前定位

公开 browser 类型只保留两类：

- `chrome-direct`：控制员工当前本机 Chrome，适合需要本机登录态、插件、证书、SSO、已有 Cookie 的任务。
- `ads`：控制公司在 VPS 上运行的 ADS/AdsPower profile，适合多账号、固定环境、外贸平台运营场景。

内部可以继续保留低层 provider/helper，例如 `adspower-cdp`、generic `cdp`、raw CDP transport，但不应该暴露给员工或桌面 Agent 作为选择项。

## 与 BrowserAct 的主要差距

### 1. Command Surface

BrowserAct 的命令面更完整，包含：

- browser/session 管理
- tabs
- cookies
- dialogs
- HAR/network
- profile import
- captcha
- remote assist
- stealth extract
- runtime `get-skills`

`browser-auto-ops` 已经具备核心闭环：

- `browser create/list/open`
- named `--session`
- `state`
- `click/input/select/hover/keys/scroll`
- `screenshot`
- `eval`
- `get title/html/text/value/markdown`
- `network requests/request/clear`
- `get-skills core`

下一步优先补齐：

```bash
bao --session s tab list
bao --session s tab switch <tab_id>
bao --session s tab close <tab_id>

bao --session s cookies get
bao --session s cookies export cookies.json
bao --session s cookies import cookies.json
bao --session s cookies clear

bao --session s dialog status
bao --session s dialog accept
bao --session s dialog dismiss

bao --session s wait selector <index> --state visible
bao --session s wait selector --selector ".btn" --state visible

bao --session s network har start
bao --session s network har stop trace.har
```

不建议当前阶段投入：

- stealth browser
- captcha solver
- BrowserAct-style hosted remote assist
- 完整 profile import

这些能力对企业 ADS/browser sidecar 不是第一优先级。

### 2. Agent 指令层

BrowserAct 的一个关键优势是：Agent 不靠记忆，而是通过 CLI 动态加载运行时说明：

```bash
browser-act get-skills core
```

`browser-auto-ops` 已经增加：

```bash
bao get-skills core
bao get-skills enterprise
```

后续应该继续拆分：

```bash
bao get-skills chrome-direct
bao get-skills ads
bao get-skills safety
```

`get-skills` 应该动态输出当前安装版本真正支持的命令，不要让 Agent 猜测 BrowserAct 命令是否存在。

建议 `get-skills` 输出包含：

- 当前支持的 browser 类型
- 当前支持的命令
- 不支持的 BrowserAct 命令
- ADS/VPS 使用方式
- chrome-direct 授权弹窗处理方式
- JS eval 安全边界
- 敏感操作确认规则

### 3. Browser Identity 模型

BrowserAct 的模型是：

```text
browser = 身份
session = 当前任务工作区
```

`browser-auto-ops` 应保持这个模型，并在企业场景里扩展 browser identity：

```text
browser_id
type: chrome-direct | ads
name
desc
owner
department
account_label
platform
allowed_domains
confirm_before_use
sensitive_actions
audit_enabled
```

Agent 应该根据业务语义选 browser，而不是根据 provider 选 browser。

示例：

```bash
bao browser create \
  --type ads \
  --name amazon-us-01 \
  --desc "美国亚马逊运营账号，用于关键词调研和竞品分析"

bao --session keyword-research browser open amazon-us-01 https://example.com
```

## AI 执行流程优化

### 当前实现

当前 `observe/act` 是启发式逻辑：

1. `state` 生成页面元素列表。
2. `ObserveService` 根据 goal 分词，匹配元素的 kind、role、text、placeholder、attributes。
3. `ActService` 选择最高分元素。
4. 根据元素类型猜测 `click`、`input_text`、`select_option`。
5. `ActionExecutor` 用真实鼠标/键盘优先执行，失败后 JS fallback。
6. `SessionManager` 做 URL/title/target/page_count verification。

优点：

- 简单
- 可控
- 便宜
- 不依赖外部 LLM
- 适合明确目标的小动作

缺点：

- 语义理解弱
- 无法稳定处理复杂页面
- 不会多步骤规划
- 对相似元素容易误判
- 不能解释复杂意图

### 推荐升级方向

借鉴 Stagehand 的 API 形态，但保持执行层确定性：

```text
state
  -> candidate generation
  -> LLM planner
  -> action JSON schema
  -> safety validator
  -> deterministic executor
  -> verification
  -> next state
```

LLM 只负责选择动作，不直接控制浏览器。

推荐结构化输出：

```json
{
  "reason": "搜索框 placeholder 与任务目标匹配",
  "actions": [
    {
      "type": "input_text",
      "index": 30,
      "text": "bluetooth speaker"
    },
    {
      "type": "click",
      "index": 31
    }
  ]
}
```

安全规则：

- LLM 不能直接执行 JS。
- LLM 输出必须通过 Pydantic schema 校验。
- 动作必须在 allowlist 内。
- 危险操作必须 `--confirm`。
- 每一步都要重新读取 state。
- 每一步都要记录 trace 和 verification。

## State Scanner 优化

### 当前实现

当前 state scanner 主要基于 DOM：

- tag
- role
- aria-label
- label
- placeholder
- text
- rect
- xpath
- clickable/fillable/selectable/scrollable

### 差距

还缺少：

- Accessibility Tree
- DOMSnapshot
- 遮挡检测
- paint order
- 跨域 iframe 更强处理
- state diff
- 稳定 selector
- 元素变化标记

### 推荐实现

补充 CDP 能力：

```text
Accessibility.getFullAXTree
DOMSnapshot.captureSnapshot
Runtime.evaluate(document.elementFromPoint)
Page.getFrameTree
DOM.describeNode
```

目标输出：

```text
url=https://example.com
title=Example

[1] input "Search products"
*[2] button "Search"
[3] link "Orders"
```

其中 `*[N]` 表示新出现或发生变化的元素，方便 Agent 判断动作是否产生效果。

## raw CDP 优化

### 当前问题

`chrome-direct` 目前使用 raw CDP transport，并模拟了一小部分 Playwright Page API。

当前能力覆盖：

- Runtime.evaluate
- Page.navigate
- Page.captureScreenshot
- Input.dispatchMouseEvent
- Input.dispatchKeyEvent
- Target.getTargets
- Target.attachToTarget
- Target.activateTarget

缺口：

- tabs 不完整
- cookies/storage 不完整
- dialogs 不完整
- network events 不完整
- file upload 不支持
- Accessibility/DOMSnapshot 未接入

### 推荐方向

定义统一 Page Adapter：

```text
PageAdapter
  navigate
  evaluate
  screenshot
  mouse
  keyboard
  targets
  network
  cookies
  dialogs
  accessibility
```

实现两套 adapter：

- `PlaywrightPageAdapter`：用于 `ads`，优先完整能力。
- `RawCdpPageAdapter`：用于 `chrome-direct`，逐步补齐 CDP domain。

不要把 raw CDP 扩成完整 Playwright；只补企业自动化必需能力。

## JS Eval 策略

BrowserAct 支持让 Agent 写 JS：

```bash
browser-act --session s eval <js> [--stdin]
```

`browser-auto-ops` 也应该保留并强化：

```bash
bao --session s eval "document.title"
```

JS 使用分级：

### 推荐：只读 JS

用于：

- 提取表格
- 提取链接
- 分析 DOM
- 读取页面状态
- 读取前端变量

### 谨慎：辅助定位 JS

用于：

- 判断某个 selector 是否存在
- 计算某个元素是否可见
- 找到复杂组件里的真实 input

### 严控：写入/执行动作 JS

例如：

- `element.click()`
- 修改表单值
- 调用 mutation API
- `fetch('/api/delete')`
- 提交表单

这些必须：

- 要求 `--confirm`
- 写入 trace
- 经过危险关键词检查
- 尽量要求 Agent 先解释原因

推荐 `get-skills core` 明确指令：

```text
优先使用 state/click/input/select。
其次使用 get/extract。
只读 eval 可以使用。
会修改页面、提交数据、调用 mutation API 的 eval 必须确认。
```

## chrome-direct 授权弹窗优化

当前问题：

控制真实本机 Chrome 时，Chrome 会显示远程调试授权弹窗。当前 `cdp_auto_allow_helper` 会尝试自动点击“允许”，但不稳定。

优化目标：

```bash
bao chrome-direct authorize
```

该命令专门处理首次授权。

优化点：

- 识别“要允许远程调试吗”
- 识别“允许 / 取消”
- 将弹窗置前
- 延长等待时间
- 输出诊断日志
- 失败时提示用户手动点击一次
- 授权成功后记录状态

`get-skills chrome-direct` 应提示：

```text
如果出现 Chrome 远程调试授权弹窗，等待用户点击允许，不要继续发送动作。
```

## ADS/VPS 架构优化

目标：

员工桌面 Agent 不直接连接裸 CDP。

推荐生产架构：

```text
Desktop Agent
  -> bao CLI
  -> enterprise API / VPS sidecar
  -> AdsPower Local API
  -> ws.puppeteer
  -> browser operation
```

原则：

- CDP 只在 VPS 内部访问
- 桌面只调用认证 API
- 所有动作写入 trace
- 敏感操作需要确认
- 按账号/部门/平台隔离 browser identity

后续可增加：

- sidecar token 鉴权
- allowed domains
- account ownership
- audit log
- screenshot evidence
- network evidence

## 开源项目借鉴关系

### BrowserAct

借鉴：

- skill + CLI 产品形态
- `get-skills`
- browser/session 模型
- indexed state/action loop
- `chrome-direct` 思路
- `eval` fallback

不直接复制：

- stealth hosted browser
- captcha solver
- remote assist 服务
- 内部实现细节

### Browser Use

借鉴：

- DOM service
- 可交互元素检测
- indexed element tree
- Agent 友好 state

适合用于：

- state scanner 升级
- selector 质量提升
- iframe/shadow DOM 处理

### Stagehand

借鉴：

- `observe`
- `act`
- `extract`
- LLM + schema 的交互模型

适合用于：

- 从启发式 act 升级到 LLM planner
- schema-based extract
- action candidate reasoning

### Skyvern

借鉴：

- workflow/action trace
- screenshot evidence
- step verification
- failure debugging

适合用于：

- 企业审计
- 可回放流程
- 任务失败分析

### Steel Browser / Browserbase 类项目

借鉴：

- remote browser session
- browser lifecycle
- server-side browser runtime

适合用于：

- VPS sidecar
- ADS remote browser 管理
- 多账号隔离

### Playwright/CDP

作为执行底座：

- tabs
- cookies
- dialogs
- HAR
- network
- selectors
- screenshot
- file upload
- frame handling

原则：

能用 Playwright 就优先用 Playwright。只有真实本地 Chrome `chrome-direct` 场景，才使用 raw CDP。

## 优先级路线图

### P0：稳定 chrome-direct

- 已增加 `bao chrome-direct authorize`
- 增强 `cdp_auto_allow_helper`
- 增加授权失败诊断
- 明确弹窗处理指南

### P1：补齐基础 BrowserAct 命令

- 已注册 tabs 命令
- 已注册 cookies 命令
- 已注册 dialogs 命令，当前明确返回边界状态
- 已增加 wait selector
- 已注册 HAR start/stop，当前明确返回边界状态
- network clear/filter/status/method

### P1.5：ActionExecutor 可信点击

- 已为 state element 增加 action target。
- Element UI checkbox 优先点击 `.el-checkbox__inner` / checkbox action target。
- Element UI dialog footer button 优先点击 `button` 本体。
- 点击前重新计算 action target rect，减少 stale rect 问题。
- 已增加 checkbox/modal 业务 verification。
- 卖家精灵类目选择流程已验证：checkbox 可通过普通 `bao click` 选中，确认后可进入结果页。

### P2：升级 state scanner

- Accessibility Tree
- DOMSnapshot
- 遮挡检测
- state diff
- 稳定 selector

### P3：升级 AI planner

- LLM planner
- structured action schema
- candidate ranking
- action validator
- verification loop
- extract schema

### P4：ADS 企业化

- VPS sidecar
- API auth
- browser ownership
- allowed domains
- audit log
- enterprise trace evidence

## 成功标准

### Agent 使用体验

- Agent 不再误用旧 provider 命令。
- Agent 能通过 `bao get-skills core` 获取当前真实能力。
- Agent 能正确选择 `chrome-direct` 或 `ads`。
- Agent 优先使用 state/action，而不是乱写 JS。

### 浏览器操作能力

- `chrome-direct` 授权弹窗可控。
- `ads` 不暴露裸 CDP。
- tabs/cookies/dialogs/network 基础命令可用。
- state 能准确表达可交互元素。

### 企业安全

- 敏感动作需要确认。
- Cookie/token/password 被脱敏。
- 每个动作有 trace。
- ADS 账号按 browser identity 管理。
- 员工无需理解 CDP/Provider 细节。

## 结论

`browser-auto-ops` 应该对齐 BrowserAct 的 Agent 交互体验，但不要受限于 BrowserAct 的产品边界。

更合适的方向是：

```text
BrowserAct-style UX
  + Browser Use-style state scanner
  + Stagehand-style planner/extract
  + Skyvern-style trace/verification
  + Playwright/CDP executor
  + ADS/VPS enterprise browser management
```

最终目标：

```text
员工用起来像 BrowserAct；
公司管理 ADS/账号/审计能力比 BrowserAct 更强。
```
