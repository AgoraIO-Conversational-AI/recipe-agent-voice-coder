"""Durable result projection and bounded Managed completion envelopes."""

import json

from task_runtime.presentation import (
    COMPLETION_FALLBACK_SPEECH,
    build_completion_envelope,
    project_final_presentation,
)


def decode_envelope(value: str) -> dict:
    marker, encoded = value.split("\n", 1)
    assert marker == "LOCAL_WORK_COMPLETED"
    return json.loads(encoded)


def test_projection_keeps_clean_inline_and_never_copies_it_to_speech():
    projected = project_final_presentation(
        "  Tests passed.\x00\nAPI_KEY=private-value  "
    )

    assert projected.speech == "The work is done."
    assert projected.inline == "Tests passed.\nAPI_KEY=[REDACTED]"
    assert COMPLETION_FALLBACK_SPEECH == "The work is done."


def test_projection_preserves_the_full_durable_result_limit():
    projected = project_final_presentation("x" * (256 * 1024))

    assert projected.inline == "x" * (256 * 1024)


def test_projection_front_bounds_oversized_utf8_results():
    projected = project_final_presentation("树" * 100000)

    assert projected.inline is not None
    assert len(projected.inline.encode("utf-8")) <= 256 * 1024
    assert projected.inline == "树" * len(projected.inline)


def test_projection_redacts_long_secret_names_and_url_schemes():
    long_key = "A" * 65 + "TOKEN"
    long_scheme = "a" * 80

    projected = project_final_presentation(
        f"{long_key}=private {long_scheme}://user:password@example.com"
    )

    assert projected.inline == (
        f"{long_key}=[REDACTED] {long_scheme}://[REDACTED]@example.com"
    )


def test_short_envelope_is_compact_redacted_json():
    envelope = build_completion_envelope(
        "Check API_KEY=private-objective",
        'Passed\npath="src/app.py"\nTOKEN=private-result',
    )

    assert envelope == (
        'LOCAL_WORK_COMPLETED\n{"objective":"Check API_KEY=[REDACTED]",'
        '"result":"Passed\\npath=\\"src/app.py\\"\\nTOKEN=[REDACTED]",'
        '"result_truncated":false}'
    )
    assert decode_envelope(envelope) == {
        "objective": "Check API_KEY=[REDACTED]",
        "result": 'Passed\npath="src/app.py"\nTOKEN=[REDACTED]',
        "result_truncated": False,
    }


def test_envelope_is_utf8_safe_and_bounded_without_private_ids():
    envelope = build_completion_envelope(
        "Inspect the project " + "目" * 1000,
        "Result " + "树" * 10000,
    )
    payload = decode_envelope(envelope)

    assert len(envelope.encode("utf-8")) <= 8 * 1024
    assert len(payload["objective"].encode("utf-8")) <= 1024
    assert payload["result"].startswith("Result ")
    assert payload["result_truncated"] is True
    assert set(payload) == {"objective", "result", "result_truncated"}
    assert "agent-a" not in envelope
    assert "�" not in payload["objective"]
    assert "�" not in payload["result"]


def test_json_escape_expansion_still_obeys_the_total_byte_limit():
    envelope = build_completion_envelope(
        "\x01" * 1024,
        "\\\"\n\x02" * 10000,
    )

    assert len(envelope.encode("utf-8")) <= 8 * 1024
    assert decode_envelope(envelope)["result_truncated"] is True
