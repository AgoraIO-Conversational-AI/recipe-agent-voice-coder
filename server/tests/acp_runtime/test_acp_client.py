"""ACP process/session lifecycle tests through the runtime's public boundary."""

import asyncio
from types import SimpleNamespace

import acp
import pytest

from acp_runtime.acp_client import (
    AcpAuthenticationRequired,
    AcpPermissionOutcome,
    AcpPromptObserver,
)
from acp_runtime.local_client import LocalAcpClient
from acp_runtime.profiles import AGENT_DEFINITIONS
from tests.acp_runtime.fake_acp_agent import FakeAcpAgentProcess


CODEX_SKILLS_NOTICE = (
    "Warning: Skill descriptions were shortened to fit the 2% skills context "
    "budget. Codex can still see every skill, but some descriptions are shorter. "
    "Disable unused skills or plugins to leave more room for the rest."
)


class RecordingPromptObserver(AcpPromptObserver):
    def __init__(self, selected_option_id: str | None = None) -> None:
        self.events = []
        self.permissions = []
        self.selected_option_id = selected_option_id

    async def on_event(self, event):
        self.events.append(event)

    async def request_permission(self, request):
        self.permissions.append(request)
        return AcpPermissionOutcome(option_id=self.selected_option_id)


@pytest.fixture
def project(tmp_path):
    directory = tmp_path / "project"
    directory.mkdir()
    return directory


@pytest.fixture
def fake_agent(tmp_path):
    return FakeAcpAgentProcess(tmp_path / "acp-requests.txt")


@pytest.mark.anyio
@pytest.mark.parametrize("profile_id", ["codex", "claude-code"])
async def test_client_initializes_and_creates_session_in_project_folder(
    fake_agent, project, profile_id
):
    client = LocalAcpClient(lambda: AGENT_DEFINITIONS[profile_id], command_override=fake_agent.command)

    session = await client.open(str(project))

    assert session.primary_directory == str(project.resolve())
    assert fake_agent.requests == ["initialize", "session/new"]

    await client.close()

    assert fake_agent.requests[-1] == "process/exited"
    assert fake_agent.process_exited


@pytest.mark.anyio
async def test_close_treats_an_already_closed_transport_as_success(
    monkeypatch, project
):
    class ClosedTransportConnection:
        async def initialize(self, **_kwargs):
            return SimpleNamespace(auth_methods=[])

        async def new_session(self, **_kwargs):
            return SimpleNamespace(session_id="closed-session")

        async def close_session(self, _session_id):
            raise ConnectionError("Connection closed")

    class ProcessContext:
        def __init__(self):
            self.exited = False

        async def __aenter__(self):
            return ClosedTransportConnection(), object()

        async def __aexit__(self, *_args):
            self.exited = True

    process = ProcessContext()
    monkeypatch.setattr(
        "acp_runtime.local_client.acp.spawn_agent_process",
        lambda *_args, **_kwargs: process,
    )
    client = LocalAcpClient(
        lambda: AGENT_DEFINITIONS["codex"], command_override=("fake-acp",)
    )
    await client.open(str(project))

    await client.close()
    await client.close()

    assert process.exited


@pytest.mark.anyio
async def test_client_reuses_saved_auth_before_trying_advertised_chatgpt(
    tmp_path, project
):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "acp-saved-auth-requests.txt", advertises_chatgpt=True
    )
    client = LocalAcpClient(lambda: AGENT_DEFINITIONS["codex"], command_override=fake_agent.command)

    await client.open(str(project))

    assert fake_agent.requests == ["initialize", "session/new"]
    await client.close()


@pytest.mark.anyio
async def test_client_authenticates_only_after_typed_auth_required_then_retries_once(
    tmp_path, project
):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "acp-auth-requests.txt",
        advertises_chatgpt=True,
        requires_authentication=True,
    )
    client = LocalAcpClient(lambda: AGENT_DEFINITIONS["codex"], command_override=fake_agent.command)

    await client.open(str(project))

    assert fake_agent.requests == [
        "initialize",
        "session/new",
        "authenticate",
        "session/new",
    ]
    await client.close()


