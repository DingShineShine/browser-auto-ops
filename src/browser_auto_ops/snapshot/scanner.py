from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from browser_auto_ops.schemas import ElementLocator, ElementRect, PageState, StateElement


DOM_SCANNER = r"""
() => {
  const out = [];
  const roleTags = new Set(['button', 'link', 'textbox', 'combobox', 'checkbox', 'radio', 'menuitem', 'tab', 'treeitem', 'dialog']);
  const clickableTags = new Set(['a', 'button', 'select', 'summary']);
  const fillableTypes = new Set(['text','search','email','password','tel','url','number','date','datetime-local','month','week','time']);

  function clean(value) {
    return (value || '').replace(/\s+/g, ' ').trim();
  }

  function classNameIncludes(el, value) {
    return String(el.className || '').includes(value);
  }

  function xpath(el) {
    if (el.id && !el.id.includes('"')) return '//*[@id="' + el.id + '"]';
    const parts = [];
    let node = el;
    while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.documentElement) {
      let index = 1;
      let sibling = node.previousElementSibling;
      while (sibling) {
        if (sibling.tagName === node.tagName) index++;
        sibling = sibling.previousElementSibling;
      }
      parts.unshift(node.tagName.toLowerCase() + '[' + index + ']');
      node = node.parentElement;
    }
    return '/html/' + parts.join('/');
  }

  function cssPath(el) {
    if (el.id && !el.id.includes('"')) return '#' + CSS.escape(el.id);
    const parts = [];
    let node = el;
    while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.documentElement) {
      const tag = node.tagName.toLowerCase();
      let part = tag;
      const testId = node.getAttribute('data-testid');
      if (testId) part += '[data-testid="' + CSS.escape(testId) + '"]';
      else {
        let index = 1;
        let sibling = node.previousElementSibling;
        while (sibling) {
          if (sibling.tagName === node.tagName) index++;
          sibling = sibling.previousElementSibling;
        }
        part += ':nth-of-type(' + index + ')';
      }
      parts.unshift(part);
      node = node.parentElement;
    }
    return parts.join(' > ');
  }

  function actionTarget(el) {
    const cls = String(el.className || '');
    if (cls.includes('el-checkbox')) {
      return el.querySelector('.el-checkbox__inner') || el.querySelector('input[type="checkbox"]') || el;
    }
    if (cls.includes('el-tree-node__content')) {
      return el.querySelector('.el-checkbox__inner') || el;
    }
    const parentButton = el.closest ? el.closest('button') : null;
    if (parentButton) return parentButton;
    const parentCheckbox = el.closest ? el.closest('.el-checkbox') : null;
    if (parentCheckbox) return parentCheckbox.querySelector('.el-checkbox__inner') || parentCheckbox;
    return el;
  }

  function componentInfo(el, cls, kind) {
    if (cls.includes('el-dialog__wrapper') || cls.includes('el-message-box__wrapper')) return {component: 'element-ui', component_role: 'dialog'};
    if (cls.includes('el-popover')) return {component: 'element-ui', component_role: 'popover'};
    if (cls.includes('el-tree-node')) return {component: 'element-ui', component_role: 'treeitem'};
    if (cls.includes('el-checkbox')) return {component: 'element-ui', component_role: 'checkbox'};
    if (cls.includes('el-button') || kind === 'button') return {component: cls.includes('el-') ? 'element-ui' : 'native', component_role: 'button'};
    if (cls.includes('el-input') || kind === 'input') return {component: cls.includes('el-') ? 'element-ui' : 'native', component_role: 'input'};
    return {component: null, component_role: null};
  }

  function labelFor(el) {
    const id = el.getAttribute('id');
    if (id) {
      const label = document.querySelector('label[for="' + CSS.escape(id) + '"]');
      if (label) return clean(label.innerText || label.textContent);
    }
    const parentLabel = el.closest('label');
    if (parentLabel) return clean(parentLabel.innerText || parentLabel.textContent);
    return '';
  }

  function nameFor(el) {
    if (String(el.className || '').includes('el-checkbox')) {
      const treeNode = el.closest('.el-tree-node');
      if (treeNode) {
        const label = treeNode.querySelector('.custom-tree-node, .label');
        const text = clean(label ? (label.innerText || label.textContent) : treeNode.innerText);
        if (text) return text;
      }
    }
    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const text = labelledBy.split(/\s+/).map(id => {
        const node = document.getElementById(id);
        return node ? clean(node.innerText || node.textContent) : '';
      }).filter(Boolean).join(' ');
      if (text) return text;
    }
    return clean(
      el.getAttribute('aria-label') ||
      labelFor(el) ||
      el.getAttribute('alt') ||
      el.getAttribute('title') ||
      el.getAttribute('placeholder') ||
      el.getAttribute('name') ||
      ''
    );
  }

  function visible(el, rect, style) {
    return style.display !== 'none' &&
      style.visibility !== 'hidden' &&
      Number(style.opacity || 1) > 0 &&
      rect.width > 0 &&
      rect.height > 0;
  }

  function classify(el, style) {
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || '';
    const type = (el.getAttribute('type') || '').toLowerCase();
    const cursor = style.cursor || '';
    const contentEditable = el.isContentEditable;
    const className = String(el.className || '');
    const elementUiClickable = className.includes('el-checkbox') || className.includes('el-tree-node__content') || className.includes('el-dialog__wrapper');
    const clickable = clickableTags.has(tag) || roleTags.has(role) || tag === 'label' || elementUiClickable || !!el.onclick || cursor === 'pointer';
    const fillable = tag === 'textarea' || contentEditable || (tag === 'input' && (fillableTypes.has(type) || !type));
    const selectable = tag === 'select';
    const scrollable = el.scrollHeight > el.clientHeight + 5 || el.scrollWidth > el.clientWidth + 5;
    let kind = tag;
    if (fillable) kind = 'input';
    else if (selectable) kind = 'select';
    else if (role === 'dialog' || className.includes('el-dialog__wrapper')) kind = 'dialog';
    else if (role === 'treeitem') kind = 'treeitem';
    else if (role === 'checkbox' || className.includes('el-checkbox') || type === 'checkbox') kind = 'checkbox';
    else if (role === 'link' || tag === 'a') kind = 'link';
    else if (role === 'button' || tag === 'button') kind = 'button';
    else if (scrollable && !clickable) kind = 'scrollable';
    return {kind, role, clickable, fillable, selectable, scrollable};
  }

  function attrs(el) {
    const result = {};
    for (const attr of ['id','class','name','type','role','aria-label','aria-checked','aria-selected','aria-expanded','placeholder','title','href','data-testid']) {
      const value = el.getAttribute(attr);
      if (value) result[attr] = value;
    }
    return result;
  }

  function occluded(el, rect) {
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    if (x < 0 || y < 0 || x > window.innerWidth || y > window.innerHeight) return false;
    const top = document.elementFromPoint(x, y);
    return !!top && top !== el && !el.contains(top) && !top.contains(el);
  }

  function visit(root) {
    const nodes = root.querySelectorAll ? Array.from(root.querySelectorAll('*')) : [];
    for (const el of nodes) {
      try {
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      const cls = classify(el, style);
      const isVisible = visible(el, rect, style);
      const enabled = !el.disabled && el.getAttribute('aria-disabled') !== 'true';
      const text = clean(el.innerText || el.textContent || '');
      const name = nameFor(el);
      const interesting = cls.clickable || cls.fillable || cls.selectable || cls.scrollable;
      const hasLabel = !!clean(name || text || el.getAttribute('placeholder') || el.getAttribute('title') || el.getAttribute('aria-label') || '');
      const tag = el.tagName.toLowerCase();
      const semanticTag = ['a','button','input','textarea','select','summary'].includes(tag);
      const noisyTag = ['svg','path','g','use','defs','clipPath'].includes(tag);
      const shouldKeep = interesting && isVisible && enabled && !noisyTag && (
        hasLabel || cls.fillable || cls.selectable || semanticTag || (cls.scrollable && text.length > 20)
      );
      if (shouldKeep) {
        const target = actionTarget(el);
        const component = componentInfo(el, String(el.className || ''), cls.kind);
        out.push({
          tag,
          kind: cls.kind,
          role: cls.role || null,
          component: component.component,
          component_role: component.component_role,
          name,
          text: text.slice(0, 200),
          placeholder: el.getAttribute('placeholder') || '',
          value: (el.value || '').toString().slice(0, 200),
          xpath: xpath(el),
          css: cssPath(el),
          action_xpath: xpath(target),
          action_css: cssPath(target),
          rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
          visible: isVisible,
          enabled,
          clickable: cls.clickable,
          fillable: cls.fillable,
          selectable: cls.selectable,
          scrollable: cls.scrollable,
          checked: (cls.kind === 'checkbox' || cls.role === 'treeitem') ? (el.checked === true || el.getAttribute('aria-checked') === 'true' || classNameIncludes(el, 'is-checked')) : null,
          selected: (cls.role === 'treeitem' || el.getAttribute('aria-selected') !== null) ? (el.getAttribute('aria-selected') === 'true' || classNameIncludes(el, 'is-current')) : null,
          expanded: el.getAttribute('aria-expanded') === null ? null : el.getAttribute('aria-expanded') === 'true',
          modal: classNameIncludes(el, 'el-dialog__wrapper') || classNameIncludes(el, 'el-message-box__wrapper') || cls.role === 'dialog',
          occluded: occluded(el, rect),
          attributes: attrs(el)
        });
      }
      if (el.shadowRoot) visit(el.shadowRoot);
      } catch (_err) {
        continue;
      }
    }
  }
  visit(document);
  return out;
}
"""


