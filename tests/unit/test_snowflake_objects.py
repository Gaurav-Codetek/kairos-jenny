"""Every Snowflake object on the map: safe properties, links, inferred locations and stubs."""

import asyncio

from kairos_kb.connectors.snowflake import SnowflakeConnector
from kairos_kb.connectors import snowflake_objects as so
from kairos_kb.ingestion.object_sync import _rationale


def test_secrets_never_become_properties():
    row = {"NAME": "INT", "TYPE": "EXTERNAL_STAGE", "STORAGE_AWS_EXTERNAL_ID": "abc", "OAUTH_CLIENT_SECRET": "x",
           "PASSWORD": "p", "ENABLED": "true", "COMMENT": ""}
    props = so._clean(row, ("NAME",))
    assert props == {"type": "EXTERNAL_STAGE", "enabled": "true"}


def test_desc_output_nests_by_parent_property_and_drops_secrets():
    rows = [{"PARENT_PROPERTY": "STAGE_LOCATION", "PROPERTY": "URL", "PROPERTY_VALUE": '["s3://b/raw/"]'},
            {"PARENT_PROPERTY": "STAGE_FILE_FORMAT", "PROPERTY": "FORMAT_NAME", "PROPERTY_VALUE": "CSV_FMT"},
            {"PARENT_PROPERTY": "STAGE_CREDENTIALS", "PROPERTY": "AWS_SECRET_KEY", "PROPERTY_VALUE": "zzz"},
            {"PROPERTY": "STORAGE_PROVIDER", "PROPERTY_VALUE": "S3"}]
    d = so._desc(rows)
    assert d["stage_location"]["url"] == '["s3://b/raw/"]' and d["stage_file_format"]["format_name"] == "CSV_FMT"
    assert d["storage_provider"] == "S3" and "stage_credentials" not in d


def test_list_values_and_stage_references():
    assert so._list_value("[s3://a/, 's3://b/']") == ["s3://a/", "s3://b/"]
    assert so._list_value(None) == []
    assert so.stage_reference("COPY INTO t FROM @ZOMATO.RAW.STG/orders/ FILE_FORMAT=(TYPE=CSV)") == \
        ("ZOMATO.RAW.STG", "/orders/")
    assert so.stage_reference("select 1") is None
    assert so.stage_reference("PUT file://x @~/staged") is None  # the user stage is not an object


def test_users_never_carry_personal_details():
    reader = so.ObjectReader(SnowflakeConnector(config={"account": "a"}))

    async def fake_try(label, sql, params=None):
        if sql == "SHOW USERS":
            return [{"NAME": "jane", "EMAIL": "jane@x.com", "FIRST_NAME": "Jane", "DISPLAY_NAME": "Jane D",
                     "LOGIN_NAME": "JANE", "DEFAULT_ROLE": "ANALYST", "TYPE": "PERSON"}]
        return []

    reader.c._try = fake_try
    asyncio.run(reader.account())
    user = next(o for o in reader.objects if o["kind"] == "user")
    assert user["properties"] == {"default_role": "ANALYST", "type": "PERSON"}


def _reader_with_load_links():
    reader = so.ObjectReader(SnowflakeConnector(config={"account": "a"}))
    reader.obj("integration", "S3_INT", "S3_INT")
    reader.link(("integration", "S3_INT"), ("location", "s3://bucket/"), "ALLOWS")
    reader.link(("stage", "DB.RAW.STG"), ("table", "DB.RAW.ORDERS"), "FEEDS", path="/orders/")
    reader.link(("location", "s3://bucket/raw/"), ("table", "DB.RAW.ORDERS"), "LOADS_INTO", rows=10)
    return reader


def test_a_stage_the_role_cannot_see_is_placed_by_its_loads_and_kept_as_a_stub(monkeypatch):
    reader = _reader_with_load_links()
    so._infer_stage_locations(reader)
    stored = [l for l in reader.links if l["relation"] == "STORED_AT"]
    assert stored and stored[0]["source"] == ("stage", "DB.RAW.STG") and stored[0]["target"] == ("location", "s3://bucket/raw/")

    async def run():
        class Fake(SnowflakeConnector):
            async def _databases(self):
                return []

        c = Fake(config={"account": "a"})

        async def no_rows(*a, **k):
            return []

        c._try = no_rows
        def use(conn):
            reader.c = conn  # the fake connector answers every read with no rows
            return reader

        monkeypatch.setattr(so, "ObjectReader", use)
        return await so.read_objects(c)

    out = run_sync(run())
    kinds = {(o["kind"], o["full_name"]) for o in out["objects"]}
    assert ("stage", "DB.RAW.STG") in kinds                      # stub for the unseen stage
    assert ("location", "s3://bucket/raw/") in kinds and ("location", "s3://bucket/") in kinds
    stub = next(o for o in out["objects"] if o["kind"] == "stage")
    assert stub["properties"]["describable"] is False
    within = [l for l in out["links"] if l["relation"] == "WITHIN"]
    assert within and within[0]["source"] == ("location", "s3://bucket/raw/") and within[0]["target"] == ("location", "s3://bucket/")


def run_sync(coro):
    return asyncio.run(coro)


def test_links_explain_themselves():
    assert _rationale("FEEDS", {"path": "/orders/", "via": "COPY INTO"}) == \
        "Platform metadata: loads it with COPY INTO (path: /orders/; via: COPY INTO)."
    assert _rationale("PROTECTS", {}) == "Platform metadata: is protected by this policy."
