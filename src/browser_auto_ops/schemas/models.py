from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


ProviderName = Literal["adspower-cdp", "local-chrome", "chrome-direct", "cdp"]
PublicBrowserType = Literal["chrome-direct", "ads"]
ActionType = Literal[
    "click",
    "input_text",
    "select_option",
    "hover",
    "scroll",
    "keypress",
    "upload_file",
    "goto_url",
    "go_back",
    "go_forward",
    "reload",
    "wait",
    "extract",
    "execute_js",
    "screenshot",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProviderConfig(BaseModel):
    provider: ProviderName
    ads_base_url: str | None = None
    ads_user_id: str | None = None
    api_key: str | None = None
    cdp_url: str | None = None
    user_data_dir: Path | None = None
    headful: bool = False
    chrome_path: Path | None = None
    chrome_profile: str | None = None
    confirm_direct: bool = False
    start_url: str | None = None
    remote_debugging_port: int | None = None
    timeout_ms: int = 30_000
    extra_args: list[str] = Field(default_factory=list)


class BrowserIdentity(BaseModel):
    browser_id: str = Field(default_factory=lambda: f"b_{uuid4().hex[:10]}")
    type: PublicBrowserType
    name: str
    desc: str = ""
    confirm_before_use: bool = False
    provider_config: ProviderConfig
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    meta: dict[str, Any] = Field(default_factory=dict)


class BrowserSession(BaseModel):
    session_id: str = Field(default_factory=lambda: f"s_{uuid4().hex[:10]}")
    name: str | None = None
    browser_id: str | None = None
    provider: ProviderName
    status: Literal["running", "stopped", "error"] = "running"
    cdp_url: str | None = None
    endpoint: str | None = None
    ads_user_id: str | None = None
    process_pid: int | None = None
    owns_browser: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    provider_config: ProviderConfig
    meta: dict[str, Any] = Field(default_factory=dict)


class ElementRect(BaseModel):
    x: float
    y: float
    width: float
    height: float


class ElementLocator(BaseModel):
    type: Literal["xpath", "css", "coordinate", "js-path"]
    value: str


class StateElement(BaseModel):
    index: int
    kind: str
    tag: str
    role: str | None = None
    name: str = ""
    text: str = ""
    placeholder: str = ""
    value: str = ""
    locator: ElementLocator
    rect: ElementRect | None = None
    frame_index: int = 0
    frame_url: str | None = None
    visible: bool = True
    enabled: bool = True
    clickable: bool = False
    fillable: bool = False
    selectable: bool = False
    scrollable: bool = False
    attributes: dict[str, str] = Field(default_factory=dict)


class PageState(BaseModel):
    session_id: str
    url: str
    title: str
    viewport: dict[str, Any] = Field(default_factory=dict)
    elements: list[StateElement] = Field(default_factory=list)
    captured_at: datetime = Field(default_factory=utc_now)

    def render_text(self) -> str:
        lines: list[str] = []
        for element in self.elements:
            label = element.name or element.text or element.placeholder or element.value
            label = label.replace("\n", " ").strip()
            if len(label) > 100:
                label = label[:97] + "..."
            lines.append(f'[{element.index}] {element.kind} "{label}"')
        return "\n".join(lines)


class ActionRequest(BaseModel):
    type: ActionType
    index: int | None = None
    text: str | None = None
    option: str | None = None
    direction: Literal["up", "down", "left", "right"] | None = None
    amount: int | None = None
    key: str | None = None
    file_path: Path | None = None
    url: str | None = None
    script: str | None = None
    output: Path | None = None
    require_confirm: bool = False


class ActionResult(BaseModel):
    action_id: str = Field(default_factory=lambda: f"a_{uuid4().hex[:10]}")
    type: ActionType
    success: bool
    message: str = ""
    fallback_used: bool = False
    data: Any = None
    verification: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime = Field(default_factory=utc_now)


class ObserveCandidate(BaseModel):
    index: int
    action: ActionType
    confidence: float
    reason: str


class NetworkRequestInfo(BaseModel):
    request_id: str = Field(default_factory=lambda: f"r_{uuid4().hex[:10]}")
    url: str
    method: str
    resource_type: str | None = None
    status: int | None = None
    request_headers: dict[str, str] = Field(default_factory=dict)
    response_headers: dict[str, str] = Field(default_factory=dict)
    post_data: str | None = None
    response_body: str | None = None
    error: str | None = None
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
