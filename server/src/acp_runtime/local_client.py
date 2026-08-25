"""Profile-driven local ACP process and session lifecycle."""

import asyncio
import os
import secrets
import sys
from contextlib import AbstractAsyncContextManager
from typing import Any, Callable, Mapping, Sequence

import acp
from acp.schema import (
    AgentMessageChunk,
    AllowedOutcome,
    DeniedOutcome,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
)

from .acp_client import (
    AcpAuthenticationRequired,
    AcpPermissionOption,
    AcpPermissionRequest,
    AcpPromptObserver,
    AcpPromptResult,
    AcpSession,
    AcpSessionEvent,
)
from .profiles import AgentDefinition, resolve_agent_launch
from .workspace import resolve_project_folder


_MAX_PERMISSION_OPTION_BYTES = 96
_MAX_PERMISSION_OPTIONS = 8
_MAX_RESULT_BYTES = 256 * 1024


class _AcpCallback:
    """Project active prompt callbacks into bounded backend-neutral values."""

    def __init__(self) -> None:
        self.events: list[AcpSessionEvent] = []
        self.permission_requests: list[AcpPermissionRequest] = []
        self._observer: AcpPromptObserver | None = None
        self._session_id: str | None = None
        self._message_chunks: list[str] = []
        self._message_bytes = 0
        self._message_limit_reached = False

    def activate(self, session_id: str, observer: AcpPromptObserver) -> None:
        self._observer = observer
        self._session_id = session_id
        self._message_chunks = []
        self._message_bytes = 0
        self._message_limit_reached = False

    def deactivate(self) -> str:
        final_text = "".join(self._message_chunks).strip()
        self._observer = None
        self._session_id = None
        self._message_chunks = []
        self._message_bytes = 0
        self._message_limit_reached = False
        return final_text

    async def settle_messages(self) -> None:
        previous_size = len(self._message_chunks)
        stable_checks = 0
        for _ in range(10):
            await asyncio.sleep(0.01)
            current_size = len(self._message_chunks)
            if current_size == previous_size:
                stable_checks += 1
                if stable_checks >= 2:
                    return
            else:
                stable_checks = 0
            previous_size = current_size

    async def session_update(
        self, session_id: str, update: object, **_kwargs: Any
    ) -> None:
        observer = self._observer
        if observer is None or session_id != self._session_id:
            return
        if isinstance(update, AgentMessageChunk) and isinstance(
            update.content, TextContentBlock
        ):
            if self._message_limit_reached:
                return
            remaining = _MAX_RESULT_BYTES - self._message_bytes
            encoded = update.content.text.encode("utf-8")
            if len(encoded) > remaining:
                bounded = encoded[:remaining].decode("utf-8", errors="ignore")
                self._message_limit_reached = True
            else:
                bounded = update.content.text
            self._message_chunks.append(bounded)
            self._message_bytes += len(bounded.encode("utf-8"))
            return
        if not isinstance(update, (ToolCallStart, ToolCallProgress)):
            return
        kind = str(update.kind or "other")
        event = AcpSessionEvent(kind=kind, label=_activity_label(kind))
        self.events.append(event)
        await observer.on_event(event)

    async def request_permission(
        self,
        session_id: str,
        tool_call: object,
        options: list[object],
        **_kwargs: Any,
    ) -> acp.RequestPermissionResponse:
        observer = self._observer
        if observer is None or session_id != self._session_id:
            return acp.RequestPermissionResponse(
                outcome=DeniedOutcome(outcome="cancelled")
            )
        kind = str(getattr(tool_call, "kind", None) or "other")
        permission_options = tuple(
            AcpPermissionOption(
                option_id=_bounded_text(
                    str(getattr(option, "option_id", "")),
                    _MAX_PERMISSION_OPTION_BYTES,
                ),
                name=_permission_name(str(getattr(option, "kind", ""))),
                kind=getattr(option, "kind"),
            )
            for option in options[:_MAX_PERMISSION_OPTIONS]
            if getattr(option, "kind", None)
            in {"allow_once", "allow_always", "reject_once", "reject_always"}
            and getattr(option, "option_id", None)
        )
        request = AcpPermissionRequest(
            authorization_id=secrets.token_urlsafe(18),
            operation=_permission_operation(kind),
            options=permission_options,
        )
        self.permission_requests.append(request)
        outcome = await observer.request_permission(request)
        allowed_ids = {option.option_id for option in permission_options}
        if outcome.option_id is not None and outcome.option_id in allowed_ids:
            return acp.RequestPermissionResponse(
                outcome=AllowedOutcome(
                    outcome="selected", option_id=outcome.option_id
                )
            )
        return acp.RequestPermissionResponse(
            outcome=DeniedOutcome(outcome="cancelled")
        )


