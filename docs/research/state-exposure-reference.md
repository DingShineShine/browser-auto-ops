# State Exposure Reference

## Scope

This note focuses only on `bao state` / StateSnapshot improvements. It does not cover ActionExecutor, daemon runtime, downloads, ADS sidecar, or LLM planning.

## Mature References

- BrowserAct observed behavior: Element UI tree checkboxes, modal buttons, and visible-page state are exposed as actionable entries.
- Playwright MCP: accessibility snapshots assign refs to interactive elements and invalidate refs after page changes.
- Agent Browser: `cli/src/native/snapshot.rs` uses `Accessibility.getFullAXTree` and compact refs for agent interaction.
- BrowsePilot: combines Accessibility tree, DOM snapshot, and runtime state.
- Browser Use: `clickable_elements.py` detects interactive elements through native tags, ARIA roles, event listeners, and DOM attributes.

## Problems

### Missing component semantics

Modern UI libraries hide real controls behind component wrappers. A visible tree row is not necessarily the clickable checkbox.

Required state:

```text
treeitem "Pillowcases"
checkbox "Pillowcases" checked=false
button "确认选择"
```

### Missing action target metadata

Agents should see a semantic element. The runtime should know the real DOM action target.

```text
display element: checkbox "Pillowcases"
action target: .el-checkbox__inner
```

### Missing modal priority

When a modal is open, it is the active UI. State should show it first.

```text
dialog "温馨提示" modal=true
button "前往查看"
button "等会儿看"
```

### Excessive output

Large pages can produce thousands of elements. Default state should prioritize modals and current viewport, while `--full` remains available.

## Implementation Guidance

### StateElement fields

```text
ref
role
checked
selected
expanded
modal
action_locator
component
component_role
```

### Component rules

Element UI first:

```text
.el-dialog__wrapper
.el-message-box__wrapper
.el-popover
.el-tree-node
.el-tree-node__content
.el-checkbox
.el-checkbox__inner
.el-checkbox__original
.el-button
```

### Output

```text
[1] @e1 dialog "选择类目" modal=true
[53] @e53 input "请输入Node ID/类目关键词"
[80] @e80 checkbox "Pillowcases" checked=false
[246] @e246 button "确认选择"
```

## Validation

SellerSprite is the regression sample, not a hardcoded target.

Success requires:

- Category search exposes a `Pillowcases` checkbox.
- After clicking checkbox, state shows `checked=true` or `已选 (1)`.
- Export prompt exposes `前往查看` and `等会儿看`.
