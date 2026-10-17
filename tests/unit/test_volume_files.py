"""Governed Volume file reads: paths, permissions, masking, redaction."""

import asyncio
import uuid

import pytest

from kairos_kb.context.access import AgentIdentity
from kairos_kb.context.files import _mask_json, _parse_delimited, check_path, extension, read_volume_file, redact_values
from kairos_kb.context.query import MASK


@pytest.mark.parametrize("path, ok", [
    ("/Volumes/cat/sch/vol/uploads/RAW_867_DLY.csv", True),
    ("/Volumes/cat/sch/vol", True),
    ("/Volumes/cat/sch", False),                       # not down to a volume
    ("/Workspace/Users/a/notebook", False),            # not a Volume
    ("abfss://c@acct.dfs.core.windows.net/x.csv", False),
    ("/Volumes/cat/sch/vol/../../other/x.csv", False),
    ("/Volumes/cat/sch/vol//x.csv", False),
])
def test_only_plain_volume_paths_are_read(path, ok):
    assert (check_path(path) is None) is ok


def test_extensions():
    assert extension("/Volumes/a/b/c/x.CSV") == "csv"
    assert extension("/Volumes/a/b/c/noext") == ""


def test_csv_with_a_header_masks_identifying_columns_and_redacts_values():
    text = ("INVOICE_ID,CUST_NAME,CUST_STATE,NOTE,AMOUNT\n"
            "I1,Ana Pharmacy,FL,call 555-123-4567 or ana@x.com,10.5\n"
            "I2,Bo Clinic,GA,ok,3\n"
            "I3,Cut Off Mid")
    out = _parse_delimited(text, ",", 10, geography=False, complete=False)
    assert out["has_header"] and out["columns"][1] == "CUST_NAME"
    assert out["masked_columns"] == ["CUST_NAME"]
    assert out["rows"][0] == ["I1", MASK, "FL", "call <phone> or <email>", "10.5"]
    assert out["rows_read"] == 2          # the cut-off last line is dropped


def test_csv_without_a_header_still_redacts_and_says_so():
    out = _parse_delimited("1,ana@x.com,3\n4,5,6\n", ",", 10, geography=False, complete=True)
    assert out["has_header"] is False and out["columns"] == ["_c0", "_c1", "_c2"]
    assert out["rows"][0][1] == "<email>" and "No header" in out["note"]


def test_json_keys_naming_personal_data_are_masked():
    masked = _mask_json({"customer_name": "Ana", "amount": 3, "nested": [{"email": "a@b.co", "note": "x"}]},
                        geography=False)
    assert masked["customer_name"] == MASK and masked["amount"] == 3
    assert masked["nested"][0]["email"] == MASK


def test_redaction():
    assert redact_values("reach +1 (555) 123-4567, ana.b@site.org") == "reach <phone>, <email>"
    assert redact_values("invoice 12345 on 2026-09-01") == "invoice 12345 on 2026-09-01"


def test_reading_needs_the_files_permission():
    reader = AgentIdentity(agent_id=uuid.uuid4(), name="r", scopes=frozenset({"read", "query"}))
    out = asyncio.run(read_volume_file(None, reader, "/Volumes/c/s/v/x.csv"))
    assert "files" in out["error"]
