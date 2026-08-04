# State Scanner v2 调研

## 结论

`bao` 当前 DOM scanner 不足以支撑复杂企业网页。卖家精灵流程证明：Element UI tree checkbox、modal、popover、toast、下载链接等关键控件如果没有被正确表达，Agent 会误判流程。

建议采用 `StateSnapshot v2`：

```text
Accessibility Tree
  + DOM Snapshot
  + Runtime State
  -> merged element graph
  -> viewport-prioritized indexed state
```

这与 BrowsePilot 的 three-tree merge 思路一致，也吸收 Agent Browser 的 element ref 和 BrowserAct 的缩进树输出。

参考：

- BrowsePilot: https://github.com/lobsterman-lobster/browsepilot
- Agent Browser: https://github.com/vercel-labs/agent-browser
- Browser Use: https://github.com/browser-use/browser-use
- Chrome DevTools Protocol Accessibility / DOMSnapshot

## 开源项目借鉴

### BrowsePilot

公开介绍强调 three-tree merge：

- Accessibility tree：语义角色、名称、值。
- DOM snapshot：可见性、bounding boxes、paint order、computed styles。
- Runtime evaluation：scroll position、shadow DOM、scrollable containers、page type。

适合 `bao` 借鉴：

- 三树合并模型。
- annotated screenshot / bounding boxes。
- `browser_snapshot` 作为 Agent 输入。
- `browser_force_click` 作为 JS fallback 明确命令，而不是隐式 fallback。

### Agent Browser

公开信息显示它使用 accessibility snapshot 和稳定 element refs，例如：

```text
agent-browser snapshot
agent-browser click @e2
agent-browser fill @e3 "text"
```

适合 `bao` 借鉴：

- 稳定 ref：`@e1`、`@e2`。
- interactive-only snapshot。
- CDP auto-connect。
- annotated screenshot。
- 对 accessibility tree 做紧凑表达。

### Browser Use

Browser Use 的价值在于：

- DOM service。
- interactive elements extraction。
- 面向 LLM 的页面状态压缩。
- 自动化循环中每步重新 observe。

适合 `bao` 借鉴：

- DOM 结构与可交互元素筛选。
- 对 iframe/shadow DOM 的遍历策略。
- 元素历史和变化跟踪。

### BrowserAct

实测证明 BrowserAct state 有这些优势：

- 保留 role、class、aria、checked。
- 以缩进树表达父子关系。
- 视口优先，滚动后 state 聚焦当前区域。
- modal/dialog 会被放进 state。
- Element UI checkbox label 能直接点击。

## `StateSnapshot v2` 数据模型

建议扩展 `StateElement`：

```text
index: int
ref: string
kind: string
tag: string
role: string
name: string
text: string
value: string
checked: bool | null
selected: bool | null
expanded: bool | null
disabled: bool
visible: bool
occluded: bool
modal: bool
frame_id: string
frame_url: string
parent_ref: string | null
children_refs: list[string]
locators:
  - css
  - xpath
  - role/name
  - data-testid
rect:
  x, y, width, height
source:
  dom
  ax
  runtime
```

## 三树合并策略

### 1. DOM tree

来源：

- `document.querySelectorAll`
- shadow DOM traversal
- same-origin iframe traversal

负责：

- tag
- class
- attributes
- value
- CSS selector
- XPath
- rect
- visibility
- component-specific rules

### 2. Accessibility tree

来源：

- CDP `Accessibility.getFullAXTree`

负责：

- role
- accessible name
- checked
- selected
- expanded
- focused
- disabled

### 3. Runtime state

来源：

- `document.elementFromPoint`
- scroll position
- active element
- modal visibility
- popover visibility
- framework component classes

负责：

- occlusion
- viewport priority
- currently active modal
- active popover
- scrollable containers

## Element UI 专项规则

卖家精灵基于 Element UI/Vue，必须内置识别规则：

```text
.el-dialog__wrapper
.el-message-box__wrapper
.el-popover
.el-tree-node
.el-tree-node__content
.el-checkbox
.el-checkbox__input
.el-checkbox__inner
.el-checkbox__original
.el-select
.el-select-dropdown
.el-input
.el-button
```

### tree checkbox

如果 DOM 中出现：

```html
<div role=\"treeitem\" class=\"el-tree-node\">
  <label class=\"el-checkbox\">
    <span class=\"el-checkbox__input\">
      <span class=\"el-checkbox__inner\"></span>
      <input type=\"checkbox\" class=\"el-checkbox__original\">
```

state 必须输出：

```text
[20] @e20 checkbox "Home & Kitchen...Pillowcases" checked=false
```

点击动作应优先落到：

```text
.el-checkbox__inner
```

而不是 tree node 文本区域。

### modal

如果有 visible `.el-dialog__wrapper` 或 `.el-message-box__wrapper`，state 应优先输出 modal：

```text
[3] @e3 dialog "温馨提示"
  数据导出中，需要1-5分钟...
  [4] @e4 button "前往查看"
  [5] @e5 button "等会儿看"
```

### popover

只输出 visible popover：

```text
visible = offsetWidth || offsetHeight || getClientRects().length
```

隐藏 popover 不应污染 state。

## 输出格式

建议采用 BrowserAct-style 缩进树：

```text
url=https://example.com
title=Example

|SCROLL|<html /> (0.0 pages above, 1.0 pages below)
  [1] @e1 button "导出"
  [2] @e2 dialog "温馨提示"
    [3] @e3 button "前往查看"
```

保留兼容模式：

```text
[1] button "导出"
```

新增 JSON mode：

```json
{
  "ref": "@e1",
  "index": 1,
  "role": "button",
  "name": "导出",
  "source": ["dom", "ax", "runtime"]
}
```

## Viewport priority

当前 `bao state` 输出过大。建议：

1. 优先 active modal。
2. 其次 viewport 内 interactive elements。
3. 其次 viewport 附近 scrollable containers。
4. 最后输出摘要，例如“还有 9.7 pages below”。

CLI 增加：

```bash
bao --session s state
bao --session s state --full
bao --session s state --json
bao --session s state --mode modal
```

## 验证用例

必须覆盖：

- Element UI tree checkbox。
- Element UI dialog。
- Element UI popover。
- Shadow DOM。
- iframe。
- occluded element。
- viewport-only output。
- state diff marker。

卖家精灵专项 smoke test：

```text
打开类目弹窗
输入 3732831
state 应出现 checkbox/ref/checked=false
点击 checkbox
state 应出现 checked=true 和 已选(1)
点击确认
state 应出现 category-wrap: Pillowcases
点击导出
state 应出现 dialog: 温馨提示 + 前往查看
```

## 决策

短期：

- 增加 Element UI 专项识别。
- modal 优先输出。
- checkbox 输出为独立可点击元素。
- 修复 state 过大问题。

中期：

- 引入 AX tree。
- 引入 DOMSnapshot。
- 引入 stable ref。

长期：

- annotated screenshot。
- vision fallback。
- framework-specific plugin registry。
