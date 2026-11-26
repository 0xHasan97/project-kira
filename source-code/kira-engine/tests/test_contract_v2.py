from __future__ import annotations

from kira.contracts import API_PREFIX, CHAIN_EVENTS, CONTRACT_VERSION, ERROR_CODES, OPENAPI, contract_facts
from kira.errors import BudgetExhausted

SCHEMAS = OPENAPI["components"]["schemas"]

# Every path here is built from the published namespace, so a namespace bump moves this file with the
# engine instead of leaving a list of stale `/v1` strings that quietly stop matching anything.
DASHBOARD_PATHS = [
    ("get", f"{API_PREFIX}/kira/overview"),
    ("get", f"{API_PREFIX}/kira/providers"),
    ("get", f"{API_PREFIX}/kira/sessions"),
    ("put", f"{API_PREFIX}/kira/providers/{{name}}/settings"),
    ("put", f"{API_PREFIX}/kira/providers/{{name}}/key"),
    ("delete", f"{API_PREFIX}/kira/providers/{{name}}/key"),
    ("delete", f"{API_PREFIX}/kira/providers/{{name}}/cooldown"),
    ("post", f"{API_PREFIX}/kira/providers/{{name}}/probe"),
    ("delete", f"{API_PREFIX}/kira/sessions/{{session_id}}"),
    ("delete", f"{API_PREFIX}/kira/sessions"),
    ("get", f"{API_PREFIX}/kira/characters"),
    ("post", f"{API_PREFIX}/kira/characters"),
    ("put", f"{API_PREFIX}/kira/characters/active"),
    ("get", f"{API_PREFIX}/kira/characters/{{character_id}}"),
    ("delete", f"{API_PREFIX}/kira/characters/{{character_id}}"),
    ("get", f"{API_PREFIX}/kira/characters/{{character_id}}/file"),
]

WRITE_PATHS = [
    ("delete", f"{API_PREFIX}/kira/sessions/{{session_id}}"),
    ("delete", f"{API_PREFIX}/kira/sessions"),
    ("delete", f"{API_PREFIX}/kira/characters/{{character_id}}"),
]

# Desktop-only writes are the exception: a human typing a key or tuning a provider is already at the
# keyboard on the machine that holds the engine token, and a paired device can never reach them.
# Character import and the stage pick join them for the same reason — the caller is supplying a file
# that already exists here, or changing which one is on screen, not destroying anything Kira made.
OWNER_ONLY_PATHS = [
    ("put", f"{API_PREFIX}/kira/providers/{{name}}/settings"),
    ("delete", f"{API_PREFIX}/kira/providers/{{name}}/cooldown"),
    ("post", f"{API_PREFIX}/kira/providers/{{name}}/probe"),
    ("put", f"{API_PREFIX}/kira/providers/{{name}}/key"),
    ("delete", f"{API_PREFIX}/kira/providers/{{name}}/key"),
    ("post", f"{API_PREFIX}/kira/characters"),
    ("put", f"{API_PREFIX}/kira/characters/active"),
]

READ_PATHS = [
    ("get", f"{API_PREFIX}/models"),
    ("get", f"{API_PREFIX}/kira/health"),
    ("get", f"{API_PREFIX}/kira/overview"),
    ("get", f"{API_PREFIX}/kira/providers"),
    ("get", f"{API_PREFIX}/kira/sessions"),
    ("get", f"{API_PREFIX}/kira/sessions/{{session_id}}/messages"),
    ("get", f"{API_PREFIX}/kira/characters"),
    ("get", f"{API_PREFIX}/kira/characters/{{character_id}}"),
    ("get", f"{API_PREFIX}/kira/characters/{{character_id}}/file"),
]


def test_the_contract_is_version_two_and_the_facts_agree():
    assert CONTRACT_VERSION == 2
    facts = contract_facts()
    assert facts["contract_version"] == 2
    assert OPENAPI["info"]["version"] == "2"
    assert facts["error_codes"] == sorted(facts["error_codes"])


