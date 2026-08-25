"""Compatibility construction for the default Codex profile."""

from typing import Sequence

from .local_client import LocalAcpClient
from .profiles import AGENT_DEFINITIONS


class CodexAcpClient(LocalAcpClient):
    """Backward-compatible default while production wiring becomes dynamic."""

    def __init__(self, command: Sequence[str] | None = None) -> None:
        super().__init__(
            lambda: AGENT_DEFINITIONS["codex"],
            command_override=command,
        )
