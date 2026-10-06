"""AgentCore Platform v1.0

post_process slot node for RealtimeShipmentTrackingAgent.

Inline slot orchestration: runs the
output sub-nodes in order and merges their partial dicts —
ResponseGenerate → ResponseValidate (the output gate). The validate gate may
refuse (ERROR) or scope-out; either way its result wins.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.nodes.response_generate_node import ResponseGenerateNode
from src.nodes.response_validate_node import ResponseValidateNode


def _is_error(status: object) -> bool:
    return status in (AgentStatus.ERROR, AgentStatus.ERROR.value)


class PostProcessNode(FunctionNode):
    """Slot node: ResponseGenerate → ResponseValidate (inline gate)."""

    # Input-facing node; agent.yaml declares VERIFIED_EXTERNAL for the agent.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self) -> None:
        self._response_generate = ResponseGenerateNode()
        self._response_validate = ResponseValidateNode()

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # Backbone edges into "post_process" are unconditional, so an upstream
        # ERROR still reaches this slot — pass it through untouched.
        if _is_error(state.get("status")):
            emit_trace_event("post_process_completed", {"outcome": "upstream_error"}, state)
            return {"status": state["status"]}

        r1 = self._response_generate.execute(state)
        if _is_error(r1.get("status")):
            emit_trace_event(
                "post_process_completed",
                {"outcome": "error", "step": "response_generate"},
                state,
            )
            return r1

        merged = {**state, **r1}
        r2 = self._response_validate.execute(merged)

        # The output gate's verdict is authoritative (refuse / scope-out / pass).
        # Its delta is applied LAST and its cleared fields must survive the
        # merge — r1 carries the un-gated narrative, so r2 wins every key it
        # sets, including the ones it deliberately blanks.
        emit_trace_event(
            "post_process_completed",
            {"outcome": "error" if _is_error(r2.get("status")) else "success"},
            state,
        )
        return {**r1, **r2}
