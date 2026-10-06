# Template Design Specification — LOG-C2-030 (RealtimeShipmentTrackingAgent)

Design of record for the real-time shipment tracking agent. This document describes what the
repository actually ships; where a design option was considered and rejected, the decision record
at the end says so.

## Position in the framework

| Property | Value |
|---|---|
| Agent class | `RealtimeShipmentTrackingAgent` (`src/graph/graph.py`) |
| L1 Base (framework base class) | `AgentBaseGraph` — direct framework inheritance |
| Category | Cat 2 — a domain-specific multi-step workflow, not a single generic capability |
| Generation mode | `deterministic` — the answer is assembled from normalized data by template code; no language model is invoked |
| Human-in-the-loop | not enabled |

`AutonomousBaseGraph` is deliberately not used: this is a fixed per-query pipeline
(parse → route → look up → normalize → generate → gate), not a self-directed loop. See DR-1.

### Three-layer separation

- **State** — a flat `TypedDict` (`State(AgentState)`, `src/schemas/state.py`) holding primitives
  and JSON-serializable values only, so checkpoint serialization stays safe. No credentials and no
  recipient personal data are persisted.
- **Node** — each business step is a `FunctionNode` under `src/nodes/` overriding
  `execute(self, state: dict) -> dict` and returning **only the fields it changes**, with an
  `AgentStatus` enum rather than a bare string.
- **Graph** — composition via `register_nodes()`, filling the fixed `pre_process` / `main` /
  `post_process` slots. `initialize` and `finalize` are injected by `super().register_nodes()`.

## Architecture

### Node configuration

Six business steps are composed onto the three domain slots. The slot node runs its sub-steps
inline and merges their partial dicts, short-circuiting on the first error.

| Slot | Business node(s) | Responsibility | Reads | Writes |
|---|---|---|---|---|
| initialize | — | session and trace identifiers | `user_input` | `session_id`, `trace_id` |
| pre_process | **InputParse** → **CarrierRoute** | Screen the query for instruction-injection; resolve and validate the consignment reference; identify the carrier from its format; select the data source and the credential **key name** | `user_input`, `input_context` | `raw_query`, `tracking_number`, `carrier_code`, `data_source`, `deployment_mode` |
| main | **TrackingAPICall** → **StatusNormalize** | Dispatch the lookup against the routed source and capture the source's own freshness timestamp; reconcile the carrier's status vocabulary into the unified schema | `tracking_number`, `carrier_code`, `data_source` | `live_data_response`, `unified_status`, `eta`, `exception_flags`, `data_timestamp` |
| post_process | **ResponseGenerate** → **ResponseValidate** | Assemble the answer from normalized data; then gate it — scope-out policy questions, redact personal data in customer-facing mode, refuse and contain credential-shaped output | `unified_status`, `eta`, `exception_flags`, `data_timestamp` | `nl_response`, `formatted_output`, `scope_out` |
| finalize | — | response metadata | `nl_response` | `response_metadata` |

### Data flow

```
START → initialize → pre_process(InputParse → CarrierRoute)
                   → main(TrackingAPICall → StatusNormalize)
                   → post_process(ResponseGenerate → ResponseValidate)
                   → finalize → END
```

Backbone edges into the domain slots are unconditional, so a slot that receives an upstream error
passes it through untouched rather than acting on partial state. The inherited `route()` sends an
errored state to `finalize`.

Outcomes other than the straight path:

- **No usable consignment reference** — `InputParse` returns an error; the run finalizes without a
  lookup. The caller receives an error envelope naming the reason.
- **Instruction-injection detected in the query** — refused at `InputParse`, before routing, the
  lookup, or any generated text.
- **Source unavailable** — `TrackingAPICall` degrades gracefully: it records that no data was
  available rather than surfacing a transport error, and the answer says tracking is temporarily
  unavailable.
- **Missing credential for an external carrier** — the call is refused rather than attempted
  unauthenticated.
- **Policy or claims question** — `ResponseValidate` sets `scope_out` and returns a redirect notice
  instead of an answer built from tracking data.

### Input channels

The consignment reference may arrive two ways, checked in this order:

