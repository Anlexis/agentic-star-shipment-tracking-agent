# LOG-C2-030 — Unit Tests: CarrierRoute node (#4)

from src.nodes.carrier_route_node import CarrierRouteNode
from framework.schemas.agent_status import AgentStatus


class TestCarrierRouteNode:
    def setup_method(self):
        self.node = CarrierRouteNode()

    def test_yamato_routes_to_carrier_api(self):
        r = self.node.execute({"carrier_code": "yamato"})
        assert r["status"] == AgentStatus.SUCCESS
        assert r["data_source"] == "carrier_api"
        routing = r["live_data_response"]["_routing"]
        assert routing["credential_key"] == "YAMATO_API_KEY"

    def test_tms_routes_to_tms(self):
        r = self.node.execute({"carrier_code": "tms"})
        assert r["status"] == AgentStatus.SUCCESS
        assert r["data_source"] == "tms"

    def test_unknown_carrier_errors(self):
        r = self.node.execute({"carrier_code": "fedex"})
        assert r["status"] == AgentStatus.ERROR
        assert r["error"] == "unknown_carrier"

    def test_missing_carrier_errors(self):
        r = self.node.execute({"carrier_code": None})
        assert r["status"] == AgentStatus.ERROR

    def test_only_key_name_not_secret(self):
        """Routing carries the credential KEY NAME only — never a value."""
        r = self.node.execute({"carrier_code": "sagawa"})
        routing = r["live_data_response"]["_routing"]
        # key name present, but no secret value field anywhere in the partial dict
        assert routing["credential_key"] == "SAGAWA_API_KEY"
        flat = str(r).lower()
        assert "sk-" not in flat
        assert "bearer " not in flat