class SnapshotEngine:
    async def capture(self, page: Page, session_id: str) -> PageState:
        elements: list[StateElement] = []
        for frame_index, frame in enumerate(page.frames):
            try:
                raw_elements = await frame.evaluate(DOM_SCANNER)
            except Exception:
                continue
            for raw in raw_elements:
                element = _to_element(raw, len(elements) + 1, frame_index, frame.url)
                if element:
                    elements.append(element)
        elements.sort(key=lambda item: (0 if item.modal else 1, item.rect.y if item.rect else 0))
        for index, element in enumerate(elements, start=1):
            element.index = index
            element.ref = f"@e{index}"
        title = await page.title()
        viewport = page.viewport_size or {}
        return PageState(
            session_id=session_id,
            url=page.url,
            title=title,
            viewport=viewport,
            elements=elements,
        )


def _to_element(
    raw: dict[str, Any],
    index: int,
    frame_index: int,
    frame_url: str,
) -> StateElement | None:
    rect_raw = raw.get("rect") or {}
    rect = ElementRect(
        x=float(rect_raw.get("x", 0)),
        y=float(rect_raw.get("y", 0)),
        width=float(rect_raw.get("width", 0)),
        height=float(rect_raw.get("height", 0)),
    )
    if rect.width <= 0 or rect.height <= 0:
        return None
    return StateElement(
        index=index,
        kind=raw.get("kind") or raw.get("tag") or "element",
        tag=raw.get("tag") or "element",
        role=raw.get("role"),
        name=raw.get("name") or "",
        text=raw.get("text") or "",
        placeholder=raw.get("placeholder") or "",
        value=raw.get("value") or "",
        locator=ElementLocator(type="xpath", value=raw.get("xpath") or ""),
        action_locator=ElementLocator(type="xpath", value=raw.get("action_xpath") or raw.get("xpath") or ""),
        selector_candidates=[
            ElementLocator(type="xpath", value=raw.get("xpath") or ""),
            ElementLocator(type="css", value=raw.get("css") or ""),
        ],
        component=raw.get("component"),
        component_role=raw.get("component_role"),
        rect=rect,
        frame_index=frame_index,
        frame_url=frame_url,
        visible=bool(raw.get("visible", True)),
        enabled=bool(raw.get("enabled", True)),
        clickable=bool(raw.get("clickable", False)),
        fillable=bool(raw.get("fillable", False)),
        selectable=bool(raw.get("selectable", False)),
        scrollable=bool(raw.get("scrollable", False)),
        checked=raw.get("checked"),
        selected=raw.get("selected"),
        expanded=raw.get("expanded"),
        modal=bool(raw.get("modal", False)),
        occluded=bool(raw.get("occluded", False)),
        attributes=raw.get("attributes") or {},
    )
