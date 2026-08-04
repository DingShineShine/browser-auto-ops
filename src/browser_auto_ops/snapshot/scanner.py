from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from browser_auto_ops.schemas import ElementLocator, ElementRect, PageState, StateElement


DOM_SCANNER = r"""
() => {
  const out = [];
  const roleTags = new Set(['button', 'link', 'textbox', 'combobox', 'checkbox', 'radio', 'menuitem', 'tab']);
  const clickableTags = new Set(['a', 'button', 'select', 'summary']);
  const fillableTypes = new Set(['text','search','email','password','tel','url','number','date','datetime-local','month','week','time']);

  function clean(value) {
    return (value || '').replace(/\s+/g, ' ').trim();
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
    const clickable = clickableTags.has(tag) || roleTags.has(role) || !!el.onclick || cursor === 'pointer';
    const fillable = tag === 'textarea' || contentEditable || (tag === 'input' && (fillableTypes.has(type) || !type));
    const selectable = tag === 'select';
    const scrollable = el.scrollHeight > el.clientHeight + 5 || el.scrollWidth > el.clientWidth + 5;
    let kind = tag;
    if (fillable) kind = 'input';
    else if (selectable) kind = 'select';
    else if (role === 'link' || tag === 'a') kind = 'link';
    else if (role === 'button' || tag === 'button') kind = 'button';
    else if (scrollable && !clickable) kind = 'scrollable';
    return {kind, role, clickable, fillable, selectable, scrollable};
  }

  function attrs(el) {
    const result = {};
    for (const attr of ['id','name','type','role','aria-label','placeholder','title','href','data-testid']) {
      const value = el.getAttribute(attr);
      if (value) result[attr] = value;
    }
    return result;
  }

  function visit(root) {
    const nodes = root.querySelectorAll ? Array.from(root.querySelectorAll('*')) : [];
    for (const el of nodes) {
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
        out.push({
          tag,
          kind: cls.kind,
          role: cls.role || null,
          name,
          text: text.slice(0, 200),
          placeholder: el.getAttribute('placeholder') || '',
          value: (el.value || '').toString().slice(0, 200),
          xpath: xpath(el),
          rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
          visible: isVisible,
          enabled,
          clickable: cls.clickable,
          fillable: cls.fillable,
          selectable: cls.selectable,
          scrollable: cls.scrollable,
          attributes: attrs(el)
        });
      }
      if (el.shadowRoot) visit(el.shadowRoot);
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
        rect=rect,
        frame_index=frame_index,
        frame_url=frame_url,
        visible=bool(raw.get("visible", True)),
        enabled=bool(raw.get("enabled", True)),
        clickable=bool(raw.get("clickable", False)),
        fillable=bool(raw.get("fillable", False)),
        selectable=bool(raw.get("selectable", False)),
        scrollable=bool(raw.get("scrollable", False)),
        attributes=raw.get("attributes") or {},
    )
