# BrowserAct 对齐实施路线图

## 总体决策

调研后，优先级需要调整：

1. 先做 `bao daemon`，解决 `chrome-direct` 每条命令重连和反复授权弹窗。
2. 再做 `StateSnapshot v2`，重点补 Element UI checkbox/modal/popover。
3. 再做 `DownloadManager`，解决卖家精灵异步导出到本地文件的闭环。
4. 最后做 `Planner v2` 和 ADS sidecar 企业化。

原因：

- 没有 daemon，授权弹窗、network、download 都无法稳定。
- 没有 StateSnapshot v2，Agent 无法理解真实可操作控件。
- 没有 DownloadManager，导出任务无法形成企业办公闭环。
- LLM planner 必须建立在可靠 state 和 action runtime 上。

## Batch 1：Local daemon / 长驻 runtime

目标：

- `chrome-direct` 操作不再每步弹授权。
- network/download/trace 跨命令持久。

任务：

- 已增加 `bao daemon start/status/stop`。
- CLI 已优先调用本地 daemon。
- `browser open` 创建 live session。
- `state/click/input/eval/network` 通过 daemon 执行。
- fallback reconnect 仅作为诊断模式。

验证：

- 连续执行 `state -> click -> state -> eval` 不重复弹授权。
- NetworkRecorder 能看到上一条 action 产生的请求。

## Batch 2：StateSnapshot v2

目标：

- 对齐 BrowserAct state 表达。
- 支持 Element UI tree checkbox 和 modal。

任务：

- 已引入 role/aria/checked/selected/expanded。
- 已增加 Element UI 组件规则。
- 已实现 modal/dialog 优先输出。
- viewport priority。
- stable ref `@eN`。
- 缩进树输出。
- 已为 Element UI checkbox/dialog button 提供 action target，配合 executor 使用。

验证：

- 卖家精灵类目弹窗中，checkbox 可直接通过 state index/ref 点击。
- 导出弹窗中，`前往查看` 按钮可直接点击。

## Batch 3：DownloadManager

目标：

- 卖家精灵导出任务能落地为本地 xlsx 文件。

任务：

- 已记录 download records。
- 已增加 `downloads list/wait/save`。
- 已对卖家精灵 `/v2/export-log` 做通用轮询。
- 已支持从 href 下载。
- 已返回本地文件路径，后续统一为绝对路径。

验证：

- 创建卖家精灵导出任务。
- 等待第一条匹配任务完成。
- 保存 `.xlsx` 到 `.bao/downloads/{session_id}` 或指定目录。

## Batch 4：Planner v2

目标：

- 从启发式 act 升级为结构化 planner。

任务：

- `PlannerInput`。
- `ActionPlan`。
- safety validator。
- read-only / mutation eval 分级。
- replay/action cache。
- 卖家精灵 workflow template。

验证：

- LLM 只输出 schema，不直接操作浏览器。
- 卖家精灵 workflow 可 replay。

## Batch 5：ADS sidecar

目标：

- ADS/CDP 留在 VPS 内部。
- 桌面 CLI 不暴露裸 CDP。

任务：

- sidecar token。
- browser identity 企业字段。
- remote runtime URL。
- trace/network/download evidence。
- session cleanup。

验证：

- 桌面通过 sidecar 控制 AdsPower profile。
- `ws.puppeteer` 不返回到桌面。

## 暂缓项

- stealth browser。
- captcha solver。
- hosted remote assist。
- 完整 profile import。
- vision-first workflow。

## 成功标准

- `chrome-direct` 不再每条命令弹授权。
- `bao state` 能表达 BrowserAct 已能表达的卖家精灵关键控件。
- `bao` 能完成卖家精灵导出并返回本地 xlsx 文件路径。
- Agent 不需要 JS hack 就能完成类目选择和导出弹窗处理。
- ADS sidecar 不暴露裸 CDP。
