"""AgentCore Platform v1.0

Step 2 — CarrierRoute node.

Determines which data source to use (the internal transport-management system
vs an external carrier API) from the parsed carrier code, and selects the
credential KEY NAME the downstream TrackingAPICall node will resolve at runtime.

Security:
  - Carrier credentials are referenced by key name only. The actual secret
    is resolved at runtime via InvocationContext.secrets — never read, stored
    in State, or hardcoded here.
"""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

# Known carriers → routing decision + credential key name (key only).
#   tms        → internal transport-management lookup
#   yamato/... → external carrier API
_CARRIER_ROUTING: dict[str, dict[str, str]] = {
    "tms": {"data_source": "tms", "credential_key": "TMS_API_KEY"},
    "yamato": {"data_source": "carrier_api", "credential_key": "YAMATO_API_KEY"},
    "sagawa": {"data_source": "carrier_api", "credential_key": "SAGAWA_API_KEY"},
    "jppost": {"data_source": "carrier_api", "credential_key": "JPPOST_API_KEY"},
}

KNOWN_CARRIERS = frozenset(_CARRIER_ROUTING)


class CarrierRouteNode(FunctionNode):
    """Decide internal vs carrier API and select the credential key name."""

    # Input-facing node; agent.yaml declares VERIFIED_EXTERNAL for the agent.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        carrier_code = state.get("carrier_code")

        routing = _CARRIER_ROUTING.get(carrier_code) if carrier_code else None
        if routing is None:
            # Unknown / ambiguous carrier → error (no downstream API guess).
            emit_trace_event("carrier_route_refused", {"reason": "unknown_carrier"}, state)
            return {
                "status": AgentStatus.ERROR,
                "error": "unknown_carrier",
                "error_log": [f"CarrierRouteNode: unknown carrier_code={carrier_code!r}"],
            }

        emit_trace_event(
            "carrier_route_selected",
            {"carrier_code": carrier_code, "data_source": routing["data_source"]},
            state,
        )
        return {
            "status": AgentStatus.SUCCESS,
            "data_source": routing["data_source"],
            # routing metadata for the dispatch step — key NAME only, never the secret.
            "live_data_response": {
                "_routing": {
                    "carrier_code": carrier_code,
                    "data_source": routing["data_source"],
                    "credential_key": routing["credential_key"],
                }
            },
        }