def test_budget_is_a_documented_non_retryable_429():
    # The count is a tripwire, not arithmetic: adding an event name has to come with a README row, a
    # chip label in the chat bundle, and a regenerated contract — tests elsewhere catch each of those,
    # and this line is what makes someone actually look at that list instead of appending in silence.
    assert "skipped_budget" in CHAIN_EVENTS and len(CHAIN_EVENTS) == 16
    assert BudgetExhausted.code == "budget_exhausted"
    assert BudgetExhausted.code in ERROR_CODES
    err = BudgetExhausted("every provider is over its monthly cap", [])
    assert (err.status, err.retryable, err.chain) == (429, False, [])


def test_every_dashboard_schema_is_published_with_properties():
    for name in (
        "FieldStateBool", "FieldStateInt", "FieldStateStr", "FieldStateCap",
        "ProviderView", "ProvidersResponse", "OverviewResponse", "TokenSplit",
        "ProviderUsage", "ModelUsage", "DailyUsage", "BudgetRow", "RecentIssue",
        "ProbeResponse", "ProviderSettings", "SettingsResponse", "SettingsRequest",
        "KeyRequest", "KeyResponse", "DeletedResponse", "SessionRow", "MessageRow",
    ):
        assert name in SCHEMAS, f"{name} is not a published schema"
        assert SCHEMAS[name]["properties"], f"{name} publishes no fields"


def test_one_probe_shape_only():
    assert "LiveProbe" not in SCHEMAS
    assert SCHEMAS["ModelsResponse"]["properties"]["live"]["items"]["$ref"].endswith("ProbeResponse")


def test_history_rows_are_named_schemas_so_the_gate_checks_them():
    assert SCHEMAS["SessionsResponse"]["properties"]["sessions"]["items"]["$ref"].endswith("SessionRow")
    assert SCHEMAS["MessagesResponse"]["properties"]["messages"]["items"]["$ref"].endswith("MessageRow")
    assert SCHEMAS["SessionRow"]["required"] == [
        "id", "mode", "created_at", "message_count", "tokens", "last_used_at",
    ]


def test_the_dashboard_endpoints_are_documented():
    for verb, path in DASHBOARD_PATHS:
        assert path in OPENAPI["paths"], path
        op = OPENAPI["paths"][path][verb]
        # A created import answers 201, not 200; the gate cares that a success body is published, not
        # which 2xx carries it. Exactly one success code, so a route cannot document two shapes.
        success = sorted(code for code in op["responses"] if code.startswith("2"))
        assert len(success) == 1, f"{verb.upper()} {path} documents {success} instead of one success body"
        assert "401" in op["responses"], f"{verb.upper()} {path} does not document auth"


def test_writes_ask_for_the_confirm_header_and_reads_do_not():
    for verb, path in WRITE_PATHS:
        params = OPENAPI["paths"][path][verb].get("parameters", [])
        assert any(p.get("$ref", "").endswith("Confirm") for p in params), f"{path} is a write with no confirm"
    for verb, path in READ_PATHS:
        params = OPENAPI["paths"][path][verb].get("parameters", [])
        assert not any("Confirm" in p.get("$ref", "") for p in params), f"{path} is a read that demands a confirm"
    # A bearer token alone must stay enough to script a read.
    assert OPENAPI["components"]["parameters"]["Confirm"]["in"] == "header"
    assert OPENAPI["components"]["parameters"]["Confirm"]["name"] == "X-Kira-Confirm"


