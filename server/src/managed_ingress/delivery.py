"""Proactive terminal Work delivery to the exact active Managed Agent session."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Literal, Protocol

from managed_ingress.models import CompletionThinkOutcome
from task_runtime.models import WorkReceipt
from task_runtime.presentation import build_completion_envelope
from task_runtime.store import WorkStore


logger = logging.getLogger("uvicorn.error")
DeliverySubmissionOutcome = Literal["accepted", "unavailable", "terminal"]


class DeliverySessionPort(Protocol):
    def has_work_session(self, agent_id: str) -> bool: ...

    async def think_work_result(
        self,
        agent_id: str,
        completion_envelope: str,
        work_id: str,
    ) -> CompletionThinkOutcome: ...

    async def say_work_result(self, agent_id: str, text: str) -> bool: ...


class DeliveryWorkspacePort(Protocol):
    def current_workspace_identity(self) -> tuple[str, int] | None: ...


class WorkDeliveryCoordinator:
    """Claim and submit one safe stored result without cross-session replay."""

    def __init__(
        self,
        *,
        store: WorkStore,
        sessions: DeliverySessionPort,
        workspace: DeliveryWorkspacePort,
    ) -> None:
        self._store = store
        self._sessions = sessions
        self._workspace = workspace
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._accepting = False
        self._active_work_id: str | None = None

    async def start(self) -> None:
        if self._worker is not None:
            return
        self._accepting = True
        self._worker = asyncio.create_task(
            self._run(), name="managed-work-delivery"
        )

    def notify(self, work_id: str) -> None:
        if self._accepting:
            self._queue.put_nowait(work_id)

    async def close(self) -> None:
        self._accepting = False
        worker = self._worker
        self._worker = None
        if worker is None:
            return
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
        active_work_id = self._active_work_id
        self._active_work_id = None
        if active_work_id is not None:
            with suppress(Exception):
                self._store.mark_delivery_unknown(active_work_id)

    async def _run(self) -> None:
        while True:
            work_id = await self._queue.get()
            try:
                await self._deliver(work_id)
            finally:
                self._queue.task_done()

    async def _deliver(self, work_id: str) -> None:
        try:
            receipt = self._store.get(work_id)
        except KeyError:
            return
        agent_id = receipt.delivery_agent_id
        if (
            not self._is_deliverable(receipt)
            or agent_id is None
            or receipt.delivery_state != "pending_delivery"
            or not self._workspace_matches(receipt)
            or not self._sessions.has_work_session(agent_id)
        ):
            return
        claimed = self._store.claim_delivery(work_id)
        if claimed is None:
            return
        self._active_work_id = work_id
        try:
            if (
                not self._workspace_matches(claimed)
                or not self._sessions.has_work_session(agent_id)
            ):
                self._store.release_delivery(work_id)
                return
            try:
                submission = await self._submit(claimed, agent_id)
            except asyncio.CancelledError:
                self._store.mark_delivery_unknown(work_id)
                raise
            except Exception as exc:
                self._store.mark_delivery_unknown(work_id)
                logger.error(
                    "Managed Work result delivery outcome is unknown error_type=%s",
                    type(exc).__name__,
                )
                return
            if submission == "unavailable":
                self._store.release_delivery(work_id)
                return
            if submission == "terminal":
                self._store.mark_delivery_unknown(work_id)
                return
            self._store.mark_delivery_accepted(work_id)
        finally:
            self._active_work_id = None

    def _workspace_matches(self, receipt: WorkReceipt) -> bool:
        identity = self._workspace.current_workspace_identity()
        return identity is not None and identity[0] == receipt.workspace_id

    async def _submit(
        self, receipt: WorkReceipt, agent_id: str
    ) -> DeliverySubmissionOutcome:
        if receipt.state == "completed" and receipt.final_presentation is not None:
            inline = receipt.final_presentation.inline
            if inline is None:
                return "unavailable"
            envelope = build_completion_envelope(receipt.objective, inline)
            outcome = await self._sessions.think_work_result(
                agent_id,
                envelope,
                receipt.work_id,
            )
            if outcome == "accepted":
                return "accepted"
            if outcome == "unavailable":
                return "unavailable"
            if outcome == "rejected":
                submitted = await self._sessions.say_work_result(
                    agent_id,
                    receipt.final_presentation.speech,
                )
                return "accepted" if submitted else "terminal"
            raise RuntimeError("Unsupported completion think outcome")
        if receipt.state == "failed" and receipt.error:
            submitted = await self._sessions.say_work_result(agent_id, receipt.error)
            return "accepted" if submitted else "unavailable"
        return "unavailable"

    @staticmethod
    def _is_deliverable(receipt: WorkReceipt) -> bool:
        if receipt.state == "completed" and receipt.final_presentation is not None:
            return receipt.final_presentation.inline is not None
        return receipt.state == "failed" and bool(receipt.error)
