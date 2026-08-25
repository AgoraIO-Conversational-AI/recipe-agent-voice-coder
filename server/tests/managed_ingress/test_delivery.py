"""Active exact-session delivery of durable terminal Work results."""

import asyncio
import json

import pytest

from managed_ingress.delivery import WorkDeliveryCoordinator
from managed_ingress.models import CompletionThinkOutcome
from task_runtime.models import FinalPresentation
from task_runtime.store import WorkStore


async def wait_until(predicate, message: str) -> None:
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.002)
    raise AssertionError(message)


class FakeSessions:
    def __init__(self) -> None:
        self.active = {"agent-a"}
        self.availability: list[bool] = []
        self.has_checks = 0
        self.think_calls: list[tuple[str, str, str]] = []
        self.think_result: CompletionThinkOutcome = "accepted"
        self.think_error: Exception | None = None
        self.think_started = asyncio.Event()
        self.block_think = False
        self.say_calls: list[tuple[str, str]] = []
        self.say_result = True
        self.say_error: Exception | None = None
        self.say_started = asyncio.Event()
        self.block_say = False

    def has_work_session(self, agent_id: str) -> bool:
        self.has_checks += 1
        if self.availability:
            return self.availability.pop(0)
        return agent_id in self.active

    async def think_work_result(
        self, agent_id: str, completion_envelope: str, work_id: str
    ) -> CompletionThinkOutcome:
        self.think_calls.append((agent_id, completion_envelope, work_id))
        self.think_started.set()
        if self.block_think:
            await asyncio.Event().wait()
        if self.think_error is not None:
            raise self.think_error
        return self.think_result

    async def say_work_result(self, agent_id: str, text: str) -> bool:
        self.say_calls.append((agent_id, text))
        self.say_started.set()
        if self.block_say:
            await asyncio.Event().wait()
        if self.say_error is not None:
            raise self.say_error
        return self.say_result


class FixedWorkspace:
    def __init__(self, workspace_id: str = "scope-a") -> None:
        self.workspace_id = workspace_id
        self.calls = 0

    def current_workspace_identity(self) -> tuple[str, int]:
        self.calls += 1
        return self.workspace_id, 1


@pytest.fixture
def store(tmp_path):
    work_store = WorkStore(tmp_path / "work.sqlite3")
    yield work_store
    work_store.close()


def completed_work(store: WorkStore, key: str = "turn-completed"):
    receipt, _ = store.create_or_get(
        "scope-a", key, "Run tests", delivery_agent_id="agent-a"
    )
    store.transition(receipt.work_id, "starting")
    store.transition(receipt.work_id, "running")
    store.save_final(
        receipt.work_id,
        FinalPresentation(
            speech="The work is done.",
            inline="Tests passed with full detail.",
        ),
    )
    return store.transition(receipt.work_id, "completed")


def failed_work(store: WorkStore):
    receipt, _ = store.create_or_get(
        "scope-a", "turn-failed", "Fail", delivery_agent_id="agent-a"
    )
    store.transition(receipt.work_id, "starting")
    return store.transition(receipt.work_id, "failed", "Safe failure")


@pytest.mark.anyio
async def test_completed_work_reenters_once_and_marks_injection_accepted(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)
    coordinator.notify(receipt.work_id)

    await wait_until(
        lambda: store.get(receipt.work_id).delivery_state == "accepted",
        "accepted delivery",
    )
    assert len(sessions.think_calls) == 1
    agent_id, envelope, work_id = sessions.think_calls[0]
    marker, encoded = envelope.split("\n", 1)
    assert agent_id == "agent-a"
    assert work_id == receipt.work_id
    assert marker == "LOCAL_WORK_COMPLETED"
    assert json.loads(encoded) == {
        "objective": "Run tests",
        "result": "Tests passed with full detail.",
        "result_truncated": False,
    }
    assert sessions.say_calls == []
    await coordinator.close()


@pytest.mark.anyio
async def test_failed_work_speaks_only_its_safe_stored_error(store):
    receipt = failed_work(store)
    sessions = FakeSessions()
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)

    await wait_until(
        lambda: store.get(receipt.work_id).delivery_state == "accepted",
        "accepted failure delivery",
    )
    assert sessions.say_calls == [("agent-a", "Safe failure")]
    assert sessions.think_calls == []
    await coordinator.close()


@pytest.mark.anyio
async def test_cancelled_work_is_never_spoken(store):
    receipt, _ = store.create_or_get(
        "scope-a", "turn-cancelled", "Cancel", delivery_agent_id="agent-a"
    )
    receipt = store.transition(receipt.work_id, "cancelled")
    sessions = FakeSessions()
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert sessions.say_calls == []
    assert sessions.think_calls == []
    assert store.get(receipt.work_id).delivery_state == "not_ready"
    await coordinator.close()


