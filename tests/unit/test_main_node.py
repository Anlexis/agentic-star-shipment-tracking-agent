# LOG-C2-030 — Unit Tests: Main slot Node (#8)
#
# MainNode is now the inline-orchestrator slot node that runs
# TrackingAPICall (act) → StatusNormalize (observe) and merges partial dicts.

from src.nodes.main_node import MainNode
from framework.schemas.agent_status import AgentStatus


def _routed_state(carrier, tracking, data_source):
    return {
        "carrier_code": carrier,
        "tracking_number": tracking,
        "data_source": data_source,
        "live_data_response": {
            "_routing": {
                "carrier_code": carrier,
                "data_source": data_source,
                "credential_key": "TMS_API_KEY",
            }
        },
        "node_history": [],
        "error_log": [],
    }


class TestMainNode:
    """Unit tests for the main slot node (tracking + normalize)."""

    def setup_method(self):
        self.node = MainNode()

    def test_success_path(self):
        """Main slot processes a routed TMS lookup and returns SUCCESS."""
        state = _routed_state("tms", "TMS000042", "tms")
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["unified_status"] == "pending"
        assert "live_data_response" in result

    def test_unknown_tracking_graceful(self):
        """Unknown tracking number degrades gracefully (still SUCCESS, pending)."""
        state = _routed_state("tms", "TMS99999", "tms")
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["unified_status"] == "pending"

    def test_carrier_api_without_credential_short_circuits(self):
        """A carrier_api route with no credential short-circuits to ERROR."""
        state = _routed_state("yamato", "123456789012", "carrier_api")
        result = self.node.execute(state, None)
        assert result["status"] == AgentStatus.ERROR
        assert result["error"] == "missing_credential"

    def test_execute_method_signature(self):
        """A node implements execute(state), not _invoke_impl.

        The framework contract:
          - Override: execute(self, state) -> dict
          - Prohibited: _invoke_impl(), overriding process()
        """
        import inspect

        assert hasattr(MainNode, "execute"), "MainNode must implement execute()"

        sig = inspect.signature(MainNode.execute)
        params = list(sig.parameters.keys())
        assert len(params) >= 2, f"execute() must accept (self, state), got params: {params}"
        assert params[1] == "state", f"Second parameter must be 'state', got '{params[1]}'"
        assert (
            "_invoke_impl" not in MainNode.__dict__
        ), "_invoke_impl() must not be defined in MainNode — use execute() instead"
