---
type: Vocabulary
title: Relation Vocabulary
description: Controlled list of predicates allowed in the `relations:` extension key.
tags:
- okf
- vocabulary
- graph
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
---
# Definition
Controlled list of predicates allowed in the `relations:` extension key.

| Predicate | Meaning |
|---|---|
| `is_a` | subtype / instance of |
| `part_of` | component or member of |
| `regulated_by` / `enforced_by` / `established_by` | legal or regulatory control |
| `requires` | precondition |
| `submits_to` / `reports_to` | sends data or filings to |
| `identified_by` / `assigned_by` / `identifies` | identifier relationships |
| `generates_data` / `captured_by` / `derived_from` / `feeds` | data lineage |
| `provided_by` / `provides` | vendor relationships |
| `uses_standard` / `used_in` / `maintained_by` | standards: what uses it and who maintains it |
| `adjudicated_by` / `pays` / `contracts_with` / `ships_to` / `dispenses` / `prescribes` | business transactions |
| `affiliated_with` / `aligned_to` | organisational mapping |
| `joins_to` | dataset join path |
| `measures` | metric relationship |
| `supersedes` / `superseded_by` | versioning |
| `feeds` / `provides` / `ships_to` | data or product delivery |
| `restricted_by` | licence/privacy limitation |
| `implements` / `instance_of` | physical table realises a logical entity / dataset type |
| `defines` / `related_to` | documentation links |

