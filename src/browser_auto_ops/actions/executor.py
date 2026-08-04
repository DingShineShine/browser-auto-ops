from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.async_api import Page

from browser_auto_ops.errors import ElementNotFoundError, UnsafeActionError
from browser_auto_ops.safety import confirmation_reason
from browser_auto_ops.schemas import ActionRequest, ActionResult, PageState, StateElement


class ActionExecutor:
    async def execute(self, page: Page, state: PageState, request: ActionRequest) -> ActionResult:
        started_type = request.type
        try:
            element = _request_element(state, request)
            reason = confirmation_reason(request, element)
            if reason and not request.require_confirm:
                raise UnsafeActionError(reason)

            if request.type == "click":
                element = _element(state, request.index)
                return await self._click(page, element)
            if request.type == "input_text":
                element = _element(state, request.index)
                return await self._input(page, element, request.text or "")
            if request.type == "select_option":
                element = _element(state, request.index)
                return await self._select(page, element, request.option or request.text or "")
            if request.type == "hover":
                element = _element(state, request.index)
                return await self._hover(page, element)
            if request.type == "scroll":
                return await self._scroll(page, request.direction or "down", request.amount or 500)
            if request.type == "keypress":
                await page.keyboard.press(request.key or request.text or "Enter")
                return ActionResult(type=request.type, success=True, message="key pressed")
            if request.type == "upload_file":
                element = _element(state, request.index)
                return await self._upload(page, element, request.file_path)
            if request.type == "execute_js":
                data = await page.evaluate(request.script or "undefined")
                return ActionResult(type=request.type, success=True, data=data)
            if request.type == "screenshot":
                path = request.output or Path("page.png")
                await page.screenshot(path=str(path), full_page=True)
                return ActionResult(type=request.type, success=True, data=str(path))
            if request.type == "goto_url":
                await page.goto(request.url or "", wait_until="domcontentloaded")
                return ActionResult(type=request.type, success=True, message=page.url)
            if request.type == "go_back":
                await page.go_back(wait_until="domcontentloaded")
                return ActionResult(type=request.type, success=True)
            if request.type == "go_forward":
                await page.go_forward(wait_until="domcontentloaded")
                return ActionResult(type=request.type, success=True)
            if request.type == "reload":
                await page.reload(wait_until="domcontentloaded")
                return ActionResult(type=request.type, success=True)
            if request.type == "wait":
                await wait_stable(page)
                return ActionResult(type=request.type, success=True, message="stable")
            raise ValueError(f"unsupported action type: {request.type}")
        except Exception as exc:
            return ActionResult(type=started_type, success=False, message=str(exc))

    async def _click(self, page: Page, element: StateElement) -> ActionResult:
        if element.rect and element.frame_index == 0:
            x = element.rect.x + element.rect.width / 2
            y = element.rect.y + element.rect.height / 2
            try:
                await page.mouse.move(x, y)
                await page.mouse.down()
                await page.mouse.up()
                await wait_stable(page)
                return ActionResult(type="click", success=True, message="clicked with mouse")
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


def _element(state: PageState, index: int | None) -> StateElement:
    if index is None:
        raise ElementNotFoundError("action requires index")
    for element in state.elements:
        if element.index == index:
            return element
    raise ElementNotFoundError(f"element index {index} not found in current state")


def _request_element(state: PageState, request: ActionRequest) -> StateElement | None:
    if request.index is None:
        return None
    try:
        return _element(state, request.index)
    except ElementNotFoundError:
        return None


def _frame(page: Page, frame_index: int):
    try:
        return page.frames[frame_index]
    except IndexError as exc:
        raise ElementNotFoundError(f"frame index {frame_index} no longer exists") from exc


async def _js_click(page: Page, element: StateElement) -> None:
    frame = _frame(page, element.frame_index)
    await frame.evaluate(
        """
        ({xpath}) => {
          const node = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
          if (!node) throw new Error('node not found');
          node.scrollIntoView({block: 'center', inline: 'center'});
          node.click();
        }
        """,
        {"xpath": element.locator.value},
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
