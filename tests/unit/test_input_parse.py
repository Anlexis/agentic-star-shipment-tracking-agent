# LOG-C2-030 — Unit Tests: InputParse node (#3)

from src.nodes.input_parse_node import InputParseNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel


class TestInputParseNode:
    def setup_method(self):
        self.node = InputParseNode()

    def test_trust_level_is_input_facing(self):
        """The input-facing node declares a non-anonymous trust floor."""
        assert InputParseNode.required_trust_level == TrustLevel.VERIFIED_EXTERNAL

    def test_yamato_12_digit(self):
        state = {"user_input": "Where is my package 123456789012?"}
        r = self.node.execute(state)
        assert r["status"] == AgentStatus.SUCCESS
        assert r["tracking_number"] == "123456789012"
        assert r["carrier_code"] == "yamato"

    def test_sagawa_11_digit(self):
        r = self.node.execute({"user_input": "track 11122233344 please"})
        assert r["status"] == AgentStatus.SUCCESS
        assert r["carrier_code"] == "sagawa"
        assert r["tracking_number"] == "11122233344"

    def test_jppost_format(self):
        r = self.node.execute({"user_input": "status of EE123456789JP"})
        assert r["status"] == AgentStatus.SUCCESS
        assert r["carrier_code"] == "jppost"

    def test_tms_internal_id(self):
        r = self.node.execute({"user_input": "lookup TMS000042"})
        assert r["status"] == AgentStatus.SUCCESS
        assert r["carrier_code"] == "tms"
        assert r["tracking_number"] == "TMS000042"

    def test_sanitizes_separators(self):
        """Non-alphanumeric characters are stripped before matching."""
        r = self.node.execute({"user_input": "track 1234-5678-9012"})
        assert r["status"] == AgentStatus.SUCCESS
        assert r["tracking_number"] == "123456789012"

    def test_empty_input_refused(self):
        """Empty input is refused."""
        r = self.node.execute({"user_input": "   "})
        assert r["status"] == AgentStatus.ERROR
        assert r["error"] == "empty_input"

    def test_no_tracking_number_short_circuits(self):
        """Injection guard: a query with no valid tracking number → ERROR."""
        r = self.node.execute({"user_input": "hello, how are you today?"})
        assert r["status"] == AgentStatus.ERROR
        assert r["error"] == "no_tracking_number"

    def test_injection_string_rejected(self):
        """A long arbitrary token that matches no carrier format is rejected."""
        r = self.node.execute({"user_input": "'; DROP TABLE shipments; --"})
        assert r["status"] == AgentStatus.ERROR
        assert "tracking_number" not in r or not r.get("tracking_number")