@pytest.mark.anyio
async def test_missing_session_leaves_delivery_pending(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    sessions.active.clear()
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)
    await wait_until(lambda: sessions.has_checks > 0, "session check")

    assert sessions.think_calls == []
    assert sessions.say_calls == []
    assert store.get(receipt.work_id).delivery_state == "pending_delivery"
    await coordinator.close()


@pytest.mark.anyio
async def test_workspace_mismatch_leaves_delivery_pending(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    workspace = FixedWorkspace("scope-b")
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=workspace
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)
    await wait_until(lambda: workspace.calls > 0, "workspace check")

    assert sessions.think_calls == []
    assert sessions.say_calls == []
    assert store.get(receipt.work_id).delivery_state == "pending_delivery"
    await coordinator.close()


@pytest.mark.anyio
async def test_session_loss_after_claim_releases_delivery_to_pending(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    sessions.availability = [True, False]
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)
    await wait_until(lambda: sessions.has_checks == 2, "session revalidation")

    assert sessions.think_calls == []
    assert sessions.say_calls == []
    assert store.get(receipt.work_id).delivery_state == "pending_delivery"
    await coordinator.close()


@pytest.mark.anyio
async def test_session_unavailable_at_submission_releases_claim(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    sessions.think_result = "unavailable"
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)
    await wait_until(lambda: len(sessions.think_calls) == 1, "submission attempt")
    await wait_until(
        lambda: store.get(receipt.work_id).delivery_state == "pending_delivery",
        "released delivery",
    )

    assert sessions.say_calls == []
    await coordinator.close()


@pytest.mark.anyio
async def test_ambiguous_think_failure_becomes_unknown_without_retry(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    sessions.think_error = ConnectionError("network outcome unknown with SECRET")
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)
    coordinator.notify(receipt.work_id)

    await wait_until(
        lambda: store.get(receipt.work_id).delivery_state == "delivery_unknown",
        "unknown delivery",
    )
    assert len(sessions.think_calls) == 1
    assert sessions.say_calls == []
    await coordinator.close()


@pytest.mark.anyio
async def test_definite_think_rejection_uses_one_fixed_fallback(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    sessions.think_result = "rejected"
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)
    coordinator.notify(receipt.work_id)

    await wait_until(
        lambda: store.get(receipt.work_id).delivery_state == "accepted",
        "accepted fallback",
    )
    assert len(sessions.think_calls) == 1
    assert sessions.say_calls == [("agent-a", "The work is done.")]
    await coordinator.close()


@pytest.mark.anyio
async def test_unavailable_fallback_becomes_terminal_without_retry(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    sessions.think_result = "rejected"
    sessions.say_result = False
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)
    await wait_until(lambda: len(sessions.say_calls) == 1, "fallback attempt")
    await wait_until(
        lambda: store.get(receipt.work_id).delivery_state == "delivery_unknown",
        "terminal fallback",
    )

    coordinator.notify(receipt.work_id)
    await asyncio.sleep(0)
    assert len(sessions.think_calls) == 1
    assert sessions.say_calls == [("agent-a", "The work is done.")]
    await coordinator.close()


@pytest.mark.anyio
async def test_ambiguous_fallback_failure_becomes_unknown(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    sessions.think_result = "rejected"
    sessions.say_error = ConnectionError("fallback outcome unknown")
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)

    await wait_until(
        lambda: store.get(receipt.work_id).delivery_state == "delivery_unknown",
        "unknown fallback",
    )
    assert len(sessions.think_calls) == 1
    assert sessions.say_calls == [("agent-a", "The work is done.")]
    await coordinator.close()


@pytest.mark.anyio
async def test_close_marks_an_inflight_submission_unknown(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    sessions.block_think = True
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()
    coordinator.notify(receipt.work_id)
    await sessions.think_started.wait()

    await coordinator.close()

    assert store.get(receipt.work_id).delivery_state == "delivery_unknown"
    coordinator.notify(receipt.work_id)
    assert len(sessions.think_calls) == 1
    assert sessions.say_calls == []


@pytest.mark.anyio
async def test_notification_before_start_does_not_replay(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )

    coordinator.notify(receipt.work_id)
    await coordinator.start()
    await asyncio.sleep(0)

    assert sessions.say_calls == []
    assert sessions.think_calls == []
    assert store.get(receipt.work_id).delivery_state == "pending_delivery"
    await coordinator.close()
