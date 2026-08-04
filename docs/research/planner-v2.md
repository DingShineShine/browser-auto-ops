# Planner v2 调研

## 结论

`browser-auto-ops` 不应直接走 Browser Use 的完全自主循环，也不应做 Skyvern 式视觉优先平台。更适合企业自动化办公的路线是 Stagehand-style：

```text
deterministic workflow
  + LLM observe/act/extract 局部增强
  + schema validation
  + safety validator
  + trace / verification
```

原因：

- 企业任务要可复现、可审计、可调试。
- 员工浏览器和 ADS 账号涉及敏感数据。
- 业务流程通常是半固定的，例如卖家精灵导出、后台报表、订单处理。
- LLM 应辅助定位和解释，不应直接无约束驾驶浏览器。

参考：

- Stagehand: https://github.com/browserbase/stagehand
- Browser Use: https://github.com/browser-use/browser-use
- Skyvern: https://github.com/Skyvern-AI/skyvern

## 三类方案对比

### Stagehand-style

特征：

- 开发者控制主流程。
- AI 只在 `observe`、`act`、`extract` 中介入。
- 可回退到 deterministic Playwright/CDP。
- 可用 schema 约束输出。
- 适合生产自动化。

适合 `browser-auto-ops`。

### Browser Use-style

特征：

- 给一个任务目标，让 agent 自己循环 observe/plan/act。
- 适合探索性任务。
- 快速验证，但可重复性较弱。
- 每步需要 LLM，成本和不确定性更高。

适合做可选高级模式，不适合默认企业流程。

### Skyvern-style

特征：

- 视觉优先，适合复杂表单、布局变化、低代码 workflow。
- 更能抗 DOM 变化。
- 成本更高，系统更重。
- AGPL/平台形态需要注意合规。

适合未来做视觉 fallback，不适合当前核心实现。

## Planner v2 架构

```text
state snapshot
  -> candidate generation
  -> planner
  -> ActionPlan JSON
  -> schema validation
  -> safety validator
  -> deterministic executor
  -> verification
  -> trace
```

## 数据结构

### PlannerInput

```text
goal
page url/title
state elements
active modal
recent action history
allowed actions
safety policy
```

### ActionPlan

```json
{
  "goal": "选择类目 3732831 并导出数据",
  "reason": "类目弹窗中有匹配的 checkbox，需先勾选再确认",
  "actions": [
    {
      "type": "input_text",
      "ref": "@e11",
      "text": "3732831",
      "reason": "输入类目 ID"
    },
    {
      "type": "keypress",
      "key": "Enter",
      "reason": "触发搜索"
    },
    {
      "type": "click",
      "ref": "@e20",
      "reason": "勾选类目 checkbox"
    }
  ]
}
```

### PlannerResult

```text
planner: heuristic | llm | replay
plan: ActionPlan
confidence
warnings
requires_confirmation
```

## 执行规则

LLM 不能直接操作浏览器。LLM 只能输出结构化计划。

允许动作：

- click
- input_text
- select_option
- keypress
- scroll
- wait
- get
- eval_readonly

受限动作：

- eval_mutation
- upload_file
- form_submit
- payment
- delete
- publish
- account change
- API mutation

受限动作必须：

- 明确用户确认。
- 写入 trace。
- 记录前后 state。
- 记录 verification。

## JS eval 分级

### 只读 eval

允许用于：

- 读取 DOM。
- 读取表格。
- 读取链接。
- 检查元素状态。
- 提取下载 href。

### 辅助定位 eval

允许用于：

- 找 Element UI checkbox inner。
- 找 active modal。
- 找当前 visible popover。

### 写入型 eval

默认禁止。需要 `--confirm`。

例子：

```javascript
document.querySelector('.el-checkbox__inner').click()
fetch('/api/delete')
form.submit()
```

## Replay / action cache

卖家精灵这类稳定流程应支持 replay：

```text
open product research
click month 2026-06
open category dialog
input category id
click checkbox
confirm
start filter
click export
click go to export
wait latest download
```

每步应存储：

- state selector/ref
- action
- verification rule
- fallback JS
- screenshot evidence

下一次执行时优先 replay，失败再调用 planner。

## Heuristic fallback

当前 `ActService` 可以保留作为 fallback，但只用于简单动作：

- find search input
- click obvious button
- select obvious option

复杂任务必须使用 planner 或 workflow。

## 卖家精灵专项流程建议

对卖家精灵导出任务，不建议完全让 LLM 自由规划。

建议做成 workflow template：

```text
SellerSpriteProductExportWorkflow
  input:
    marketplace
    month
    node_id
    export_type
  steps:
    navigate
    set marketplace
    set month
    select category
    filter
    export
    wait export log
    download latest
```

LLM 只负责：

- 在 state 中定位当前步骤的控件。
- 失败时解释可能原因。
- 选择 fallback。

## 决策

短期：

- 完成 `ActionPlan` schema。
- `act` 输出 planner reasoning。
- 卖家精灵流程沉淀成 workflow template。

中期：

- 接入 OpenAI-compatible planner。
- 增加 replay/action cache。
- 增加 verification rule DSL。

长期：

- 增加视觉 fallback。
- 借鉴 Skyvern 做 SOP/workflow builder。
