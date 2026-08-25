"""Loopback-only Project Folder configuration routes."""

import asyncio
from dataclasses import asdict
from dataclasses import dataclass
from typing import Literal, Protocol

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .browse import (
    BrowseAlreadyActive,
    BrowseOperationNotFound,
    BrowseOperationStatus,
    BrowseSelectionFailed,
    WorkspaceBrowseCoordinator,
)
from .loopback import require_loopback
from .claude_auth import ClaudeAuthService
from .picker import DirectoryPicker
from .profiles import get_agent_definition
from .readiness import LocalRuntimeCoordinator, LocalRuntimeStatus
from .settings import AgentSettingsService, AgentSettingsStatus
from .workspace import WorkspaceService, WorkspaceStatus


class SelectWorkspaceRequest(BaseModel):
    path: str


class SelectAgentRequest(BaseModel):
    profile_id: str


@dataclass(frozen=True)
class WorkspaceChange:
    """One explicit Workspace mutation a future Work/permission gate may block."""

    operation: Literal["replace", "clear", "profile"]
    path: str | None = None


class WorkspaceSwitchGuard(Protocol):
    """Optional future Work/permission gate before a Workspace mutation."""

    def check(self, previous: WorkspaceStatus, change: WorkspaceChange) -> str | None:
        """Return a stable conflict message, or None when a switch is allowed."""


class AllowWorkspaceSwitch:
    """Default guard for the current runtime, which has no Work state yet."""

    def check(self, previous: WorkspaceStatus, change: WorkspaceChange) -> str | None:
        del previous, change
        return None


@dataclass(frozen=True)
class AgentSelectionResult:
    settings: AgentSettingsStatus
    runtime: LocalRuntimeStatus


def _envelope(status: object) -> dict[str, object]:
    return {
        "code": 0,
        "msg": "success",
        "data": asdict(status),
    }


def build_workspace_router(
    *,
    service: WorkspaceService,
    picker: DirectoryPicker,
    runtime: LocalRuntimeCoordinator,
    switch_guard: WorkspaceSwitchGuard | None = None,
    mutation_lock: asyncio.Lock | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/local/workspace", include_in_schema=False)
    resolved_guard = switch_guard or AllowWorkspaceSwitch()
    resolved_lock = mutation_lock or asyncio.Lock()

    async def select_and_activate(path: str) -> WorkspaceStatus:
        async with resolved_lock:
            return await _select_and_activate_status(
                service, runtime, resolved_guard, path
            )

    async def select_for_browse(path: str) -> WorkspaceStatus:
        try:
            return await select_and_activate(path)
        except HTTPException as exc:
            detail = (
                exc.detail
                if isinstance(exc.detail, str)
                else "Could not select the Project Folder"
            )
            raise BrowseSelectionFailed(detail) from exc

    browse_coordinator = WorkspaceBrowseCoordinator(picker, select_for_browse)

    @router.get("")
    async def get_workspace(request: Request) -> dict[str, object]:
        require_loopback(request)
        return _envelope(service.status())

    @router.post("/browse", status_code=202)
    async def browse_workspace(request: Request) -> dict[str, object]:
        require_loopback(request)
        try:
            return _envelope(browse_coordinator.start())
        except BrowseAlreadyActive as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/browse/{operation_id}")
    async def get_browse_operation(
        operation_id: str, request: Request
    ) -> dict[str, object]:
        require_loopback(request)
        try:
            return _envelope(browse_coordinator.status(operation_id))
        except BrowseOperationNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.put("")
    async def select_workspace(
        payload: SelectWorkspaceRequest, request: Request
    ) -> dict[str, object]:
        require_loopback(request)
        return _envelope(await select_and_activate(payload.path))

    @router.delete("")
    async def clear_workspace(request: Request) -> dict[str, object]:
        require_loopback(request)
        async with resolved_lock:
            previous = service.status()
            conflict = resolved_guard.check(
                previous, WorkspaceChange(operation="clear")
            )
            if conflict is not None:
                raise HTTPException(status_code=409, detail=conflict)
            await runtime.close()
            return _envelope(service.clear())

    return router


def build_agent_router(
    *,
    settings: AgentSettingsService,
    workspace: WorkspaceService,
    runtime: LocalRuntimeCoordinator,
    switch_guard: WorkspaceSwitchGuard | None = None,
    mutation_lock: asyncio.Lock | None = None,
) -> APIRouter:
    """Expose selected Agent metadata without exposing process configuration."""
    router = APIRouter(prefix="/local/agent", include_in_schema=False)
    resolved_guard = switch_guard or AllowWorkspaceSwitch()
    resolved_lock = mutation_lock or asyncio.Lock()

    @router.get("")
    async def get_agent_settings(request: Request) -> dict[str, object]:
        require_loopback(request)
        return _envelope(settings.status())

    @router.put("")
    async def select_agent(
        payload: SelectAgentRequest, request: Request
    ) -> dict[str, object]:
        require_loopback(request)
        try:
            get_agent_definition(payload.profile_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        async with resolved_lock:
            previous = workspace.status()
            conflict = resolved_guard.check(
                previous, WorkspaceChange(operation="profile")
            )
            if conflict is not None:
                raise HTTPException(status_code=409, detail=conflict)
            current = settings.status().selected_profile.id
            if current != payload.profile_id:
                await runtime.close()
                selected = settings.select(payload.profile_id)
            else:
                selected = settings.status()
            readiness = await runtime.start()
            return _envelope(
                AgentSelectionResult(settings=selected, runtime=readiness)
            )

    return router


def build_claude_auth_router(*, service: ClaudeAuthService) -> APIRouter:
    """Expose one predefined Claude Code sign-in flow on loopback only."""
    router = APIRouter(prefix="/local/auth/claude-code", include_in_schema=False)

    @router.get("")
    async def get_claude_auth(request: Request) -> dict[str, object]:
        require_loopback(request)
        return _envelope(await service.status())

    @router.post("")
    async def start_claude_auth(request: Request) -> dict[str, object]:
        require_loopback(request)
        return _envelope(await service.start())

    return router


def build_runtime_router(
    *, runtime: LocalRuntimeCoordinator, mutation_lock: asyncio.Lock | None = None
) -> APIRouter:
    """Expose local readiness without exposing ACP process details."""
    router = APIRouter(prefix="/local/runtime", include_in_schema=False)
    resolved_lock = mutation_lock or asyncio.Lock()

    @router.get("")
    async def get_runtime(request: Request) -> dict[str, object]:
        require_loopback(request)
        return {
            "code": 0,
            "msg": "success",
            "data": asdict(runtime.status()),
        }

    @router.post("")
    async def start_runtime(request: Request) -> dict[str, object]:
        require_loopback(request)
        async with resolved_lock:
            return {
                "code": 0,
                "msg": "success",
                "data": asdict(await runtime.start()),
            }

    return router


async def _select_and_activate_status(
    service: WorkspaceService,
    runtime: LocalRuntimeCoordinator,
    switch_guard: WorkspaceSwitchGuard,
    path: str,
) -> WorkspaceStatus:
    """Persist a new folder only when its replacement ACP session is ready."""
    previous = service.status()
    conflict = switch_guard.check(
        previous, WorkspaceChange(operation="replace", path=path)
    )
    if conflict is not None:
        raise HTTPException(status_code=409, detail=conflict)
    try:
        selected = service.select(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    readiness = await runtime.activate_workspace()
    if readiness.state == "ready":
        return selected

    if readiness.state == "authentication_required":
        return selected

    service.restore(previous)
    raise HTTPException(
        status_code=503,
        detail=readiness.error or "The local coding agent is not ready.",
    )