def test_owner_only_writes_are_the_only_bearer_writes_without_a_confirm():
    # The published contract is what the chat bundle and any third-party client reads. If a
    # desktop-only route grew a Confirm parameter back, or some other write quietly lost one, this is
    # where it shows up.
    for verb, path in OWNER_ONLY_PATHS:
        params = OPENAPI["paths"][path][verb].get("parameters", [])
        assert not any("Confirm" in p.get("$ref", "") for p in params), f"{path} asks a desktop write for a secret"
    bearer_writes = {
        (verb, path)
        for path, ops in OPENAPI["paths"].items()
        for verb, op in ops.items()
        if verb in ("put", "post", "delete") and any("bearerAuth" in s for s in op.get("security", []))
    }
    # A chat turn is a bearer write with no confirm: it answers with a stream, and anything destructive
    # it wants to do comes back as an approval the human decides on. Pairing has no bearer to check -
    # it is gated on the one-time code - so it never enters this sweep at all.
    exempt = set(OWNER_ONLY_PATHS) | {("post", f"{API_PREFIX}/chat/completions")}
    assert exempt <= bearer_writes, "an exempt write that the contract no longer publishes"
    for verb, path in bearer_writes:
        if (verb, path) in exempt:
            continue
        params = OPENAPI["paths"][path][verb].get("parameters", [])
        assert any(p.get("$ref", "").endswith("Confirm") for p in params), f"{verb.upper()} {path} writes with no gate"


def test_chat_documents_the_budget_status():
    responses = OPENAPI["paths"]["/v1/chat/completions"]["post"]["responses"]
    assert "429" in responses
    assert responses["429"]["content"]["application/json"]["schema"]["$ref"].endswith("ErrorResponse")
    assert "503" in responses, "the old exhaustion status must survive the bump"


def test_tool_harness_is_additive():
    assert {"tool_approval_requested", "tool_denied", "checkpoint_created", "usage_estimated"} <= set(CHAIN_EVENTS)
    schemas = OPENAPI["components"]["schemas"]
    for name in (
        "ToolInfo", "PluginInfo", "CheckpointInfo", "ApprovalInfo", "ToolPolicyRequest",
        "ApprovalDecision", "CheckpointRestoreRequest", "ChainRecord",
    ):
        assert name in schemas
    assert schemas["WireUsage"]["properties"]["estimated"]["type"] == "boolean"
    paths = OPENAPI["paths"]
    for path in (
        f"{API_PREFIX}/kira/tools",
        f"{API_PREFIX}/kira/tools/{{name}}",
        f"{API_PREFIX}/kira/checkpoints",
        f"{API_PREFIX}/kira/checkpoints/{{checkpoint_id}}/restore",
        f"{API_PREFIX}/kira/approvals",
        f"{API_PREFIX}/kira/approvals/{{approval_id}}",
    ):
        assert path in paths


MEMORY_PATHS = [
    ("get", f"{API_PREFIX}/kira/memory"),
    ("post", f"{API_PREFIX}/kira/memory"),
    ("patch", f"{API_PREFIX}/kira/memory/{{memory_id}}"),
    ("delete", f"{API_PREFIX}/kira/memory/{{memory_id}}"),
    ("get", f"{API_PREFIX}/kira/memory/search"),
    ("get", f"{API_PREFIX}/kira/memory/export"),
    ("get", f"{API_PREFIX}/kira/memory/settings"),
    ("put", f"{API_PREFIX}/kira/memory/settings"),
]


def test_memory_paths_are_published_and_the_writes_carry_the_confirm_header():
    for method, path in MEMORY_PATHS:
        assert method in OPENAPI["paths"][path], f"{method} {path} is not published"
    for method, path in MEMORY_PATHS:
        if method == "get":
            continue
        params = [p.get("$ref", "") for p in OPENAPI["paths"][path][method]["parameters"]]
        assert "#/components/parameters/Confirm" in params, f"{method} {path} is not confirm-gated"


def test_memory_schemas_are_additive_only():
    assert CONTRACT_VERSION == 2
    for name in ("MemoryItem", "MemoryList", "MemorySettings", "MemorySearch", "MemoryExport"):
        assert name in SCHEMAS


def test_skills_are_additive_and_a_turn_can_name_one():
    assert CONTRACT_VERSION == 2
    for name in ("SkillInfo", "SkillFile", "SkillsResponse"):
        assert name in SCHEMAS, f"{name} is not a published schema"
        assert SCHEMAS[name]["properties"], f"{name} publishes no fields"
    assert ("get", f"{API_PREFIX}/kira/skills") in [
        (verb, path) for path in OPENAPI["paths"] for verb in OPENAPI["paths"][path]
    ]
    op = OPENAPI["paths"][f"{API_PREFIX}/kira/skills"]["get"]
    assert "401" in op["responses"]
    chat = SCHEMAS["ChatRequest"]["properties"]["skill"]
    assert chat["type"] == "string" and chat["nullable"] is True