@pytest.mark.anyio
async def test_client_exposes_authentication_failure_as_typed_boundary_result(
    tmp_path, project
):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "acp-auth-failure-requests.txt",
        advertises_chatgpt=True,
        requires_authentication=True,
        authentication_fails=True,
    )
    client = LocalAcpClient(lambda: AGENT_DEFINITIONS["codex"], command_override=fake_agent.command)

    with pytest.raises(AcpAuthenticationRequired):
        await client.open(str(project))

    assert fake_agent.requests == [
        "initialize",
        "session/new",
        "authenticate",
        "process/exited",
    ]


@pytest.mark.anyio
async def test_client_does_not_relabel_post_auth_session_failure(tmp_path, project):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "acp-post-auth-session-failure.txt",
        advertises_chatgpt=True,
        requires_authentication=True,
        session_fails_after_authentication=True,
    )
    client = LocalAcpClient(lambda: AGENT_DEFINITIONS["codex"], command_override=fake_agent.command)

    with pytest.raises(acp.RequestError) as raised:
        await client.open(str(project))

    assert raised.value.code == -32603
    assert fake_agent.requests == [
        "initialize",
        "session/new",
        "authenticate",
        "session/new",
        "process/exited",
    ]


@pytest.mark.anyio
async def test_client_does_not_guess_an_unadvertised_authentication_method(
    tmp_path, project
):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "acp-unadvertised-auth.txt",
        requires_authentication=True,
    )
    client = LocalAcpClient(lambda: AGENT_DEFINITIONS["codex"], command_override=fake_agent.command)

    with pytest.raises(AcpAuthenticationRequired):
        await client.open(str(project))

    assert fake_agent.requests == ["initialize", "session/new", "process/exited"]


@pytest.mark.anyio
@pytest.mark.parametrize("profile_id", ["codex", "claude-code"])
async def test_prompt_streams_only_safe_updates_and_returns_final_text(
    tmp_path, project, profile_id
):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "acp-prompt-requests.txt",
        prompt_result="All tests passed.",
    )
    observer = RecordingPromptObserver()
    client = LocalAcpClient(lambda: AGENT_DEFINITIONS[profile_id], command_override=fake_agent.command)
    await client.open(str(project))

    result = await client.prompt("Run the tests", observer)

    assert result.stop_reason == "end_turn"
    assert result.final_text == "All tests passed."
    assert [(event.kind, event.label) for event in observer.events] == [
        ("execute", "Running command")
    ]
    assert "private reasoning" not in repr(observer.events)
    assert "SECRET=value" not in repr(observer.events)
    await client.close()


@pytest.mark.anyio
async def test_prompt_removes_the_captured_leading_codex_skills_notice(
    tmp_path, project
):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "acp-skills-notice.txt",
        prompt_result=(
            f"{CODEX_SKILLS_NOTICE}\n\n"
            "Repository structure:\n- README.md"
        ),
    )
    client = LocalAcpClient(lambda: AGENT_DEFINITIONS["codex"], command_override=fake_agent.command)
    await client.open(str(project))

    result = await client.prompt("Inspect the project", RecordingPromptObserver())

    assert result.final_text == "Repository structure:\n- README.md"
    await client.close()


@pytest.mark.anyio
async def test_claude_profile_preserves_codex_notice_text(tmp_path, project):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "claude-preserved-warning.txt",
        prompt_result=f"{CODEX_SKILLS_NOTICE}\n\nUseful result.",
    )
    client = LocalAcpClient(
        lambda: AGENT_DEFINITIONS["claude-code"],
        command_override=fake_agent.command,
    )
    await client.open(str(project))

    result = await client.prompt("Inspect the project", RecordingPromptObserver())

    assert result.final_text == f"{CODEX_SKILLS_NOTICE}\n\nUseful result."
    await client.close()


