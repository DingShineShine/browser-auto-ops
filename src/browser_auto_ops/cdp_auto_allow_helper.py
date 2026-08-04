from __future__ import annotations

import argparse
import time


ALLOW_LABELS = {
    "allow",
    "允许",
    "准许",
}
REMOTE_DEBUGGING_KEYWORDS = {
    "remote debugging",
    "allow remote debugging",
    "devtools",
    "远程调试",
    "允许远程调试",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    args = parser.parse_args()
    deadline = time.monotonic() + max(0.5, args.timeout_seconds)
    while time.monotonic() < deadline:
        if _click_allow_once():
            return 0
        time.sleep(0.2)
    return 1


def _click_allow_once() -> bool:
    try:
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        for window in desktop.windows():
            if not _window_may_be_chrome_dialog(window):
                continue
            if _click_allow_button(window):
                return True
    except Exception:
        return False
    return False


def _window_may_be_chrome_dialog(window) -> bool:
    text = _safe_text(window)
    if _has_keyword(text):
        return True
    try:
        for child in window.descendants():
            if _has_keyword(_safe_text(child)):
                return True
    except Exception:
        return False
    return False


def _click_allow_button(window) -> bool:
    try:
        controls = window.descendants(control_type="Button")
    except Exception:
        controls = []
    for control in controls:
        label = _safe_text(control).strip().lower()
        if label in ALLOW_LABELS or any(label.startswith(item) for item in ALLOW_LABELS):
            try:
                control.invoke()
            except Exception:
                try:
                    control.click_input()
                except Exception:
                    continue
            return True
    return False


def _has_keyword(value: str) -> bool:
    lower = value.lower()
    return any(keyword in lower for keyword in REMOTE_DEBUGGING_KEYWORDS)


def _safe_text(control) -> str:
    parts: list[str] = []
    for attr in ("window_text", "element_info"):
        try:
            value = getattr(control, attr)
            if callable(value):
                value = value()
            if attr == "element_info":
                value = getattr(value, "name", "")
            if value:
                parts.append(str(value))
        except Exception:
            continue
    return " ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
