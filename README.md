# Real-Time Shipment Tracking Agent

AI agent for tracking shipments in real time across carriers, built with Agentic Star.

> **Category**: Cat 2 (multi-step domain workflow)
> **Industry**: Logistics
> **Template ID**: LOG-C2-030

## Overview

Answers natural-language questions about where a shipment is. Given a consignment
reference, it identifies the carrier from the reference format, looks the shipment up against
that carrier's tracking source, reconciles the carrier's own status vocabulary into one
consistent set of states (`in_transit`, `delivered`, `exception`, `pending`), and returns a plain
answer with the estimated delivery date, any exception flags, and the age of the data it used.

Different carriers describe the same shipment in incompatible ways — one returns a numeric status
code, another a text state, another a customs hold reason. This template's job is to hide that
difference behind a single question-and-answer surface, so a caller asks "where is this?" once
rather than integrating each carrier separately.

Questions that are about policy rather than location — claims, compensation, returns — are
detected and routed out rather than answered from tracking data.

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent connects to the platform at start-up. Without it, start-up fails immediately (see *Behaviour without the platform* below). Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Installed from PyPI as a dependency. |
| Python | >=3.11 |

```bash
pip install -e .
```

### Behaviour without the platform

The framework is designed to run **only** on AGENTIC STAR. There is no fallback or degraded
mode. If the platform is unreachable or the SDK version does not match, the agent fails at
graph compile / start-up preflight rather than starting in a partially working state. This is intentional — a half-running agent is worse than one that refuses to start.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Tests run without a platform connection. Running the agent itself does not.

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit, integration and boundary tests
config/       agent configuration
docs/         design and operational documentation
```

See `docs/` for the design and the test specification.

## Customising

1. Adjust `config/` for your own environment and policies.
2. Replace the knowledge sources and sample data with your own.
3. Review the node implementations under `src/nodes/` for domain-specific logic.
4. Re-run the test suite.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.