class LocalAcpClient:
    """Own one selected local ACP child process and one session at a time."""

    def __init__(
        self,
        profile_provider: Callable[[], AgentDefinition],
        *,
        environ: Mapping[str, str] | None = None,
        command_override: Sequence[str] | None = None,
    ) -> None:
        self._profile_provider = profile_provider
        self._environ = os.environ if environ is None else environ
        self._command_override = (
            tuple(command_override) if command_override is not None else None
        )
        if self._command_override is not None and not self._command_override:
            raise ValueError("ACP command cannot be empty")
        self._callback = _AcpCallback()
        self._process_context: AbstractAsyncContextManager[tuple[Any, Any]] | None = (
            None
        )
        self._connection: Any | None = None
        self._session_id: str | None = None
        self._session: AcpSession | None = None
        self._active_definition: AgentDefinition | None = None
        self._prompt_lock = asyncio.Lock()

    @property
    def events(self) -> tuple[AcpSessionEvent, ...]:
        return tuple(self._callback.events)

    @property
    def permission_requests(self) -> tuple[AcpPermissionRequest, ...]:
        return tuple(self._callback.permission_requests)

    async def open(self, primary_directory: str) -> AcpSession:
        if self._session is not None:
            raise RuntimeError("An ACP session is already open")
        resolved_path = resolve_project_folder(primary_directory)
        definition = self._profile_provider()
        launch = resolve_agent_launch(definition.profile.id, self._environ)
        argv = self._command_override or launch.argv
        process_context = acp.spawn_agent_process(
            self._callback,
            argv[0],
            *argv[1:],
            env=launch.env,
            cwd=resolved_path,
        )
        connection: Any | None = None
        try:
            connection, _process = await process_context.__aenter__()
            initialized = await connection.initialize(
                protocol_version=acp.PROTOCOL_VERSION
            )
            try:
                new_session = await connection.new_session(
                    cwd=resolved_path,
                    mcp_servers=[],
                )
            except acp.RequestError as exc:
                if exc.code != -32000:
                    raise
                method_id = definition.agent_auth_method_id
                advertised_ids = {
                    str(getattr(method, "id", ""))
                    for method in (initialized.auth_methods or [])
                }
                if method_id is None or method_id not in advertised_ids:
                    raise AcpAuthenticationRequired(definition.profile.id) from exc
                try:
                    await connection.authenticate(method_id)
                except Exception as auth_exc:
                    raise AcpAuthenticationRequired(
                        definition.profile.id
                    ) from auth_exc
                new_session = await connection.new_session(
                    cwd=resolved_path,
                    mcp_servers=[],
                )
        except BaseException:
            if connection is not None:
                await process_context.__aexit__(*sys.exc_info())
            raise
        self._process_context = process_context
        self._connection = connection
        self._session_id = new_session.session_id
        self._session = AcpSession(primary_directory=resolved_path)
        self._active_definition = definition
        return self._session

    async def prompt(
        self, objective: str, observer: AcpPromptObserver
    ) -> AcpPromptResult:
        connection = self._connection
        session_id = self._session_id
        definition = self._active_definition
        if connection is None or session_id is None or definition is None:
            raise RuntimeError("An ACP session is not open")
        objective = objective.strip()
        if not objective:
            raise ValueError("ACP prompt objective is required")
        if self._prompt_lock.locked():
            raise RuntimeError("An ACP prompt is already active")
        await self._prompt_lock.acquire()
        self._callback.activate(session_id, observer)
        response = None
        try:
            response = await connection.prompt(
                session_id,
                [TextContentBlock(type="text", text=objective)],
            )
            await self._callback.settle_messages()
        finally:
            raw_final_text = self._callback.deactivate()
            self._prompt_lock.release()
        final_text = definition.clean_final_text(raw_final_text)
        stop_reason = response.stop_reason
        if stop_reason != "cancelled" and not final_text:
            raise RuntimeError("ACP prompt completed without a final response")
        return AcpPromptResult(stop_reason=stop_reason, final_text=final_text)

    async def cancel(self) -> None:
        connection = self._connection
        session_id = self._session_id
        if connection is None or session_id is None:
            raise RuntimeError("An ACP session is not open")
        await connection.cancel(session_id)

    async def close(self) -> None:
        process_context = self._process_context
        connection = self._connection
        session_id = self._session_id
        self._process_context = None
        self._connection = None
        self._session_id = None
        self._session = None
        self._active_definition = None
        if process_context is None:
            return
        try:
            if connection is not None and session_id is not None:
                try:
                    await connection.close_session(session_id)
                except ConnectionError:
                    pass
        finally:
            await process_context.__aexit__(None, None, None)


def _bounded_text(value: str, max_bytes: int) -> str:
    normalized = " ".join(value.split())
    return normalized.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


_OPERATION_METADATA: dict[str, tuple[str, str]] = {
    "read": ("Inspecting files", "Read project files"),
    "search": ("Inspecting files", "Search project files"),
    "edit": ("Editing files", "Edit project files"),
    "delete": ("Editing files", "Delete project files"),
    "move": ("Editing files", "Move project files"),
    "execute": ("Running command", "Run a command"),
    "fetch": ("Fetching information", "Fetch information"),
    "think": ("Organizing work", "Perform the current operation"),
    "switch_mode": ("Updating work mode", "Change the Agent mode"),
}


def _activity_label(kind: str) -> str:
    return _OPERATION_METADATA.get(
        kind, ("Working", "Perform the current operation")
    )[0]


def _permission_operation(kind: str) -> str:
    return _OPERATION_METADATA.get(
        kind, ("Working", "Perform the current operation")
    )[1]


def _permission_name(kind: str) -> str:
    return {
        "allow_once": "Allow once",
        "allow_always": "Always allow",
        "reject_once": "Reject once",
        "reject_always": "Always reject",
    }.get(kind, "Unsupported option")