@pytest.mark.anyio
async def test_terminal_auth_is_reported_without_invoking_agent_auth(
    tmp_path, project
):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "claude-terminal-auth.txt",
        requires_authentication=True,
    )
    client = LocalAcpClient(
        lambda: AGENT_DEFINITIONS["claude-code"],
        command_override=fake_agent.command,
    )

    with pytest.raises(AcpAuthenticationRequired) as raised:
        await client.open(str(project))

    assert raised.value.profile_id == "claude-code"
    assert fake_agent.requests == ["initialize", "session/new", "process/exited"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "prompt_result",
    [
        f"Useful result.\n\n{CODEX_SKILLS_NOTICE}",
        "Warning: A different provider warning.\n\nUseful result.",
    ],
)
async def test_prompt_preserves_nonleading_and_unrecognized_warnings(
    tmp_path, project, prompt_result
):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "acp-preserved-warning.txt",
        prompt_result=prompt_result,
    )
    client = LocalAcpClient(lambda: AGENT_DEFINITIONS["codex"], command_override=fake_agent.command)
    await client.open(str(project))

    result = await client.prompt("Inspect the project", RecordingPromptObserver())

    assert result.final_text == prompt_result
    await client.close()


@pytest.mark.anyio
async def test_prompt_front_bounds_oversized_agent_text(tmp_path, project):
    result_file = tmp_path / "oversized-result.txt"
    result_file.write_text("树" * 100000, encoding="utf-8")
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "acp-oversized-result.txt",
        prompt_result_file=result_file,
    )
    client = LocalAcpClient(lambda: AGENT_DEFINITIONS["codex"], command_override=fake_agent.command)
    await client.open(str(project))

    result = await client.prompt("Inspect the project", RecordingPromptObserver())

    assert len(result.final_text.encode("utf-8")) <= 256 * 1024
    assert result.final_text == "树" * len(result.final_text)
    await client.close()


@pytest.mark.anyio
@pytest.mark.parametrize("profile_id", ["codex", "claude-code"])
async def test_prompt_maps_only_observer_selected_permission_option(
    tmp_path, project, profile_id
):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "acp-permission-requests.txt",
        prompt_result="Permission resolved.",
        requests_permission=True,
    )
    observer = RecordingPromptObserver(selected_option_id="allow-once")
    client = LocalAcpClient(lambda: AGENT_DEFINITIONS[profile_id], command_override=fake_agent.command)
    await client.open(str(project))

    await client.prompt("Update the project", observer)

    assert len(observer.permissions) == 1
    assert observer.permissions[0].operation == "Run a command"
    assert [option.kind for option in observer.permissions[0].options] == [
        "allow_once",
        "allow_always",
        "reject_once",
    ]
    assert "permission/selected:allow-once" in fake_agent.requests
    await client.close()


@pytest.mark.anyio
@pytest.mark.parametrize("profile_id", ["codex", "claude-code"])
async def test_cancel_notifies_the_active_session_and_prompt_confirms_cancelled(
    tmp_path, project, profile_id
):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "acp-cancel-requests.txt",
        blocks_until_cancel=True,
    )
    observer = RecordingPromptObserver()
    client = LocalAcpClient(lambda: AGENT_DEFINITIONS[profile_id], command_override=fake_agent.command)
    await client.open(str(project))
    prompt = asyncio.create_task(client.prompt("Wait", observer))
    for _ in range(100):
        if "session/prompt" in fake_agent.requests:
            break
        await asyncio.sleep(0.01)

    await client.cancel()
    result = await prompt

    assert result.stop_reason == "cancelled"
    assert fake_agent.requests.count("session/cancel") == 1
    await client.close()


@pytest.mark.anyio
async def test_concurrent_prompt_fails_closed(tmp_path, project):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "acp-concurrent-requests.txt",
        blocks_until_cancel=True,
    )
    client = LocalAcpClient(lambda: AGENT_DEFINITIONS["codex"], command_override=fake_agent.command)
    await client.open(str(project))
    active = asyncio.create_task(client.prompt("First", RecordingPromptObserver()))
    for _ in range(100):
        if "session/prompt" in fake_agent.requests:
            break
        await asyncio.sleep(0.01)

    with pytest.raises(RuntimeError, match="already active"):
        await client.prompt("Second", RecordingPromptObserver())

    await client.cancel()
    await active
    await client.close()
