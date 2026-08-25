"""Loopback Project Folder API tests with a fake native picker."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from acp_runtime.acp_client import AcpAuthenticationRequired, AcpSession
from acp_runtime.readiness import LocalRuntimeCoordinator
from acp_runtime.routes import (
    build_agent_router,
    build_claude_auth_router,
    build_runtime_router,
    build_workspace_router,
)
from acp_runtime.settings import AgentSettingsService, AgentSettingsStore
from acp_runtime.claude_auth import ClaudeAuthStatus
from acp_runtime.workspace import WorkspaceConfigStore, WorkspaceService
from task_runtime.permissions import PermissionBroker
from task_runtime.runtime import TaskRuntimeWorkspaceSwitchGuard
from task_runtime.store import WorkStore


class FakeDirectoryPicker:
    def __init__(self) -> None:
        self.result: str | None = None
        self.calls = 0

    async def pick(self) -> str | None:
        self.calls += 1
        return self.result


class FakeAcpClient:
    def __init__(self) -> None:
        self.opened: list[str] = []
        self.close_calls = 0
        self.open_error: Exception | None = None

    async def open(self, primary_directory: str) -> AcpSession:
        self.opened.append(primary_directory)
        if self.open_error is not None:
            raise self.open_error
        return AcpSession(primary_directory=primary_directory)

    async def close(self) -> None:
        self.close_calls += 1


class FakeWorkspaceSwitchGuard:
    def __init__(self) -> None:
        self.reason: str | None = None
        self.calls: list[tuple[str | None, str, str | None]] = []

    def check(self, previous, change) -> str | None:
        directory = previous.workspace.primary_directory if previous.workspace else None
        self.calls.append((directory, change.operation, change.path))
        return self.reason


def make_app(tmp_path, switch_guard=None):
    service = WorkspaceService(WorkspaceConfigStore(tmp_path / "workspace.json"))
    picker = FakeDirectoryPicker()
    fake_acp = FakeAcpClient()
    runtime = LocalRuntimeCoordinator(service, fake_acp)
    app = FastAPI()
    app.include_router(
        build_workspace_router(
            service=service,
            picker=picker,
            runtime=runtime,
            switch_guard=switch_guard,
        )
    )
    app.include_router(build_runtime_router(runtime=runtime))
    return app, picker, runtime, fake_acp


def make_agent_app(tmp_path, switch_guard=None):
    settings = AgentSettingsService(AgentSettingsStore(tmp_path / "agent.json"))
    service = WorkspaceService(
        WorkspaceConfigStore(tmp_path / "workspace.json"),
        profile_provider=lambda: settings.status().selected_profile,
    )
    fake_acp = FakeAcpClient()
    runtime = LocalRuntimeCoordinator(service, fake_acp)
    app = FastAPI()
    app.include_router(
        build_agent_router(
            settings=settings,
            workspace=service,
            runtime=runtime,
            switch_guard=switch_guard,
        )
    )
    return app, settings, service, runtime, fake_acp


def wait_for_browse(client: TestClient, operation_id: str) -> dict:
    for _ in range(50):
        response = client.get(f"/local/workspace/browse/{operation_id}")
        assert response.status_code == 200
        data = response.json()["data"]
        if data["state"] != "picking":
            return data
    raise AssertionError("Project Folder picker operation did not complete")


def test_get_workspace_returns_unconfigured_envelope(tmp_path):
    app, _picker, _runtime, _fake_acp = make_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/local/workspace")

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "msg": "success",
        "data": {
            "state": "unconfigured",
            "profile": {
                "id": "codex",
                "label": "Codex",
                "requires_primary_directory": True,
                "supports_additional_directories": False,
            },
            "workspace": None,
        },
    }


def test_workspace_routes_are_loopback_only(tmp_path):
    app, _picker, _runtime, _fake_acp = make_app(tmp_path)

    with TestClient(app, client=("203.0.113.10", 50000)) as remote:
        assert remote.get("/local/workspace").status_code == 403
        assert remote.get("/local/runtime").status_code == 403
        assert remote.post("/local/workspace/browse").status_code == 403
        assert remote.get("/local/workspace/browse/operation-a").status_code == 403
        assert (
            remote.put("/local/workspace", json={"path": "/tmp"}).status_code
            == 403
        )
        assert remote.delete("/local/workspace").status_code == 403


def test_agent_settings_returns_supported_profiles_and_persists_selection(tmp_path):
    app, _settings, _workspace, _runtime, _fake_acp = make_agent_app(tmp_path)

    with TestClient(app) as client:
        before = client.get("/local/agent")
        selected = client.put(
            "/local/agent", json={"profile_id": "claude-code"}
        )
        restored = client.get("/local/agent")

    assert [item["id"] for item in before.json()["data"]["profiles"]] == [
        "codex",
        "claude-code",
    ]
    assert selected.status_code == 200
    assert selected.json()["data"]["settings"]["selected_profile"]["id"] == (
        "claude-code"
    )
    assert selected.json()["data"]["runtime"]["state"] == "configuration_required"
    assert restored.json()["data"]["selected_profile"]["id"] == "claude-code"


def test_agent_settings_routes_are_loopback_only(tmp_path):
    app, _settings, _workspace, _runtime, _fake_acp = make_agent_app(tmp_path)

    with TestClient(app, client=("203.0.113.10", 50000)) as remote:
        assert remote.get("/local/agent").status_code == 403
        assert (
            remote.put("/local/agent", json={"profile_id": "claude-code"}).status_code
            == 403
        )


def test_claude_auth_routes_expose_no_command_or_credentials():
    class FakeClaudeAuth:
        async def status(self):
            return ClaudeAuthStatus(state="signed_out")

        async def start(self):
            return ClaudeAuthStatus(state="waiting")

    app = FastAPI()
    app.include_router(build_claude_auth_router(service=FakeClaudeAuth()))

    with TestClient(app) as client:
        before = client.get("/local/auth/claude-code")
        started = client.post("/local/auth/claude-code")

    assert before.json()["data"] == {"state": "signed_out", "error": None}
    assert started.json()["data"] == {"state": "waiting", "error": None}
    assert "command" not in str(started.json()).lower()


def test_claude_auth_routes_are_loopback_only():
    class FakeClaudeAuth:
        async def status(self):
            return ClaudeAuthStatus(state="signed_out")

        async def start(self):
            return ClaudeAuthStatus(state="waiting")

    app = FastAPI()
    app.include_router(build_claude_auth_router(service=FakeClaudeAuth()))

    with TestClient(app, client=("203.0.113.10", 50000)) as remote:
        assert remote.get("/local/auth/claude-code").status_code == 403
        assert remote.post("/local/auth/claude-code").status_code == 403


def test_failed_agent_start_keeps_selected_profile(tmp_path):
    app, _settings, workspace, _runtime, fake_acp = make_agent_app(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    workspace.select(str(project))
    fake_acp.open_error = AcpAuthenticationRequired("claude-code")

    with TestClient(app) as client:
        selected = client.put(
            "/local/agent", json={"profile_id": "claude-code"}
        )
        restored = client.get("/local/agent")

    assert selected.status_code == 200
    assert selected.json()["data"]["runtime"]["state"] == "authentication_required"
    assert restored.json()["data"]["selected_profile"]["id"] == "claude-code"


def test_unknown_agent_profile_fails_before_closing_runtime(tmp_path):
    app, _settings, workspace, runtime, fake_acp = make_agent_app(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    workspace.select(str(project))
    import asyncio

    asyncio.run(runtime.start())

    with TestClient(app) as client:
        rejected = client.put("/local/agent", json={"profile_id": "unknown"})

    assert rejected.status_code == 400
    assert fake_acp.close_calls == 0


def test_switch_guard_blocks_agent_change_before_persistence_or_close(tmp_path):
    guard = FakeWorkspaceSwitchGuard()
    guard.reason = "Finish the current Work before changing local setup."
    app, settings, _workspace, _runtime, fake_acp = make_agent_app(
        tmp_path, switch_guard=guard
    )

    with TestClient(app) as client:
        blocked = client.put(
            "/local/agent", json={"profile_id": "claude-code"}
        )

    assert blocked.status_code == 409
    assert settings.status().selected_profile.id == "codex"
    assert fake_acp.close_calls == 0
    assert guard.calls[-1][1] == "profile"


def test_cross_site_browser_origin_is_rejected(tmp_path):
    """A malicious web page cannot drive loopback routes through the browser."""
    app, _picker, _runtime, _fake_acp = make_app(tmp_path)

    with TestClient(app) as client:
        # The socket peer is loopback (the browser runs on the same machine), but
        # the forbidden Origin header exposes the cross-site caller.
        blocked = client.post(
            "/local/workspace/browse",
            headers={"origin": "https://evil.example.com"},
        )
        rebinding = client.get(
            "/local/workspace", headers={"host": "evil.example.com:8000"}
        )

    assert blocked.status_code == 403
    assert rebinding.status_code == 403


def test_same_origin_and_headerless_callers_are_allowed(tmp_path):
    """The dev frontend (loopback Origin) and non-browser callers still pass."""
    app, _picker, _runtime, _fake_acp = make_app(tmp_path)

    with TestClient(app) as client:
        no_origin = client.get("/local/workspace")
        loopback_origin = client.get(
            "/local/workspace", headers={"origin": "http://127.0.0.1:3000"}
        )
        localhost_origin = client.get(
            "/local/workspace", headers={"origin": "http://localhost:3000"}
        )

    assert no_origin.status_code == 200
    assert loopback_origin.status_code == 200
    assert localhost_origin.status_code == 200


def test_browse_persists_only_picker_result(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    app, picker, runtime, _fake_acp = make_app(tmp_path)
    picker.result = str(project)

    with TestClient(app) as client:
        started = client.post("/local/workspace/browse")
        response = wait_for_browse(client, started.json()["data"]["operation_id"])
        restored = client.get("/local/workspace")

    assert started.status_code == 202
    assert started.json()["data"]["state"] == "picking"
    assert response["state"] == "ready"
    assert response["workspace"]["workspace"]["primary_directory"] == str(
        project.resolve()
    )
    assert restored.json()["data"] == response["workspace"]
    assert picker.calls == 1
    assert runtime.status().state == "ready"


def test_cancelled_picker_does_not_replace_selection(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    app, picker, _runtime, _fake_acp = make_app(tmp_path)

    with TestClient(app) as client:
        selected = client.put("/local/workspace", json={"path": str(project)})
        picker.result = None
        started = client.post("/local/workspace/browse")
        cancelled = wait_for_browse(client, started.json()["data"]["operation_id"])
        restored = client.get("/local/workspace")

    assert selected.status_code == 200
    assert started.status_code == 202
    assert cancelled["state"] == "cancelled"
    assert cancelled["error"] == "Project Folder selection was cancelled"
    assert restored.json()["data"] == selected.json()["data"]


def test_manual_selection_rejects_invalid_folder_without_replacing_state(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    app, _picker, _runtime, _fake_acp = make_app(tmp_path)

    with TestClient(app) as client:
        client.put("/local/workspace", json={"path": str(project)})
        rejected = client.put(
            "/local/workspace", json={"path": str(tmp_path / "missing")}
        )
        restored = client.get("/local/workspace")

    assert rejected.status_code == 400
    assert restored.json()["data"]["workspace"]["primary_directory"] == str(
        project.resolve()
    )


def test_delete_clears_selection_without_touching_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    app, _picker, _runtime, _fake_acp = make_app(tmp_path)

    with TestClient(app) as client:
        client.put("/local/workspace", json={"path": str(project)})
        cleared = client.delete("/local/workspace")

    assert cleared.status_code == 200
    assert cleared.json()["data"]["state"] == "unconfigured"
    assert project.is_dir()


def test_nonterminal_work_blocks_workspace_replacement_and_clear(tmp_path):
    project = tmp_path / "project"
    replacement = tmp_path / "replacement"
    project.mkdir()
    replacement.mkdir()
    store = WorkStore(tmp_path / "work.sqlite3")
    guard = TaskRuntimeWorkspaceSwitchGuard(store, PermissionBroker(store))
    app, _picker, _runtime, _fake_acp = make_app(tmp_path, switch_guard=guard)

    try:
        with TestClient(app) as client:
            selected = client.put(
                "/local/workspace", json={"path": str(project)}
            ).json()["data"]
            store.create_or_get(
                selected["workspace"]["id"],
                "turn-a",
                "Run the tests",
            )

            replaced = client.put(
                "/local/workspace", json={"path": str(replacement)}
            )
            cleared = client.delete("/local/workspace")

        expected = (
            "Wait for the current Work or permission decision before changing local setup."
        )
        assert replaced.status_code == 409
        assert replaced.json()["detail"] == expected
        assert cleared.status_code == 409
        assert cleared.json()["detail"] == expected
    finally:
        store.close()


def test_get_runtime_reports_configuration_required_without_starting_acp(tmp_path):
    app, _picker, runtime, _fake_acp = make_app(tmp_path)

    with TestClient(app) as client:
        response = client.get("/local/runtime")

    assert response.status_code == 200
    assert response.json()["data"]["state"] == "configuration_required"
    assert runtime.status().state == "configuration_required"


def test_post_runtime_explicitly_activates_a_saved_workspace(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    service = WorkspaceService(WorkspaceConfigStore(tmp_path / "workspace.json"))
    service.select(str(project))
    fake_acp = FakeAcpClient()
    runtime = LocalRuntimeCoordinator(service, fake_acp)
    app = FastAPI()
    app.include_router(build_runtime_router(runtime=runtime))

    with TestClient(app) as client:
        before = client.get("/local/runtime")
        activated = client.post("/local/runtime")

    assert before.json()["data"]["state"] == "configuration_required"
    assert activated.status_code == 200
    assert activated.json()["data"]["state"] == "ready"
    assert fake_acp.opened == [str(project)]


def test_failed_activation_keeps_the_previous_workspace_selection(tmp_path):
    previous = tmp_path / "previous"
    next_project = tmp_path / "next"
    previous.mkdir()
    next_project.mkdir()
    app, _picker, runtime, fake_acp = make_app(tmp_path)

    with TestClient(app) as client:
        selected = client.put("/local/workspace", json={"path": str(previous)})
        fake_acp.open_error = RuntimeError("missing executable")
        failed = client.put("/local/workspace", json={"path": str(next_project)})
        restored = client.get("/local/workspace")

    assert selected.status_code == 200
    assert failed.status_code == 503
    assert failed.json()["detail"] == (
        "Could not start the selected coding agent. Check local setup and retry."
    )
    assert restored.json()["data"]["workspace"]["primary_directory"] == str(previous)


def test_browse_activation_failure_preserves_actionable_runtime_reason(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    app, picker, _runtime, fake_acp = make_app(tmp_path)
    picker.result = str(project)
    fake_acp.open_error = RuntimeError("missing executable")

    with TestClient(app) as client:
        started = client.post("/local/workspace/browse")
        failed = wait_for_browse(
            client, started.json()["data"]["operation_id"]
        )
        restored = client.get("/local/workspace")

    assert failed["state"] == "failed"
    assert failed["error"] == (
        "Could not start the selected coding agent. Check local setup and retry."
    )
    assert restored.json()["data"]["state"] == "unconfigured"


def test_switch_guard_blocks_before_persistence_or_acp_session_replacement(tmp_path):
    previous = tmp_path / "previous"
    next_project = tmp_path / "next"
    previous.mkdir()
    next_project.mkdir()
    guard = FakeWorkspaceSwitchGuard()
    app, _picker, _runtime, fake_acp = make_app(tmp_path, switch_guard=guard)

    with TestClient(app) as client:
        selected = client.put("/local/workspace", json={"path": str(previous)})
        guard.reason = "Finish or resolve the pending permission before changing Project Folder."
        blocked = client.put("/local/workspace", json={"path": str(next_project)})
        restored = client.get("/local/workspace")

    assert selected.status_code == 200
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == guard.reason
    assert restored.json()["data"]["workspace"]["primary_directory"] == str(previous)
    assert fake_acp.opened == [str(previous)]
    assert fake_acp.close_calls == 0


def test_switch_guard_blocks_clear_before_session_close_or_store_mutation(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    guard = FakeWorkspaceSwitchGuard()
    app, _picker, _runtime, fake_acp = make_app(tmp_path, switch_guard=guard)

    with TestClient(app) as client:
        selected = client.put("/local/workspace", json={"path": str(project)})
        guard.reason = "Finish or resolve the pending permission before clearing Project Folder."
        blocked = client.delete("/local/workspace")
        restored = client.get("/local/workspace")

    assert selected.status_code == 200
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == guard.reason
    assert restored.json()["data"]["workspace"]["primary_directory"] == str(project)
    assert fake_acp.opened == [str(project)]
    assert fake_acp.close_calls == 0
    assert guard.calls[-1] == (str(project), "clear", None)


def test_authentication_required_keeps_new_workspace_for_login_retry(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    app, _picker, _runtime, fake_acp = make_app(tmp_path)
    fake_acp.open_error = AcpAuthenticationRequired("claude-code")

    with TestClient(app) as client:
        selected = client.put("/local/workspace", json={"path": str(project)})
        restored = client.get("/local/workspace")

    assert selected.status_code == 200
    assert restored.json()["data"]["workspace"]["primary_directory"] == str(project)
