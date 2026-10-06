# LOG-C2-030 — Unit tests: TrackingAPICall node

from src.nodes.tracking_api_call_node import TrackingAPICallNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext


class _FakeSecrets:
    def __init__(self, mapping):
        self._m = mapping

    def get(self, key, default=None):
        return self._m.get(key, default)


def _routed_state(carrier, tracking, data_source, credential_key):
    return {
        "carrier_code": carrier,
        "tracking_number": tracking,
        "data_source": data_source,
        "live_data_response": {
            "_routing": {
                "carrier_code": carrier,
                "data_source": data_source,
                "credential_key": credential_key,
            }
        },
    }


def _config_with_secret(key, value):
    # InvocationContext is a frozen dataclass — the provider is supplied at
    # construction, never assigned afterwards.
    ctx = InvocationContext(secrets=_FakeSecrets({key: value}))
    return {"configurable": {"invocation_context": ctx}}


class TestTrackingAPICallNode:
    def setup_method(self):
        self.node = TrackingAPICallNode()

    def test_carrier_api_with_credential_returns_raw(self):
        state = _routed_state("yamato", "123456789012", "carrier_api", "YAMATO_API_KEY")
        cfg = _config_with_secret("YAMATO_API_KEY", "secret-value-xyz")
        r = self.node.execute(state, cfg)
        assert r["status"] == AgentStatus.SUCCESS
        assert r["live_data_response"]["_available"] is True
        assert r["data_timestamp"] == "2026-06-08 09:15"

    def test_missing_credential_refuses_carrier_api(self):
        """A carrier API call with no resolvable credential is refused."""
        state = _routed_state("yamato", "123456789012", "carrier_api", "YAMATO_API_KEY")
        # config with NO secret bound for the key
        cfg = _config_with_secret("OTHER_KEY", "x")
        r = self.node.execute(state, cfg)
        assert r["status"] == AgentStatus.ERROR
        assert r["error"] == "missing_credential"

    def test_secret_value_never_in_state(self):
        """The secret value must not leak into the returned partial dict."""
        state = _routed_state("yamato", "123456789012", "carrier_api", "YAMATO_API_KEY")
        cfg = _config_with_secret("YAMATO_API_KEY", "super-secret-token-123")
        r = self.node.execute(state, cfg)
        assert "super-secret-token-123" not in str(r)

    def test_internal_lookup_without_credential_ok(self):
        """Internal lookups do not require an external carrier credential."""
        state = _routed_state("tms", "TMS000042", "tms", "TMS_API_KEY")
        r = self.node.execute(state, None)
        assert r["status"] == AgentStatus.SUCCESS
        assert r["live_data_response"]["_available"] is True

    def test_graceful_degradation_unknown_tracking(self):
        """Unknown tracking number → friendly unavailable signal, not a tool error."""
        state = _routed_state("tms", "TMS99999", "tms", "TMS_API_KEY")
        r = self.node.execute(state, None)
        assert r["status"] == AgentStatus.SUCCESS
        assert r["live_data_response"]["_available"] is False
        assert "unavailable" in r["live_data_response"]["_message"]
