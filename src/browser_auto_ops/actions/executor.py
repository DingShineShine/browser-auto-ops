from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.async_api import Page

from browser_auto_ops.errors import ElementNotFoundError, UnsafeActionError
from browser_auto_ops.safety import confirmation_reason
from browser_auto_ops.schemas import ActionRequest, ActionResult, ElementRect, PageState, StateElement
from browser_auto_ops.snapshot.resolve import resolve_element


class ActionExecutor:
    async def execute(self, page: Page, state: PageState, request: ActionRequest) -> ActionResult:
        started_type = request.type
        try:
            element = _request_element(state, request)
            reason = confirmation_reason(request, element)
            if reason and not request.require_confirm:
                raise UnsafeActionError(reason)
            return await self._dispatch(page, state, request)
        except Exception as exc:
            return ActionResult(type=started_type, success=False, message=str(exc))

    async def _dispatch(self, page: Page, state: PageState, request: ActionRequest) -> ActionResult:
        handlers = {
            "click": lambda: self._click(page, _element(state, request)),
            "input_text": lambda: self._input(page, _element(state, request), request.text or ""),
            "select_option": lambda: self._select(
                page,
                _element(state, request),
                request.option or request.text or "",
            ),
            "hover": lambda: self._hover(page, _element(state, request)),
            "scroll": lambda: self._scroll(page, request.direction or "down", request.amount or 500),
            "keypress": lambda: self._keypress(page, request),
            "upload_file": lambda: self._upload(page, _element(state, request), request.file_path),
            "execute_js": lambda: self._execute_js(page, request),
            "screenshot": lambda: self._screenshot(page, request),
            "goto_url": lambda: self._goto_url(page, request),
            "go_back": lambda: self._go_back(page, request),
            "go_forward": lambda: self._go_forward(page, request),
            "reload": lambda: self._reload(page, request),
            "wait": lambda: self._wait(page, request),
        }
        handler = handlers.get(request.type)
        if not handler:
            raise ValueError(f"unsupported action type: {request.type}")
        return await handler()

    async def _keypress(self, page: Page, request: ActionRequest) -> ActionResult:
        await page.keyboard.press(request.key or request.text or "Enter")
        return ActionResult(type=request.type, success=True, message="key pressed")

    async def _execute_js(self, page: Page, request: ActionRequest) -> ActionResult:
        data = await page.evaluate(request.script or "undefined")
        return ActionResult(type=request.type, success=True, data=data)

    async def _screenshot(self, page: Page, request: ActionRequest) -> ActionResult:
        path = request.output or Path("page.png")
        await page.screenshot(path=str(path), full_page=True)
        return ActionResult(type=request.type, success=True, data=str(path))

    async def _goto_url(self, page: Page, request: ActionRequest) -> ActionResult:
        await page.goto(request.url or "", wait_until="domcontentloaded")
        return ActionResult(type=request.type, success=True, message=page.url)

    async def _go_back(self, page: Page, request: ActionRequest) -> ActionResult:
        await page.go_back(wait_until="domcontentloaded")
        return ActionResult(type=request.type, success=True)

    async def _go_forward(self, page: Page, request: ActionRequest) -> ActionResult:
        await page.go_forward(wait_until="domcontentloaded")
        return ActionResult(type=request.type, success=True)

    async def _reload(self, page: Page, request: ActionRequest) -> ActionResult:
        await page.reload(wait_until="domcontentloaded")
        return ActionResult(type=request.type, success=True)

    async def _wait(self, page: Page, request: ActionRequest) -> ActionResult:
        await wait_stable(page)
        return ActionResult(type=request.type, success=True, message="stable")

    async def _click(self, page: Page, element: StateElement) -> ActionResult:
        if element.occluded:
            raise ElementNotFoundError("element is occluded; handle the covering element and run `bao state` again")
        fresh_rect = await _fresh_action_rect(page, element)
        if fresh_rect and element.frame_index == 0:
            x = fresh_rect.x + fresh_rect.width / 2
            y = fresh_rect.y + fresh_rect.height / 2
            try:
                await page.mouse.move(x, y)
                await page.mouse.down()
                await page.mouse.up()
                await wait_stable(page)
                return ActionResult(type="click", success=True, message="clicked action target with mouse")
            except Exception:
                pass
        await _js_click(page, element)
        await wait_stable(page)
        return ActionResult(type="click", success=True, message="clicked with JS fallback", fallback_used=True)

    async def _hover(self, page: Page, element: StateElement) -> ActionResult:
        if element.rect and element.frame_index == 0:
            x = element.rect.x + element.rect.width / 2
            y = element.rect.y + element.rect.height / 2
            try:
                await page.mouse.move(x, y)
                await page.wait_for_timeout(250)
                return ActionResult(type="hover", success=True, message="hovered with mouse")
            except Exception:
                pass
        await _js_hover(page, element)
        await page.wait_for_timeout(250)
        return ActionResult(type="hover", success=True, message="hovered with JS fallback", fallback_used=True)

    async def _input(self, page: Page, element: StateElement, text: str) -> ActionResult:
        if element.rect and element.frame_index == 0:
            try:
                x = element.rect.x + element.rect.width / 2
                y = element.rect.y + element.rect.height / 2
                await page.mouse.click(x, y)
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                await page.keyboard.type(text)
                await wait_stable(page)
                return ActionResult(type="input_text", success=True, message="typed with keyboard")
            except Exception:
                pass
        await _js_set_value(page, element, text)
        await wait_stable(page)
        return ActionResult(type="input_text", success=True, message="input with JS fallback", fallback_used=True)

    async def _select(self, page: Page, element: StateElement, option: str) -> ActionResult:
        frame = _frame(page, element.frame_index)
        try:
            await frame.locator(f"xpath={element.locator.value}").select_option(label=option)
            await wait_stable(page)
            return ActionResult(type="select_option", success=True, message="selected option")
        except Exception:
            await _js_select_option(page, element, option)
            await wait_stable(page)
            return ActionResult(
                type="select_option",
                success=True,
                message="selected option with JS fallback",
                fallback_used=True,
            )

    async def _scroll(self, page: Page, direction: str, amount: int) -> ActionResult:
        dx, dy = 0, 0
        if direction == "down":
            dy = amount
        elif direction == "up":
            dy = -amount
        elif direction == "right":
            dx = amount
        elif direction == "left":
            dx = -amount
        await page.mouse.wheel(dx, dy)
        await wait_stable(page)
        return ActionResult(type="scroll", success=True, message=f"scrolled {direction} {amount}")

    async def _upload(self, page: Page, element: StateElement, file_path: Path | None) -> ActionResult:
        if not file_path:
            raise ValueError("upload_file requires file_path")
        frame = _frame(page, element.frame_index)
        await frame.locator(f"xpath={element.locator.value}").set_input_files(str(file_path))
        return ActionResult(type="upload_file", success=True, message="file uploaded")


