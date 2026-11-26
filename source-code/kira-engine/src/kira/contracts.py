from __future__ import annotations

import json
from pathlib import Path

from .characters import ANSWER_FOR_CODE
from .config import MODES
from .downloads import DownloadFailed, DownloadRefused
from .images import (
    ImageBackendMissing,
    ImageGenerationFailed,
    ImageNotFound,
    ImageRequestInvalid,
)
from .llamacpp import LlmStartFailed, LlmUnavailable
from .errors import (
    PROVIDER_CODES,
    AllProvidersExhausted,
    AuthError,
    BudgetExhausted,
    ConfigError,
    KiraError,
    ModelNotFound,
    SecretStoreUnavailable,
    UnsupportedVersion,
)
from .net import MAX_COOLDOWN_S
from .pairing import PairingRateLimited, PairingRefused
from .studio_server import StudioError, StudioRefused

CONTRACT_VERSION = 2

#: The URL namespace the engine serves, e.g. `/v1`. Two versions, two rules, deliberately separate:
#:
#: - `API_VERSION` bumps only when a documented method+path is removed, renamed, or its response
#:   changes meaning — the things that break a caller that already parsed the old shape.
#: - `CONTRACT_VERSION` bumps when a schema's field set or an enum's meaning changes.
#: - Adding a field, a schema or an enum value is additive and bumps neither, because a reader that
#:   ignores what it has not seen keeps working.
API_VERSION = 1
API_PREFIX = f"/v{API_VERSION}"

CHAIN_EVENTS = (
    "attempt",
    "served",
    "failed",
    "skipped_cooling",
    "skipped_missing_key",
    "skipped_config",
    "skipped_budget",
    "aborted_mid_stream",
    # A stream that opened, ran and closed without one character of text and without a tool call.
    # Not an answer: the router fails over instead of serving silence.
    "empty_answer",
    "tool_executed",
    "tool_approval_requested",
    "tool_denied",
    "checkpoint_created",
    "usage_estimated",
    # A call's webcam frame either reaches the provider or it does not, and the chain records which.
    "images_attached",
    "images_dropped",
)

CHAT_CHUNK_TYPES = ("delta", "tool_call", "chain", "approval", "done", "error")

ERROR_CODES = tuple(
    sorted(
        {
            ConfigError.code,
            AuthError.code,
            ModelNotFound.code,
            SecretStoreUnavailable.code,
            AllProvidersExhausted.code,
            BudgetExhausted.code,
            UnsupportedVersion.code,
            KiraError.code,
            PairingRefused.code,
            PairingRateLimited.code,
            ImageBackendMissing.code,
            ImageGenerationFailed.code,
            ImageNotFound.code,
            ImageRequestInvalid.code,
            LlmUnavailable.code,
            LlmStartFailed.code,
            DownloadRefused.code,
            DownloadFailed.code,
            StudioError.code,
            StudioRefused.code,
            # The character family comes from `characters.ANSWER_FOR_CODE` rather than a second hand-written
            # list here: that mapping is built by walking `CharacterRefusal.__subclasses__()`, so a refusal
            # the importer can raise and the contract has not published fails `test_units` where the class
            # tree is compared to this list — instead of arriving as the generic 400 it would fall back to.
            *ANSWER_FOR_CODE,
        }
    )
)

#: What a non-streaming chat-completions body and the streaming `done` chunk share.
WIRE_USAGE_FIELDS = ("prompt_tokens", "completion_tokens")


def contract_facts() -> dict:
    """Machine-readable constants the TS client is checked against."""
    return {
        "contract_version": CONTRACT_VERSION,
        "api_version": API_VERSION,
        "api_prefix": API_PREFIX,
        "modes": list(MODES),
        "chain_events": list(CHAIN_EVENTS),
        "chunk_types": list(CHAT_CHUNK_TYPES),
        "error_codes": list(ERROR_CODES),
        "provider_error_codes": list(PROVIDER_CODES),
        "wire_usage_fields": list(WIRE_USAGE_FIELDS),
        "default_port": 8901,
        "max_cooldown_s": MAX_COOLDOWN_S,
    }


CHUNK = {
    "type": "object",
    "description": f"One SSE `data:` frame on {API_PREFIX}/chat/completions when stream=true.",
    "required": ["type"],
    "properties": {
        "type": {"type": "string", "enum": list(CHAT_CHUNK_TYPES)},
        "text": {"type": "string", "description": "delta only"},
        "id": {"type": "string", "description": "tool_call, approval and done"},
        "name": {"type": "string", "description": "tool_call only"},
        "tool": {"type": "string", "description": "approval only"},
        "risk": {"type": "string", "enum": ["read", "write", "exec", "network"], "description": "approval only"},
        "arguments": {"type": "object", "description": "tool_call and approval"},
        "record": {"$ref": "#/components/schemas/ChainRecord", "description": "chain only"},
        "session_id": {"type": "string", "description": "done"},
        "provider": {"type": "string", "nullable": True, "description": "done"},
        "model": {"type": "string", "nullable": True, "description": "done"},
        "finish_reason": {"type": "string", "description": "done"},
        "status": {"type": "string", "enum": ["complete", "max_steps", "interrupted", "failed"], "description": "done"},
        "usage": {"$ref": "#/components/schemas/WireUsage", "description": "done"},
        "provider_chain": {"type": "array", "items": {"$ref": "#/components/schemas/ChainRecord"}, "description": "done and error"},
        "error": {"$ref": "#/components/schemas/ErrorBody", "description": "error only"},
    },
}

def _ref(name: str) -> str:
    return f"#/components/schemas/{name}"


def _ok(schema: str) -> dict:
    return {"description": "ok", "content": {"application/json": {"schema": {"$ref": _ref(schema)}}}}


def _bad_request() -> dict:
    return {
        "description": "config_error - unknown provider, unknown field, or an out-of-range value",
        "content": {"application/json": {"schema": {"$ref": _ref("ErrorResponse")}}},
    }


def _provider_param() -> dict:
    return {"name": "name", "in": "path", "required": True, "schema": {"type": "string"}}


def _ref_confirm() -> dict:
    return {"$ref": "#/components/parameters/Confirm"}


def _read(summary: str, schema: str, params: list[dict] | None = None) -> dict:
    return {
        "summary": summary,
        "security": [{"bearerAuth": []}],
        "parameters": params or [],
        "responses": {"200": _ok(schema), "400": _bad_request(), "401": {"$ref": "#/components/responses/Unauthorized"}},
    }


def _write(summary: str, schema: str, params: list[dict], body: str | None = None) -> dict:
    op = _read(summary, schema, [_ref_confirm()] + params)
    if body:
        op["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": {"$ref": _ref(body)}}},
        }
    op["description"] = (
        "Needs the bearer token AND the X-Kira-Confirm secret: a missing, wrong or bearer-equal "
        "confirm is 401 unauthorized."
    )
    return op


def _owner_write(summary: str, schema: str, params: list[dict], body: str | None = None) -> dict:
    """A write the engine token alone gates: no confirm header is asked for, so none is accepted either."""
    op = _write(summary, schema, params, body)
    op["parameters"] = params
    op["description"] = (
        "Needs the engine token itself and nothing typed: a paired device token is refused with "
        "401 unauthorized, so credentials and provider controls stay on the desktop."
    )
    return op


def _error(status: int, code: str, description: str) -> dict:
    return {
        "description": f"{status} {code} - {description}",
        "content": {"application/json": {"schema": {"$ref": _ref("ErrorResponse")}}},
    }


def _approval_write() -> dict:
    """A decision is confirm-gated, and the id it names may be gone or already settled."""
    op = _write(
        "Allow or deny one pending tool call",
        "ApprovalResponse",
        [{"name": "approval_id", "in": "path", "required": True, "schema": {"type": "string"}}],
        "ApprovalDecision",
    )
    op["responses"]["404"] = _error(404, "not_found", "no approval has ever had that id")
    op["responses"]["409"] = _error(409, "not_pending", "the approval already expired or was decided")
    return op


def _checkpoint_restore() -> dict:
    """Restore refuses on a moved file unless forced, and an undo is itself undoable."""
    op = _write(
        "Restore the files a checkpoint holds",
        "CheckpointRestore",
        [{"name": "checkpoint_id", "in": "path", "required": True, "schema": {"type": "string"}}],
        "CheckpointRestoreRequest",
    )
    op["responses"]["404"] = _error(404, "not_found", "no checkpoint has ever had that id")
    op["responses"]["409"] = _error(409, "checkpoint_conflict", "a file changed since the checkpoint; resend with force")
    return op


def _memory_write(summary: str, schema: str, body: str | None = None) -> dict:
    """Edit and forget both name a fact by id, and an id the store has never seen is a 404."""
    op = _write(
        summary,
        schema,
        [{"name": "memory_id", "in": "path", "required": True, "schema": {"type": "string"}}],
        body,
    )
    op["responses"]["404"] = _error(404, "not_found", "no memory has ever had that id")
    return op


def _device_revoke() -> dict:
    """Revoking is confirm-gated, and an id that was never paired is a 404, not a silent success."""
    op = _write(
        "Revoke a device; its token stops authenticating immediately",
        "DeviceDeleted",
        [{"name": "device_id", "in": "path", "required": True, "schema": {"type": "string"}}],
    )
    op["responses"]["404"] = _error(404, "not_found", "no device has ever had that id")
    return op


#: One generated image, addressed by the name this workspace gave it. The name is not a path.
_IMAGE_NAME = {"name": "name", "in": "path", "required": True, "schema": {"type": "string"}}


def _image_generate() -> dict:
    op = {
        "summary": "Draw one image locally with stable-diffusion.cpp",
        "security": [{"bearerAuth": []}],
        "parameters": [_ref_confirm()],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {"$ref": _ref("ImageGenerateRequest")}}},
        },
        "responses": {
            "200": _ok("ImageOutput"),
            "400": _error(
                400,
                "image_request_invalid",
                "an empty prompt, a size that is not a multiple of 8, or a sampler name the engine cannot take; "
                "model_not_found is the other 400 — the name is not a checkpoint in the images folder",
            ),
            "401": {"$ref": "#/components/responses/Unauthorized"},
            "503": _error(
                503,
                "image_backend_missing",
                "no engine executable and no KIRA_SD_URL, or no checkpoint in the images folder; the message "
                "names the folder to fill",
            ),
            "502": _error(502, "image_generation_failed", "the engine started and failed, or returned something that is not a PNG"),
        },
        "description": (
            "Needs the bearer token AND the typed X-Kira-Confirm secret: a generation writes a file "
            "into the user's gallery, and every bearer write in Kira carries the same gate. Generation "
            "is minutes on a CPU, so the work runs off the event loop and the chat stream keeps flowing. "
            "The PNG and a JSON sidecar land in the images/outputs folder together; the answer is the "
            "row the gallery will show after a restart."
        ),
    }
    return op


