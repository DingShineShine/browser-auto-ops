# Forge 与首次探索质量改进计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 Agent 第一次探索少付基础设施税，并把一次成功操作固化成可参数化、可自测、可复跑的 skill，而不是通用扒页壳。

**Architecture:** 先修数据面，再按 Skill Forge / Playwright / Skyvern 的通用模型做固化。对照会话只当缺口证据，不把临场改法写进引擎。

**Tech Stack:** 现有 Python 包、`bao` CLI、daemon FastAPI、`.bao/trace` JSONL、`ForgeEngine`、pytest。

**对照来源:** 会话 `6393ae4a`（browser-act）与 `f7f3fbcb`（bao）；产物 `wayfair-po-date-export` vs `wayfair-dropship-po-export`；trace `s_7b4b3255e8` 只有 3 个事件。

---

## 背景：问题不在「会不会点页面」

Wayfair 同一条流程两边都走通了：Clear All → T-5/T-4 → Export All → 模态框 Export，页面都是 149 单。差距在：

1. **首次探索**：bao 大约 22 分钟，大量时间花在 daemon 404、`--help`、翻仓库；browser-act 大约 12 分钟，且有 wait/state/screenshot 和导出前 HAR。
2. **固化产物**：browser-act 产出 7 个任务脚本 + 检查点 + 活页自测 + 二次复跑成功。bao 官方 Forge 产出通用 `capability.py`，可回放步骤是 Agent 手写的；`bao forge test` 只检查文件在不在。

下载落盘不在本计划验收范围内（一期交付计划另有文件落地项）。

---

## 改进点

按「先修断点、再提高固化质量、最后补探索纪律」排序。

| ID | 优先级 | 改进点 | 这次的证据 | 目标 |
|---|---|---|---|---|
| E1 | P0 | 统一 daemon / CLI 的数据目录 | `browser create` 写当前目录 `.bao/browsers.json`，daemon 读自己启动时的目录，open 404。Agent 用手写 `POST /browsers` 绕过。 | `create` 后当前 daemon 立刻可见；`health` 返回 `data_root` |
| E2 | P0 | 探索期 trace 不断档 | `SessionManager` 已记动作，但 `s_7b4b3255e8` 只有 `connect/state/forge.explore`，`actions=[]`。`forge explore` 本地 attach，另起一份稀疏 trace。 | 一次会话的 click/input/wait/network 都在同一 `events.jsonl` |
| E3 | P0 | generate 读完整动作图，不再依赖事后 explore | 现在 generate 主要吃 last_state + 空 actions。 | `bao forge generate --session wayfair-po` 即可，explore 变成可选补 goal |
| F1 | P0 | 主产物改成回放 SKILL，不是通用提取器 | `_skill_markdown()` 是 text/tables/links/inputs 模板。 | 输出目标、前置、逐步回放、定位表、成功标准 |
| F2 | P0 | 语义定位，禁止把数字下标当稳定选择器 | bao 手写稿这点是对的；官方 generate 没做。act 工作流也残留 `click <index>`。 | 生成 `text/name/aria-label` 匹配规则；脚本按规则点 |
| F3 | P0 | `forge test` 跑检查点 | 现在是 `(SKILL.md exists) and (capability.py exists)`。 | 最低：解析 SKILL 检查点；有会话时 eval inspect 断言 URL/标题/关键控件 |
| F4 | P1 | 自动安装到 Agent 可发现目录 | `.bao/skills` 被 gitignore，Agent 必须再写 `.agents/skills`。 | generate 同时写 `.bao/skills/<name>` 和 `.agents/skills/<name>` |
| F5 | P1 | 有网络证据则生成 API 路径 | Skill Forge 规定 API-first。对照里两边都抓到 GraphQL，bao 固化丢掉了。 | 能复现则生成 API 脚本；用户要官方下载时 UI 可并列，不是「API 只能校验」 |
| F6 | P1 | 参数化 goal/trace 里的可变字面量 | Skill Forge：business variables become CLI parameters。 | 抽本次任务里的可变值。不做 T-n / 时区专模 |
| X1 | P0 | `get-skills explore` 只写已有观察命令 | BrowserAct `get-skills` 模型。 | wait/state/get title/screenshot/network requests。无 login_hint、无换点法 |
| X2 | P0 | open 回传 url + title | BrowserAct 有 `get title`。 | 不回 login_hint，不强制截图 |
| X3 | P0 | action JSON 压出已有 verification | 本仓库 `_verification_payload`。 | checkpoint = url/title/url_changed/title_changed。不附带 network |
| G1 | P1 | `get-skills forge` 写官方四步 | Skill Forge Describe → Explore → Generate → Self-test。 | 不把探索临场改法写进来 |
| G3 | P2 | 生成器不写入密钥 | 通用安全，不是站点规则。 | 密码 / cookie / user_id 不进可提交 skill |

