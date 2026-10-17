---
type: Convention
title: OKF Conventions Used in This Bundle
description: How this bundle applies Google's Open Knowledge Format v0.2 and which producer extension keys it adds.
tags:
- okf
- conventions
generated:
  by: claude-opus-5.5/us-pharma-kb-builder
  at: '2026-10-02T00:00:00Z'
sources:
- id: okf-spec
  resource: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md
  title: OKF SPEC.md (Google Cloud)
- id: okf-blog
  resource: https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing/
  title: 'Google Cloud blog: Open Knowledge Format'
resource: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md
relations:
- predicate: defines
  target: /_meta/relation-vocabulary.md
- predicate: defines
  target: /_meta/type-vocabulary.md
---
# Definition
How this bundle applies Google's Open Knowledge Format v0.2 and which producer extension keys it adds.[^okf-spec][^okf-blog]

# Rules applied
* One concept = one UTF-8 Markdown file with YAML frontmatter; the concept ID is the file path without `.md`.
* `type` is always set. `title`, `description`, `tags`, `resource`, `sources`, `generated`, `stale_after` are filled where known.
* `index.md` files list every concept and sub-section; `log.md` at the root records changes, newest first.
* Links are absolute (`/domain/concept.md`).

# Producer extensions (spec-permitted extra keys)
* `relations:` — list of `{predicate, target}` typed edges. OKF links are untyped; this key carries the edge type. Every relation is mirrored in the body under `# Relationships` so OKF-only consumers still see the link.
* Dataset Type concepts add `dataset_category`, `grain`, `primary_key`, `join_keys`, `refresh_cadence`, `projection`, `measures`, `phi_status`.
* Warehouse Table concepts add `kairos_entity_id`, `kairos_trust_level`, `layer`.

# Trust
All concepts were machine-generated (`generated.by`) and carry no `verified` entry, so OKF consumers should treat them as *unverified* until a domain owner adds `verified: [{by: human:<id>, at: ...}]`.

# Relationships
* **defines** → [Relation Vocabulary](/_meta/relation-vocabulary.md)
* **defines** → [Concept Type Vocabulary](/_meta/type-vocabulary.md)

[^okf-spec]: [OKF SPEC.md (Google Cloud)](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
[^okf-blog]: [Google Cloud blog: Open Knowledge Format](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing/)