1. `input_context["tracking_number"]` — a structured field locked to `[A-Za-z0-9]{1,18}`.
2. The narrative question — scanned token by token; each token is reduced to its alphanumeric
   characters and kept if it matches a known format.

The structured channel is not a convenience. Free-text input passes through the framework's
personal-data mask before any node sees it, and a bare 12-digit run is indistinguishable from a
national identification number — so a 12-digit reference embedded in a sentence arrives already
masked and cannot be recovered. Callers holding the reference as a field should send it as a field.

### State definition

Flat `TypedDict` extending `AgentState`. Inherited: `user_input`, `input_context`, `status`,
`session_id`, `node_history`, `error_log`.

| Field | Type | Purpose | Required |
|---|---|---|---|
| `raw_query` | `str` | the question as received, after screening | yes |
| `tracking_number` | `str` | validated consignment reference | yes |
| `carrier_code` | `str \| None` | `yamato` / `sagawa` / `jppost` / `tms`, or `None` | no |
| `data_source` | `"tms" \| "carrier_api"` | routing decision | yes |
| `live_data_response` | `dict` | normalized source response; no personal data persisted | no |
| `unified_status` | `"in_transit" \| "delivered" \| "exception" \| "pending"` | reconciled status | yes |
| `eta` | `str \| None` | source-estimated delivery, when provided | no |
| `exception_flags` | `list[str]` | subset of `delay` / `customs` / `damage` / `returned` | no |
| `data_timestamp` | `str` | source freshness, rendered as "data as of HH:MM" | yes |
| `nl_response` | `str` | assembled answer | yes |
| `scope_out` | `bool` | the question was policy, not tracking | no |
| `deployment_mode` | `"coordinator" \| "customer_facing"` | controls redaction; defaults to `coordinator` | no |
| `error` | `str \| None` | short inert failure code | no |

Constraints: flat `TypedDict` only; no carrier credential and no recipient personal data in state
or in trace logs; the secrets accessor is reached through `InvocationContext`, never `os.environ`.

## Data sources

| Source | Access | Notes |
|---|---|---|
| Internal transport-management system | credential resolved through `InvocationContext` | unified internal schema |
| Yamato Transport API | per-carrier credential | own status taxonomy → mapping table |
| Sagawa Express API | per-carrier credential | own status taxonomy → mapping table |
| JP Post API | per-carrier credential | own status taxonomy → mapping table |

**What ships in this repository:** the dispatch step resolves the credential and then reads a
deterministic reference dataset (`_STUB_RESPONSES` in `src/nodes/tracking_api_call_node.py`) rather
than making live HTTP calls, so the whole pipeline is exercisable without carrier agreements.
Replacing that dataset with a real transport is the integration point; nothing else in the pipeline
changes, because everything downstream consumes the normalized shape.

The per-carrier status mapping tables live in `src/nodes/status_normalize_node.py`. Every carrier
code maps to one of `in_transit | delivered | exception | pending`, and exception detail is
extracted into `exception_flags`. An exception flag forces the unified status to `exception` unless
the shipment is already delivered.

Credentials are referenced by **key name only** (`src/nodes/carrier_route_node.py`); the value is
resolved at call time and used solely to decide whether the call may proceed. It is never returned
in a node's partial dict, written to state, or logged.

## Security design

| Concern | Where it is enforced | What this template does |
|---|---|---|
| Caller trust | `required_trust_level` on every registered node | `VERIFIED_EXTERNAL`. The standalone adapter promotes a caller to that level only after a Bearer token check, when one is configured. |
| Hostile input | `InputParseNode.execute` | Screens the query for chat-template control tokens (`<\|…\|>`, `[INST]`, `<<SYS>>`) as a class, and for anchored directive and role-reassignment forms — scanning both the text as received and the text after markup removal, so neither a control-token payload nor a directive spliced through markup survives. Refusal happens in the template's own node, not only in the framework gate, so the guarantee holds wherever the agent runs. |
| Unbounded input | `InputParseNode`, adapter | The consignment reference is locked to an inert alphanumeric identifier; the context channel accepts only declared keys and is size-capped at the adapter. |
| Personal data | `ResponseValidateNode` | In `customer_facing` mode, consignee details, internal references and phone-shaped runs are redacted before release. |
| Output containment | `ResponseValidateNode` + `RealtimeShipmentTrackingAgent.get_output` | See below. |
| Audit | every node | Each `execute()` emits a domain trace event carrying codes and flags — never the consignment reference's surroundings, a credential, or recipient detail. |