### 明确不做

- 不把通用 `capability.py` 提取器当成自动化任务的主产物（可留作可选附件）。
- 不在本迭代做完整浏览器下载拦截修复（另跟一期「文件落地」走）。
- 不新造 BrowserAct 的 `network har` 命令；继续用已有 `bao network requests` 和 `NetworkRecorder`。
- 不把对照会话里的临场改法写成通用纪律。
- 不要求第一次探索完全零 `--help`。
- 不把密码、cookie、Ads `user_id` 明文写入仓库里的 skill。

### 脑补审计（对照会话 ≠ 产品规则）

这些曾经写进计划，现降级或删除：

- `login_hint`（Sign in / Email+Password → login_required）：猜登录页，BrowserAct 没有此分类器。open 只回 url/title。
- 每个 click 默认附带 `recent_network`：BrowserAct 用独立 network 命令。Forge 生成时再读 recorder。
- URL 变化就自动截图并当探索纪律：Skyvern `screenshot_action` 是 run 证据，不是 CLI 协议。本迭代不做。
- 「官方 UI 永远主路径，API 只能校验」：与 Skill Forge 的 API-first 相反。
- T-n / `America/New_York` / `compute-relative-dates.py` 专模：那次产物，不是通用引擎。
- 把「英文完整日期 aria」「Export vs Export All」写进定位引擎：只能当夹具例子。
- Experience Notes：只出现在那次生成模板，官方文档没有。本迭代不做。
- 「input 无效就点日历」：Wayfair 临场改法。

### 实现依据（开源 / 本仓库）

