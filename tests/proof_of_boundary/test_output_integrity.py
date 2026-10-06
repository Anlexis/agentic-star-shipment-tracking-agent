# LOG-C2-030 — Boundary: the output must not rewrite the numbers it reports.
#
# This agent renders NO monetary aggregates, so the rounding grid some templates
# apply to money is not applicable here (docs/02_design.md, "Numeric and
# structural bounds"). That is not a gap to fill — importing such a grid would
# actively corrupt this agent's primary output, because a consignment reference
# IS a long digit run and a grouping transform would rewrite it.
#
# So the invariant this agent enforces instead is the opposite one: every
# identifier, timestamp and estimate it reports comes through BYTE-IDENTICAL.
# These tests pin that, so a future change that adds a numeric transform to the
# output path fails here rather than in production.

import pytest
from framework.schemas.agent_status import AgentStatus

from src.nodes.response_generate_node import ResponseGenerateNode
from src.nodes.response_validate_node import ResponseValidateNode

# Every reference format this agent supports, plus the neighbouring forms a
# grouping transform would be most likely to mangle.
IDENTIFIERS = [
    "TMS000042",  # internal reference
    "123456789012",  # 12-digit
    "11122233344",  # 11-digit
    "EE123456789JP",  # alphanumeric international
    "1234567890123",  # 13-digit
    "TMS999999999999",  # internal reference at maximum length
]

# Non-identifier numeric forms that also appear in an answer.
STRUCTURAL_VALUES = [
    "2026-06-09 18:00",
    "2026-06-12",
    "06:30",
    "9999",
    "1000",
]


def _generated_answer(tracking_number: str, eta: str) -> str:
    result = ResponseGenerateNode().execute(
        {
            "tracking_number": tracking_number,
            "unified_status": "in_transit",
            "eta": eta,
            "exception_flags": [],
            "data_timestamp": "2026-06-08 09:15",
            "live_data_response": {"_carrier": "yamato", "_available": True},
        }
    )
    assert result["status"] == AgentStatus.SUCCESS
    return result["nl_response"]


class TestIdentifiersSurviveGeneration:
    @pytest.mark.parametrize("reference", IDENTIFIERS)
    def test_reference_is_rendered_byte_identical(self, reference):
        answer = _generated_answer(reference, "2026-06-09 18:00")
        assert reference in answer

    @pytest.mark.parametrize("value", STRUCTURAL_VALUES)
    def test_structural_values_are_rendered_byte_identical(self, value):
        answer = _generated_answer("TMS000042", value)
        assert value in answer


class TestIdentifiersSurviveTheOutputGate:
    @pytest.mark.parametrize("reference", IDENTIFIERS)
    def test_gate_passes_identifiers_through_untouched(self, reference):
        narrative = f"Tracking number {reference}: status is in transit. ETA 2026-06-09 18:00."
        result = ResponseValidateNode().execute(
            {
                "raw_query": "where is my parcel",
                "nl_response": narrative,
                "deployment_mode": "coordinator",
                "unified_status": "in_transit",
                "eta": "2026-06-09 18:00",
                "exception_flags": [],
                "data_timestamp": "2026-06-08 09:15",
            }
        )
        assert result["status"] == AgentStatus.SUCCESS
        assert result["nl_response"] == narrative

    def test_customer_facing_redaction_is_the_only_transform(self):
        """Redaction removes whole marked spans; it never rewrites digits.

        The internal reference is redacted by design in customer-facing mode;
        an external carrier reference on the same line must be untouched.
        """
        narrative = "Parcel 123456789012 relates to internal id TMS000042."
        result = ResponseValidateNode().execute(
            {
                "raw_query": "where is my parcel",
                "nl_response": narrative,
                "deployment_mode": "customer_facing",
            }
        )
        assert result["status"] == AgentStatus.SUCCESS
        assert "TMS000042" not in result["nl_response"]
        assert "123456789012" in result["nl_response"]


class TestNoRoundingGridIsApplied:
    def test_a_grid_style_grouping_never_appears_in_output(self):
        """Guard against a future copy of a monetary precision gate.

        If one were added, a 12-digit reference would come back grouped.
        """
        answer = _generated_answer("123456789012", "2026-06-09 18:00")
        assert "123,456,789,012" not in answer
        assert "123456789012" in answer