async def wait_stable(page: Page, timeout_ms: int = 5_000) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass
    await page.wait_for_timeout(300)


def _element(state: PageState, request: ActionRequest) -> StateElement:
    return resolve_element(state, request)


def _request_element(state: PageState, request: ActionRequest) -> StateElement | None:
    if request.index is None and request.ref is None and request.match is None:
        return None
    try:
        return _element(state, request)
    except ElementNotFoundError:
        return None


def _frame(page: Page, frame_index: int):
    try:
        return page.frames[frame_index]
    except IndexError as exc:
        raise ElementNotFoundError(f"frame index {frame_index} no longer exists") from exc


async def _fresh_action_rect(page: Page, element: StateElement) -> ElementRect | None:
    locator = element.action_locator or element.locator
    frame = _frame(page, element.frame_index)
    try:
        raw = await frame.evaluate(
            """
            ({xpath}) => {
              const node = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
              if (!node) return null;
              node.scrollIntoView({block: 'center', inline: 'center'});
              const rect = node.getBoundingClientRect();
              const x = rect.left + rect.width / 2;
              const y = rect.top + rect.height / 2;
              const top = document.elementFromPoint(x, y);
              const receives = !!top && (top === node || node.contains(top) || top.contains(node));
              return {x: rect.x, y: rect.y, width: rect.width, height: rect.height, receives};
            }
            """,
            {"xpath": locator.value},
        )
    except Exception:
        return element.rect
    if not raw:
        return element.rect
    if raw.get("width", 0) <= 0 or raw.get("height", 0) <= 0:
        return element.rect
    return ElementRect(
        x=float(raw.get("x", 0)),
        y=float(raw.get("y", 0)),
        width=float(raw.get("width", 0)),
        height=float(raw.get("height", 0)),
    )
async def _js_click(page: Page, element: StateElement) -> None:
    frame = _frame(page, element.frame_index)
    locator = element.action_locator or element.locator
    await frame.evaluate(
        """
        ({xpath}) => {
          const node = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
          if (!node) throw new Error('node not found');
          node.scrollIntoView({block: 'center', inline: 'center'});
          node.click();
        }
        """,
        {"xpath": locator.value},
    )


async def _js_hover(page: Page, element: StateElement) -> None:
    frame = _frame(page, element.frame_index)
    await frame.evaluate(
        """
        ({xpath}) => {
          const node = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
          if (!node) throw new Error('node not found');
          node.scrollIntoView({block: 'center', inline: 'center'});
          const rect = node.getBoundingClientRect();
          const init = {
            bubbles: true,
            cancelable: true,
            view: window,
            clientX: rect.left + rect.width / 2,
            clientY: rect.top + rect.height / 2
          };
          node.dispatchEvent(new MouseEvent('mouseover', init));
          node.dispatchEvent(new MouseEvent('mouseenter', init));
          node.dispatchEvent(new MouseEvent('mousemove', init));
        }
        """,
        {"xpath": element.locator.value},
    )


async def _js_set_value(page: Page, element: StateElement, text: str) -> None:
    frame = _frame(page, element.frame_index)
    await frame.evaluate(
        """
        ({xpath, text}) => {
          const node = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
          if (!node) throw new Error('node not found');
          node.scrollIntoView({block: 'center', inline: 'center'});
          node.focus();
          if ('value' in node) node.value = text;
          else node.textContent = text;
          node.dispatchEvent(new Event('input', {bubbles: true}));
          node.dispatchEvent(new Event('change', {bubbles: true}));
        }
        """,
        {"xpath": element.locator.value, "text": text},
    )


async def _js_select_option(page: Page, element: StateElement, option: str) -> None:
    frame = _frame(page, element.frame_index)
    await frame.evaluate(
        """
        ({xpath, option}) => {
          const node = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
          if (!node) throw new Error('node not found');
          const match = Array.from(node.options || []).find(o => o.label === option || o.text === option || o.value === option);
          if (!match) throw new Error('option not found');
          node.value = match.value;
          node.dispatchEvent(new Event('input', {bubbles: true}));
          node.dispatchEvent(new Event('change', {bubbles: true}));
        }
        """,
        {"xpath": element.locator.value, "option": option},
    )
