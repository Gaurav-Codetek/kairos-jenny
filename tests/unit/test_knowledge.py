"""Industry knowledge: reading an OKF bundle, matching tables and columns to it, rules on cards."""

from types import SimpleNamespace

import pytest

from kairos_kb.knowledge.binding import (
    IDENTIFIER_PATTERNS,
    identifier_like,
    identifier_patterns,
    identify_columns,
    score_table,
    signature,
)
from kairos_kb.knowledge.context import _why, applicable_rules, parse_rules, topics_for
from kairos_kb.knowledge.loader import normalise_target, parse_concept, read_bundle

DATASET = """---
type: Dataset Type
title: 3PL EDI 867 Feed
description: Product movement from a third-party logistics provider.
tags: [867, edi]
grain: invoice line
primary_key: [INVOICE_ID, INVOICE_ITEM, SOURCE]
join_keys: [CUST_DEA / HCO_DEA, NDC_CODE]
phi_status: none
relations:
- predicate: related_to
  target: /identifiers/product/ndc.md
---
# Definition
What a 3PL sends.[^a]

# Schema
| Field | Meaning |
|---|---|
| `INVOICE_ID` | invoice |
| `CUST_*` | ship-to customer fields |
| `QUANTITY` | units |
| `WAC` | price |

# Pitfalls
* Returns are negative.

[^a]: a source
"""


def concept(cid, text, ctype="Dataset Type"):
    front, sections = parse_concept(text)
    fields = {k: v for k, v in front.items() if k not in {"type", "title", "description", "tags", "relations", "sources"}}
    return SimpleNamespace(concept_id=cid, type=ctype, title=front["title"], tags=front.get("tags"),
                           fields=fields, sections=sections)


def test_parse_concept_splits_sections_and_drops_footnotes():
    front, sections = parse_concept(DATASET)
    assert front["type"] == "Dataset Type" and front["grain"] == "invoice line"
    assert sections["Definition"] == "What a 3PL sends."
    assert "Returns are negative" in sections["Pitfalls"]
    assert parse_concept("no frontmatter") is None
    assert parse_concept("---\ntitle: x\n---\nbody") is None  # no type


def test_relation_targets_become_concept_ids():
    assert normalise_target("/identifiers/product/ndc.md") == "/identifiers/product/ndc"
    assert normalise_target("actors/x") == "/actors/x"


def test_read_bundle_skips_navigation_and_excluded_folders(tmp_path):
    (tmp_path / "data-assets").mkdir()
    (tmp_path / "warehouse").mkdir()
    (tmp_path / "data-assets" / "edi-867-3pl.md").write_text(DATASET, encoding="utf-8")
    (tmp_path / "data-assets" / "index.md").write_text("---\ntype: Index\ntitle: i\n---\n", encoding="utf-8")
    (tmp_path / "warehouse" / "fct.md").write_text(DATASET, encoding="utf-8")
    (tmp_path / "index.md").write_text('okf_version: "0.2"\n# My Pack\n', encoding="utf-8")
    concepts, relations, meta = read_bundle(tmp_path, exclude=["warehouse"])
    assert [c["concept_id"] for c in concepts] == ["/data-assets/edi-867-3pl"]
    assert relations == [("/data-assets/edi-867-3pl", "related_to", "/identifiers/product/ndc")]
    assert meta["okf_version"] == "0.2" and meta["title"] == "My Pack" and len(meta["version"]) == 16
    # The version follows the content.
    (tmp_path / "data-assets" / "edi-867-3pl.md").write_text(DATASET.replace("units", "cases"), encoding="utf-8")
    assert read_bundle(tmp_path, exclude=["warehouse"])[2]["version"] != meta["version"]


def test_signature_reads_keys_schema_patterns_and_name_hints():
    sig = signature(concept("/data-assets/sales-distribution/edi-867-3pl", DATASET))
    assert {"invoice_id", "invoice_item", "cust_dea", "hco_dea", "ndc_code", "wac"} <= sig["exact"]
    assert not {"source", "quantity"} & sig["exact"]  # too generic to be evidence
    assert sig["prefixes"] == {"cust_"}
    assert "867" in sig["hints"]


def test_a_table_matching_the_signature_and_name_scores_high():
    sig = signature(concept("/x/edi-867-3pl", DATASET))
    score, ev = score_table(sig, "cat.silver.fct_867", ["INVOICE_ID", "INVOICE_ITEM", "CUST_NAME", "QUANTITY", "WAC", "NDC_CODE"])
    assert score > 0.75
    assert ev["name_hints"] == ["867"] and "cust_*" in ev["matched_patterns"]


def test_identifier_columns_alone_are_not_membership():
    # A table carrying an NDC or a DEA number joins to 867 data; it is not 867 data.
    sig = signature(concept("/x/edi-867-3pl", DATASET))
    assert score_table(sig, "cat.gold.product_dim", ["NDC_CODE", "PRODUCT_NAME"])[0] == 0
    assert score_table(sig, "cat.gold.accounts", ["CUST_DEA", "INVOICE_ID"])[0] == 0  # one pattern, no name hint
    assert identifier_like("NDC_CODE") and identifier_like("hcp_id") and not identifier_like("QUANTITY")


