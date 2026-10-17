"""The context layer: what Kairos gives any agent that connects to it.

An agent that has never seen this warehouse should be able to orient itself,
find data by what it means, understand how far to trust it, learn how to use
it, and report back when something is wrong — with no setup of its own.

  documents    flatten each entity (profile, columns, links) into a searchable document
  embeddings   meaning vectors for those documents (Azure OpenAI)
  search       hybrid search: meaning + keywords + names, merged by rank fusion
  orientation  "what have I been connected to?" — domains, products, trust, freshness
  cards        everything about one entity, with trust and usage as fields
  joins        how two tables join, and on what evidence
  feedback     agents report wrong, missing or stale context
  access       agent keys, workspace scoping, and the audit trail
"""