CHARACTER_PATHS = [
    ("get", f"{API_PREFIX}/kira/characters"),
    ("post", f"{API_PREFIX}/kira/characters"),
    ("put", f"{API_PREFIX}/kira/characters/active"),
    ("get", f"{API_PREFIX}/kira/characters/{{character_id}}"),
    ("delete", f"{API_PREFIX}/kira/characters/{{character_id}}"),
    ("get", f"{API_PREFIX}/kira/characters/{{character_id}}/file"),
]


def test_character_paths_are_published_and_only_the_delete_carries_the_confirm():
    for method, path in CHARACTER_PATHS:
        assert method in OPENAPI["paths"][path], f"{method} {path} is not published"
        assert "401" in OPENAPI["paths"][path][method]["responses"], f"{method} {path} hides its gate"
    confirm_paths = {
        path
        for method, path in CHARACTER_PATHS
        if method in ("post", "put", "delete")
        for p in OPENAPI["paths"][path][method].get("parameters", [])
        if p.get("$ref", "").endswith("Confirm")
    }
    # Supplying a file or moving the stage pick is the key-route gate; removing a character is not.
    assert confirm_paths == {f"{API_PREFIX}/kira/characters/{{character_id}}"}


def test_an_import_answers_created_and_documents_the_importer_refusals():
    op = OPENAPI["paths"][f"{API_PREFIX}/kira/characters"]["post"]
    assert "201" in op["responses"], "an import adds a row; a 200 would say it replaced one"
    assert op["responses"]["201"]["content"]["application/json"]["schema"]["$ref"].endswith("CharacterRow")
    for status, code in (("400", "unsupported_source"), ("409", "already_imported"), ("413", "too_large")):
        body = op["responses"][status]
        assert body["content"]["application/json"]["schema"]["$ref"].endswith("ErrorResponse")
        assert body["description"].startswith(f"{status} {code} - "), f"{code} is not the named {status}"


def test_the_character_schemas_are_additive_only():
    assert CONTRACT_VERSION == 2
    for name in (
        "TextureFinding", "CharacterCapability", "CharacterRow", "CharacterList", "CharacterProfile",
        "CharacterImportRequest", "CharacterActiveRequest", "CharacterActiveResponse", "CharacterDeleted",
    ):
        assert name in SCHEMAS, f"{name} is not a published schema"
        assert SCHEMAS[name]["properties"], f"{name} publishes no fields"
    assert SCHEMAS["CharacterList"]["required"] == ["characters", "active"]
    assert SCHEMAS["CharacterImportRequest"]["additionalProperties"] is False
    assert SCHEMAS["CharacterImportRequest"]["required"] == ["path"]
    # `null` is a real answer here — take everyone off stage — so the field must be nullable, not absent.
    assert SCHEMAS["CharacterActiveRequest"]["properties"]["id"]["type"] == ["string", "null"]
    assert SCHEMAS["CharacterRow"]["properties"]["id"]["type"] == "string"


def test_every_character_refusal_is_a_published_error_code():
    from kira.characters import ANSWER_FOR_CODE, CharacterRefusal

    assert set(ANSWER_FOR_CODE) <= set(ERROR_CODES)
    assert {cls.status for cls in ANSWER_FOR_CODE.values()} <= {400, 404, 409, 413}
    # The base class inherits `internal_error` and a 500, so it publishes no code of its own: a caller
    # only ever sees a leaf, and the error-code walk in test_units reads this tree to build its list.
    assert CharacterRefusal.code == "internal_error"
    assert SCHEMAS["ErrorBody"]["properties"]["entry"]["type"] == "string"
    assert "entry" not in SCHEMAS["ErrorBody"]["required"], "only three refusals carry a name"