def test_hints_that_are_field_names_are_dropped():
    nppes = concept("/data-assets/reference/nppes", "---\ntype: Dataset Type\ntitle: NPPES NPI File\n"
                    "primary_key: [NPI]\n---\n# Schema\n| f |\n|---|\n| `NPI` |\n| `ENTITY_TYPE` |\n")
    sig = signature(nppes)
    assert "npi" not in sig["hints"] and "nppes" in sig["hints"]
    assert score_table(sig, "cat.s.t_npi_tweet", ["npi", "tweet"])[0] == 0


@pytest.mark.parametrize("column, concept_id", [
    ("NDC_CODE", "/identifiers/product/ndc"),
    ("ndc11", "/identifiers/product/ndc"),
    ("HCO_NPI", "/identifiers/provider/npi"),
    ("npi_id", "/identifiers/provider/npi"),
    ("CUST_DEA", "/identifiers/provider/dea-number"),
    ("CUST_HIN", "/identifiers/provider/hin"),
    ("ORG_VID", "/identifiers/provider/veeva-vid"),
    ("me_number", "/identifiers/provider/ama-me-number"),
    ("ims_prescriber_id", "/identifiers/provider/ims-prescriber-id"),
    ("usc_code", "/identifiers/product/usc"),
    ("payer_plan_id", "/identifiers/payer/plan-id"),
    ("NPI_VOD", "/identifiers/provider/npi"),
    ("NDC_Norm", "/identifiers/product/ndc"),
    ("prov_rendering_npi", "/identifiers/provider/npi"),
])
def test_identifier_columns_are_recognised(column, concept_id):
    concepts = [SimpleNamespace(concept_id=c, type="Identifier", fields={}) for c in IDENTIFIER_PATTERNS]
    assert identify_columns([column], identifier_patterns(concepts)) == [(column, concept_id)]


@pytest.mark.parametrize("column", ["vendor_name", "spinach", "hindsight", "deadline", "INVOICE_ID", "dealer",
                                    "UNIQ_DRUGS_WITH_NPI", "UNIQ_FINAL_REGIMEN_NAME_WITH_NPI", "USC_DESCRIPTION",
                                    "BB_USC_DESCRIPTION", "OK_NPI_IN_CONTRACT", "NPI_COUNT", "HIN_FLAG"])
def test_ordinary_columns_are_not_identifiers(column):
    concepts = [SimpleNamespace(concept_id=c, type="Identifier", fields={}) for c in IDENTIFIER_PATTERNS]
    assert identify_columns([column], identifier_patterns(concepts)) == []


def test_a_concept_can_carry_its_own_column_patterns():
    custom = SimpleNamespace(concept_id="/identifiers/x/abc", type="Identifier", fields={"column_patterns": ["^abc_no$"]})
    assert identify_columns(["ABC_NO", "abc"], identifier_patterns([custom])) == [("ABC_NO", "/identifiers/x/abc")]


RULES = SimpleNamespace(concept_id="/_meta/data-quality-rules", sections={"Definition": """Intro.

* **NDC:** strip dashes.
* **NPI:** 10 digits.
* **Zip:** keep leading zeros.
* **867:** net sales = sold - returned.
* **Medical claims:** collapse versions.
* **Never re-identify.** Patient-level data is de-identified.
* **Off-label/OPDP.** Promotional content stays on-label."""})


def test_rules_are_read_from_bullets():
    rules = parse_rules(RULES)
    assert [r["rule"] for r in rules] == ["NDC", "NPI", "Zip", "867", "Medical claims", "Never re-identify", "Off-label/OPDP"]
    assert rules[0]["text"] == "NDC: strip dashes."


def test_only_rules_about_what_the_table_holds_apply():
    ds = concept("/data-assets/sales-distribution/edi-867-3pl", DATASET)
    topics = topics_for([ds], ["/identifiers/product/ndc"], ["CUST_ZIP"])
    applied = [r["rule"] for r in applicable_rules(parse_rules(RULES), topics)]
    assert applied == ["NDC", "Zip", "867"]
    claims = SimpleNamespace(concept_id="/x/apld", title="Patient claims", tags=[], fields={"phi_status": "de-identified PHI"})
    applied = [r["rule"] for r in applicable_rules(parse_rules(RULES), topics_for([claims], [], []))]
    assert "Never re-identify" in applied and "Off-label/OPDP" not in applied


def test_why_explains_a_binding():
    text = _why({"matched_keys": ["invoice_id"], "matched_patterns": ["cust_*"], "name_hints": ["867"],
                 "meaning_similarity": 0.8})
    assert text == "key columns invoice_id; column patterns cust_*; name mentions 867; meaning similarity 0.8"
    assert _why(None) is None
