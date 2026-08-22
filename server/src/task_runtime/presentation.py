"""Backend-neutral durable results and Managed completion envelopes."""

import json

from .models import FinalPresentation
from .safety import redact_durable_text


COMPLETION_MARKER = "LOCAL_WORK_COMPLETED"
COMPLETION_FALLBACK_SPEECH = "The work is done."
MAX_COMPLETION_ENVELOPE_BYTES = 8 * 1024
MAX_COMPLETION_OBJECTIVE_BYTES = 1024


def project_final_presentation(value: str) -> FinalPresentation:
    """Keep full cleaned detail durable without treating it as ready speech."""
    return FinalPresentation(
        speech=COMPLETION_FALLBACK_SPEECH,
        inline=_clean_text(value),
    )


def build_completion_envelope(objective: str, inline: str) -> str:
    """Build the longest valid front-bounded JSON result for Managed re-entry."""
    normalized_objective = " ".join(objective.replace("\x00", "").split())
    safe_objective = _utf8_prefix(
        redact_durable_text(normalized_objective),
        MAX_COMPLETION_OBJECTIVE_BYTES,
    )
    safe_result = _clean_text(inline)

    complete = _serialize_envelope(safe_objective, safe_result, False)
    if len(complete.encode("utf-8")) <= MAX_COMPLETION_ENVELOPE_BYTES:
        return complete

    low = 0
    high = len(safe_result)
    best = ""
    while low <= high:
        midpoint = (low + high) // 2
        candidate_result = safe_result[:midpoint]
        candidate = _serialize_envelope(
            safe_objective,
            candidate_result,
            True,
        )
        if len(candidate.encode("utf-8")) <= MAX_COMPLETION_ENVELOPE_BYTES:
            best = candidate_result
            low = midpoint + 1
        else:
            high = midpoint - 1

    envelope = _serialize_envelope(safe_objective, best, True)
    if len(envelope.encode("utf-8")) > MAX_COMPLETION_ENVELOPE_BYTES:
        raise ValueError("Completion envelope exceeds its byte limit")
    return envelope


def _clean_text(value: str) -> str:
    return redact_durable_text(value.replace("\x00", "").strip())


def _utf8_prefix(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _serialize_envelope(
    objective: str,
    result: str,
    result_truncated: bool,
) -> str:
    payload = json.dumps(
        {
            "objective": objective,
            "result": result,
            "result_truncated": result_truncated,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"{COMPLETION_MARKER}\n{payload}"
