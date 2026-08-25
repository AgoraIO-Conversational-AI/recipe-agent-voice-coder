"""Bounded macOS terminal authentication for the pinned Claude Agent."""

import asyncio
import json
import logging
import shlex
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

from .profiles import CLAUDE_ACP_PACKAGE

CLAUDE_AUTH_STATUS_COMMAND = (
    "npx",
    "-y",
    CLAUDE_ACP_PACKAGE,
    "--cli",
    "auth",
    "status",
    "--json",
)
CLAUDE_LOGIN_COMMAND = (
    "npx",
    "-y",
    CLAUDE_ACP_PACKAGE,
    "--cli",
    "auth",
    "login",
    "--claudeai",
)
_APPLESCRIPT = """on run argv
tell application "Terminal"
  activate
  do script item 1 of argv
end tell
end run"""

ClaudeAuthState = Literal["signed_out", "waiting", "signed_in", "failed"]
StatusRunner = Callable[[], Awaitable[tuple[int, str]]]
TerminalLauncher = Callable[[tuple[str, ...]], Awaitable[None]]
Clock = Callable[[], float]
logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class ClaudeAuthStatus:
    state: ClaudeAuthState
    error: str | None = None


async def _run_status() -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        *CLAUDE_AUTH_STATUS_COMMAND,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=15)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    return process.returncode or 0, stdout[: 64 * 1024].decode(
        "utf-8", errors="replace"
    )


async def _open_terminal(command: tuple[str, ...]) -> None:
    display_command = shlex.join(command)
    process = await asyncio.create_subprocess_exec(
        "osascript",
        "-e",
        _APPLESCRIPT,
        display_command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    returncode = await process.wait()
    if returncode != 0:
        raise RuntimeError("Could not open Claude Code sign-in")


class ClaudeAuthService:
    """Expose only sign-in state and one fixed Terminal launch."""

    def __init__(
        self,
        status_runner: StatusRunner = _run_status,
        terminal_launcher: TerminalLauncher = _open_terminal,
        clock: Clock = time.monotonic,
    ) -> None:
        self._status_runner = status_runner
        self._terminal_launcher = terminal_launcher
        self._clock = clock
        self._waiting_since: float | None = None
        self._start_lock = asyncio.Lock()

    async def status(self) -> ClaudeAuthStatus:
        try:
            _returncode, stdout = await self._status_runner()
            payload = json.loads(stdout)
            if not isinstance(payload, dict) or not isinstance(
                payload.get("loggedIn"), bool
            ):
                raise ValueError("invalid auth status")
            if payload["loggedIn"]:
                self._waiting_since = None
                return ClaudeAuthStatus(state="signed_in")
            if (
                self._waiting_since is not None
                and self._clock() - self._waiting_since >= 120
            ):
                self._waiting_since = None
            return ClaudeAuthStatus(
                state="waiting" if self._waiting_since is not None else "signed_out"
            )
        except Exception as exc:
            logger.error(
                "Claude Code auth status check failed error_type=%s",
                type(exc).__name__,
            )
            return ClaudeAuthStatus(
                state="failed", error="Could not check Claude Code sign-in."
            )

    async def start(self) -> ClaudeAuthStatus:
        async with self._start_lock:
            current = await self.status()
            if current.state == "signed_in":
                return current
            if self._waiting_since is not None:
                return ClaudeAuthStatus(state="waiting")
            try:
                await self._terminal_launcher(CLAUDE_LOGIN_COMMAND)
            except Exception as exc:
                logger.error(
                    "Claude Code auth terminal launch failed error_type=%s",
                    type(exc).__name__,
                )
                return ClaudeAuthStatus(
                    state="failed", error="Could not open Claude Code sign-in."
                )
            self._waiting_since = self._clock()
            return ClaudeAuthStatus(state="waiting")
