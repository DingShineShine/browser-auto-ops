# State Snapshot

`state` is a generated browser-auto-ops concept, not a browser primitive.

It captures:

- URL/title/viewport
- indexed interactive elements
- tag/role/name/text/placeholder/value
- XPath locator
- rect
- frame index
- clickable/fillable/selectable/scrollable flags

v1 uses `Runtime.evaluate` to run a DOM scanner in each Playwright frame. It inspects `getBoundingClientRect`, computed style, ARIA, labels, placeholders, text, open shadow roots, and same-origin frames.

v1.1 should add CDP Accessibility tree, DOMSnapshot, paint-order/occlusion checks, and better cross-origin iframe handling.