def _image_file() -> dict:
    return {
        "summary": "The bytes of one generated PNG",
        "security": [{"bearerAuth": []}],
        "parameters": [_IMAGE_NAME],
        "description": (
            "The token is the bearer header, never a query parameter. The name is checked against the shape "
            "this workspace writes and resolved inside the outputs folder, so no caller string becomes a path."
        ),
        "responses": {
            "200": {
                "description": "the PNG",
                "content": {"image/png": {"schema": {"type": "string", "format": "binary"}}},
            },
            "401": {"$ref": "#/components/responses/Unauthorized"},
            "404": _error(404, "image_not_found", "no image with that name was written by this workspace"),
        },
    }


def _image_delete() -> dict:
    op = _write("Forget one generated image and its sidecar", "ImageDeleted", [_IMAGE_NAME])
    op["parameters"] = [_IMAGE_NAME, _ref_confirm()]
    op["responses"]["404"] = _error(404, "image_not_found", "no image with that name was written by this workspace")
    return op


#: The character routes all name the same thing, and the name is the folder: `CharacterRow.id`, the id in
#: `CharacterActiveRequest`, and this path parameter are one value with one rule about what it can contain.
_CHARACTER_ID = {"name": "character_id", "in": "path", "required": True, "schema": {"type": "string"}}

_OWNER_ONLY = (
    "Needs the engine token itself and nothing typed: a paired device token is refused with 401 "
    "unauthorized, so no character can be added to this machine or taken off stage from another one."
)


def _character_detail() -> dict:
    op = _read("One character, whole", "CharacterProfile", [_CHARACTER_ID])
    op["responses"]["404"] = _error(
        404,
        "character_not_found",
        "no character in the library has that id — and an id that could never name a folder, because it "
        "has a separator, a NUL, or a leading dot, answers the same way",
    )
    return op


def _character_import() -> dict:
    """Supplying a file is not destroying one, so this is the key-route gate: owner, no secret.

    The refusals are the importer's own codes and statuses, not a route's opinion about them: the CLI reads
    the same `CharacterError` for the same bytes and says the same thing, and a caller that got a softer
    answer over the wire would have no way to tell a duplicate from a zip bomb.
    """
    op = _owner_write(
        "Import a character from a path on this machine", "CharacterRow", [], "CharacterImportRequest"
    )
    op["description"] = _OWNER_ONLY
    op["responses"] = {
        "201": _ok("CharacterRow"),
        "400": _error(
            400,
            "unsupported_source",
            "no file there, or not a .pmx or .zip; also unsafe_entry when an archive entry climbs out of "
            "the folder, bad_archive, no_pmx_in_archive, and the three pmx_* refusals",
        ),
        "401": {"$ref": "#/components/responses/Unauthorized"},
        "409": _error(
            409,
            "already_imported",
            "those bytes are already in the library, and the message names the character; character_exists "
            "is the same answer for a different id collision. Nothing was overwritten",
        ),
        "413": _error(
            413, "too_large", "over the archive, entry, expanded or expansion-ratio caps, or more entries than Kira unpacks"
        ),
    }
    return op


def _character_active() -> dict:
    """A preference, not data on disk: owner-only like the key routes, and no secret to type."""
    op = _owner_write(
        "Put a character on stage, or take everyone off", "CharacterActiveResponse", [], "CharacterActiveRequest"
    )
    op["description"] = _OWNER_ONLY
    op["responses"]["404"] = _error(404, "character_not_found", "the library has no character with that id to put on stage")
    return op


def _character_delete() -> dict:
    """Destruction is the other half of the split: owner and the confirm secret, like every other delete."""
    op = _write("Delete an imported character and its files", "CharacterDeleted", [_CHARACTER_ID])
    op["parameters"] = [_CHARACTER_ID, _ref_confirm()]
    op["responses"]["404"] = _error(404, "character_not_found", "no character in the library has that id")
    return op


def _character_file() -> dict:
    """The only route that turns a caller's string into a file on this disk, so it is the leak to test.

    The media type comes from the extension table, and an extension off that table is refused before the
    disk is touched — which is what stops this being a file server that will hand back an `.html` with this
    engine's origin and its token-bearing sibling routes one click away.
    """
    return {
        "summary": "One file from a character's folder: the model, a texture, or its profile",
        "security": [{"bearerAuth": []}],
        "parameters": [
            _CHARACTER_ID,
            {
                "name": "path",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "description": (
                    "relative to the character's own folder, e.g. `model.pmx` or `tex/颜.png`. Dot-dot "
                    "segments that cancel themselves inside the folder are allowed; a path that resolves "
                    "outside it is not, after any percent-decoding and through a symlink"
                ),
            },
        ],
        "description": (
            "The token is the bearer header, never a query parameter: a URL with a secret in it is a URL "
            "that ends up in an access log. A phone that paired may fetch this — showing the avatar is a "
            "read — and `Content-Length` is the file's, so a 45 MB body streams instead of buffering."
        ),
        "responses": {
            "200": {
                "description": "the bytes, with the media type the extension says: application/octet-stream "
                               "for .pmx, image/png, image/bmp, image/x-tga, image/vnd-directx, "
                               "application/json for the profile",
                "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
            },
            "400": _error(
                400,
                "unsafe_entry",
                "absolute, escaping, empty, or NUL-bearing — unsupported_source is the other 400 here: an "
                "extension the stage does not load",
            ),
            "401": {"$ref": "#/components/responses/Unauthorized"},
            "404": _error(
                404,
                "character_not_found",
                "that id is not in the library; character_file_not_found is the other 404 — the folder "
                "exists and does not have that file, which is what a texture shipped apart from its model "
                "looks like",
            ),
        },
    }


def _character_mesh() -> dict:
    """The body as the stage draws it: one flat KRM1 blob, packed by the reader that walked the PMX.

    Documented as `application/octet-stream` with an inlined binary schema, the same shape `/file` uses — a
    mesh has no JSON twin and the drift check does not ask a TypeScript interface for bytes. The point of
    the route is that the browser never parses a PMX: framing probes, the material retry and the morph
    boundary search are paid for once, on this side, and a model they cannot certify is refused here rather
    than half-drawn on a stage.
    """
    return {
        "summary": "One character's body as a KRM1 mesh: positions, skin, faces, materials, bones, vertex morphs",
        "security": [{"bearerAuth": []}],
        "parameters": [_CHARACTER_ID],
        "description": (
            "Little-endian and consumed to the last byte: `KRM1` | u32 format | u32 vertex | u32 face index "
            "| u32 bone | u32 material | u32 texture | u32 vertex morph, then the position, normal, uv, "
            "skin, face, texture, material, bone and morph blocks in that order. The path is the library's "
            "own — the profile the importer wrote names the model — so a caller can ask for nothing that is "
            "not already here. A paired device may ask: showing the avatar is a read."
        ),
        "responses": {
            "200": {
                "description": "the KRM1 blob; the format version is the word after the magic, and a stage "
                               "that does not know that number refuses the bytes instead of drawing them",
                "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
            },
            "400": _error(
                400,
                "pmx_truncated",
                "the model on disk is not certifiable — its morph table had to be searched for a boundary, "
                "or the walk left bytes it could not place, or it stopped before a count. not_a_pmx is the "
                "other 400: those bytes are not a PMX at all",
            ),
            "401": {"$ref": "#/components/responses/Unauthorized"},
            "404": _error(
                404,
                "character_not_found",
                "that id is not in the library; character_file_not_found is the other 404 — a character "
                "with no body to put on stage, which is what a prop-only archive looks like",
            ),
        },
    }


