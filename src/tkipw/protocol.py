"""IPC message shapes between Python and the WebView widget runtime."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

Channel = Literal["comm", "display", "ready", "error"]
CommMsgType = Literal["comm_open", "comm_msg", "comm_close"]


class CommMessage(TypedDict, total=False):
    channel: Literal["comm"]
    msg_type: CommMsgType
    comm_id: str
    target_name: str
    target_module: str | None
    data: dict[str, Any]
    metadata: dict[str, Any]
    buffers: list[str]  # base64-encoded


class DisplayMessage(TypedDict):
    channel: Literal["display"]
    model_ids: list[str]


class ReadyMessage(TypedDict):
    channel: Literal["ready"]


class ErrorMessage(TypedDict, total=False):
    channel: Literal["error"]
    message: str
    detail: str
