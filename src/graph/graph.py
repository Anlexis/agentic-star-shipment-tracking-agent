"""AgentCore Platform v1.0

LOG-C2-030 — RealtimeShipmentTrackingAgent graph.

Cat 2 multi-step tracking pipeline. Inherits directly from the framework base
class AgentBaseGraph. The six business steps are composed into the fixed
5-node backbone via inline slot orchestration:

    pre_process  → InputParse  → CarrierRoute
    main         → TrackingAPICall (act) → StatusNormalize (observe)
    post_process → ResponseGenerate → ResponseValidate (output gate)

route() (inherited from AgentBaseGraph) short-circuits to finalize on any
node ERROR — so an InputParse failure or a refused output never proceeds.
"""

import re
from typing import Any

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.schemas.agent_status import AgentStatus
from src.nodes.main_node import MainNode
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import State

# Domain payload fields. These describe a shipment and are released only on the
# gated success path — see get_output. Anything added here must also be cleared
# by the output gate's refusal path; the boundary tests pin the two lists equal.
_DOMAIN_OUTPUT_FIELDS = ("unified_status", "eta", "exception_flags", "data_timestamp")

# Withheld values for the domain fields, by field, so an error envelope has a
# stable shape rather than missing keys.
_DOMAIN_WITHHELD: dict[str, Any] = {
    "unified_status": None,
    "eta": None,
    "exception_flags": [],
    "data_timestamp": "",
}

# Error codes are short inert identifiers set by this template's own nodes.
# Anything else (a framework message, a formatted exception) is replaced with a
# generic code so no traceback, path or caller value reaches the surface.
_INERT_ERROR_RE = re.compile(r"^[a-z0-9_]{1,64}$")


class RealtimeShipmentTrackingAgent(AgentBaseGraph):
    """Real-time shipment tracking pipeline (Cat 2, direct framework inheritance)."""

    @property
    def name(self) -> str:
        return "RealtimeShipmentTrackingAgent"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        # super() injects the "initialize" and "finalize" backbone slots.
        super().register_nodes()

        # Domain pipeline slots (inline-orchestrator slot nodes).
        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = MainNode()
        self._nodes["post_process"] = PostProcessNode()

    @staticmethod
    def _safe_error(state: dict[str, Any]) -> Any:
        error = state.get("error")
        if error is None:
            return None
        if isinstance(error, str) and _INERT_ERROR_RE.match(error):
            return error
        return "internal_error"

    def get_output(self, state: dict[str, Any]) -> dict[str, Any]:
        """Assemble the caller envelope.

        Domain payload fields are released ONLY when the pipeline succeeded.
        On any non-success the envelope carries the output gate's withheld
        notice and inert provenance — never shipment data, and never the
        narrative text, which on a refusal is the un-gated answer.

        This is the outer half of the containment contract; the output gate
        clears the same fields in state. The two are deliberately independent:
        each is covered by its own test so neither can hide a regression in
        the other (see tests/proof_of_boundary/test_shipment_boundary.py).
        """
        status = state.get("status")
        succeeded = status in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value)

        envelope: dict[str, Any] = {
            "status": status,
            "scope_out": state.get("scope_out", False),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
            "error": self._safe_error(state),
        }

        if not succeeded:
            # formatted_output holds the gate's truthy withheld notice when the
            # gate refused. It is never re-derived from nl_response here: on a
            # refusal that field is the answer the gate declined to release.
            envelope["output"] = state.get("formatted_output") or None
            envelope.update(_DOMAIN_WITHHELD)
            return envelope

        envelope["output"] = state.get("nl_response") or state.get("formatted_output")
        for field in _DOMAIN_OUTPUT_FIELDS:
            envelope[field] = state.get(field, _DOMAIN_WITHHELD[field])
        return envelope


# Back-compat alias: some importers reference `Graph`.
Graph = RealtimeShipmentTrackingAgent
