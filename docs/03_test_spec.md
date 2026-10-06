# Test Specification — LOG-C2-030 (RealtimeShipmentTrackingAgent)

Describes the tests this repository actually ships. Every row below maps to a
test that exists; run the suite with:

```bash
python -m pytest tests/ -v
```

## Strategy

| Layer | Location | What it covers |
|---|---|---|
| Unit | `tests/unit/` | One node at a time, called through `execute()` directly — no framework wrapper in front, so a guarantee the template owns is proven to be the template's |
| Integration | `tests/integration/` | The compiled graph end to end via `agent.invoke()` |
| Boundary | `tests/proof_of_boundary/` | The framework contract and the agent's own security boundaries, including the real ASGI `/invoke` surface |

Two directions are probed everywhere a screen or gate exists: the hostile form
is refused, **and** ordinary domain input still works. A screen that blocks real
traffic is a defect, not a safety margin.

## Framework contract

| ID | Test | File |
|---|---|---|
| FC-01 | State is a flat `TypedDict` — no Pydantic, no dataclass | `proof_of_boundary/test_state_safety.py` |
| FC-02 | Post-invoke state is primitives only, safe to checkpoint | `proof_of_boundary/test_state_safety.py` |
| FC-03 | No credential or non-serializable object reaches a checkpoint | `proof_of_boundary/test_state_safety.py` |
| FC-04 | The template does not import the platform SDK directly | `proof_of_boundary/test_import_isolation.py` |
| FC-05 | The default input gate cannot be overridden | `unit/test_framework_compliance_tc06_tc07.py` |
| FC-06 | The default output gate cannot be overridden | `unit/test_framework_compliance_tc06_tc07.py` |
| FC-07 | Invoke order: trust gate → node_start → input gate → `execute()` → output gate → node_complete, for every node | `proof_of_boundary/test_pb_invoke_order.py` |
| FC-08 | An under-privileged caller is refused before `execute()` runs | `proof_of_boundary/test_pb_invoke_order.py` |
| FC-09 | Every node declares a non-anonymous trust floor | `unit/test_input_parse.py`, `scripts/check_trust_level.py` |
| FC-10 | Interrupt propagation — skipped, as this template does not enable human-in-the-loop | `proof_of_boundary/test_pb7_hitl_interrupt_propagation.py` |
| FC-11 | A node implements `execute(state)`, not `_invoke_impl` | `unit/test_main_node.py` |
| FC-12 | Every node emits a domain audit event on a reachable path | `scripts/check_audit_trace.py` |

## Input contract

| ID | Test | File |
|---|---|---|
| IN-01 | Empty input is refused | `unit/test_input_parse.py`, `proof_of_boundary/test_shipment_boundary.py` |
| IN-02 | Chat-template control tokens (`<\|…\|>`, `[INST]`, `<<SYS>>`) are refused as a class | `unit/test_input_screen.py` |
| IN-03 | Anchored directive forms are refused | `unit/test_input_screen.py` |
| IN-04 | Role-reassignment onto a privileged role is refused | `unit/test_input_screen.py` |
| IN-05 | A directive spliced through markup is refused once the markup is stripped | `unit/test_input_screen.py` |
| IN-06 | Ordinary logistics prose containing screen vocabulary is **not** refused | `unit/test_input_screen.py` |
| IN-07 | A refusal never echoes the rejected value | `unit/test_input_screen.py` |
| IN-08 | The structured reference channel accepts every supported carrier format | `unit/test_input_screen.py` |
| IN-09 | A non-inert reference (spaces, markup, over-length, wrong type) is refused | `unit/test_input_screen.py` |
| IN-10 | An inert but unrecognised format is refused distinctly | `unit/test_input_screen.py` |
| IN-11 | The structured channel takes priority over the narrative | `unit/test_input_screen.py` |
| IN-12 | A malformed `input_context` type degrades safely | `unit/test_input_screen.py` |
| IN-13 | `deployment_mode` falls back to `coordinator` when absent or unrecognised | `proof_of_boundary/test_shipment_boundary.py` |
| IN-14 | A 12-digit reference in the narrative is masked before parsing — the reason the structured channel exists | `integration/test_graph_invoke.py` |

## Adapter contract

| ID | Test | File |
|---|---|---|
| AD-01 | The context contract is exactly `tracking_number` + `deployment_mode` | `unit/test_adapter_contract.py` |
| AD-02 | An undeclared key is refused with `400`, not ignored | `unit/test_adapter_contract.py` |
| AD-03 | Refusals use `400`, not `422` (which pydantic owns) | `unit/test_adapter_contract.py` |
| AD-04 | A hostile field name is not echoed back | `unit/test_adapter_contract.py` |
| AD-05 | A credential-shaped context value is refused, naming the field only | `unit/test_adapter_contract.py` |
| AD-06 | Ordinary domain values on the same field still pass | `unit/test_adapter_contract.py` |
| AD-07 | The adapter's refusal set equals the framework's block set (anti-drift property test) | `unit/test_adapter_contract.py` |
| AD-08 | An oversized `input_context` is refused with `413` before the agent runs | `unit/test_adapter_contract.py` |
| AD-09 | The public contract carries no caller-supplied numeric — inventory guard | `unit/test_adapter_contract.py` |
| AD-10 | A missing or wrong Bearer token is refused with `401`, without saying which | `proof_of_boundary/test_output_containment.py` |
| AD-11 | A valid Bearer token promotes the caller and the request succeeds | `proof_of_boundary/test_output_containment.py` |

