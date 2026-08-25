#!/usr/bin/env python3
"""Run one explicit local ACP profile smoke check without Agora services."""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "server" / "src"))

from acp_runtime import (  # noqa: E402
    AGENT_DEFINITIONS,
    AcpPermissionOutcome,
    AcpPermissionRequest,
    AcpSessionEvent,
    LocalAcpClient,
)


class RejectingObserver:
    async def on_event(self, event: AcpSessionEvent) -> None:
        del event

    async def request_permission(
        self, request: AcpPermissionRequest
    ) -> AcpPermissionOutcome:
        del request
        return AcpPermissionOutcome(option_id=None)


async def smoke(profile_id: str) -> None:
    definition = AGENT_DEFINITIONS[profile_id]
    client = LocalAcpClient(profile_provider=lambda: definition)
    with tempfile.TemporaryDirectory(prefix="voice-coder-acp-smoke-") as folder:
        await client.open(folder)
        try:
            result = await client.prompt("Reply with ready.", RejectingObserver())
            result_size = len(result.final_text.encode("utf-8"))
            if not result.final_text or result_size > 256 * 1024:
                raise RuntimeError("ACP smoke response was empty or oversized")
        finally:
            await client.close()
    print(f"{definition.profile.label}: {result.stop_reason}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check one local coding Agent profile without starting Agora."
    )
    parser.add_argument("--profile", required=True, choices=AGENT_DEFINITIONS)
    args = parser.parse_args()
    asyncio.run(smoke(args.profile))


if __name__ == "__main__":
    main()
