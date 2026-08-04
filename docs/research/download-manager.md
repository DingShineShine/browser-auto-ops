# Download Manager 与异步导出调研

## 结论

`browser-auto-ops` 需要独立的 `DownloadManager`。仅靠点击页面上的下载链接无法满足企业自动化，因为下载通常是异步任务：

```text
点击导出
  -> 页面提示导出中
  -> 前往我的导出
  -> 轮询任务状态
  -> 状态已完成
  -> 获取 href
  -> 下载 xlsx
  -> 返回本地文件路径
```

卖家精灵实测证明，BrowserAct 能识别导出弹窗和“我的导出”任务，但点击下载后文件落点仍不直接明确。`bao` 应该比 BrowserAct 更企业化：明确返回下载路径。

## 卖家精灵实测链路

BrowserAct 执行成功路径：

```text
click 导出
state:
  [3] dialog 温馨提示
    数据导出中，需要1-5分钟...
    [4] button 前往查看
    [5] button 等会儿看

click 前往查看
进入 /v2/export-log
第一行任务：
  Product-Home&Kitchen-US-2026.06-98670
  状态: 导出中

等待并刷新
状态: 已完成
第一行 href:
  https://o.sellersprite.com/batch-exports/2026/8/Product-Home%26Kitchen-US-2026.06-98670.xlsx...
```

## 当前 bao 问题

- 导出 modal 没进入 state。
- “前往查看”按钮没被识别。
- network recorder 跨命令不持久。
- 没有 download event。
- 没有下载目录管理。
- 点击下载后 CLI 不返回文件路径。

## Playwright 下载机制

Playwright 支持：

```python
async with page.expect_download() as download_info:
    await page.click(selector)
download = await download_info.value
path = await download.path()
await download.save_as(target)
```

适合 `ads` / Playwright-backed sessions。

## CDP 下载机制

raw CDP 可考虑：

```text
Browser.setDownloadBehavior
Page.downloadWillBegin
Page.downloadProgress
```

但 Chrome 版本和 target session 支持需要验证。

对于 `chrome-direct`，更稳的短期方案是：

- 从页面 DOM 获取下载 href。
- 用当前浏览器 cookies/auth headers 发起下载。
- 或导航到 href 并观察文件系统。

## DownloadManager 设计

### 数据结构

```text
DownloadRecord
  download_id
  session_id
  browser_id
  source_url
  suggested_filename
  final_path
  status: pending | running | completed | failed
  started_at
  finished_at
  error
```

### CLI

```bash
bao --session s downloads list
bao --session s downloads wait latest --timeout 300000
bao --session s downloads open latest
bao --session s downloads save latest --output D:\exports
```

### API

```text
GET /sessions/{id}/downloads
POST /sessions/{id}/downloads/wait
POST /sessions/{id}/downloads/{download_id}/save
```

## 卖家精灵专项命令

可以先做站点专项 workflow：

```bash
bao --session s seller-sprite export-product-research \
  --market US \
  --month 2026-06 \
  --node-id 3732831 \
  --output D:\exports
```

内部流程：

```text
navigate product research
select month
select category
start filter
click export
click go to export
poll export log first matching task
download href
save local path
```

## 下载路径策略

建议统一下载到：

```text
.bao/downloads/{session_id}/
```

并支持：

```text
BAO_DOWNLOAD_DIR
--output
```

企业场景可配置：

```text
D:\company-exports\{browser_name}\{date}\
```

## 轮询策略

对于卖家精灵：

1. 点击导出。
2. 从 modal 点击“前往查看”。
3. 在 `/v2/export-log` 中找第一行或按名称匹配：
   - `Product-Home&Kitchen-US-2026.06`
   - 创建时间接近当前任务时间。
4. 如果状态为 `导出中`，点击刷新或等待。
5. 如果状态为 `已完成`，读取第一行 href。
6. 下载 href。
7. 验证本地文件存在且大小大于 0。

## 风险

- 下载 href 可能带临时 token。
- 点击下载可能依赖浏览器 cookies。
- Shell 直接下载可能缺少 Cookie。
- BrowserAct/Chrome 下载目录可能不是系统 Downloads。
- 企业环境可能拦截跨域下载。

## 决策

短期：

- 实现 DOM href 提取。
- 增加 `downloads wait latest`。
- 卖家精灵 workflow 通过 href 下载。

中期：

- Playwright-backed provider 用 `expect_download`。
- raw CDP provider 尝试 `Browser.setDownloadBehavior`。
- 下载记录写 trace。

长期：

- 下载队列。
- 文件校验。
- 企业导出目录。
- 自动发送到内部系统或飞书/网盘。