## Output contract

| ID | Test | File |
|---|---|---|
| OU-01 | The template's credential scan catches everything the framework's does | `proof_of_boundary/test_output_containment.py` |
| OU-02 | It additionally catches this domain's own shapes | `proof_of_boundary/test_output_containment.py` |
| OU-03 | The scan walks nested structures, with a clean control alongside | `proof_of_boundary/test_output_containment.py` |
| OU-04 | Ordinary shipment data is not flagged | `proof_of_boundary/test_output_containment.py` |
| OU-05 | A violation clears **every** output-bearing field | `proof_of_boundary/test_output_containment.py` |
| OU-06 | The withheld notice is truthy, so the fallback cannot re-activate | `proof_of_boundary/test_output_containment.py` |
| OU-07 | The gate scans beyond the narrative — the violation is in a sibling field only | `proof_of_boundary/test_output_containment.py` |
| OU-08 | A violation message names the field, never the value, and carries no traceback or path | `proof_of_boundary/test_output_containment.py` |
| OU-09 | An error envelope withholds the domain payload | `proof_of_boundary/test_output_containment.py` |
| OU-10 | An error envelope never re-derives the narrative | `proof_of_boundary/test_output_containment.py` |
| OU-11 | A non-inert error code is replaced with a generic one | `proof_of_boundary/test_output_containment.py` |
| OU-12 | A success envelope does release the domain payload | `proof_of_boundary/test_output_containment.py` |
| OU-13 | Every field the graph releases is a field the gate clears | `proof_of_boundary/test_output_containment.py` |
| OU-14 | End to end: a refused value never reaches the caller through `/invoke` | `proof_of_boundary/test_output_containment.py` |
| OU-15 | The block happened at the output gate, not upstream | `proof_of_boundary/test_output_containment.py` |
| OU-16 | Clean-path control: the same request still returns its real answer | `proof_of_boundary/test_output_containment.py` |
| OU-17 | A policy question scopes out, carrying no tracking data | `unit/test_response.py`, `integration/test_graph_invoke.py` |
| OU-18 | `customer_facing` mode redacts consignee details and internal references | `proof_of_boundary/test_shipment_boundary.py` |
| OU-19 | `coordinator` mode keeps them | `integration/test_graph_invoke.py` |

### Output integrity

This agent renders no monetary aggregates, so no rounding grid applies. It
renders identifiers and digit runs, which such a grid would corrupt — so the
invariant enforced instead is that they pass through untouched.

| ID | Test | File |
|---|---|---|
| OI-01 | Every supported reference format renders byte-identical | `proof_of_boundary/test_output_integrity.py` |
| OI-02 | Timestamps, dates and bare digit runs render byte-identical | `proof_of_boundary/test_output_integrity.py` |
| OI-03 | The output gate passes identifiers through untouched | `proof_of_boundary/test_output_integrity.py` |
| OI-04 | Redaction removes whole marked spans and never rewrites digits | `proof_of_boundary/test_output_integrity.py` |
| OI-05 | No grid-style grouping ever appears in output | `proof_of_boundary/test_output_integrity.py` |

## Credential handling

| ID | Test | File |
|---|---|---|
| CR-01 | Routing carries the credential key name only, never a value | `unit/test_carrier_route.py` |
| CR-02 | The secret value never enters the returned partial dict | `unit/test_tracking_api.py`, `proof_of_boundary/test_shipment_boundary.py` |
| CR-03 | An external carrier call with no resolvable credential is refused | `unit/test_tracking_api.py`, `unit/test_main_node.py` |
| CR-04 | Internal lookups proceed without an external credential | `unit/test_tracking_api.py` |

## Business logic

| ID | Test | File |
|---|---|---|
| BL-01 | Each carrier's status vocabulary maps to the unified schema | `unit/test_status_normalize.py` |
| BL-02 | An exception flag forces the unified status to `exception` | `unit/test_status_normalize.py` |
| BL-03 | An unavailable source degrades to `pending` with a friendly message, not a transport error | `unit/test_tracking_api.py`, `unit/test_response.py` |
| BL-04 | The answer always carries the data-freshness timestamp | `unit/test_response.py` |
| BL-05 | The estimated delivery is framed as an estimate, never a guarantee | `unit/test_response.py` |
| BL-06 | An unknown or ambiguous carrier is refused rather than guessed | `unit/test_carrier_route.py` |
| BL-07 | End-to-end happy path over the internal source | `integration/test_graph_invoke.py` |
| BL-08 | End-to-end happy path over a carrier API with a bound credential | `integration/test_graph_invoke.py` |

## Execution summary

Run under the SDK version the pipeline installs. The suite is expected to be
fully green, with the interrupt-propagation cases skipping because this
template does not enable human-in-the-loop.