OPENAPI: dict = {
    "openapi": "3.1.0",
    "info": {"title": "Kira spine", "version": str(CONTRACT_VERSION)},
    "servers": [{"url": "http://127.0.0.1:8901"}],
    "components": {
        "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}},
        "schemas": {
            "ChatRequest": {
                "type": "object",
                "required": ["messages"],
                "properties": {
                    "model": {"type": "string", "nullable": True},
                    "messages": {"type": "array", "items": {"$ref": "#/components/schemas/Message"}},
                    "stream": {"type": "boolean", "default": False},
                    "temperature": {"type": "number", "default": 1.0},
                    "max_tokens": {"type": "integer", "nullable": True},
                    "mode": {"type": "string", "enum": list(MODES)},
                    "provider": {"type": "string", "nullable": True},
                    "session_id": {"type": "string", "nullable": True},
                    "tools_enabled": {"type": "boolean", "default": True},
                    "skill": {"type": "string", "nullable": True},
                },
            },
            "Message": {
                "type": "object",
                "required": ["role"],
                "properties": {
                    "role": {"type": "string", "enum": ["system", "user", "assistant", "tool"]},
                    "content": {"type": "string", "nullable": True},
                    "tool_calls": {"type": "array", "items": {"type": "object"}, "nullable": True},
                    "tool_call_id": {"type": "string", "nullable": True},
                    "name": {"type": "string", "nullable": True},
                },
            },
            "ChainRecord": {
                "type": "object",
                "description": "One routing decision. Every attempt, skip, failure and tool run is visible.",
                "required": ["event"],
                "properties": {
                    "provider": {"type": "string"},
                    "model": {"type": "string"},
                    "event": {"type": "string", "enum": list(CHAIN_EVENTS)},
                    "reason": {"type": "string"},
                    "retry_in_s": {"type": "number", "description": "skipped_cooling only"},
                    "cooldown_s": {"type": "number", "description": "failed only"},
                    "tool": {"type": "string", "description": "tool_executed, tool_denied and tool_approval_requested"},
                    "call_id": {"type": "string", "description": "tool_executed, tool_denied and tool_approval_requested"},
                    "ok": {"type": "boolean", "description": "tool_executed only"},
                    "chars": {"type": "integer", "description": "tool_executed only"},
                    "risk": {"type": "string", "enum": ["read", "write", "exec", "network"], "description": "tool events"},
                    "summary": {"type": "string", "description": "tool_executed only"},
                    "duration_ms": {"type": "integer", "description": "tool_executed for run_command"},
                    "exit_code": {"type": "integer", "description": "tool_executed for run_command"},
                    "kind": {"type": "string", "enum": ["command", "test"], "description": "tool_executed for run_command"},
                    "checkpoint_id": {"type": "string", "description": "checkpoint_created and tool_executed"},
                    "approval_id": {"type": "string", "description": "tool_approval_requested only"},
                    "files": {"type": "integer", "description": "checkpoint_created only"},
                },
            },
            "WireUsage": {
                "type": "object",
                "required": list(WIRE_USAGE_FIELDS),
                "properties": {
                    "prompt_tokens": {"type": "integer"},
                    "completion_tokens": {"type": "integer"},
                    "estimated": {
                        "type": "boolean",
                        "default": False,
                        "description": "true when the provider sent no usage and the engine estimated it",
                    },
                },
            },
            "ToolCallWire": {
                "type": "object",
                "required": ["id", "name", "arguments"],
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "arguments": {"type": "object"},
                },
            },
            "ChatCompletion": {
                "type": "object",
                "description": "Non-streaming response. Mirrors chat.completion plus Kira provenance.",
                "required": ["id", "object", "choices", "provider_chain", "status", "session_id"],
                "properties": {
                    "id": {"type": "string"},
                    "object": {"type": "string", "const": "chat.completion"},
                    "created": {"type": "integer"},
                    "model": {"type": "string", "nullable": True},
                    "provider": {"type": "string", "nullable": True},
                    "session_id": {"type": "string"},
                    "message_id": {"type": "integer"},
                    "choices": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "index": {"type": "integer"},
                                "message": {
                                    "type": "object",
                                    "properties": {
                                        "role": {"type": "string"},
                                        "content": {"type": "string"},
                                        "tool_calls": {"type": "array", "items": {"$ref": "#/components/schemas/ToolCallWire"}},
                                    },
                                },
                                "finish_reason": {"type": "string"},
                            },
                        },
                    },
                    "usage": {"$ref": "#/components/schemas/WireUsage"},
                    "status": {"type": "string", "enum": ["complete", "max_steps", "interrupted", "failed"]},
                    "provider_chain": {"type": "array", "items": {"$ref": "#/components/schemas/ChainRecord"}},
                },
            },
            "ChatChunk": CHUNK,
            "ErrorBody": {
                "type": "object",
                "required": ["code", "message", "status", "retryable"],
                "properties": {
                    "code": {
                        "type": "string",
                        "description": (
                            f"Kira codes: {', '.join(ERROR_CODES)}. "
                            f"Provider-side failures add: {', '.join(PROVIDER_CODES)}, "
                            "plus any code string the provider itself sends, so treat this as open-ended."
                        ),
                    },
                    "message": {"type": "string"},
                    "provider": {"type": "string"},
                    "status": {"type": "integer"},
                    "retryable": {"type": "boolean"},
                    "entry": {
                        "type": "string",
                        "description": (
                            "what a character refusal is about, when it has a name: the archive entry that "
                            "climbed out of the folder, the id that is not in the library, the source path "
                            "the caller supplied. Carried beside `message` so a screen can point at the "
                            "thing without parsing a sentence."
                        ),
                    },
                    "provider_chain": {"type": "array", "items": {"$ref": "#/components/schemas/ChainRecord"}},
                },
            },
            "ErrorResponse": {
                "type": "object",
                "required": ["error"],
                "properties": {"error": {"$ref": "#/components/schemas/ErrorBody"}},
            },
            "ModelInfo": {
                "type": "object",
                "required": ["id", "provider", "tier", "key_present", "needs_key"],
                "properties": {
                    "id": {"type": "string"},
                    "object": {"type": "string"},
                    "owned_by": {"type": "string"},
                    "provider": {"type": "string"},
                    "tier": {"type": "string", "enum": ["fast", "powerful"]},
                    "key_present": {
                        "type": "boolean",
                        "description": "Whether the vault holds this provider's key. False means either "
                        "'a key is wanted and missing' or 'no key is wanted'; `needs_key` tells them apart.",
                    },
                    "needs_key": {
                        "type": "boolean",
                        "description": "False for a provider that asks for no credential — a local "
                        "server on loopback. Read with `key_present`: false here means 'nothing to "
                        "store', never 'broken'.",
                    },
                },
            },
            "ModelsResponse": {
                "type": "object",
                "required": ["object", "data"],
                "properties": {
                    "object": {"type": "string", "const": "list"},
                    "data": {"type": "array", "items": {"$ref": "#/components/schemas/ModelInfo"}},
                    "live": {"type": "array", "items": {"$ref": "#/components/schemas/ProbeResponse"}},
                },
            },
            "ProviderState": {
                "type": "object",
                "description": "Cooldown ledger view. `cooling_s` counts down; 0 means ready.",
                "required": ["failures", "successes", "cooling_s", "last_reason"],
                "properties": {
                    "failures": {"type": "integer"},
                    "successes": {"type": "integer"},
                    "cooling_s": {"type": "number"},
                    "last_reason": {"type": ["string", "null"]},
                },
            },
            "ConfiguredProvider": {
                "type": "object",
                "required": ["name", "kind", "tier", "priority", "models", "key_present", "needs_key"],
                "properties": {
                    "name": {"type": "string"},
                    "kind": {"type": "string", "enum": ["openai_compat", "anthropic", "gemini"]},
                    "tier": {"type": "string"},
                    "priority": {"type": "integer"},
                    "models": {"type": "array", "items": {"type": "string"}},
                    "key_present": {"type": "boolean"},
                    "needs_key": {"type": "boolean"},
                },
            },
            "HealthResponse": {
                "type": "object",
                "required": ["providers", "configured"],
                "properties": {
                    "providers": {"type": "object", "additionalProperties": {"$ref": "#/components/schemas/ProviderState"}},
                    "configured": {"type": "array", "items": {"$ref": "#/components/schemas/ConfiguredProvider"}},
                },
            },
            "VoiceStage": {
                "type": "object",
                "description": "One half of a call. `available` is whether the configured mode can "
                "actually run here; `detail` names the missing install or provider problem verbatim, "
                "so a client never has to guess why listening or speaking is off.",
                "required": ["mode", "available", "detail"],
                "properties": {
                    "mode": {"type": "string", "enum": ["local", "remote", "off"]},
                    "available": {"type": "boolean"},
                    "detail": {"type": "string"},
                },
            },
            "VoiceStatus": {
                "type": "object",
                "required": ["stt", "tts", "vision", "limits"],
                "properties": {
                    "stt": {"$ref": "#/components/schemas/VoiceStage"},
                    "tts": {"$ref": "#/components/schemas/VoiceStage"},
                    "vision": {
                        "type": ["object", "null"],
                        "description": "The provider webcam frames would go to, or null when no enabled "
                        "provider declares `vision: true` — then frames stay on this device.",
                        "required": ["provider", "model"],
                        "properties": {
                            "provider": {"type": "string"},
                            "model": {"type": "string"},
                        },
                    },
                    "limits": {
                        "type": "object",
                        "required": ["max_utterance_s", "silence_ms"],
                        "properties": {
                            "max_utterance_s": {"type": "integer", "description": "Longest single utterance the VAD will hand to STT."},
                            "silence_ms": {"type": "integer", "description": "Quiet time that closes an utterance."},
                        },
                    },
                },
            },
            "SessionRow": {
                "type": "object",
                "description": "One session with what it cost. `last_used_at` is the newest message timestamp, null for an empty session.",
                "required": ["id", "mode", "created_at", "message_count", "tokens", "last_used_at"],
                "properties": {
                    "id": {"type": "string"},
                    "mode": {"type": "string"},
                    "created_at": {"type": "number"},
                    "message_count": {"type": "integer"},
                    "tokens": {"type": "integer", "description": "input + output, combined, as every other total in this contract"},
                    "last_used_at": {"type": ["number", "null"]},
                },
            },
            "SessionsResponse": {
                "type": "object",
                "required": ["sessions"],
                "properties": {
                    "sessions": {"type": "array", "items": {"$ref": "#/components/schemas/SessionRow"}}
                },
            },
            "MessageRow": {
                "type": "object",
                "description": "One stored message, with the chain that produced it when it is an answer.",
                "required": ["id", "session_id", "role", "content", "status"],
                "properties": {
                    "id": {"type": "integer"},
                    "session_id": {"type": "string"},
                    "role": {"type": "string"},
                    "content": {"type": "string"},
                    "provider": {"type": ["string", "null"]},
                    "model": {"type": ["string", "null"]},
                    "finish_reason": {"type": ["string", "null"]},
                    "status": {"type": "string", "enum": ["complete", "max_steps", "interrupted", "failed"]},
                    "created_at": {"type": "number"},
                    "tool_calls": {"type": "array", "items": {"$ref": "#/components/schemas/ToolCallWire"}},
                    "usage": {
                        "type": "object",
                        "description": "Stored with engine-internal names, not the OpenAI-style wire names.",
                        "properties": {
                            "input_tokens": {"type": "integer"},
                            "output_tokens": {"type": "integer"},
                        },
                    },
                    "chain": {"type": "array", "items": {"$ref": "#/components/schemas/ChainRecord"}},
                },
            },
            "MessagesResponse": {
                "type": "object",
                "required": ["session_id", "messages"],
                "properties": {
                    "session_id": {"type": "string"},
                    "messages": {"type": "array", "items": {"$ref": "#/components/schemas/MessageRow"}},
                },
            },
            "HealthzResponse": {
                "type": "object",
                "description": (
                    "The one endpoint outside the version namespace, because it is how a caller finds out which "
                    "namespace this engine serves. Both versions are published here: `api_version` says whether "
                    "the paths still mean what the caller thinks, `contract_version` says whether the fields did."
                ),
                "required": ["ok", "api_version", "contract_version", "providers_configured", "default_mode"],
                "properties": {
                    "ok": {"type": "boolean", "const": True},
                    "api_version": {"type": "integer"},
                    "contract_version": {"type": "integer"},
                    "providers_configured": {"type": "integer"},
                    "default_mode": {"type": "string"},
                },
            },
            "FieldStateBool": {
                "type": "object",
                "description": "One tunable boolean: what config.yaml says, what the settings table overrides, what the router uses.",
                "required": ["base", "override", "effective"],
                "properties": {
                    "base": {"type": "boolean"},
                    "override": {"type": ["boolean", "null"]},
                    "effective": {"type": "boolean"},
                },
            },
            "FieldStateInt": {
                "type": "object",
                "required": ["base", "override", "effective"],
                "properties": {
                    "base": {"type": "integer"},
                    "override": {"type": ["integer", "null"]},
                    "effective": {"type": "integer"},
                },
            },
            "FieldStateStr": {
                "type": "object",
                "required": ["base", "override", "effective"],
                "properties": {
                    "base": {"type": "string"},
                    "override": {"type": ["string", "null"]},
                    "effective": {"type": "string"},
                },
            },
            "FieldStateCap": {
                "type": "object",
                "description": "Monthly token cap. null means unlimited at every level, so a null effective value is not 'missing'.",
                "required": ["base", "override", "effective"],
                "properties": {
                    "base": {"type": ["integer", "null"]},
                    "override": {"type": ["integer", "null"]},
                    "effective": {"type": ["integer", "null"]},
                },
            },
            "ProviderView": {
                "type": "object",
                "description": "A provider as the router currently sees it. `name`, `kind`, `base_url`, `models` and `vision` are config.yaml-only.",
                "required": [
                    "name", "kind", "base_url", "models", "key_ref", "key_present", "needs_key", "vision",
                    "enabled", "priority", "tier", "monthly_cap", "spend_this_month", "health",
                ],
                "properties": {
                    "name": {"type": "string"},
                    "kind": {"type": "string", "enum": ["openai_compat", "anthropic", "gemini"]},
                    "base_url": {"type": "string"},
                    "models": {"type": "array", "items": {"type": "string"}},
                    "key_ref": {"type": "string", "description": "Credential Locker ref name. Never the value."},
                    "key_present": {"type": "boolean"},
                    "needs_key": {
                        "type": "boolean",
                        "description": "False when the stanza declares no `key_ref` and none is wanted — "
                        "a local server on loopback. A dashboard must not call that row 'no key'.",
                    },
                    "vision": {
                        "type": "boolean",
                        "description": "True only when config.yaml says this endpoint accepts images, "
                        "which is what lets a call attach a webcam frame to an answer.",
                    },
                    "enabled": {"$ref": "#/components/schemas/FieldStateBool"},
                    "priority": {"$ref": "#/components/schemas/FieldStateInt"},
                    "tier": {"$ref": "#/components/schemas/FieldStateStr"},
                    "monthly_cap": {"$ref": "#/components/schemas/FieldStateCap"},
                    "spend_this_month": {"type": "integer"},
                    "health": {"$ref": "#/components/schemas/ProviderState"},
                },
            },
            "ProvidersResponse": {
                "type": "object",
                "required": ["providers", "orphan_settings", "month"],
                "properties": {
                    "providers": {"type": "array", "items": {"$ref": "#/components/schemas/ProviderView"}},
                    "orphan_settings": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "'provider.key' rows the settings table holds but config.yaml no longer has a provider or a tunable key for",
                    },
                    "month": {"type": "string", "description": "YYYY-MM the spend figures are for"},
                },
            },
            "TokenSplit": {
                "type": "object",
                "required": ["input", "output"],
                "properties": {"input": {"type": "integer"}, "output": {"type": "integer"}},
            },
            "ProviderUsage": {
                "type": "object",
                "required": ["provider", "turns", "tokens"],
                "properties": {
                    "provider": {"type": "string"},
                    "turns": {"type": "integer"},
                    "tokens": {"type": "integer"},
                },
            },
            "ModelUsage": {
                "type": "object",
                "required": ["provider", "model", "turns", "tokens"],
                "properties": {
                    "provider": {"type": "string"},
                    # A turn that failed before a model was answered with has nothing to name.
                    # It still counts in `turns`, so dropping the row would make the table
                    # disagree with the stat card above it.
                    "model": {"type": ["string", "null"]},
                    "turns": {"type": "integer"},
                    "tokens": {"type": "integer"},
                },
            },
            "DailyUsage": {
                "type": "object",
                "description": "Only days inside the selected month, oldest first: the sparkline plots exactly these points.",
                "required": ["date", "turns", "tokens"],
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD in UTC"},
                    "turns": {"type": "integer"},
                    "tokens": {"type": "integer"},
                },
            },
            "BudgetRow": {
                "type": "object",
                "description": "cap null means unlimited, and then remaining is null - a bar with no right edge, not a full one.",
                "required": ["provider", "cap", "used", "remaining"],
                "properties": {
                    "provider": {"type": "string"},
                    "cap": {"type": ["integer", "null"]},
                    "used": {"type": "integer"},
                    "remaining": {"type": ["integer", "null"]},
                },
            },
            "RecentIssue": {
                "type": "object",
                "description": "A turn that did not finish cleanly, newest first, at most ten.",
                "required": ["id", "session_id", "status", "provider", "model", "created_at", "reason"],
                "properties": {
                    "id": {"type": "integer"},
                    "session_id": {"type": "string"},
                    "status": {"type": "string", "enum": ["interrupted", "failed"]},
                    "provider": {"type": ["string", "null"]},
                    "model": {"type": ["string", "null"]},
                    "created_at": {"type": "number"},
                    "reason": {"type": "string"},
                },
            },
            "RefusalRecord": {
                "type": "object",
                "description": "A turn the plan refused before a session existed. No message row can hold it; this ledger is the record.",
                "required": ["code", "message", "mode", "model", "created_at"],
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "mode": {"type": ["string", "null"]},
                    "model": {"type": ["string", "null"]},
                    "created_at": {"type": "number"},
                },
            },
            "RefusalSummary": {
                "type": "object",
                "description": "Refusals in the window. They are not in `turns`: a refusal writes no message row, so counting it there would invent a turn that never started.",
                "required": ["count", "by_code", "recent"],
                "properties": {
                    "count": {"type": "integer"},
                    "by_code": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["code", "count"],
                            "properties": {
                                "code": {"type": "string"},
                                "count": {"type": "integer"},
                            },
                        },
                    },
                    "recent": {"type": "array", "items": {"$ref": "#/components/schemas/RefusalRecord"}},
                },
            },
            "OverviewResponse": {
                "type": "object",
                "required": [
                    "month", "turns", "tokens", "success_rate", "interrupted", "failed",
                    "by_provider", "by_model", "daily", "budgets", "recent_issues", "refusals",
                ],
                "properties": {
                    "month": {"type": "string"},
                    "turns": {"type": "integer", "description": "assistant rows in the window"},
                    "tokens": {"$ref": "#/components/schemas/TokenSplit"},
                    "success_rate": {
                        "type": ["number", "null"],
                        "description": "(turns - interrupted - failed) / turns; null when turns is 0 because 'no data' is not '0% healthy'",
                    },
                    "interrupted": {"type": "integer"},
                    "failed": {"type": "integer"},
                    "by_provider": {"type": "array", "items": {"$ref": "#/components/schemas/ProviderUsage"}},
                    "by_model": {"type": "array", "items": {"$ref": "#/components/schemas/ModelUsage"}},
                    "daily": {"type": "array", "items": {"$ref": "#/components/schemas/DailyUsage"}},
                    "budgets": {"type": "array", "items": {"$ref": "#/components/schemas/BudgetRow"}},
                    "recent_issues": {"type": "array", "items": {"$ref": "#/components/schemas/RecentIssue"}},
                    "refusals": {"$ref": "#/components/schemas/RefusalSummary"},
                },
            },
            "ProbeResponse": {
                "type": "object",
                "description": "One live probe. A failure is ok:false with the reason, never an HTTP error, so the UI can show it inline. Probe traffic is not stored as a conversation and does not count toward a month's spend.",
                "required": ["provider", "ok", "latency_ms", "error"],
                "properties": {
                    "provider": {"type": "string"},
                    "ok": {"type": "boolean"},
                    "model_count": {"type": "integer"},
                    "sample": {"type": "array", "items": {"type": "string"}},
                    "latency_ms": {"type": ["integer", "null"], "description": "the one-cap completion only; null for a list-only probe"},
                    "error": {"type": ["string", "null"]},
                },
            },
            "ProviderSettings": {
                "type": "object",
                "description": "The four tunable fields, as base/override/effective after a write.",
                "required": ["enabled", "priority", "tier", "monthly_cap"],
                "properties": {
                    "enabled": {"$ref": "#/components/schemas/FieldStateBool"},
                    "priority": {"$ref": "#/components/schemas/FieldStateInt"},
                    "tier": {"$ref": "#/components/schemas/FieldStateStr"},
                    "monthly_cap": {"$ref": "#/components/schemas/FieldStateCap"},
                },
            },
            "SettingsResponse": {
                "type": "object",
                "required": ["provider", "settings"],
                "properties": {
                    "provider": {"type": "string"},
                    "settings": {"$ref": "#/components/schemas/ProviderSettings"},
                },
            },
            "SettingsRequest": {
                "type": "object",
                "description": "Any subset of the tunable fields. null deletes that override and returns to config.yaml; monthly_cap 0 means unlimited - the two must not be confused.",
                "properties": {
                    "enabled": {"type": ["boolean", "null"]},
                    "priority": {"type": ["integer", "null"], "minimum": 0, "maximum": 1000},
                    "tier": {"type": ["string", "null"]},
                    "monthly_cap": {"type": ["integer", "null"], "minimum": 0},
                },
            },
            "KeyRequest": {
                "type": "object",
                "required": ["key"],
                "properties": {"key": {"type": "string", "minLength": 1}},
            },
            "KeyResponse": {
                "type": "object",
                "description": "Presence, never the value.",
                "required": ["provider", "key_ref", "key_present"],
                "properties": {
                    "provider": {"type": "string"},
                    "key_ref": {"type": "string"},
                    "key_present": {"type": "boolean"},
                },
            },
            "DeletedResponse": {
                "type": "object",
                "required": ["deleted", "messages"],
                "properties": {
                    "deleted": {"type": "integer", "description": "sessions removed"},
                    "messages": {"type": "integer", "description": "messages removed with them"},
                },
            },
            "ApprovalInfo": {
                "type": "object",
                "description": "One ask-policy tool call waiting on a decision. The arguments are what the model wanted to run, never a secret.",
                "required": ["id", "tool", "arguments", "risk", "status", "created_at", "expires_at"],
                "properties": {
                    "id": {"type": "string"},
                    "session_id": {"type": ["string", "null"]},
                    "tool": {"type": "string"},
                    "arguments": {"type": "object"},
                    "risk": {"type": "string", "enum": ["read", "write", "exec", "network"]},
                    "status": {"type": "string", "enum": ["pending", "allowed", "denied", "expired"]},
                    "reason": {"type": ["string", "null"]},
                    "created_at": {"type": "number"},
                    "expires_at": {"type": "number"},
                    "decided_at": {"type": ["number", "null"]},
                },
            },
            "ApprovalsResponse": {
                "type": "object",
                "required": ["approvals"],
                "properties": {"approvals": {"type": "array", "items": {"$ref": "#/components/schemas/ApprovalInfo"}}},
            },
            "ApprovalResponse": {
                "type": "object",
                "required": ["approval"],
                "properties": {"approval": {"$ref": "#/components/schemas/ApprovalInfo"}},
            },
            "ApprovalDecision": {
                "type": "object",
                "required": ["decision"],
                "properties": {
                    "decision": {"type": "string", "enum": ["allow", "deny"]},
                    "reason": {"type": "string", "description": "shown to the model when the answer is deny"},
                },
            },
            "CheckpointFile": {
                "type": "object",
                "description": "One file a checkpoint holds. `existed: false` means the write created it, so restoring deletes it.",
                "required": ["path", "existed"],
                "properties": {
                    "path": {"type": "string", "description": "workspace-relative, posix separators"},
                    "existed": {"type": "boolean"},
                    "sha256_before": {"type": ["string", "null"]},
                    "sha256_after": {"type": ["string", "null"]},
                    "size": {"type": "integer"},
                    "blob": {"type": ["string", "null"], "description": "engine-internal blob name"},
                },
            },
            "CheckpointInfo": {
                "type": "object",
                "description": "One pre-write snapshot. `restore` itself takes a checkpoint whose tool is 'restore'.",
                "required": ["id", "tool", "files", "status", "created_at"],
                "properties": {
                    "id": {"type": "string"},
                    "session_id": {"type": ["string", "null"]},
                    "tool": {"type": "string"},
                    "call_id": {"type": "string"},
                    "scope": {"type": "string", "enum": ["files"]},
                    "files": {"type": "array", "items": {"$ref": "#/components/schemas/CheckpointFile"}},
                    "status": {"type": "string", "enum": ["open", "complete", "restored"]},
                    "created_at": {"type": "number"},
                    "finalized_at": {"type": ["number", "null"]},
                    "restored_at": {"type": ["number", "null"]},
                },
            },
            "CheckpointsResponse": {
                "type": "object",
                "required": ["checkpoints"],
                "properties": {"checkpoints": {"type": "array", "items": {"$ref": "#/components/schemas/CheckpointInfo"}}},
            },
            "CheckpointDiff": {
                "type": "object",
                "required": ["checkpoint", "files"],
                "properties": {
                    "checkpoint": {"$ref": "#/components/schemas/CheckpointInfo"},
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["path", "existed", "changed", "diff"],
                            "properties": {
                                "path": {"type": "string"},
                                "existed": {"type": "boolean"},
                                "changed": {"type": "boolean"},
                                "diff": {"type": "string", "description": "unified diff, or 'binary differs'"},
                            },
                        },
                    },
                },
            },
            "CheckpointRestore": {
                "type": "object",
                "required": ["restored", "conflicts", "checkpoint_id"],
                "properties": {
                    "restored": {"type": "array", "items": {"type": "string"}},
                    "conflicts": {"type": "array", "items": {"type": "object"}},
                    "checkpoint_id": {"type": "string", "description": "the safety checkpoint this restore took"},
                },
            },
            "CheckpointRestoreRequest": {
                "type": "object",
                "properties": {
                    "force": {"type": "boolean", "default": False, "description": "restore over files that changed since the checkpoint"},
                },
            },
            "ToolInfo": {
                "type": "object",
                "description": "One callable tool: its JSON schema, the risk class, where it came from and what it is set to now.",
                "required": ["name", "description", "parameters", "risk", "source", "default_policy", "policy", "overridden"],
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "parameters": {"type": "object"},
                    "risk": {"type": "string", "enum": ["read", "write", "exec", "network"]},
                    "source": {"type": "string", "description": "'builtin' or 'plugin:<file>'"},
                    "default_policy": {"type": "string", "enum": ["allow", "ask", "deny"]},
                    "policy": {"type": "string", "enum": ["allow", "ask", "deny"], "description": "override if set, else the default"},
                    "overridden": {"type": "boolean"},
                },
            },
            "PluginInfo": {
                "type": "object",
                "description": "One file in the plugins directory. A bad file is 'skipped' with its reason, never a startup failure.",
                "required": ["file", "name", "status", "reason"],
                "properties": {
                    "file": {"type": "string"},
                    "name": {"type": "string"},
                    "status": {"type": "string", "enum": ["loaded", "skipped"]},
                    "reason": {"type": "string"},
                },
            },
            "MemoryItem": {
                "type": "object",
                "required": ["id", "kind", "text", "pinned", "origin", "created_at", "updated_at", "use_count"],
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"type": "string", "enum": ["fact", "preference", "note"]},
                    "text": {"type": "string"},
                    "pinned": {"type": "boolean"},
                    "origin": {"type": "string", "enum": ["user", "tool", "auto"]},
                    "session_id": {"type": "string", "nullable": True},
                    "tokens_spent": {"type": "integer", "description": "the extraction call's share, origin=auto"},
                    "created_at": {"type": "number"},
                    "updated_at": {"type": "number"},
                    "last_used_at": {"type": "number", "nullable": True},
                    "use_count": {"type": "integer"},
                },
            },
            "MemoryList": {
                "type": "object",
                "required": ["memories", "total", "settings"],
                "properties": {
                    "memories": {"type": "array", "items": {"$ref": "#/components/schemas/MemoryItem"}},
                    "total": {"type": "integer"},
                    "settings": {"$ref": "#/components/schemas/MemorySettings"},
                },
            },
            "MemoryWrite": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text"],
                "properties": {
                    "text": {"type": "string", "maxLength": 2000},
                    "kind": {"type": "string", "enum": ["fact", "preference", "note"]},
                    "pinned": {"type": "boolean"},
                },
            },
            "MemoryPatch": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "text": {"type": "string", "maxLength": 2000},
                    "kind": {"type": "string", "enum": ["fact", "preference", "note"]},
                    "pinned": {"type": "boolean"},
                },
            },
            "MemorySettings": {
                "type": "object",
                "required": ["inject", "capture", "extract", "tokenizer"],
                "properties": {
                    "inject": {"type": "boolean"},
                    "capture": {"type": "string", "enum": ["off", "explicit"]},
                    "extract": {"type": "boolean"},
                    "tokenizer": {
                        "type": "string",
                        "enum": ["trigram", "unicode61"],
                        "description": "read-only: which index tokenizer this SQLite build gave us",
                    },
                },
            },
            "MemoryDeleted": {
                "type": "object",
                "required": ["deleted"],
                "properties": {"deleted": {"type": "string"}},
            },
            "MemoryHit": {
                "type": "object",
                "required": ["session_id", "message_id", "role", "snippet", "created_at"],
                "properties": {
                    "session_id": {"type": "string"},
                    "message_id": {"type": "integer"},
                    "role": {"type": "string", "enum": ["user", "assistant"]},
                    "snippet": {"type": "string", "description": "the engine brackets the match with [ ]"},
                    "created_at": {"type": "number"},
                },
            },
            "MemorySearch": {
                "type": "object",
                "required": ["hits"],
                "properties": {"hits": {"type": "array", "items": {"$ref": "#/components/schemas/MemoryHit"}}},
            },
            "MemoryExport": {
                "type": "object",
                "required": ["version", "exported_at", "memories"],
                "properties": {
                    "version": {"type": "integer", "description": "export format, not the API version"},
                    "exported_at": {"type": "number"},
                    "memories": {"type": "array", "items": {"$ref": "#/components/schemas/MemoryItem"}},
                },
            },
            "MemorySettingsPatch": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "inject": {"type": "boolean"},
                    "capture": {"type": "string", "enum": ["off", "explicit"]},
                    "extract": {"type": "boolean"},
                },
                "description": (
                    "a subset of the three writable switches; strict-typed, so a prose boolean like "
                    "\"yes\" is 400, and `tokenizer` is not writable"
                ),
            },
            "ToolsResponse": {
                "type": "object",
                "required": ["tools", "plugins"],
                "properties": {
                    "tools": {"type": "array", "items": {"$ref": "#/components/schemas/ToolInfo"}},
                    "plugins": {"type": "array", "items": {"$ref": "#/components/schemas/PluginInfo"}},
                },
            },
            "SkillInfo": {
                "type": "object",
                "required": ["name", "description", "kind", "source", "body_bytes"],
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "kind": {"type": "string", "enum": ["persona", "method"]},
                    "source": {"type": "string", "enum": ["builtin", "user"]},
                    "body_bytes": {"type": "integer"},
                },
            },
            "SkillFile": {
                "type": "object",
                "required": ["file", "name", "status", "reason", "source"],
                "properties": {
                    "file": {"type": "string"},
                    "name": {"type": "string"},
                    "status": {"type": "string", "enum": ["loaded", "skipped", "shadowed"]},
                    "reason": {"type": "string"},
                    "source": {"type": "string", "enum": ["builtin", "user"]},
                },
            },
            "SkillsResponse": {
                "type": "object",
                "required": ["skills", "files", "discovery"],
                "properties": {
                    "skills": {"type": "array", "items": {"$ref": "#/components/schemas/SkillInfo"}},
                    "files": {"type": "array", "items": {"$ref": "#/components/schemas/SkillFile"}},
                    "discovery": {
                        "type": "string",
                        "enum": ["none", "inline", "search"],
                        "description": "how a model reaches a method: no methods, the names are in the use_skill schema, or search_skills finds them",
                    },
                },
            },
            "PairRequest": {
                "type": "object",
                "additionalProperties": False,
                "required": ["code", "name"],
                "properties": {
                    "code": {"type": "string", "description": "the 8 characters the desktop showed"},
                    "name": {"type": "string", "description": "1-40 characters, shown in the device list"},
                },
            },
            "DeviceInfo": {
                "type": "object",
                "required": ["id", "name", "created_at", "last_seen_at"],
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "created_at": {"type": "number"},
                    "last_seen_at": {"type": "number"},
                },
            },
            "PairResponse": {
                "type": "object",
                "required": ["token", "device"],
                "properties": {
                    "token": {
                        "type": "string",
                        "description": "shown once, and only its SHA-256 is stored engine-side",
                    },
                    "device": {"$ref": "#/components/schemas/DeviceInfo"},
                },
            },
            "DevicesResponse": {
                "type": "object",
                "required": ["devices"],
                "properties": {
                    "devices": {"type": "array", "items": {"$ref": "#/components/schemas/DeviceInfo"}},
                },
            },
            "DeviceDeleted": {
                "type": "object",
                "required": ["deleted"],
                "properties": {"deleted": {"type": "string", "description": "the revoked device's id"}},
            },
            "PairingCodeResponse": {
                "type": "object",
                "required": ["code", "expires_at"],
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "8 characters from 0-9 and A-Z without I, L, O or U",
                    },
                    "expires_at": {"type": "number", "description": "unix seconds; the code dies after 120"},
                },
            },
            "ToolPolicyRequest": {
                "type": "object",
                "description": "null deletes the override and returns the tool to its risk default.",
                "properties": {"policy": {"type": ["string", "null"], "enum": ["allow", "ask", "deny", None]}},
            },
            "ToolPolicyResponse": {
                "type": "object",
                "required": ["tool"],
                "properties": {
                    "tool": {
                        "type": "object",
                        "required": ["name", "policy", "overridden"],
                        "properties": {
                            "name": {"type": "string"},
                            "policy": {"type": "string", "enum": ["allow", "ask", "deny"]},
                            "overridden": {"type": "boolean"},
                        },
                    }
                },
            },
            # --- the character library (unit 11) -------------------------------------------------------
            # The report is published field by field, not as a free-form object, because the stage reads
            # these numbers to decide whether physics is worth running and whether the model is a body at
            # all. A client that reimplemented that test from a guess is how two screens end up disagreeing
            # about the same file, so the engine's own derived answers ship next to the counts they came
            # from. `unreadable` and the two nullable names are the engine admitting what it could not
            # measure, which is why they are in the contract rather than absent from it.
            "TextureFinding": {
                "type": "object",
                "required": ["declared", "relative", "exists", "format", "escapes"],
                "properties": {
                    "declared": {
                        "type": "string",
                        "description": "the path the material table wrote, verbatim: `tex\\\\颜.tga` stays a windows path",
                    },
                    "relative": {"type": "string", "description": "normalised to posix, relative to the model's own folder"},
                    "exists": {"type": "boolean"},
                    "size": {"type": ["integer", "null"], "description": "bytes on disk, null when it does not exist"},
                    "format": {"type": "string", "description": "png/bmp/tga/... from the bytes, '' when unread"},
                    "escapes": {
                        "type": "boolean",
                        "description": "the declared path points outside the character folder: never fetched",
                    },
                },
            },
            "CharacterCapability": {
                "type": "object",
                "description": "One PMX, measured by walking it. The same code writes this at import and the CLI shows it.",
                "required": [
                    "path", "name", "english_name", "file_name", "version", "count_framing",
                    "material_framing", "counts", "vertices", "bones", "triangles", "has_physics",
                    "is_character", "texture_status", "standard_groups", "finger_bone_count",
                    "morph_names", "morph_kinds", "frame_names", "textures", "texture_resolved",
                    "missing_textures", "sphere_texture_refs", "shared_toon_refs", "ik_bone_count",
                    "trailing_bytes", "findings",
                ],
                "properties": {
                    "path": {"type": "string", "description": "relative to the character's folder; the body is always `model.pmx`"},
                    "name": {"type": "string", "description": "as the file wrote it, in its own script"},
                    "english_name": {"type": "string"},
                    "file_name": {"type": "string", "description": "the name it arrived under"},
                    "version": {"type": "number", "description": "2.0 or 2.1; the only two this reader walks"},
                    "count_framing": {"type": "string", "enum": ["header", "inline"]},
                    "material_framing": {"type": "string", "enum": ["draw_and_memos", "memo_only"]},
                    "counts": {
                        "type": "object",
                        "description": "the nine section counts, each null when the walk could not earn it",
                        "properties": {
                            "vertex_count": {"type": ["integer", "null"]},
                            "face_index_count": {"type": ["integer", "null"]},
                            "texture_count": {"type": ["integer", "null"]},
                            "material_count": {"type": ["integer", "null"]},
                            "bone_count": {"type": ["integer", "null"]},
                            "morph_count": {"type": ["integer", "null"]},
                            "frame_count": {"type": ["integer", "null"]},
                            "rigid_body_count": {"type": ["integer", "null"]},
                            "constraint_count": {"type": ["integer", "null"]},
                        },
                    },
                    "vertices": {"type": "integer"},
                    "bones": {"type": "integer"},
                    "triangles": {"type": "integer", "description": "face_index_count / 3"},
                    "has_physics": {"type": "boolean", "description": "at least one rigid body"},
                    "is_character": {"type": "boolean", "description": "the body test: bones and vertices, decided engine-side"},
                    "texture_status": {"type": "string", "description": "`8/8`, `7/8 — hair.bmp absent`, or `no textures`"},
                    "standard_groups": {"type": "array", "items": {"type": "string"}},
                    "finger_bone_count": {"type": "integer"},
                    "morph_names": {"type": "array", "items": {"type": "string"}},
                    "morph_kinds": {"type": "array", "items": {"type": "integer"}},
                    "frame_names": {"type": "array", "items": {"type": "string"}},
                    "textures": {"type": "array", "items": {"$ref": "#/components/schemas/TextureFinding"}},
                    "texture_resolved": {"type": "integer"},
                    "missing_textures": {"type": "array", "items": {"type": "string"}},
                    "sphere_texture_refs": {"type": "integer"},
                    "shared_toon_refs": {"type": "integer"},
                    "ik_bone_count": {"type": "integer"},
                    "trailing_bytes": {"type": "integer", "description": "bytes past the last section the walk reached"},
                    "findings": {"type": "array", "items": {"type": "string"}},
                    "license_note": {"type": ["string", "null"]},
                    "unreadable": {"type": ["string", "null"], "description": "why nothing was measured, in words"},
                },
            },
            "ImageModel": {
                "type": "object",
                "description": "One checkpoint this machine can draw with. The name is the filename without its extension, and it is what a generation request names.",
                "required": ["name", "filename", "size_bytes", "kind"],
                "properties": {
                    "name": {"type": "string"},
                    "filename": {"type": "string"},
                    "size_bytes": {"type": "integer"},
                    "kind": {"type": "string", "description": "safetensors, ckpt or gguf"},
                },
            },
            "ImageOutput": {
                "type": "object",
                "description": "One generated PNG and the settings that made it, as the sidecar recorded them.",
                "required": [
                    "name", "url", "prompt", "negative_prompt", "model", "steps", "cfg_scale",
                    "width", "height", "seed", "sampler", "created_at", "duration_ms", "backend",
                ],
                "properties": {
                    "name": {"type": "string", "description": "the PNG's filename; the id the file and delete routes take"},
                    "url": {"type": "string", "description": "the authenticated path the bytes are fetched from"},
                    "prompt": {"type": "string"},
                    "negative_prompt": {"type": "string"},
                    "model": {"type": "string"},
                    "steps": {"type": "integer"},
                    "cfg_scale": {"type": "number"},
                    "width": {"type": "integer"},
                    "height": {"type": "integer"},
                    "seed": {"type": "integer"},
                    "sampler": {"type": "string"},
                    "created_at": {"type": "string", "description": "ISO-8601 UTC"},
                    "duration_ms": {"type": "integer"},
                    "backend": {"type": "string", "description": "local for the managed executable, remote for KIRA_SD_URL"},
                },
            },
            "ImagesStatus": {
                "type": "object",
                "description": "What the Images screen needs to draw a form or say why it cannot: the engine, the checkpoints, and the gallery.",
                "required": [
                    "ready", "reason", "backend", "backend_path", "remote_url", "engine_dir",
                    "model_dir", "output_dir", "models", "outputs",
                ],
                "properties": {
                    "ready": {"type": "boolean"},
                    "reason": {"type": ["string", "null"], "description": "why nothing can draw yet, in the words the screen shows"},
                    "backend": {"type": ["string", "null"], "description": "local, remote, or null when neither is configured"},
                    "backend_path": {"type": ["string", "null"]},
                    "remote_url": {"type": ["string", "null"]},
                    "engine_dir": {"type": "string"},
                    "model_dir": {"type": "string"},
                    "output_dir": {"type": "string"},
                    "models": {"type": "array", "items": {"$ref": "#/components/schemas/ImageModel"}},
                    "outputs": {"type": "array", "items": {"$ref": "#/components/schemas/ImageOutput"}},
                },
            },
            "ImageGenerateRequest": {
                "type": "object",
                "required": ["prompt"],
                "properties": {
                    "prompt": {"type": "string"},
                    "negative_prompt": {"type": "string"},
                    "model": {"type": ["string", "null"], "description": "a name from ImagesStatus.models; absent picks the first"},
                    "steps": {"type": "integer", "description": "1-150"},
                    "cfg_scale": {"type": "number", "description": "0-30"},
                    "width": {"type": "integer", "description": "multiple of 8, 64-2048"},
                    "height": {"type": "integer", "description": "multiple of 8, 64-2048"},
                    "seed": {"type": "integer", "description": "-1 picks one and the answer carries it"},
                    "sampler": {"type": "string"},
                },
            },
            "StudioModel": {
                "type": "object",
                "required": ["name", "filename", "size_bytes", "kind"],
                "properties": {
                    "name": {"type": "string"},
                    "filename": {"type": "string"},
                    "size_bytes": {"type": "integer"},
                    "kind": {"type": "string"},
                },
            },
            "StudioPart": {
                "type": "object",
                "required": ["available", "engine", "detail", "models"],
                "properties": {
                    "available": {"type": "boolean"},
                    "engine": {"type": ["string", "null"]},
                    "detail": {"type": "string"},
                    "models": {"type": "array", "items": {"$ref": "#/components/schemas/StudioModel"}},
                },
            },
            "StudioLlmPart": {
                "type": "object",
                "required": [
                    "available", "engine", "detail", "models", "running", "model", "url",
                    "model_dir", "engine_dir", "reason",
                ],
                "properties": {
                    "available": {"type": "boolean"},
                    "engine": {"type": ["string", "null"]},
                    "detail": {"type": "string"},
                    "models": {"type": "array", "items": {"$ref": "#/components/schemas/StudioModel"}},
                    "running": {"type": "boolean"},
                    "model": {"type": ["string", "null"]},
                    "url": {"type": ["string", "null"]},
                    "model_dir": {"type": "string"},
                    "engine_dir": {"type": "string"},
                    "reason": {"type": ["string", "null"], "description": "why a start would refuse, in the screen's words"},
                },
            },
            "StudioStatus": {
                "type": "object",
                "description": "The Portable AI Studio components Kira can see, or Kira's own folders when there is no studio.",
                "required": ["root", "available", "image", "llm", "stt", "tts"],
                "properties": {
                    "root": {"type": ["string", "null"], "description": "the studio folder, or null"},
                    "available": {"type": "boolean"},
                    "image": {"$ref": "#/components/schemas/StudioPart"},
                    "llm": {"$ref": "#/components/schemas/StudioLlmPart"},
                    "stt": {"$ref": "#/components/schemas/StudioPart"},
                    "tts": {"$ref": "#/components/schemas/StudioPart"},
                },
            },
            "StudioLlmRequest": {
                "type": "object",
                "properties": {"model": {"type": ["string", "null"], "description": "a GGUF name; absent picks the first"}},
            },
            "StudioDownloadRequest": {
                "type": "object",
                "required": ["kind", "url"],
                "properties": {
                    "kind": {"type": "string", "enum": ["llm", "image", "stt"]},
                    "url": {"type": "string"},
                    "filename": {"type": ["string", "null"]},
                },
            },
            "StudioDownloadResult": {
                "type": "object",
                "required": ["name", "filename", "kind", "bytes", "path"],
                "properties": {
                    "name": {"type": "string"},
                    "filename": {"type": "string"},
                    "kind": {"type": "string"},
                    "bytes": {"type": "integer"},
                    "path": {"type": "string"},
                },
            },
            "StudioRuntime": {
                "type": "object",
                "description": "The studio's Node server: whether it answers, who owns the process, and on which loopback port.",
                "required": ["found", "running", "managed", "external", "url", "root", "pid", "error", "health"],
                "properties": {
                    "found": {"type": "boolean", "description": "a studio folder was discovered"},
                    "running": {"type": "boolean", "description": "the server answered its health probe"},
                    "managed": {"type": "boolean", "description": "Kira spawned this process and stops it"},
                    "external": {"type": "boolean", "description": "the address came from KIRA_STUDIO_URL, not Kira"},
                    "url": {"type": ["string", "null"], "description": "loopback base URL, or null while stopped"},
                    "root": {"type": ["string", "null"]},
                    "pid": {"type": ["integer", "null"]},
                    "error": {"type": ["string", "null"]},
                    "health": {
                        "type": ["object", "null"],
                        "properties": {
                            "build": {"type": ["string", "null"]},
                            "issues": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
            "StudioProxyResult": {
                "type": "object",
                "description": "The studio's own JSON, passed through unchanged. A WAV or image body keeps its content type instead.",
                "additionalProperties": True,
            },
            "StudioProxyRequest": {
                "type": "object",
                "description": "Sent to the studio unchanged. Transcribe is the exception: it takes a raw WAV body as audio/wav, not JSON.",
                "additionalProperties": True,
            },
            "ImageDeleted": {
                "type": "object",
                "required": ["deleted"],
                "properties": {"deleted": {"type": "string"}},
            },
            "CharacterRow": {
                "type": "object",
                "description": "The library list item: enough to choose a character without opening its folder. Every number here was written by the import that measured it.",
                "required": [
                    "id", "display_name", "english_name", "source_file_name", "sha256", "imported_at",
                    "is_character", "vertices", "bones", "has_physics", "companion_count", "reason",
                ],
                "properties": {
                    "id": {"type": "string", "description": "`<slug>-<8 hex>`; the folder name, and the id every other route takes"},
                    "display_name": {"type": "string"},
                    "english_name": {"type": "string"},
                    "source_file_name": {"type": "string", "description": "the archive or file it was imported from"},
                    "sha256": {"type": "string", "description": "of the source bytes; importing them again answers already_imported"},
                    "imported_at": {"type": "string", "description": "ISO-8601 UTC, second precision"},
                    "is_character": {"type": "boolean", "description": "false when the archive held only props"},
                    "main_name": {"type": ["string", "null"]},
                    "path": {"type": ["string", "null"], "description": "the body's path, always `model.pmx`"},
                    "vertices": {"type": "integer", "description": "0 when there is no body"},
                    "bones": {"type": "integer"},
                    "has_physics": {"type": "boolean"},
                    "texture_status": {"type": ["string", "null"]},
                    "companion_count": {"type": "integer", "description": "the other models in the same archive"},
                    "license_note": {"type": ["string", "null"]},
                    "reason": {"type": "string", "description": "why this model was chosen as the body"},
                },
            },
            "CharacterList": {
                "type": "object",
                "required": ["characters", "active"],
                "properties": {
                    "characters": {"type": "array", "items": {"$ref": "#/components/schemas/CharacterRow"}},
                    "active": {
                        "type": ["string", "null"],
                        "description": "who is on stage, or null. A pointer at a folder that is gone reads null, never the stale id",
                    },
                },
            },
            "CharacterProfile": {
                "type": "object",
                "description": "One character, whole: the body, the props that came with it, and every file in its folder.",
                "required": ["schema", "id", "display_name", "english_name", "imported_at", "source", "reason", "companions", "files"],
                "properties": {
                    "schema": {"type": "integer", "description": "which report fields this profile was made from"},
                    "id": {"type": "string"},
                    "display_name": {"type": "string"},
                    "english_name": {"type": "string"},
                    "imported_at": {"type": "string"},
                    "source": {
                        "type": "object",
                        "required": ["file_name", "sha256", "bytes", "archive"],
                        "properties": {
                            "file_name": {"type": "string"},
                            "sha256": {"type": "string"},
                            "bytes": {"type": "integer"},
                            "archive": {"type": "boolean", "description": "false for a bare .pmx"},
                        },
                    },
                    "reason": {"type": "string"},
                    "license_note": {"type": ["string", "null"]},
                    "main": {
                        "allOf": [{"$ref": "#/components/schemas/CharacterCapability"}],
                        "description": "the body the stage loads, or null when the archive has none",
                    },
                    "companions": {"type": "array", "items": {"$ref": "#/components/schemas/CharacterCapability"}},
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["path", "bytes"],
                            "properties": {
                                "path": {"type": "string"},
                                "bytes": {"type": "integer"},
                            },
                        },
                        "description": "everything in the folder, so a missing texture is visible without a second request",
                    },
                },
            },
            "CharacterImportRequest": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path"],
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "a .pmx or .zip on this machine, typed or picked by the desktop app — never a device",
                    },
                },
            },
            "CharacterActiveRequest": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id"],
                "properties": {
                    "id": {"type": ["string", "null"], "description": "who goes on stage; null takes everyone off"},
                },
            },
            "CharacterActiveResponse": {
                "type": "object",
                "required": ["active"],
                "properties": {"active": {"type": ["string", "null"]}},
            },
            "CharacterDeleted": {
                "type": "object",
                "required": ["deleted"],
                "properties": {
                    "deleted": {"type": "string", "description": "the removed character's id; its folder and its pick are both gone"},
                },
            },
        },
    },
    "paths": {
        "/healthz": {
            "get": {
                "summary": "Liveness, no auth",
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/HealthzResponse"}}},
                    }
                },
            }
        },
        f"{API_PREFIX}/models": {
            "get": {
                "summary": "Configured models, optionally probed live",
                "parameters": [
                    {"name": "live", "in": "query", "schema": {"type": "boolean"}, "description": "Probe each provider"}
                ],
                "security": [{"bearerAuth": []}],
                "responses": {
                    "200": {
                        "description": "model catalogue",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ModelsResponse"}}},
                    },
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                },
            }
        },
        f"{API_PREFIX}/chat/completions": {
            "post": {
                "security": [{"bearerAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ChatRequest"}}},
                },
                "responses": {
                    "200": {
                        "description": "chat.completion, or text/event-stream when stream=true",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/ChatCompletion"}},
                            "text/event-stream": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/ChatChunk"},
                                    "description": "SSE frames, one ChatChunk per `data:` line",
                                }
                            },
                        },
                    },
                    "400": {
                        "description": "config_error / model_not_found / invalid request body",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                    },
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                    "500": {
                        "description": "secret_store_unavailable / internal_error",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                    },
                    "502": {
                        "description": "provider_* / bad_stream — the turn had no other provider to fall back to",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                    },
                    "429": {
                        "description": "budget_exhausted - every candidate had reached its monthly cap",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                    },
                    "503": {
                        "description": "providers_exhausted",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
                    },
                },
            }
        },
        f"{API_PREFIX}/kira/health": {
            "get": {
                "security": [{"bearerAuth": []}],
                "summary": "Provider cooldown snapshot",
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/HealthResponse"}}},
                    },
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                },
            }
        },
        f"{API_PREFIX}/kira/sessions": {
            "get": {
                "security": [{"bearerAuth": []}],
                "summary": "Recent sessions",
                "parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50}}],
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/SessionsResponse"}}},
                    },
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                },
            },
            "delete": _write("Delete every session and message", "DeletedResponse", []),
        },
        f"{API_PREFIX}/kira/sessions/{{session_id}}/messages": {
            "get": {
                "security": [{"bearerAuth": []}],
                "summary": "Message history",
                "parameters": [{"name": "session_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/MessagesResponse"}}},
                    },
                    "401": {"$ref": "#/components/responses/Unauthorized"},
                },
            }
        },
        f"{API_PREFIX}/kira/overview": {
            "get": _read(
                "Month aggregates for the Overview screen",
                "OverviewResponse",
                [{"name": "month", "in": "query", "schema": {"type": "string"}, "description": "YYYY-MM; default is the current UTC month; junk is config_error 400"}],
            )
        },
        f"{API_PREFIX}/kira/providers": {"get": _read("Merged view + key presence + spend + health + orphans", "ProvidersResponse")},
        f"{API_PREFIX}/kira/providers/{{name}}/settings": {
            "put": _owner_write("Set any subset of the tunable fields", "SettingsResponse", [_provider_param()], "SettingsRequest")
        },
        f"{API_PREFIX}/kira/providers/{{name}}/key": {
            "put": _owner_write("Store a provider key in the Credential Locker", "KeyResponse", [_provider_param()], "KeyRequest"),
            "delete": _owner_write("Forget a provider key", "KeyResponse", [_provider_param()]),
        },
        f"{API_PREFIX}/kira/providers/{{name}}/cooldown": {
            "delete": _owner_write("Drop cooling for one provider now", "ProvidersResponse", [_provider_param()])
        },
        f"{API_PREFIX}/kira/providers/{{name}}/probe": {
            "post": _owner_write("list_models plus one 8-token completion", "ProbeResponse", [_provider_param()])
        },
        f"{API_PREFIX}/kira/sessions/{{session_id}}": {
            "delete": _write("Delete one session and its messages", "DeletedResponse", [{"name": "session_id", "in": "path", "required": True, "schema": {"type": "string"}}])
        },
        f"{API_PREFIX}/kira/approvals": {"get": _read("Tool calls waiting on a decision", "ApprovalsResponse")},
        f"{API_PREFIX}/kira/approvals/{{approval_id}}": {
            "post": _approval_write()
        },
        f"{API_PREFIX}/kira/checkpoints": {
            "get": _read(
                "Recent pre-write snapshots",
                "CheckpointsResponse",
                [
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 20}},
                    {"name": "session_id", "in": "query", "schema": {"type": "string"}},
                ],
            )
        },
        f"{API_PREFIX}/kira/checkpoints/{{checkpoint_id}}": {
            "get": _read(
                "One checkpoint with a per-file diff",
                "CheckpointDiff",
                [{"name": "checkpoint_id", "in": "path", "required": True, "schema": {"type": "string"}}],
            )
        },
        f"{API_PREFIX}/kira/checkpoints/{{checkpoint_id}}/restore": {
            "post": _checkpoint_restore()
        },
        f"{API_PREFIX}/kira/voice": {
            "get": _read("Which speech and vision engines a real-time call gets, and why a stage is unavailable", "VoiceStatus")
        },
        f"{API_PREFIX}/kira/memory": {
            "get": _read(
                "Facts, newest first; `query` searches them",
                "MemoryList",
                [
                    {"name": "query", "in": "query", "schema": {"type": "string"}},
                    {
                        "name": "kind",
                        "in": "query",
                        "schema": {"type": "string", "enum": ["fact", "preference", "note"]},
                        "description": (
                            "filter by kind; an absent, empty or whitespace-only value means \"no filter\", "
                            "while a non-blank value outside the enum is 400 config_error"
                        ),
                    },
                    {"name": "pinned", "in": "query", "schema": {"type": "boolean"}},
                    # The bounds are what the route serves: `max(1, min(200, limit))` clamps anything
                    # outside them, so 0 or 5 000 never reaches a caller as a page size.
                    {
                        "name": "limit",
                        "in": "query",
                        "schema": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
                        "description": "values outside 1..200 are clamped to them, not refused",
                    },
                ],
            ),
            "post": _write("Keep one fact", "MemoryItem", [], "MemoryWrite"),
        },
        f"{API_PREFIX}/kira/memory/{{memory_id}}": {
            "patch": _memory_write("Edit text, kind or pin", "MemoryItem", "MemoryPatch"),
            "delete": _memory_write("Forget one fact", "MemoryDeleted"),
        },
        f"{API_PREFIX}/kira/memory/search": {
            "get": _read(
                "Ranked snippets over saved conversation text",
                "MemorySearch",
                [
                    {"name": "q", "in": "query", "schema": {"type": "string"}},
                    # The route clamps to `max(1, min(50, limit))`, so a value outside 1..50 comes back
                    # as a page at the edge rather than a refusal.
                    {
                        "name": "limit",
                        "in": "query",
                        "schema": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50},
                        "description": "values outside 1..50 are clamped to them, not refused",
                    },
                ],
            )
        },
        f"{API_PREFIX}/kira/memory/export": {"get": _read("Every fact, as JSON", "MemoryExport")},
        f"{API_PREFIX}/kira/memory/settings": {
            "get": _read("The three switches plus the tokenizer in use", "MemorySettings"),
            "put": _write("Set any subset of the three switches", "MemorySettings", [], "MemorySettingsPatch"),
        },
        f"{API_PREFIX}/kira/tools": {"get": _read("Every callable tool and every plugin file", "ToolsResponse")},
        f"{API_PREFIX}/kira/skills": {
            "get": _read("Every loaded skill and every file's status", "SkillsResponse")
        },
        f"{API_PREFIX}/kira/pairing-code": {
            "post": _write("Mint a single-use pairing code, good for 120 seconds", "PairingCodeResponse", [])
        },
        # The one unauthenticated write: the phone has no secret yet, so the code is the secret.
        f"{API_PREFIX}/kira/pair": {
            "post": {
                "summary": "Exchange a pairing code for a device token",
                "security": [],
                "parameters": [],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": _ref("PairRequest")}}},
                },
                "responses": {
                    "200": _ok("PairResponse"),
                    # One message for expired, spent and unknown alike - telling them apart would
                    # tell a guesser which of their guesses was closest.
                    "400": _bad_request(),
                    "429": _error(429, "rate_limited", "more than ten pairing attempts in a minute"),
                },
                "description": (
                    "No bearer token. A code is short-lived and single use, and minting one needs the "
                    "desktop's engine token plus the confirm secret."
                ),
            }
        },
        f"{API_PREFIX}/kira/devices": {
            "get": _read("The devices allowed to read and chat", "DevicesResponse")
        },
        f"{API_PREFIX}/kira/devices/{{device_id}}": {"delete": _device_revoke()},
        f"{API_PREFIX}/kira/tools/{{name}}": {
            "put": _write(
                "Set or clear one tool's policy",
                "ToolPolicyResponse",
                [{"name": "name", "in": "path", "required": True, "schema": {"type": "string"}}],
                "ToolPolicyRequest",
            )
        },
        # The literal `active` before `{character_id}`, the way memory's `search`/`export`/`settings` come
        # before `{memory_id}`: a documented path is a promise about what that string means, and `/kira/
        # characters/active` must never read as a character called "active".
        f"{API_PREFIX}/kira/characters": {
            "get": _read("The library, and who is on stage", "CharacterList"),
            "post": _character_import(),
        },
        f"{API_PREFIX}/kira/characters/active": {"put": _character_active()},
        f"{API_PREFIX}/kira/characters/{{character_id}}": {
            "get": _character_detail(),
            "delete": _character_delete(),
        },
        f"{API_PREFIX}/kira/characters/{{character_id}}/file": {"get": _character_file()},
        f"{API_PREFIX}/kira/characters/{{character_id}}/mesh": {"get": _character_mesh()},
        # `file` is a literal path before `{name}`, the same ordering rule the character routes follow.
        f"{API_PREFIX}/kira/images": {"get": _read("The local image workspace: engine, models, gallery", "ImagesStatus")},
        f"{API_PREFIX}/kira/images/generate": {"post": _image_generate()},
        f"{API_PREFIX}/kira/images/file/{{name}}": {"get": _image_file()},
        f"{API_PREFIX}/kira/images/{{name}}": {"delete": _image_delete()},
        f"{API_PREFIX}/kira/studio": {"get": _read("The studio components and the local chat server", "StudioStatus")},
        f"{API_PREFIX}/kira/studio/llm/start": {
            "post": _write("Start llama.cpp on one GGUF and add it as a local provider", "StudioStatus", [], "StudioLlmRequest")
        },
        f"{API_PREFIX}/kira/studio/llm/stop": {
            "post": _write("Stop llama.cpp and remove the local provider", "StudioStatus", [])
        },
        f"{API_PREFIX}/kira/studio/download": {
            "post": _write("Download one model from Hugging Face into the folder its loader reads", "StudioDownloadResult", [], "StudioDownloadRequest")
        },
        f"{API_PREFIX}/kira/studio/app": {
            "get": _read("The studio's Node server: running, managed, and on which loopback port", "StudioRuntime")
        },
        f"{API_PREFIX}/kira/studio/app/start": {
            "post": _write("Start the studio's Node server under Kira on loopback", "StudioRuntime", [])
        },
        f"{API_PREFIX}/kira/studio/app/stop": {
            "post": _write("Stop the studio server Kira started; a studio Kira did not start is left alone", "StudioRuntime", [])
        },
        f"{API_PREFIX}/kira/studio/proxy": {
            "get": _read(
                "Forward one allowlisted studio API call; the bearer token is never passed on",
                "StudioProxyResult",
                [{"name": "path", "in": "query", "required": True, "schema": {"type": "string"}}],
            ),
            "post": _write(
                "Forward one allowlisted studio API call with its body; delete and stop paths need the confirm secret",
                "StudioProxyResult",
                [{"name": "path", "in": "query", "required": True, "schema": {"type": "string"}}],
                "StudioProxyRequest",
            ),
        },
    },
}

OPENAPI["components"]["parameters"] = {
    "Confirm": {
        "name": "X-Kira-Confirm",
        "in": "header",
        "required": True,
        "schema": {"type": "string"},
        "description": (
            "The engine/confirm secret from the Credential Locker, re-typed per write in the UI. "
            "Custom header, so a page on another origin cannot set it without a CORS preflight this "
            "engine never grants, and a local process would have to guess 43 characters."
        ),
    }
}

OPENAPI["components"]["responses"] = {
    "Unauthorized": {
        "description": "unauthorized",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
    }
}


def export_contracts(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "openapi.json"
    path.write_text(json.dumps(OPENAPI, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "VERSION").write_text(f"{CONTRACT_VERSION}\n", encoding="utf-8")
    (out_dir / "contract.json").write_text(
        json.dumps(contract_facts(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path
