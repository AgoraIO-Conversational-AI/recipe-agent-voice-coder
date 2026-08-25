"""Claude Code terminal-auth boundary tests."""

import asyncio

import pytest

from acp_runtime.claude_auth import (
    CLAUDE_LOGIN_COMMAND,
    ClaudeAuthService,
    ClaudeAuthStatus,
)
from acp_runtime import claude_auth


class FakeStatusRunner:
    def __init__(self, returncode: int, stdout: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        return self.returncode, self.stdout


class FakeTerminalLauncher:
    def __init__(self) -> None:
        self.commands = []

    async def __call__(self, command):
        self.commands.append(command)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


@pytest.mark.anyio
async def test_status_process_receives_only_trimmed_claude_environment(monkeypatch):
    captured = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b'{"loggedIn":true}', b""

    async def fake_subprocess(*_args, **kwargs):
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")
    monkeypatch.setenv("HOME", "/Users/example")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/Users/example/.claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-secret")
    monkeypatch.setenv("AGORA_APP_CERTIFICATE", "agora-secret")
    monkeypatch.setattr(claude_auth.asyncio, "create_subprocess_exec", fake_subprocess)

    await claude_auth._run_status()

    assert captured["env"]["PATH"] == "/usr/local/bin:/usr/bin"
    assert captured["env"]["HOME"] == "/Users/example"
    assert captured["env"]["CLAUDE_CONFIG_DIR"] == "/Users/example/.claude"
    assert captured["env"]["ANTHROPIC_API_KEY"] == "anthropic-secret"
    assert "AGORA_APP_CERTIFICATE" not in captured["env"]


@pytest.mark.anyio
async def test_status_returns_only_bounded_login_state():
    service = ClaudeAuthService(
        status_runner=FakeStatusRunner(
            0, '{"loggedIn":true,"email":"secret@example.com"}'
        ),
        terminal_launcher=FakeTerminalLauncher(),
    )

    status = await service.status()

    assert status == ClaudeAuthStatus(state="signed_in", error=None)
    assert "secret@example.com" not in repr(status)


@pytest.mark.anyio
async def test_start_launches_only_fixed_subscription_command():
    launcher = FakeTerminalLauncher()
    service = ClaudeAuthService(
        status_runner=FakeStatusRunner(1, '{"loggedIn":false}'),
        terminal_launcher=launcher,
    )

    status = await service.start()

    assert status.state == "waiting"
    assert launcher.commands == [CLAUDE_LOGIN_COMMAND]


@pytest.mark.anyio
async def test_start_is_idempotent_while_waiting():
    launcher = FakeTerminalLauncher()
    service = ClaudeAuthService(
        status_runner=FakeStatusRunner(1, '{"loggedIn":false}'),
        terminal_launcher=launcher,
    )

    await service.start()
    await service.start()

    assert launcher.commands == [CLAUDE_LOGIN_COMMAND]


@pytest.mark.anyio
async def test_concurrent_start_opens_only_one_terminal():
    started = asyncio.Event()
    release = asyncio.Event()
    commands = []

    async def blocking_launcher(command):
        commands.append(command)
        started.set()
        await release.wait()

    service = ClaudeAuthService(
        status_runner=FakeStatusRunner(1, '{"loggedIn":false}'),
        terminal_launcher=blocking_launcher,
    )

    first = asyncio.create_task(service.start())
    await started.wait()
    second = asyncio.create_task(service.start())
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second)

    assert commands == [CLAUDE_LOGIN_COMMAND]


@pytest.mark.anyio
async def test_invalid_status_output_is_bounded():
    service = ClaudeAuthService(
        status_runner=FakeStatusRunner(0, "not-json secret@example.com"),
        terminal_launcher=FakeTerminalLauncher(),
    )

    status = await service.status()

    assert status == ClaudeAuthStatus(
        state="failed", error="Could not check Claude Code sign-in."
    )
    assert "secret" not in repr(status)


@pytest.mark.anyio
async def test_wait_timeout_allows_one_explicit_retry():
    launcher = FakeTerminalLauncher()
    clock = FakeClock()
    service = ClaudeAuthService(
        status_runner=FakeStatusRunner(1, '{"loggedIn":false}'),
        terminal_launcher=launcher,
        clock=clock,
    )
    await service.start()
    clock.value = 121

    await service.start()

    assert launcher.commands == [CLAUDE_LOGIN_COMMAND, CLAUDE_LOGIN_COMMAND]