- 数据根与 named session：本仓库 bug；对齐 BrowserAct browser/session 打到同一运行时。
- 动作图进 generate：`SessionManager.action()` 已写 `action.request/result`；[Skyvern artifacts](https://www.skyvern.com/docs/developers/debugging/using-artifacts) 同一次 run 保留步骤与 HAR。
- Explore → Generate → Self-test、API-first、参数化：[BrowserAct Skill Forge](https://docs.browseract.com/agent-cli/skill-forge)。
- 语义定位：[Playwright locators](https://playwright.dev/docs/locators) `getByRole` / `getByLabel` / `getByText`；[Stagehand observe](https://docs.stagehand.dev/v3/basics/observe)。
- get-skills：本仓库已模仿 BrowserAct `get-skills`。新篇只描述已有命令。
- open 回 url/title：BrowserAct `get title`，少一次往返。
- checkpoint：本仓库 `_verification_payload`（url/title 是否变化）。
- 安装到 `.agents/skills`：Agent Skills 发现约定。
- 实现时同步改 [docs/REFERENCE_MATRIX.md](docs/REFERENCE_MATRIX.md)，不抄源码。

---

## 分期与预估

```text
Phase A  基础设施一致 + trace 不断档     2-3 天
Phase E  探索信号（收敛：title/checkpoint） 1 天
Phase B  回放 SKILL + role/name 定位     3-4 天
Phase C  真自测 + 安装到 .agents/skills  2 天
Phase D  API-first + 字面量参数化        2-3 天
```

---

## Phase A — 基础设施一致，探索不再付税

### 根因

`project_data_dir()` 默认是 `Path.cwd() / ".bao"`。daemon 用 `Popen` 拉起 uvicorn，**不传 `BAO_HOME`**，`server.py` 在 import 时 `SessionManager()` / `BrowserStore()` 各绑一份 cwd。已有 daemon 若从别的目录启动（对照里搜到过其它工程 cwd），CLI 的 `browser create` 和 daemon 的 `GET /browsers` 就是两套数据。

`forge explore` 不走 daemon，本地 `_attach` 再 `state()`，于是 workspace 里出现一份只有 3 个事件的新 trace。

### Task A1: health 暴露数据根，daemon 启动子进程继承 BAO_HOME

**Files:**
- Modify: `src/browser_auto_ops/config.py`
- Modify: `src/browser_auto_ops/cli.py`（`daemon_start`）
- Modify: `src/browser_auto_ops/server.py`（`/health`）
- Test: `tests/unit/test_config_home.py`

**做法:**

1. `project_data_dir()` 保持 `BAO_HOME` 优先；未设置时仍用 `cwd/.bao`。
2. `daemon start` 在 `Popen` 的 `env` 里写入 `BAO_HOME=<ensure_data_dirs()>`，并设置 `cwd` 为当前工作目录。
3. `/health` 返回：

```json
{"ok": true, "sessions": 1, "data_root": "E:\\code\\work\\browser-auto-ops\\.bao", "cwd": "..."}
```

4. `bao daemon status` 把 `data_root` 打出来。

**验收:** 在仓库根目录 `bao daemon start` 后，`bao daemon status` 的 `data_root` 等于该仓库 `.bao`。换目录启动的旧 daemon 能被识别为「数据根不一致」并给出重启提示（见 A2）。

### Task A2: browser create/list/delete 走 daemon

**Files:**
- Modify: `src/browser_auto_ops/cli.py`（`browser_create` / `browser_list` / `browser_delete`）
- Modify: `src/browser_auto_ops/server.py`（已有 `POST /browsers`，补齐即可）
- Test: `tests/unit/test_browser_daemon_sync.py`（可用 httpx 测 FastAPI app，或 mock `_daemon_request`）

**做法:**

- daemon 可用时：`browser create` → `POST /browsers`；`browser list` → `GET /browsers`；不要只写本地 `BrowserStore`。
- daemon 不可用时：保持写本地 store，并提示先 `bao daemon start`。
- 若 `/health.data_root` 与当前 `ensure_data_dirs()` 不一致：命令失败，提示停掉旧 daemon 后在本仓库重开。不要再让 Agent 手写 REST 注册。

**验收:** 同一仓库里 `bao browser create --type ads ...` 后，`bao browser list` 与 `GET http://127.0.0.1:8765/browsers` 看到同一条；`browser open <name>` 不再 404。

### Task A3: forge 命令使用 daemon 会话的现有 trace

**Files:**
- Modify: `src/browser_auto_ops/cli.py`（`forge_explore` / `forge_generate` / `forge_test`）
- Modify: `src/browser_auto_ops/server.py`（新增 `POST /forge/explore`、`POST /forge/generate`）
- Test: `tests/unit/test_forge_cli_session.py`

**做法:**

```bash
bao forge generate --session wayfair-po --name wayfair-dropship-po-export --goal "..."
```

- `--session` 与 `--trace` 二选一；有 session 时用该 session 的 `managed.trace.root`。
- daemon 可用时走 HTTP，保证和 click/input 写的是同一份 `events.jsonl`。
- `forge explore` 只追加 `forge.explore`（goal + 当前 state），**禁止**为此新建另一份 TraceRecorder。
- `GET /sessions/{ref}/trace` 返回 `{trace_dir, events, event_types}`，方便 Agent 自检。

**验收:** 对已有 click 的会话 generate，`evidence/trace-summary.json` 的 `actions` 非空，`event_types` 含 `action.request`。用 Wayfair 旧会话或单测夹具即可，不必真开浏览器。

### Task A4: 单测夹具 — 带动作链的假 trace

**Files:**
- Create: `tests/fixtures/forge/wayfair_like_events.jsonl`（精简，不含密码）
- Create: `tests/unit/test_forge_trace_summary.py`

夹具至少包含：

- `provider.connect`
- `state.capture`（登录页：Email / Password / Log In）
- `action.request/result`：input email、input password、click Log In
- `state.capture`（Dropship Orders：Clear All、Order From、Export All）
- `action.request/result`：click Clear All、click Order From、click 日期、click Export All、click Export
- `forge.explore`（goal）

**验收:** `_load_trace_summary` 得到 `len(actions) >= 6`，`last_state.url` 含 `orderDateFrom`。

---

## Phase E — 探索信号（只暴露已有能力）

依据：BrowserAct 把 title / screenshot / state / network 做成**独立命令**；本仓库已有 `get title`、`screenshot`、`state`、`network requests`、`_verification_payload`。本阶段只减少往返和翻 `--help`，不发明新语义。

### Task E1: `bao get-skills explore`

**Files:**
- Modify: `src/browser_auto_ops/cli.py`
- Test: `tests/unit/test_get_skills_explore.py`

只写已有命令怎么用：

1. 打开后看 url/title（open 会带回，或 `get title`）。
2. 需要看页面时用 `screenshot` / `state`，不要复用过期数字下标。
3. 需要看接口时用 `bao network requests`，不要假装有 har 子命令。
4. 把常用参数写进这篇，少翻源码。

禁止写入：login_hint、日历换点、每次 click 必须看 network。

**验收:** 文中出现上述命令名；不出现 `login_required`、日历、T-5。

### Task E2: `browser open` 回传 url + title

**Files:**
- Modify: `src/browser_auto_ops/cli.py`、`src/browser_auto_ops/server.py`
- Test: `tests/unit/test_browser_open_observe.py`

```json
{"session": {"session_id": "s_xxx"}, "url": "https://...", "title": "..."}
```

不截图、不做登录分类。

**验收:** 单测 title/url 来自页面，无 `login_hint` 字段。

### Task E3: action 输出 compact checkpoint

**Files:**
- Modify: `src/browser_auto_ops/cli.py`（`_action`）
- Test: `tests/unit/test_action_checkpoint.py`

把已有 `verification` 压成 `checkpoint: {url, title, url_changed, title_changed}`。不附带 `recent_network`。完整元素列表仍用 `bao state`。

**验收:** click 结果含 checkpoint，不含 recent_network。

---

## Phase B — 回放 SKILL 才是主产物

### Task B1: 从动作图生成定位表

**Files:**
- Create: `src/browser_auto_ops/forge/locators.py`
- Test: `tests/unit/test_forge_locators.py`

**规则（对齐 Playwright，按可访问性，不写站点特例）:**

1. 优先 `role` + accessible name（`name` / `text` / `aria-label`），对应 `getByRole`
2. 表单项用 label / placeholder，对应 `getByLabel` / `getByPlaceholder`
3. 同一 name 出现多次时，用最近的容器 role（如 `dialog`）收窄，对应 Playwright locator 限定范围
4. 禁止把数字 `index` 写进 SKILL

夹具里可以出现 Clear All / Export，那是测试数据，不是引擎分支。

输出示例：

```json
{
  "step": "clear_all",
  "match": {"kind": "button", "text": "Clear All"},
  "action": "click",
  "checkpoint": "url has no filter query"
}
```

**禁止:** 把 `index: 122` 写进 SKILL 当稳定选择器。index 只允许出现在 evidence，并标注 ephemeral。

**验收:** 夹具里的按钮按 role+name 产出匹配规则；同名按钮在 dialog 内时带容器约束；无 index。

### Task B2: 生成回放 SKILL.md

**Files:**
- Modify: `src/browser_auto_ops/forge/engine.py`（`_skill_markdown`）
- Create: `src/browser_auto_ops/forge/workflow.py`
- Test: `tests/unit/test_forge_workflow_skill.py`

生成结构对齐对照里「两边各自的优点」：

```text
---
name / description / allowed-tools / forge_trace
---
# <name>
## 目标
## 已验证环境          ← 浏览器类型、session 建议名，Ads user_id 不进 git 副本
## 前置检查            ← get-skills core；先看 title 再决定是否填凭证
## 复跑流程            ← 按动作图逐步回放
## 查找元素            ← B1 定位表
## 成功标准            ← 布尔表达式
## 安全                ← 不写密码；危险操作需确认
```

`capability.py` 降为 `scripts/extract.py` 可选附件，SKILL 里写「仅用于读页面，不用于回放」。

**验收:** 对 A4 夹具 generate 后，SKILL.md 含「Clear All」「禁止复用旧 index」「成功标准」；不含 `click 122`；不含密码。

### Task B3: 成功标准从 trace 推导

**Files:**
- Modify: `src/browser_auto_ops/forge/workflow.py`
- Test: `tests/unit/test_forge_success_criteria.py`

启发式只允许用动作图里**实际发生的变化**，不要写死业务字段名：

- 某步之后 URL 相对该步之前新增了 query 键 → `url contains <该键>`
- 某步之后 title 变了 → `title == <新 title>`
- 没有 URL/title 变化则不强造成功标准句子，可以只写「关键步骤的 checkpoint 成功」

**验收:** 夹具若 URL 新增了 query，生成标准里出现这些键；引擎源码不出现 `orderDateFrom` / `Dropship` 常量。

---

## Phase C — 自测必须失败得出来

### Task C1: 替换文件存在式 test

**Files:**
- Modify: `src/browser_auto_ops/cli.py`（`forge_test`）
- Create: `src/browser_auto_ops/forge/tester.py`
- Modify: `src/browser_auto_ops/server.py`（`POST /forge/test`）
- Test: `tests/unit/test_forge_tester.py`

`bao forge test <skill_dir>` 返回：

```json
{
  "ok": false,
  "checks": [
    {"name": "skill_md_present", "ok": true},
    {"name": "replay_steps_present", "ok": true},
    {"name": "no_ephemeral_index", "ok": true},
    {"name": "success_criteria_present", "ok": true},
    {"name": "locator_table_present", "ok": true},
    {"name": "live_inspect", "ok": false, "reason": "no session"}
  ]
}
```

静态检查不过 → `ok=false`，退出码非 0。  
`live_inspect`：若给了 `--session` 且会话还在，eval 一个最小 inspect（url/title/关键文本），不断言下载文件。

**验收:** 旧版通用 `capability.py` 壳（只有 Usage 提取命令）测试失败；B2 生成的 skill 静态检查通过。

### Task C2: generate 安装到 `.agents/skills`

**Files:**
- Create: `src/browser_auto_ops/forge/install.py`
- Modify: `src/browser_auto_ops/forge/engine.py`
- Test: `tests/unit/test_forge_install.py`

- 运行时副本：`.bao/skills/<name>/`（evidence + 完整 trace 引用）
- 可提交副本：`<cwd>/.agents/skills/<name>/SKILL.md` + 脚本；**去掉** Ads `user_id`、绝对本机路径中的用户名可保留但密码必须剔除
- SKILL front matter 写 `forge_trace` / `forge_skill`

**验收:** generate 后两个目录都有 SKILL.md；git 副本 grep 不到密码；`user_id` 只出现在 `.bao` evidence 或「已验证环境」的本机提示，不作为硬编码复跑前提（可用参数 `--ads-user-id`）。

---

## Phase D — 固化侧：API 校验、参数、Forge 纪律

### Task D1: network 证据 → 可选校验脚本

**Files:**
- Create: `src/browser_auto_ops/forge/api_scripts.py`
- Modify: `src/browser_auto_ops/forge/engine.py`
- Test: `tests/unit/test_forge_api_scripts.py`

从 trace/network（或 events 里已保存的 request）识别：

- GraphQL `operationName`
- 重复出现的 `supplierId`
- 日期类 variables

按 Skill Forge：**能复现的 API 做成路径，而不是默认降级成「校验附件」**。脚本按 `operationName` 或 URL path 命名。用户目标明确是官方文件下载时，SKILL 可以并列写 UI 导出（任务约束）。

**不做:** 手搓文件冒充官方下载；不把「UI 永远主路径」写进引擎。

**验收:** 夹具有 GraphQL 时生成 API 脚本；无 network 时不生成、不失败。引擎不写死 `OrderListExportQuery`。

### Task D2: 参数化字面量

**Files:**
- Create: `src/browser_auto_ops/forge/params.py`
- Test: `tests/unit/test_forge_params.py`

把 goal / 动作入参里重复或明显可变的字面量抽成参数（Skill Forge 的 keyword/location/limit 模型）。不要做相对日期、时区、aria 日期格式专模。

**验收:** goal 里的可变词出现在 SKILL 参数表；源码不出现 `America/New_York` 或 `from-offset` 默认业务值。

### Task D3: `bao get-skills forge` + 收紧 core

**Files:**
- Modify: `src/browser_auto_ops/cli.py`（`_skill_text` / `get_skills` 允许 `forge`）
- Modify: `docs/FORGE.md`
- Test: `tests/unit/test_get_skills_forge.py`

探索纪律已在 Phase E 的 `get-skills explore`。这里只写固化：

1. 先确认 `daemon status` 的 `data_root` 是当前仓库。
2. `bao forge generate --session <name> --goal ...`（不要事后另起 explore 当唯一证据）。
3. `bao forge test` 必须跑检查点，文件在不算通过。
4. 用生成的 `.agents/skills/<name>` 复跑，不要手写第二份 SKILL。
5. 安全：登录要 `--confirm`；密码不入库。

core 里加一句：做可复用流程时读 `bao get-skills forge`；第一次探索读 `explore`。

**验收:** `bao get-skills forge` 含上述固化步骤，不再重复探索闭环全文。

### Task D4: 本迭代不做经验记忆

Skill Forge 官方文档没有 failure-only memory 文件。对照产物里的 Experience Notes 不升格为本期任务。

---

## 回归验收

1. 本仓库 daemon 上 create/open 不再 404。
2. `get-skills explore` 只有已有命令，无 login_hint / 日历 / T-n。
3. `browser open` 含 url/title，无 login_hint。
4. click 含 checkpoint，不含 recent_network。
5. generate 产出无数字下标的回放 SKILL；成功标准不写死业务常量。
6. 有 network 证据时生成 API 路径；无则跳过。
7. forge test 旧壳失败；`.agents/skills` 有副本。

---

## 建议实现顺序（给执行会话）

```text
A1 → A2 → A4 → A3 → E1 → E2 → E3 → B1 → B2 → B3 → C1 → C2 → D3 → D2 → D1
```

每完成一个 Task：跑对应 pytest，再按该 Task 的验收看一眼生成物或 health 输出。

---

## 与一期交付计划的关系

`docs/project/PHASE_1_MVP_DELIVERY_PLAN.md` 管的是单平台报表闭环（登录、下载、人工介入、追溯）。本计划补的是底层 **「探索一次、固化复用」**：

- 第 2 周「3–5 张报表自动化」不应每张都从零探索；应走 Forge 固化后复跑。
- 第 3 周「执行追溯」依赖同一套不断档的 trace（本计划 A3）。
- 文件落地、验证码人工介入仍按一期计划，不在本文件展开。

---

## 参考代码位置

| 现状 | 路径 |
|---|---|
| 数据根 | `src/browser_auto_ops/config.py` |
| 动作已记账 | `src/browser_auto_ops/sessions/manager.py` `action()` 119-125 行 |
| 已有 verification 未压给 Agent | 同文件 `_verification_payload` |
| open 只回 session | `src/browser_auto_ops/cli.py` `browser_open` |
| 浏览器店 | `src/browser_auto_ops/browsers/store.py` |
| daemon 未传 BAO_HOME | `src/browser_auto_ops/cli.py` `daemon_start` |
| 通用 SKILL 模板 | `src/browser_auto_ops/forge/engine.py` `_skill_markdown` |
| 文件存在式 test | `src/browser_auto_ops/cli.py` `forge_test` |
| 现有单测 | `tests/unit/test_core.py` `test_forge_generates_trace_informed_skill` |
| 文档 | `docs/FORGE.md` |