### Output containment

The output gate refuses when any output-bearing field carries a credential shape. Two properties
make the naive form of that gate insufficient, and both are addressed:

1. **The scan covers every output-bearing field, not just the narrative.** A carrier-supplied `eta`
   is caller-visible output exactly as the narrative is. Scanning only the narrative lets a refused
   value ship in a sibling field.
2. **A refusal clears state, and the envelope withholds.** Returning an error status is not by
   itself containment: the graph's output assembly reads state fields directly, and a *falsy*
   withheld marker falls back to the un-gated answer. So the gate clears every output-bearing field
   and sets a **truthy** notice, and `get_output` releases domain fields only on the success path.

The two layers are deliberately independent and separately tested, so neither can conceal a
regression in the other.

The credential scan calls the framework's own detector and adds domain patterns on top. It is never
narrower than the framework's set: a value the framework catches and the template misses would make
the framework raise inside post-processing, and the wrapper would then discard the gate's clearing
along with the rest of its delta.

### Numeric and structural bounds

The agent takes no caller-supplied numeric parameter — there is no threshold, ratio, top-k or
scenario table on the public contract. The only caller-controlled values are the question text, the
consignment reference (inert identifier) and `deployment_mode` (a closed two-value enum, defaulting
to the redacting mode when absent or unrecognised). Bounds are therefore structural: declared keys
only, size cap, identifier pattern, enum membership.

The agent renders **no monetary aggregates**, so no rounding grid applies. What it does render is
identifiers and digit runs — consignment references of 11 to 13 digits. Any output transform that
rewrote digit runs would corrupt the agent's primary output, so none is applied, and a boundary
test pins representative references as passing through byte-identical.

## Framework facilities used

- `InvocationContext` — correlation and session identifiers, caller trust level, secrets accessor.
- `emit_trace_event` — structured audit records.
- `FunctionNode` input and output gates — the framework's own personal-data mask and credential
  scan, with the template's checks layered on top.
- `detect_credentials` / `detect_credentials_in_value` — the credential pattern set, used directly
  so the template's block set matches the framework's exactly.

### Composition

- **Pattern**: fixed three-slot backbone; each slot orchestrates its sub-steps inline.
- **Invoke chain**: the agent is entered through `.invoke()`.
- **Error propagation**: nodes return `AgentStatus.ERROR` with an `error_log` entry; the graph
  routes to finalize and the caller receives an error envelope, never a raised transport exception.

## Import isolation

- The template does not import the platform SDK directly.
- Import targets are `framework/` and `shared/` only.

## Design decision record

| ID | Decision | Option A | Option B | Chosen | Rationale |
|---|---|---|---|---|---|
| DR-1 | Base class | `AgentBaseGraph` | `AutonomousBaseGraph` | **A** | Fixed per-query pipeline; no autonomous loop and no self-directed termination |
| DR-2 | Lookup dispatch | One lookup per query | Multi-call reasoning loop | **A** | One consignment reference resolves to one lookup. A loop would be justified only by compound questions ("which of my orders are late?"), which are out of scope here |
| DR-3 | Slot mapping | Six steps grouped into three slots | `main` as a nested subgraph of six discrete nodes | **A** | Keeps the graph flat and the state one level deep. A nested graph would also require bridging the context channel into the inner graph, which the framework does not forward |
| DR-4 | Redaction policy | One redaction level | Per-`deployment_mode` | **B** | Internal coordinators need full consignee detail; customer-facing must not have it. The default is the **redacting** mode, so an unset or unrecognised value fails safe |
| DR-5 | Reference channel | Narrative only | Narrative plus a structured field | **B** | The framework's personal-data mask cannot distinguish a 12-digit consignment reference from a national identification number, so the narrative channel alone loses the agent's most common input |
