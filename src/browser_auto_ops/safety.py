from __future__ import annotations

from browser_auto_ops.schemas import ActionRequest, StateElement


DANGEROUS_ACTION_WORDS = {
    "delete",
    "remove",
    "destroy",
    "pay",
    "payment",
    "purchase",
    "checkout",
    "submit order",
    "publish",
    "withdraw",
    "transfer",
    "refund",
    "cancel order",
    "change password",
    "reset password",
    "\u5220\u9664",
    "\u79fb\u9664",
    "\u652f\u4ed8",
    "\u4ed8\u6b3e",
    "\u63d0\u4ea4\u8ba2\u5355",
    "\u53d1\u5e03",
    "\u8f6c\u8d26",
    "\u63d0\u73b0",
    "\u9000\u6b3e",
    "\u53d6\u6d88\u8ba2\u5355",
    "\u6539\u5bc6\u7801",
    "\u91cd\u7f6e\u5bc6\u7801",
}

CONFIRMABLE_ACTIONS = {
    "click",
    "input_text",
    "select_option",
    "keypress",
    "upload_file",
    "goto_url",
    "execute_js",
}


def is_dangerous_text(value: str | None) -> bool:
    if not value:
        return False
    text = value.lower()
    return any(word in text for word in DANGEROUS_ACTION_WORDS)


def confirmation_reason(request: ActionRequest, element: StateElement | None = None) -> str | None:
    if request.type not in CONFIRMABLE_ACTIONS:
        return None

    fields = [
        request.text,
        request.option,
        request.key,
        request.url,
        request.script,
    ]
    if element:
        fields.extend(
            [
                element.kind,
                element.tag,
                element.role,
                element.name,
                element.text,
                element.placeholder,
                element.value,
                " ".join(element.attributes.values()),
            ]
        )

    corpus = " ".join(field for field in fields if field)
    if not is_dangerous_text(corpus):
        return None
    return "action matches a dangerous operation keyword; rerun with --confirm or require_confirm=true"


def action_requires_confirmation(request: ActionRequest, element: StateElement | None = None) -> bool:
    return confirmation_reason(request, element) is not None
