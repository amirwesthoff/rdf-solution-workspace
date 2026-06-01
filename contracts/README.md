# Contracts

Semantic contract artifacts used by all pipelines.

The current domain is retail order analytics using synthetic data only.

## Contents

- `ontology/core.ttl`: retail ontology terms (Customer, Product, Order, OrderLine, Store).
- `shapes/core.shacl.ttl`: retail SHACL constraints and structural quality checks.
- `sample-data/sample.ttl`: synthetic retail dataset for local demos.
- `competency-questions/`: SPARQL competency questions for business validation.

## Competency Question Registry

- Registry file: `competency-questions/cq-registry.yaml`
- Each CQ has a stable ID (for example `CQ-001`) and natural-language wording.
- Query templates refer back to CQ IDs in header comments at the top of each `.rq` file.
- Planned CQs can exist in the registry before a SPARQL template is implemented.

## Versioning Policy

Use semantic versioning for contract changes:

- Patch: non-breaking clarifications
- Minor: backward-compatible additions
- Major: breaking changes
