# BrowserAct 与 bao 行为对标报告

## 场景

测试网站：卖家精灵。

任务：

1. 打开产品调研页。
2. 选择亚马逊、美国站、2026-06。
3. 选择类目 `3732831`。
4. 开始筛选。
5. 导出数据。
6. 前往“我的导出”等待任务完成。
7. 下载 Excel。

## BrowserAct 实测结果

重启电脑后，BrowserAct `chrome-direct` 可以成功打开本机 Chrome 并复用登录态。

关键流程成功：

- 登录态恢复成功。
- 产品调研页 state 正常。
- 类目弹窗 state 正常。
- 输入 `3732831` 后，候选类目被正确表达。
- checkbox 可以通过 index 直接点击。
- 确认选择后，主页面显示 `4 级 | Pillowcases (枕头套)`。
- 点击开始筛选后，结果页出现 `导出`。
- 点击导出后，modal 被正确识别。
- 点击“前往查看”成功进入“我的导出”。
- 导出任务从“导出中”刷新到“已完成”。
- 第一行出现 `.xlsx` 下载链接。

## BrowserAct state 优势

### 1. Element UI tree checkbox

BrowserAct 在类目弹窗初始 state 中表达为：

```text
[8] div class=el-dialog__wrapper
  [11] input placeholder=请输入Node ID/类目关键词，如281407/Electronics
  [17] div role=treeitem selected=false
    [20] label class=el-checkbox
```

输入 `3732831` 后表达为：

```text
[17] div role=treeitem level=1 selected=false
  [20] label class=el-checkbox
  [22] span class=label
    Home & Kitchen>Bedding>Sheets & Pillowcases>Pillowcases
```

点击 `[20]` 后表达为：

```text
[16] div role=treeitem aria-checked=true level=1 checked=true
  [19] label class=el-checkbox is-checked
已选 (1)
[31] button 确认选择
```

这让 Agent 能自然推断：

```text
输入类目 ID -> 点击 checkbox label -> 确认选择
```

### 2. modal/dialog

点击导出后，BrowserAct 能识别导出提示：

```text
[3] div class=el-dialog__wrapper yun-box
  温馨提示
  数据导出中，需要1-5分钟...
  请稍后在“个人中心-我的导出”中下载
  [4] button 前往查看
  [5] button 等会儿看
```

这让 Agent 能自然执行：

```text
click 4 -> 进入我的导出
```

### 3. 视口优先 state

BrowserAct 的 state 会随着滚动聚焦当前视口。例如滚动到筛选区后，state 重新编号并只输出当前可见关键区域：

```text
[38] div class=category-wrap
  4 级 | Pillowcases (枕头套)
[40] button 开始筛选
```

这比 `bao` 当前一次性输出大量 DOM 更适合 Agent。

### 4. 下载链接识别

BrowserAct 进入“我的导出”后，表格 state 能显示导出任务状态。

DOM 检查显示第一行完成任务有链接：

```text
Product-Home&Kitchen-US-2026.06-98670
status=已完成
href=https://o.sellersprite.com/batch-exports/2026/8/Product-Home%26Kitchen-US-2026.06-98670.xlsx...
```

下载落点仍需进一步确认，但 BrowserAct 至少能稳定识别任务和链接。

## bao 当前问题

### 1. 类目 checkbox 未暴露

`bao state` 搜索 `3732831` 后只看到：

```text
[271] scrollable "Home & Kitchen>Bedding>Sheets & Pillowcases>Pillowcases..."
[272] div "Home & Kitchen>Bedding>Sheets & Pillowcases>Pillowcases..."
[283] button "确认选择"
```

但没有暴露：

```text
label.el-checkbox
input.el-checkbox__original
span.el-checkbox__inner
role=treeitem
aria-checked
```

导致普通 click 只让 tree item 变成 current，没有选中 checkbox。最终只能用 JS：

```javascript
document.querySelector('.el-tree-node.is-current .el-checkbox__inner').click()
```

### 2. modal 未识别

点击导出后页面出现了：

```text
温馨提示
数据导出中，需要1-5分钟...
请稍后在“个人中心-我的导出”中下载
前往查看
等会儿看
```

但 `bao state` 没把这个 modal 识别成可操作元素，导致无法自然点击“前往查看”。

### 3. state 输出过大

`bao state --json` 在卖家精灵结果页输出数万行，且不聚焦视口。

Agent 需要在大量重复元素中搜索，容易误选。

### 4. network recorder 不持久

`bao network requests` 在导出后查不到刚刚发生的请求，因为每个 CLI 命令重新 attach 并创建新的 `NetworkRecorder`。

### 5. eval 包装问题

raw CDP `eval` 对 `(() => {})()` 或箭头函数会二次包装，出现：

```text
TypeError: JSON.stringify(...) is not a function
```

这影响 Agent 在复杂页面使用 JS fallback。

## 具体改进清单

### State scanner

必须新增：

- `role=treeitem`
- `aria-checked`
- `checked`
- `label.el-checkbox`
- `input[type=checkbox]`
- `span.el-checkbox__inner`
- modal/dialog wrapper
- toast/message box
- visible viewport prioritization

### Element UI 专项规则

识别：

```text
.el-dialog__wrapper
.el-message-box__wrapper
.el-tree-node
.el-tree-node__content
.el-checkbox
.el-checkbox__input
.el-checkbox__inner
.el-popover
.el-select-dropdown
```

### Output format

改成 BrowserAct-style 缩进树：

```text
[8] div class=el-dialog__wrapper
  [11] input "请输入Node ID..."
  [17] div role=treeitem selected=false
    [20] label class=el-checkbox
      Home & Kitchen...
```

保留数字 index，但同时增加稳定 ref：

```text
[20] @e20 label class=el-checkbox
```

### Dialog handling

`bao state` 必须优先输出 modal 内元素，尤其是：

- 标题
- 正文
- primary button
- secondary button

### Download handling

需要：

- 识别完成任务第一行链接。
- 提供 `bao --session s downloads wait latest`。
- 返回文件路径或下载 URL。

## 结论

BrowserAct 在卖家精灵流程中比 `bao` 稳定，核心不是 AI 更聪明，而是 state 表达更贴近真实可操作结构：

- tree checkbox 可点击。
- modal button 可点击。
- 视口 state 更干净。
- role/class/aria 信息更完整。

`bao` 下一步最重要的是 StateSnapshot v2，而不是先做更强的 LLM planner。
