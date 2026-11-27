from __future__ import annotations

import asyncio
import contextlib
import hashlib
import ipaddress
import json
import os
import re
import secrets
import sys
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import Cookie, Depends, FastAPI, Header, Request, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.websockets import WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, field_validator
from starlette.datastructures import MutableHeaders
from starlette.staticfiles import StaticFiles

from .checkpoints import CheckpointConflict, CheckpointManager
from .characters import (
    CharacterError,
    character_file,
    get_active,
    get_character,
    import_from_path,
    list_characters,
    remove_character,
    set_active,
    wire_for,
)
from .config import MODES, Config, ProviderConfig, load_config
from .contracts import API_PREFIX, API_VERSION, CONTRACT_VERSION, OPENAPI
from .downloads import DOWNLOAD_KINDS, download_model
from .approvals import ApprovalBroker
from .errors import AllProvidersExhausted, AuthError, BudgetExhausted, ConfigError, KiraError, ProviderCallError, UnsupportedVersion
from .images import (
    DEFAULT_SAMPLER,
    ImageStudio,
    register_image_tool,
)
from .llamacpp import LocalLlm
from .loop import AgentRun
from .memory import CAPTURES, KINDS, MAX_TEXT, MemoryStore, build_block, extract_facts, inject, register_memory_tools, register_remember_tool
from .mesh import MESH_MEDIA_TYPE, export_mesh
from .net import HealthLedger
from .overrides import EffectiveProvider, MergedView, TUNABLE_FIELDS, build_view, enabled_providers, matches_baseline, validate_setting
from .pairing import DEVICE_NAME_MAX, DEVICE_TOKEN_PREFIX, Pairing
from .plugins import PluginStatus, load_plugins
from .policy import effective_policy
from .probe import probe_models, probe_provider
from .providers.registry import ProviderRegistry
from .router import Note, Router
from .skills import Skill, builtin_dir, discovery_mode, load_skills, register_skill_tool
from .studio import find_studio
from .studio_server import StudioServer
from .store import Store, month_bounds
from .tools import ToolRegistry, register_demo_tools, register_workspace_tools
from .types import ApprovalRequest, Completed, Delta, Message, ToolCall, ToolCallEvent, Usage
from .vault import Vault
from .voice.call import Hello, VoiceCall
from .voice.stack import build_voice_stack
from .workspace import Workspace


class WireMessage(BaseModel):
    role: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[WireMessage]
    stream: bool = False
    temperature: float = 1.0
    max_tokens: int | None = None
    mode: str | None = None
    provider: str | None = None
    session_id: str | None = None
    tools_enabled: bool = True
    skill: str | None = None

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        upper = value.upper()
        if upper not in MODES:
            raise ValueError(f"mode must be one of {list(MODES)}")
        return upper

    @field_validator("messages")
    @classmethod
    def _validate_messages(cls, value: list[WireMessage]) -> list[WireMessage]:
        if not value:
            raise ValueError("messages must not be empty")
        return value


class PairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str


class CharacterImportRequest(BaseModel):
    # `strict` for the same reason `MemorySettingsPatch` has it: lax mode would read `{"path": 7}` as a
    # path and hand `Path(7)` to the importer, so the refusal would come out as a filesystem error naming a
    # number instead of a 400 about the body.
    model_config = ConfigDict(extra="forbid", strict=True)

    path: str

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("path must not be empty")
        return value


class CharacterActiveRequest(BaseModel):
    """Who goes on stage: an id, or `null` to take everyone off. Nothing else.

    A number or a list is a 400 here rather than a `str()` of it, because the alternative is a character
    called `7` that the library cannot have and a message about a missing character that the user did not
    ask for.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str | None


class ImageGenerateRequest(BaseModel):
    """One image, with the fields stable-diffusion.cpp's txt2img accepts.

    The bounds live in `images.py`, so the screen and an agent tool get the same refusal in the same
    words. This model only says the body is the shape the route expects.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    prompt: str
    negative_prompt: str = ""
    model: str | None = None
    steps: int = 24
    cfg_scale: float = 7.0
    width: int = 512
    height: int = 512
    seed: int = -1
    sampler: str = DEFAULT_SAMPLER


class StudioLlmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    model: str | None = None


class StudioDownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: str
    url: str
    filename: str | None = None


class MemoryWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    kind: str = "fact"
    pinned: bool = False

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("text must not be empty")
        if len(clean) > MAX_TEXT:
            raise ValueError(f"text is limited to {MAX_TEXT} characters")
        return clean

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        if value not in KINDS:
            raise ValueError(f"kind must be one of {list(KINDS)}")
        return value


class MemoryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = None
    kind: str | None = None
    pinned: bool | None = None

    # Written out rather than borrowed from MemoryWrite: a shared classmethod validator fights the
    # decorator in pydantic v2, and four duplicated lines are cheaper than a framework trick. The two
    # text messages differ from memory.py's `_clean_text`, which does the same checks on the same
    # constant: it says "memory text must not be empty" and ends the limit message with ", got N".
    # Neither string is ever on the wire — a validator failure answers through `_validation_handler`,
    # which names fields only — so the difference stays where nothing can see it.
    @field_validator("text")
    @classmethod
    def _text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("text must not be empty")
        if len(clean) > MAX_TEXT:
            raise ValueError(f"text is limited to {MAX_TEXT} characters")
        return clean

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str | None) -> str | None:
        if value is not None and value not in KINDS:
            raise ValueError(f"kind must be one of {list(KINDS)}")
        return value


class MemorySettingsPatch(BaseModel):
    # Strict on purpose: pydantic's lax mode reads the string "yes" as `True`, so `{"inject": "yes"}`
    # would quietly become a real write. A JSON body that spells a boolean as prose is a 400 here.
    model_config = ConfigDict(extra="forbid", strict=True)

    inject: bool | None = None
    capture: str | None = None
    extract: bool | None = None

    @field_validator("capture")
    @classmethod
    def _capture(cls, value: str | None) -> str | None:
        if value is not None and value not in CAPTURES:
            raise ValueError(f"capture must be one of {list(CAPTURES)}")
        return value


@dataclass
class PreparedTurn:
    """One request, once: the run, the session it belongs to, and what memory went into it."""

    run: AgentRun
    session_id: str
    memory_used: list[str]
    user_text: str


def to_internal(items: list[WireMessage]) -> list[Message]:
    out: list[Message] = []
    for item in items:
        calls = []
        for raw in item.tool_calls or []:
            fn = raw.get("function") or {}
            arguments = fn.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"raw": arguments}
            calls.append(ToolCall(id=str(raw.get("id") or f"call_{len(calls)}"), name=str(fn.get("name") or ""), arguments=dict(arguments or {})))
        out.append(
            Message(
                role=item.role,
                content=item.content or "",
                tool_calls=calls,
                tool_call_id=item.tool_call_id,
                name=item.name,
            )
        )
    return out


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def wire_usage(usage: Usage) -> dict[str, int | bool]:
    """One usage shape on the wire, OpenAI names, for both the body and the done chunk.
    `estimated` is the engine's own addition: OpenAI names plus one honest caveat."""
    return {
        "prompt_tokens": usage.input_tokens,
        "completion_tokens": usage.output_tokens,
        "estimated": usage.estimated,
    }


def _settings_wire(provider: EffectiveProvider) -> dict[str, dict]:
    """The four tunable fields as base/override/effective, from the same FieldStates the merge built."""
    return {key: provider.states[key].to_wire() for key in TUNABLE_FIELDS}


def key_present(engine: "Engine", provider: EffectiveProvider) -> bool:
    """Whether this provider can answer at all right now: a `key_ref` the vault actually holds.

    A stanza with no `key_ref` has nothing to look up, so it reads False rather than raising. Same rule
    every dashboard row already used; now the model catalogue can tell a picker which rows will reply.
    """
    return (engine.registry.key_for(provider.name) is not None) if provider.key_ref else False


def needs_key(provider: EffectiveProvider) -> bool:
    """Whether this provider asks for a credential at all — a local server on loopback asks for none.

    Read together with `key_present`: `needs_key` false is "nothing to store", not "broken". Without the
    pair, a keyless provider is reported as missing its key and unit 5's offline model ships looking dead.
    """
    return bool(provider.key_ref)


SESSION_COOKIE = "kira_session"


def _loopback_name(value: str) -> bool:
    """A host name or address that only this machine can reach.

    The browser session is minted for a page loaded from loopback: typing the launcher's token was the
    only way in, and a bookmark or a reloaded tab landed on the gate because the fragment was gone. The
    cookie is the same owner credential, so it is never handed to a remote page — pairing still owns
    that path.
    """
    try:
        host = urlsplit("//" + value).hostname or ""
    except ValueError:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _local_browser(request: Request) -> bool:
    """Whether this request came from a page on the same loopback origin.

    Both ends matter: a tunnel can connect from 127.0.0.1 and forward a public Host, and a local
    process can forge Host. Requiring the peer and the Host to be loopback keeps the cookie on the
    machine. A present Origin must name that same origin, which is what a browser sends on the POST.
    """
    host = request.headers.get("host", "")
    client = request.client.host if request.client else ""
    if not (_loopback_name(host) and _loopback_name(client)):
        return False
    origin = request.headers.get("origin")
    if origin:
        try:
            parsed = urlsplit(origin)
        except ValueError:
            # A malformed Origin is a refusal, not a 500: only a browser on this page mints.
            return False
        return parsed.scheme in {"http", "https"} and parsed.netloc == host
    return True


def chat_dist_dir(config: Config) -> Path:
    env = os.environ.get("KIRA_CHAT_DIST")
    if env:
        return Path(env)
    return config.data_dir.parent / "kira-chat" / "dist"


class ChatBundle(StaticFiles):
    """The built chat bundle: an ordinary static tree with three files a browser may not cache.

    `sw.js` is the worker itself — a cached copy pins the browser to old cache logic with no way to
    ship a fix. `index.html` names the hashed assets, so a cached copy points at files a rebuild has
    already emptied. The manifest names the shell too, so it revalidates instead of pinning an old
    start URL. Everything under `assets/` is content-hashed, which is the one case that earns a year
    of immutable caching: the filename changes when the bytes do.
    """

    NEVER_CACHE = {"sw.js", "index.html", "manifest.webmanifest"}
    IMMUTABLE_SECONDS = 31_536_000

    # Keyed on the file that is actually served, not the request path: `/chat/` reaches index.html
    # through the directory branch, which builds its own response without a second `get_response`.
    def file_response(self, full_path: Any, stat_result: Any, scope: Any, status_code: int = 200) -> Any:
        response = super().file_response(full_path, stat_result, scope, status_code)
        if response.status_code >= 400:
            return response
        path = Path(full_path)
        if path.name in self.NEVER_CACHE:
            response.headers["cache-control"] = "no-cache"
        elif path.parent.name == "assets":
            response.headers["cache-control"] = (
                f"public, max-age={self.IMMUTABLE_SECONDS}, immutable"
            )
        return response


def _token_hash(token: str) -> str:
    """What the devices table stores: a token is shown once, and never written down."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Engine:
    def __init__(
        self,
        config: Config,
        *,
        vault: Vault | None = None,
        http_client: httpx.AsyncClient | None = None,
        store: Store | None = None,
        tools: ToolRegistry | None = None,
    ) -> None:
        self.config = config
        self.vault = vault or Vault()
        self.store = store or Store(config.db_path)
        self.ledger = HealthLedger(store=self.store)
        self.client = http_client or httpx.AsyncClient(timeout=config.request_timeout_s)
        self.registry = ProviderRegistry(config, self.vault, self.client)
        self.router = Router(
            self.registry,
            self.ledger,
            view_source=self.view,
            spend_source=self.store.usage_for_month,
        )
        # A snapshot taken once at startup: which speech engines a call gets, and what is missing.
        # Never raises — a machine without faster-whisper or Piper still serves chat, and `/call`
        # reads this status to say honestly that listening or speaking is unavailable.
        self.voice = build_voice_stack(config, self.registry, self.view)
        self.tools = tools if tools is not None else ToolRegistry()
        if tools is None:
            register_demo_tools(self.tools)
        self.workspace = Workspace(config.workspace_path)
        register_workspace_tools(self.tools, self.workspace)
        # The image workspace is a folder on this machine, exactly like the voice engines: a missing
        # executable or checkpoint is a status sentence, never a startup failure.
        self.images = ImageStudio(config)
        register_image_tool(self.tools, self.images)
        # The same studio discovery gives chat a local tier: a llama-server child that is started
        # from the UI and appended to `config.providers` as a keyless provider while it runs.
        self.studio = find_studio(config.data_dir)
        # The studio's own Node server, started from the UI. Only discovery happens here; the process
        # is owned by `studio_server` and stopped when the engine shuts down.
        self.studio_server = StudioServer(config, self.studio)
        self.llm = LocalLlm(config, studio=self.studio)
        self.checkpoints = CheckpointManager(
            self.workspace,
            config.data_dir / "checkpoints",
            self.store,
            retention=config.checkpoint_retention,
        )
        self.memory = MemoryStore(self.store)
        register_memory_tools(self.tools, self.memory)
        self.skills, self.skill_files = load_skills(builtin_dir(), config.skills_dir)
        self._skills = {skill.name: skill for skill in self.skills}
        # Before plugins: a plugin that also calls itself `use_skill` is refused, not quietly added
        # beside it. The starter pack's methods are what the tool exists for.
        register_skill_tool(self.tools, self.skills)
        self.plugins, self.plugin_status = load_plugins(
            config.data_dir / "plugins", self.client, self.vault
        )
        accepted = []
        for tool in self.plugins:
            try:
                self.tools.register(tool)
                accepted.append(tool)
            except ValueError as exc:
                self.plugin_status.append(
                    PluginStatus(
                        file=tool.source.split(":", 1)[-1],
                        name=tool.name,
                        status="skipped",
                        reason=str(exc),
                    )
                )
        self.plugins = accepted
        self.approvals = ApprovalBroker(self.store, config.approval_timeout_s)
        self.approvals.expire_all()
        self.pairing = Pairing()
        self.token, token_created = self.vault.get_or_create_engine_token()
        if token_created:
            print(
                f"[kira] first run — engine token (shown once, stored in the {self.vault.location}): {self.token}",
                file=sys.stderr,
            )
        self.confirm, confirm_created = self.vault.get_or_create_confirm()
        if confirm_created:
            print(
                f"[kira] first run — confirm secret (shown once, stored in the {self.vault.location}): {self.confirm}",
                file=sys.stderr,
            )

    def view(self) -> MergedView:
        """The merged config for this request: YAML baseline plus the settings table."""
        return build_view(self.config, self.store)

    def device_for(self, token: str) -> dict[str, Any] | None:
        """The live device a `kd_` token names, or None. A seen token counts as seen now."""
        if not token.startswith(DEVICE_TOKEN_PREFIX):
            return None
        device = self.store.device_by_token_hash(_token_hash(token))
        if device is not None:
            self.store.touch_device(device["id"])
        return device


    def persona(self, name: str | None) -> Skill | None:
        """The skill a turn pinned, or a named refusal — an empty answer would be a silent miss."""
        if not name:
            return None
        skill = self._skills.get(name)
        if skill is None:
            raise ConfigError(f"unknown skill '{name}'")
        if skill.kind != "persona":
            raise ConfigError(f"'{name}' is a method skill; the model loads it with use_skill")
        return skill

    def sync_memory_tools(self) -> None:
        """`remember` exists only while capture is on: a model cannot call what it is not told about."""
        if self.memory.settings()["capture"] == "off":
            self.tools.unregister("remember")
        elif self.tools.get("remember") is None:
            register_remember_tool(self.tools, self.memory)

    def persist_assistant_row(self, session_id: str, run: AgentRun, status: str) -> int:
        """The one way an answer becomes a history row.

        Chat and a call write the same columns through here, so "what served me and what did it cost"
        never depends on which surface asked — and an `interrupted` partial is stored exactly as the
        streamed one is.
        """
        return self.store.add_message(
            session_id,
            "assistant",
            run.state.text,
            provider=run.attempt.served_by,
            model=run.attempt.served_model,
            finish_reason=run.state.finish_reason,
            status=status,
            tool_calls=[{"id": call.id, "name": call.name, "arguments": call.arguments} for call in run.state.tool_calls],
            usage={
                "input_tokens": run.state.usage.input_tokens,
                "output_tokens": run.state.usage.output_tokens,
                "estimated": run.state.usage.estimated,
            },
            chain=run.attempt.chain,
        )


#: A leading path segment that looks like a version namespace, e.g. `/v2/...`.
_VERSION_SEGMENT = re.compile(r"^/(?P<version>v\d+)(?:/|$)")


class KiraVersionMiddleware:
    """Turn away a `/vN` this engine does not serve, before any credential is consulted.

    Pure ASGI on purpose. In a `BaseHTTPMiddleware` an exception raised by the middleware itself never
    reaches `@app.exception_handler` — those live inside `ExceptionMiddleware`, which nests *under* user
    middleware — so the contract-shaped body has to be written here by hand. And the streaming chat
    response must not be pushed through a task group, which is how a client-side abort gets mangled.

    Nothing needs an exemption list: `/healthz`, `/openapi.json` and the `/chat` bundle never start with a
    `v<digits>` segment, so they cannot be confused for a version request.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        match = _VERSION_SEGMENT.match(path)
        requested = f"/{match.group('version')}" if match else ""
        if match and requested != API_PREFIX:
            rejection = UnsupportedVersion(
                f"this engine serves {API_PREFIX} only; '{requested}' is not a version it speaks"
            )
            await JSONResponse(status_code=rejection.status, content=rejection.to_dict())(scope, receive, send)
            return

        under_prefix = path == API_PREFIX or path.startswith(f"{API_PREFIX}/")

        async def send_versioned(message: dict) -> None:
            if under_prefix and message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Kira-Contract-Version", str(CONTRACT_VERSION))
            await send(message)

        await self.app(scope, receive, send_versioned)


def _unknown_checkpoint() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": {"code": "not_found", "message": "unknown checkpoint", "status": 404, "retryable": False}},
    )


def _unknown_device() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": {"code": "not_found", "message": "unknown device", "status": 404, "retryable": False}},
    )


def _baseline_config(engine: Engine, name: str) -> ProviderConfig:
    """config.yaml's stanza for a provider, or a 400. Key storage is keyed by the YAML ref, not the
    merged view: `key_ref` is not one of the four tunable fields, so the two can never disagree."""
    try:
        return engine.registry.config_for(name)
    except ConfigError as exc:
        raise ConfigError(f"unknown provider '{name}': {exc.message}") from exc


def create_app(config: Config | None = None, *, engine: Engine | None = None, **engine_kwargs: Any) -> FastAPI:
    cfg = config or load_config()
    engine = engine or Engine(cfg, **engine_kwargs)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        # A studio server this engine started does not outlive it. One the user started is untouched.
        await engine.studio_server.aclose()

    app = FastAPI(
        title="kira-engine",
        version=str(CONTRACT_VERSION),
        # FastAPI's generated document is a second, disagreeing opinion about this API: it describes only
        # registered routes (so it cannot see the writes the contract already publishes) and its `info`
        # comes from the app, not the contract. It is switched off rather than overridden, because 0.162
        # invalidates `app.openapi_schema` whenever a route is added, and because `/docs` and `/redoc`
        # load their JavaScript from a CDN — something a loopback-only, offline-first engine cannot promise.
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(KiraVersionMiddleware)
    app.state.engine = engine

    @app.exception_handler(KiraError)
    async def _kira_error_handler(_: Request, exc: KiraError) -> JSONResponse:
        content = exc.to_dict()
        # Both exhaustion classes carry the notes that explain themselves; the client draws them
        # as a chain instead of showing a bare status.
        if isinstance(exc, (AllProvidersExhausted, BudgetExhausted)):
            content["error"]["provider_chain"] = exc.chain
        return JSONResponse(status_code=exc.status, content=content)

    @app.exception_handler(CharacterError)
    async def _character_error_handler(_: Request, exc: CharacterError) -> JSONResponse:
        # `characters.py` refuses in its own vocabulary — codes about bytes, entries and ids — and the
        # wire answers with the published twin of whichever one it used. One mapping, in one place, so the
        # routes and the CLI cannot disagree about what a zip-slip entry is worth.
        refusal = wire_for(exc)
        return JSONResponse(status_code=refusal.status, content=refusal.to_dict())

    @app.exception_handler(ProviderCallError)
    async def _provider_error_handler(_: Request, exc: ProviderCallError) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "provider": exc.provider,
                    "status": exc.status,
                    "retryable": exc.retryable,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's 422 echoes the offending value under `ctx`/`input`. For a provider-key body that
        # would hand the secret back to whoever guessed the shape, so the response names fields only.
        fields = sorted({
            ".".join(str(part) for part in err.get("loc", ())[1:]) or "body" for err in exc.errors()
        })
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": ConfigError.code,
                    "message": f"malformed request body; check {', '.join(fields) or 'the body'}",
                    "status": 400,
                    "retryable": False,
                }
            },
        )

    def bearer(authorization: str | None) -> str:
        if authorization and authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
        return ""

    def presented(authorization: str | None, kira_session: str | None) -> str:
        """The bearer header, or the session cookie the bundle minted for a loopback page.

        A header wins: a stale token must fail and send the UI back through the gate rather than be
        silently replaced by a cookie for another engine on the same browser.
        """
        return bearer(authorization) or (kira_session or "").strip()

    def require_token(
        authorization: str | None = Header(None),
        kira_session: str | None = Cookie(None),
    ) -> None:
        # Two principals, one door: the owner's engine token, or a device a pairing code minted. The
        # owner token may arrive as the loopback browser's cookie; a device token never does.
        # The device is read-only in practice: mutations ask for the confirm secret below, and
        # provider keys ask for the engine token itself - neither ever leaves the desktop.
        provided = presented(authorization, kira_session)
        if provided.startswith(DEVICE_TOKEN_PREFIX) and engine.device_for(provided) is not None:
            return
        if not provided or not secrets.compare_digest(provided, engine.token):
            raise AuthError("missing or invalid bearer token")

    auth = Depends(require_token)

    def require_owner(
        authorization: str | None = Header(None),
        kira_session: str | None = Cookie(None),
    ) -> None:
        """Pairing and device management belong to the machine, not to a device that machine paired."""
        provided = presented(authorization, kira_session)
        if not provided or not secrets.compare_digest(provided, engine.token):
            raise AuthError("this endpoint needs the engine token from the desktop, not a device token")

    owner = Depends(require_owner)

    def require_confirm(x_kira_confirm: str | None = Header(None)) -> None:
        provided = (x_kira_confirm or "").strip()
        if provided and secrets.compare_digest(provided, engine.token):
            raise AuthError("the confirm secret is a different value from the bearer token")
        if not provided or not secrets.compare_digest(provided, engine.confirm):
            raise AuthError("this write needs the confirm secret in X-Kira-Confirm - re-enter it in the dialog")

    confirm = Depends(require_confirm)

    def build_run(body: ChatRequest, *, streaming: bool) -> PreparedTurn:
        persona = engine.persona(body.skill)
        try:
            plan = engine.router.plan(model=body.model, mode=body.mode, provider=body.provider)
        except (BudgetExhausted, AllProvidersExhausted) as exc:
            # The plan raises before `create_session`, so nothing downstream — no session, no user
            # row, no usage — can carry this. Its own ledger is the only way the month can say the
            # engine was asked for a turn and had no one to ask.
            engine.store.record_refusal(
                exc.code, exc.message, mode=(body.mode or cfg.default_mode).upper(), model=body.model
            )
            raise
        session_id = engine.store.create_session(plan.mode, body.session_id)
        messages = to_internal(body.messages)
        last_user = next((m for m in reversed(messages) if m.role == "user"), None)
        user_text = last_user.content if last_user is not None else ""
        if last_user is not None and last_user.content:
            engine.store.add_message(session_id, "user", last_user.content)
        if persona is not None:
            # First system message, so memory's existing inject() appends its block to it and the
            # persona stays the opening instruction rather than a postscript.
            messages.insert(0, Message(role="system", content=persona.body))
        block, memory_used = build_block(engine.memory, messages)
        run = AgentRun(
            router=engine.router,
            tools=engine.tools if body.tools_enabled else ToolRegistry(),
            plan=plan,
            messages=inject(messages, block),
            max_steps=cfg.max_agent_steps,
            temperature=body.temperature,
            max_output_tokens=body.max_tokens,
            approvals=engine.approvals if streaming else None,
            checkpoints=engine.checkpoints,
            policies=engine.store.tool_policies(),
            session_id=session_id,
        )
        return PreparedTurn(run, session_id, memory_used, user_text)

    def assistant_row(session_id: str, run: AgentRun, status: str) -> int:
        return engine.persist_assistant_row(session_id, run, status)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {
            "ok": True,
            "api_version": API_VERSION,
            "contract_version": CONTRACT_VERSION,
            "providers_configured": len(cfg.providers),
            "default_mode": cfg.default_mode,
        }

    @app.get("/openapi.json", include_in_schema=False)
    @app.get(f"{API_PREFIX}/openapi.json")
    async def openapi() -> dict:
        return OPENAPI

    @app.post(f"{API_PREFIX}/kira/session")
    async def open_browser_session(request: Request, response: Response) -> dict:
        """Mint the loopback page's owner session, so a reload does not land on the connect gate.

        The launcher's fragment is the first way in and still works; this is the path for a bookmark, a
        restored tab, or a page whose fragment was already consumed. Only a page served to this machine
        qualifies, and the cookie is HttpOnly and SameSite=Strict — a remote visitor still pairs.
        """
        if not _local_browser(request):
            raise AuthError(
                "a browser session is only available to a page on this machine; use the launcher or pair a device"
            )
        response.set_cookie(
            SESSION_COOKIE,
            engine.token,
            max_age=30 * 24 * 60 * 60,
            httponly=True,
            samesite="strict",
            path=API_PREFIX,
            secure=request.url.scheme == "https",
        )
        return {"connected": True}

    @app.delete(f"{API_PREFIX}/kira/session")
    async def close_browser_session(request: Request, response: Response) -> dict:
        if not _local_browser(request):
            raise AuthError("only a page on this machine can close its browser session")
        response.delete_cookie(SESSION_COOKIE, path=API_PREFIX)
        return {"connected": False}

    @app.get(f"{API_PREFIX}/models", dependencies=[auth])
    async def models(live: bool = False) -> dict:
        view = engine.view()
        data = [
            {
                "id": model,
                "object": "model",
                "owned_by": provider.name,
                "provider": provider.name,
                "tier": provider.tier,
                # A picker cannot default sensibly without this: a row that exists is not a row that answers.
                "key_present": key_present(engine, provider),
                "needs_key": needs_key(provider),
                "context_window": provider.context_window,
            }
            for provider in enabled_providers(view)
            for model in provider.models
        ]
        payload: dict[str, Any] = {"object": "list", "data": data}
        if live:
            # One implementation for CLI, chat and dashboard probes, so none of them can drift.
            payload["live"] = [
                (await probe_models(engine.registry, provider.name)).to_wire()
                for provider in enabled_providers(view)
            ]
        return payload

    @app.post(f"{API_PREFIX}/chat/completions", dependencies=[auth])
    async def chat(body: ChatRequest) -> Any:
        turn = build_run(body, streaming=body.stream)
        run, session_id = turn.run, turn.session_id
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:20]}"
        created = int(time.time())

        if body.stream:

            async def event_stream() -> AsyncIterator[str]:
                try:
                    async for event in run.events():
                        if isinstance(event, Delta):
                            yield sse({"type": "delta", "text": event.text})
                        elif isinstance(event, ToolCallEvent):
                            yield sse(
                                {
                                    "type": "tool_call",
                                    "id": event.call.id,
                                    "name": event.call.name,
                                    "arguments": event.call.arguments,
                                }
                            )
                        elif isinstance(event, Note):
                            yield sse({"type": "chain", "record": event.record})
                        elif isinstance(event, ApprovalRequest):
                            yield sse(
                                {
                                    "type": "approval",
                                    "id": event.id,
                                    "tool": event.tool,
                                    "risk": event.risk,
                                    "arguments": event.arguments,
                                }
                            )
                        elif isinstance(event, Completed):
                            continue
                    assistant_row(session_id, run, run.state.status)
                    if run.state.status != "failed":
                        engine.memory.mark_used(turn.memory_used)
                    yield sse(
                        {
                            "type": "done",
                            "id": completion_id,
                            "session_id": session_id,
                            "provider": run.attempt.served_by,
                            "model": run.attempt.served_model,
                            "finish_reason": run.state.finish_reason,
                            "status": run.state.status,
                            "usage": wire_usage(run.state.usage),
                            "provider_chain": run.attempt.chain,
                        }
                    )
                except (KiraError, ProviderCallError) as exc:
                    assistant_row(session_id, run, "interrupted" if run.state.text else "failed")
                    detail = exc.to_dict()["error"] if isinstance(exc, KiraError) else {
                        "code": exc.code,
                        "message": exc.message,
                        "provider": exc.provider,
                    }
                    yield sse({"type": "error", "error": detail, "provider_chain": run.attempt.chain})
                else:
                    if run.state.text:
                        await extract_facts(
                            engine,
                            session_id=session_id,
                            user_text=turn.user_text,
                            answer_text=run.state.text,
                            memory=engine.memory,
                        )

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "X-Kira-Session-Id": session_id,
                },
            )

        try:
            async for _event in run.events():
                pass
        except KiraError:
            assistant_row(session_id, run, "interrupted" if run.state.text else "failed")
            raise
        except ProviderCallError as exc:
            # A provider error that escaped the loop is the turn's last word, so it is also the row's:
            # falling through to the success path below used to write a second row and label the empty
            # answer `complete`, which is what the live Gemini 400 did — see `tests/test_api.py`.
            assistant_row(session_id, run, "interrupted" if run.state.text else "failed")
            return JSONResponse(
                status_code=502,
                content={
                    "error": {
                        "code": exc.code,
                        "message": exc.message,
                        "provider": exc.provider,
                        "status": exc.status,
                        "retryable": exc.retryable,
                        "provider_chain": run.attempt.chain,
                    }
                },
            )
        status = run.state.status if run.state.text or run.state.tool_calls else "failed"
        message_id = assistant_row(session_id, run, status)
        if status != "failed":
            engine.memory.mark_used(turn.memory_used)
        if run.state.text:
            await extract_facts(
                engine,
                session_id=session_id,
                user_text=turn.user_text,
                answer_text=run.state.text,
                memory=engine.memory,
            )
        return JSONResponse(
            status_code=200,
            content={
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": run.attempt.served_model,
                "provider": run.attempt.served_by,
                "session_id": session_id,
                "message_id": message_id,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": run.state.text,
                            "tool_calls": [
                                {"id": c.id, "name": c.name, "arguments": c.arguments} for c in run.state.tool_calls
                            ],
                        },
                        "finish_reason": run.state.finish_reason,
                    }
                ],
                "usage": wire_usage(run.state.usage),
                "status": run.state.status,
                "provider_chain": run.attempt.chain,
            },
            headers={
                "X-Kira-Provider": run.attempt.served_by or "",
                "X-Kira-Session-Id": session_id,
            },
        )

    @app.get(f"{API_PREFIX}/kira/health", dependencies=[auth])
    async def kira_health() -> dict:
        return {
            "providers": engine.ledger.snapshot(),
            "configured": [
                {
                    "name": p.name,
                    "kind": p.kind,
                    "tier": p.tier,
                    "priority": p.priority,
                    "models": p.models,
                    "key_present": key_present(engine, p),
                    "needs_key": needs_key(p),
                }
                for p in engine.view().providers
            ],
        }

    @app.get(f"{API_PREFIX}/kira/voice", dependencies=[auth])
    async def kira_voice() -> dict:
        """What a call would get: listen / speak / see, each with the reason it is missing."""
        return engine.voice.status()

    @app.websocket(f"{API_PREFIX}/voice")
    async def voice_socket(websocket: WebSocket) -> None:
        """A live call. Browsers cannot set headers on a WebSocket, so the token rides the first frame.

        It is compared with `compare_digest` and then dropped: it never reaches the store, a log line,
        a chain record or a URL. Nothing before the hello is read, and a hello that does not pass ends
        the socket with 4401 — the same 401 the HTTP surface gives, in the one place a header cannot go.
        """
        await websocket.accept()
        try:
            raw = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
        except (asyncio.TimeoutError, RuntimeError, ValueError, WebSocketDisconnect):
            try:
                await websocket.close(code=4401)
            except RuntimeError:
                pass  # already gone; there is no one left to tell
            return
        hello = raw if isinstance(raw, dict) else {}
        token = hello.get("token")
        if (
            hello.get("type") != "hello"
            or not isinstance(token, str)
            or not secrets.compare_digest(token, engine.token)
        ):
            await websocket.close(code=4401)
            return

        def opt(name: str) -> str | None:
            value = hello.get(name)
            return value if isinstance(value, str) and value else None

        await VoiceCall(
            engine,
            websocket,
            Hello(token=token, model=opt("model"), mode=opt("mode"), session_id=opt("session_id")),
        ).run()

    @app.get(f"{API_PREFIX}/kira/overview", dependencies=[auth])
    async def kira_overview(month: str | None = None) -> dict:
        _, start, end = month_bounds(month)
        view = engine.view()
        spend = engine.store.monthly_spend(start, end)
        overview = engine.store.overview(start, end)
        budgets = [
            {
                "provider": p.name,
                "cap": p.monthly_cap,
                "used": spend.get(p.name, 0),
                "remaining": None if p.monthly_cap is None else max(0, p.monthly_cap - spend.get(p.name, 0)),
            }
            for p in view.providers
        ]
        return {**overview, "budgets": budgets}

    def providers_payload() -> dict:
        """The one ProvidersResponse shape, shared by the read endpoint and the cooldown clear."""
        # `label` is the month the payload names; `start`/`end` are the spend window.
        label, start, end = month_bounds(None)
        spend = engine.store.monthly_spend(start, end)
        view = engine.view()
        rows = []
        for provider in view.providers:
            rows.append(
                {
                    "name": provider.name,
                    "kind": provider.kind,
                    "base_url": provider.base_url,
                    "models": list(provider.models),
                    "key_ref": provider.key_ref,
                    "key_present": key_present(engine, provider),
                    "needs_key": needs_key(provider),
                    # Read from the config stanza, not the merged view: whether an endpoint takes
                    # images is a fact about the model, so it has no settings override to merge.
                    "vision": provider.base.vision,
                    "context_window": provider.base.context_window,
                    **_settings_wire(provider),
                    "spend_this_month": spend.get(provider.name, 0),
                    "health": engine.ledger.view(provider.name),
                }
            )
        return {"providers": rows, "orphan_settings": list(view.orphan_settings), "month": label}

    @app.get(f"{API_PREFIX}/kira/providers", dependencies=[auth])
    async def kira_providers() -> dict:
        return providers_payload()

    @app.put(f"{API_PREFIX}/kira/providers/{{name}}/settings", dependencies=[owner])
    async def kira_put_settings(name: str, body: dict[str, Any]) -> dict:
        view = engine.view()
        if name not in view.by_name:
            raise ConfigError(f"unknown provider '{name}'")
        if not isinstance(body, dict):
            raise ConfigError("the settings body must be a JSON object of field names to values")
        # Whole-body validation first: a rejected write must leave the table exactly as it was.
        checked = {key: validate_setting(key, value) for key, value in body.items()}
        base = _baseline_config(engine, name)
        for key, value in checked.items():
            # A value the YAML already states is not an override; store nothing rather than a row
            # that reads "on — was on" and offers a `clear override` that clears nothing.
            if value is None or matches_baseline(key, base, value):
                engine.store.clear_setting(name, key)
            else:
                engine.store.set_setting(name, key, value)
        return {"provider": name, "settings": _settings_wire(engine.view().by_name[name])}

    @app.put(f"{API_PREFIX}/kira/providers/{{name}}/key", dependencies=[owner])
    async def kira_put_key(name: str, body: dict[str, Any]) -> dict:
        base = _baseline_config(engine, name)
        submitted = body.get("key") if isinstance(body, dict) else None
        if not isinstance(submitted, str) or not submitted.strip():
            raise ConfigError("the key body needs a non-empty 'key' string")
        if not base.key_ref:
            raise ConfigError(f"provider '{name}' has no key_ref in config.yaml - nothing to store it under")
        engine.vault.set(base.key_ref, submitted.strip())
        return {"provider": name, "key_ref": base.key_ref, "key_present": True}

    @app.delete(f"{API_PREFIX}/kira/providers/{{name}}/key", dependencies=[owner])
    async def kira_delete_key(name: str) -> dict:
        base = _baseline_config(engine, name)
        if base.key_ref:
            engine.vault.delete(base.key_ref)
        return {"provider": name, "key_ref": base.key_ref, "key_present": engine.registry.key_for(name) is not None}

    @app.delete(f"{API_PREFIX}/kira/providers/{{name}}/cooldown", dependencies=[owner])
    async def kira_clear_cooldown(name: str) -> dict:
        if name not in engine.view().by_name:
            raise ConfigError(f"unknown provider '{name}'")
        engine.ledger.clear_cooldown(name)
        return providers_payload()

    @app.post(f"{API_PREFIX}/kira/providers/{{name}}/probe", dependencies=[owner])
    async def kira_probe(name: str) -> dict:
        if name not in engine.view().by_name:
            raise ConfigError(f"unknown provider '{name}'")
        return (await probe_provider(engine.registry, name)).to_wire()

    @app.get(f"{API_PREFIX}/kira/sessions", dependencies=[auth])
    async def kira_sessions(limit: int = 50) -> dict:
        return {"sessions": engine.store.session_rows(limit)}

    @app.get(f"{API_PREFIX}/kira/sessions/{{session_id}}/messages", dependencies=[auth])
    async def session_messages(session_id: str) -> dict:
        return {"session_id": session_id, "messages": engine.store.messages(session_id)}

    @app.delete(f"{API_PREFIX}/kira/sessions/{{session_id}}", dependencies=[auth, confirm])
    async def kira_delete_session(session_id: str) -> dict:
        deleted, messages = engine.store.delete_session(session_id)
        return {"deleted": deleted, "messages": messages}

    @app.delete(f"{API_PREFIX}/kira/sessions", dependencies=[auth, confirm])
    async def kira_clear_sessions() -> dict:
        deleted, messages = engine.store.clear_sessions()
        return {"deleted": deleted, "messages": messages}

    @app.get(f"{API_PREFIX}/kira/approvals", dependencies=[auth])
    async def kira_approvals() -> dict:
        return {"approvals": engine.store.pending_approvals()}

    @app.post(f"{API_PREFIX}/kira/approvals/{{approval_id}}", dependencies=[auth, confirm])
    async def kira_decide_approval(approval_id: str, body: dict) -> Any:
        decision = str(body.get("decision", ""))
        if decision not in ("allow", "deny"):
            return JSONResponse(
                status_code=400,
                content={"error": {"code": "bad_request", "message": "decision must be 'allow' or 'deny'", "status": 400, "retryable": False}},
            )
        row = engine.approvals.decide(approval_id, decision)
        if row is None:
            current = engine.store.get_approval(approval_id)
            if current is None:
                return JSONResponse(
                    status_code=404,
                    content={"error": {"code": "not_found", "message": "unknown approval", "status": 404, "retryable": False}},
                )
            return JSONResponse(
                status_code=409,
                content={"error": {"code": "not_pending", "message": f"approval is {current['status']}", "status": 409, "retryable": False}},
            )
        return {"approval": row}

    @app.get(f"{API_PREFIX}/kira/tools", dependencies=[auth])
    async def kira_tools() -> dict:
        overrides = engine.store.tool_policies()
        rows = [
            {**info, "policy": overrides.get(info["name"], info["default_policy"]), "overridden": info["name"] in overrides}
            for info in engine.tools.info()
        ]
        return {"tools": rows, "plugins": [status.to_wire() for status in engine.plugin_status]}

    @app.get(f"{API_PREFIX}/kira/skills", dependencies=[auth])
    async def kira_skills() -> dict:
        return {
            "skills": [skill.to_wire() for skill in engine.skills],
            "files": [status.to_wire() for status in engine.skill_files],
            "discovery": discovery_mode(engine.skills),
        }

    @app.put(f"{API_PREFIX}/kira/tools/{{name}}", dependencies=[auth, confirm])
    async def kira_set_tool_policy(name: str, body: dict) -> Any:
        if engine.tools.get(name) is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "unknown tool", "status": 404, "retryable": False}},
            )
        policy = body.get("policy")
        try:
            engine.store.set_tool_policy(name, policy if isinstance(policy, str) else None)
        except ConfigError as exc:
            return JSONResponse(
                status_code=400,
                content={"error": {"code": "bad_request", "message": exc.message, "status": 400, "retryable": False}},
            )
        tool = engine.tools.get(name)
        overrides = engine.store.tool_policies()
        return {
            "tool": {
                "name": name,
                "policy": overrides.get(name, effective_policy(tool, overrides)),
                "overridden": name in overrides,
            }
        }

    def missing_memory() -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": "unknown memory", "status": 404,
                               "retryable": False}},
        )

    # The literals (`search`, `export`, `settings`) are declared before `{memory_id}` on purpose.
    # Starlette prefers a full path+method match, so today's PATCH/DELETE cannot swallow them; the
    # day a single-fact GET lands, a search answering `404 unknown memory` is the trap this ordering
    # keeps shut.
    @app.get(f"{API_PREFIX}/kira/memory", dependencies=[auth])
    async def memory_list(
        query: str | None = None,
        kind: str | None = None,
        pinned: bool | None = None,
        limit: int = 50,
    ) -> dict:
        # The contract publishes an enum for this filter, so a value off that list is a malformed
        # request, not an empty page: `ConfigError` gives it the same 400 `config_error` the body
        # validators reach, exactly as `/kira/overview` hands a junk `month` to `month_bounds`.
        # A present-but-blank kind (empty or whitespace-only) is the client saying "no filter", the
        # same way `query` reads; the raw value still faces the enum untouched.
        if kind is not None and not kind.strip():
            kind = None
        if kind is not None and kind not in KINDS:
            raise ConfigError(f"kind must be one of {list(KINDS)}, got {kind!r}")
        rows, total = engine.memory.list(
            query=query, kind=kind, pinned=pinned, limit=max(1, min(200, limit))
        )
        return {"memories": rows, "total": total, "settings": engine.memory.settings()}

    @app.post(f"{API_PREFIX}/kira/memory", dependencies=[auth, confirm])
    async def memory_add(body: MemoryWrite) -> dict:
        return engine.memory.add(body.text, kind=body.kind, pinned=body.pinned)

    @app.get(f"{API_PREFIX}/kira/memory/search", dependencies=[auth])
    async def memory_search(q: str = "", limit: int = 20) -> dict:
        hits = engine.memory.search_history(q, max(1, min(50, limit)))
        return {"hits": hits}

    @app.get(f"{API_PREFIX}/kira/memory/export", dependencies=[auth])
    async def memory_export() -> dict:
        return engine.memory.export()

    @app.get(f"{API_PREFIX}/kira/memory/settings", dependencies=[auth])
    async def memory_settings() -> dict:
        return engine.memory.settings()

    @app.put(f"{API_PREFIX}/kira/memory/settings", dependencies=[auth, confirm])
    async def memory_settings_put(body: MemorySettingsPatch) -> dict:
        written = engine.memory.set_settings(body.model_dump(exclude_none=True))
        engine.sync_memory_tools()
        return written

    @app.patch(f"{API_PREFIX}/kira/memory/{{memory_id}}", dependencies=[auth, confirm])
    async def memory_patch(memory_id: str, body: MemoryPatch) -> Any:
        patch = body.model_dump(exclude_none=True)
        item = engine.memory.update(memory_id, patch)
        return missing_memory() if item is None else item

    @app.delete(f"{API_PREFIX}/kira/memory/{{memory_id}}", dependencies=[auth, confirm])
    async def memory_delete(memory_id: str) -> Any:
        return {"deleted": memory_id} if engine.memory.delete(memory_id) else missing_memory()

    @app.get(f"{API_PREFIX}/kira/checkpoints", dependencies=[auth])
    async def kira_checkpoints(limit: int = 20, session_id: str | None = None) -> dict:
        rows = engine.checkpoints.list(limit=max(1, min(limit, 100)), session_id=session_id)
        return {"checkpoints": rows}

    @app.get(f"{API_PREFIX}/kira/checkpoints/{{checkpoint_id}}", dependencies=[auth])
    async def kira_checkpoint_detail(checkpoint_id: str) -> Any:
        try:
            return engine.checkpoints.diff(checkpoint_id)
        except KeyError:
            return _unknown_checkpoint()

    @app.post(f"{API_PREFIX}/kira/checkpoints/{{checkpoint_id}}/restore", dependencies=[auth, confirm])
    async def kira_checkpoint_restore(checkpoint_id: str, body: dict | None = None) -> Any:
        force = bool((body or {}).get("force", False))
        try:
            return engine.checkpoints.restore(checkpoint_id, force=force)
        except KeyError:
            return _unknown_checkpoint()
        except CheckpointConflict as exc:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": "checkpoint_conflict",
                        "message": str(exc),
                        "status": 409,
                        "retryable": True,
                        "conflicts": exc.conflicts,
                    }
                },
            )

    @app.post(f"{API_PREFIX}/kira/pairing-code", dependencies=[owner, confirm])
    async def kira_pairing_code() -> dict:
        code, expires_at = engine.pairing.mint()
        return {"code": code, "expires_at": expires_at}

    @app.post(f"{API_PREFIX}/kira/pair")
    async def kira_pair(body: PairRequest) -> dict:
        # Unauthenticated on purpose: the phone has no secret yet. The code is the secret, it is
        # short-lived, single use and only mintable from the desktop. The name is checked before
        # the exchange so a typo does not burn the code the user is reading off their other screen.
        name = body.name.strip()
        if not 1 <= len(name) <= DEVICE_NAME_MAX:
            raise ConfigError(f"name must be 1-{DEVICE_NAME_MAX} characters")
        engine.pairing.exchange(body.code)
        token = DEVICE_TOKEN_PREFIX + secrets.token_urlsafe(32)
        return {"token": token, "device": engine.store.add_device(name, _token_hash(token))}

    @app.get(f"{API_PREFIX}/kira/devices", dependencies=[owner])
    async def kira_devices() -> dict:
        return {"devices": engine.store.list_devices()}

    @app.delete(f"{API_PREFIX}/kira/devices/{{device_id}}", dependencies=[owner, confirm])
    async def kira_device_delete(device_id: str) -> Any:
        return {"deleted": device_id} if engine.store.revoke_device(device_id) else _unknown_device()

    # `active` is a literal and comes before `{character_id}`, the way memory's `search`, `export` and
    # `settings` come before `{memory_id}`: nothing registered later can win a path an earlier route already
    # matches, so the day a `GET /kira/characters/active` lands it must not answer `character_not_found`
    # for a body called "active".
    @app.get(f"{API_PREFIX}/kira/characters", dependencies=[auth])
    async def kira_characters() -> dict:
        # The row comes from the profile the importer wrote, so listing a full library costs one small read
        # per character and never a 45 MB model walk.
        directory = cfg.characters_dir
        return {"characters": list_characters(directory), "active": get_active(directory, engine.store)}

    @app.post(f"{API_PREFIX}/kira/characters", dependencies=[owner], status_code=201)
    async def kira_character_import(body: CharacterImportRequest) -> dict:
        # Owner, and deliberately no confirm secret: this is the key-route shape. The caller is supplying a
        # file that already exists on this machine, not destroying one Kira made, and a paired device is
        # refused here so nothing a phone can do reaches this disk.
        #
        # Threadpool because an import is a 45 MB read and a walk of every model in it — around a second of
        # work the voice call and the chat stream are waiting on if it runs on the loop.
        entry = await run_in_threadpool(import_from_path, cfg.characters_dir, body.path)
        # Re-read from the library rather than reshape what the importer returned: the answer the caller
        # gets is the row the very next `GET` will give, which is the claim that matters after a rename.
        return next(row for row in list_characters(cfg.characters_dir) if row["id"] == entry.id)

    @app.put(f"{API_PREFIX}/kira/characters/active", dependencies=[owner])
    async def kira_character_active(body: CharacterActiveRequest) -> dict:
        # A preference, not data on disk: owner-only so a phone cannot repaint the desktop's stage, but no
        # secret to type, because there is nothing here a user would be confirming.
        return {"active": set_active(cfg.characters_dir, body.id, engine.store)}

    @app.get(f"{API_PREFIX}/kira/characters/{{character_id}}", dependencies=[auth])
    async def kira_character_detail(character_id: str) -> dict:
        return get_character(cfg.characters_dir, character_id)

    @app.delete(f"{API_PREFIX}/kira/characters/{{character_id}}", dependencies=[owner, confirm])
    async def kira_character_delete(character_id: str) -> dict:
        # Takes it off stage in the same call if that is who it was — `remove_character` clears the pick
        # first, so a delete that dies halfway leaves no pointer at a folder that is gone.
        remove_character(cfg.characters_dir, character_id, engine.store)
        return {"deleted": character_id}

    @app.get(f"{API_PREFIX}/kira/characters/{{character_id}}/file", dependencies=[auth])
    async def kira_character_file(character_id: str, path: str = "") -> FileResponse:
        # The one route in Kira that turns a string from a caller into a file on this disk, so it is checked
        # by `character_file`: inside the character's folder after the percent-decoding and the dot-dots, and
        # an extension the stage can load. The token is a header, never a query parameter — a URL with a
        # secret in it is a URL that ends up in a log.
        resolved, media_type = character_file(cfg.characters_dir, character_id, path)
        return FileResponse(path=str(resolved), media_type=media_type)

    @app.get(f"{API_PREFIX}/kira/characters/{{character_id}}/mesh", dependencies=[auth])
    async def kira_character_mesh(character_id: str) -> Response:
        # The stage's one geometry request. A device token may ask for it — a paired phone showing the
        # avatar needs the body the same way the desktop does — and the answer is a flat KRM1 blob rather
        # than the PMX, so the browser never has to re-decide what an unreadable morph table means.
        #
        # Threadpool because a mesh is the whole model walk: 45 MB read and stepped over, which the voice
        # call and the chat stream would otherwise wait on.
        blob = await run_in_threadpool(export_mesh, cfg.characters_dir, character_id)
        return Response(content=blob, media_type=MESH_MEDIA_TYPE)

    @app.get(f"{API_PREFIX}/kira/images", dependencies=[auth])
    async def kira_images() -> dict:
        # A status read walks two small folders; the threadpool keeps a slow disk off the event loop.
        return await run_in_threadpool(engine.images.status)

    @app.post(f"{API_PREFIX}/kira/images/generate", dependencies=[auth, confirm])
    async def kira_image_generate(body: ImageGenerateRequest) -> dict:
        # Generation is minutes on a CPU and the process is blocking, so it runs off the loop and
        # the chat stream keeps flowing while a picture draws. No confirm secret: nothing is
        # destroyed, and the caller is asking for work rather than overwriting someone else's.
        record = await engine.images.generate_async(
            prompt=body.prompt,
            negative_prompt=body.negative_prompt,
            model=body.model,
            steps=body.steps,
            cfg_scale=body.cfg_scale,
            width=body.width,
            height=body.height,
            seed=body.seed,
            sampler=body.sampler,
        )
        return record.to_wire()

    @app.get(f"{API_PREFIX}/kira/images/file/{{name}}", dependencies=[auth])
    async def kira_image_file(name: str) -> FileResponse:
        # The name is checked against the shape this workspace writes, then resolved inside the
        # output folder. No caller-supplied path reaches the filesystem, and the token stays a header.
        return FileResponse(path=str(engine.images.file_path(name)), media_type="image/png")

    @app.delete(f"{API_PREFIX}/kira/images/{{name}}", dependencies=[auth, confirm])
    async def kira_image_delete(name: str) -> dict:
        await run_in_threadpool(engine.images.delete, name)
        return {"deleted": name}

    def studio_status() -> dict:
        """One shape whether or not a studio exists: Kira's own folders fill in when it does not."""
        images = engine.images.status()
        llm = engine.llm.status()
        voice = engine.voice.status()

        def without_paths(part: dict) -> dict:
            # The contract's model row is name/filename/size/kind. The path is how discovery found it,
            # not something the screen should render, and letting it through would be an undocumented field.
            return {
                **part,
                "models": [
                    {key: model[key] for key in ("name", "filename", "size_bytes", "kind")}
                    for model in part.get("models", [])
                ],
            }

        if engine.studio is not None:
            folder = engine.studio.status()
            image_part = without_paths(folder["image"])
            stt_part = without_paths(folder["stt"])
            tts_part = without_paths(folder["tts"])
            llm_folder = without_paths(folder["llm"])
            root = folder["root"]
        else:
            image_part = {
                "available": bool(images["ready"]),
                "engine": images.get("backend_path") or images.get("remote_url"),
                "detail": images.get("reason") or "ready",
                "models": images.get("models", []),
            }
            stt_part = {
                "available": bool(voice["stt"]["available"]),
                "engine": None,
                "detail": voice["stt"]["detail"],
                "models": [],
            }
            tts_part = {
                "available": bool(voice["tts"]["available"]),
                "engine": None,
                "detail": voice["tts"]["detail"],
                "models": [],
            }
            llm_folder = {"available": False, "engine": None, "detail": "", "models": []}
            root = None
        return {
            "root": root,
            "available": engine.studio is not None,
            "image": image_part,
            "llm": {
                "available": bool(llm_folder.get("available")) or bool(llm["engine"] and llm["models"]),
                "engine": llm["engine"] or llm_folder.get("engine"),
                "detail": llm_folder.get("detail") or llm.get("reason") or "ready",
                "models": llm["models"],
                "running": llm["running"],
                "model": llm["model"],
                "url": llm["url"],
                "model_dir": llm["model_dir"],
                "engine_dir": llm["engine_dir"],
                "reason": llm["reason"],
            },
            "stt": {
                "available": bool(stt_part.get("available")) or bool(voice["stt"]["available"]),
                "engine": stt_part.get("engine"),
                "detail": stt_part.get("detail") or voice["stt"]["detail"],
                "models": stt_part.get("models", []),
            },
            "tts": {
                "available": bool(tts_part.get("available")) or bool(voice["tts"]["available"]),
                "engine": tts_part.get("engine"),
                "detail": tts_part.get("detail") or voice["tts"]["detail"],
                "models": tts_part.get("models", []),
            },
        }

    @app.get(f"{API_PREFIX}/kira/studio", dependencies=[auth])
    async def kira_studio() -> dict:
        # Folder scans and a process `poll()`; the threadpool keeps a slow disk off the event loop.
        return await run_in_threadpool(studio_status)

    @app.post(f"{API_PREFIX}/kira/studio/llm/start", dependencies=[auth, confirm])
    async def kira_studio_llm_start(body: StudioLlmRequest) -> dict:
        # Starting a process is an exec-shaped write, which is why it carries the confirm secret.
        await run_in_threadpool(engine.llm.start, body.model)
        return await run_in_threadpool(studio_status)

    @app.post(f"{API_PREFIX}/kira/studio/llm/stop", dependencies=[auth, confirm])
    async def kira_studio_llm_stop() -> dict:
        await run_in_threadpool(engine.llm.stop)
        return await run_in_threadpool(studio_status)

    @app.post(f"{API_PREFIX}/kira/studio/download", dependencies=[auth, confirm])
    async def kira_studio_download(body: StudioDownloadRequest) -> dict:
        # One model at a time into a folder the loaders already scan. The ceiling and the host
        # allowlist live in `downloads.py`, so the refusal is the same from any caller.
        return await run_in_threadpool(download_model, cfg.data_dir, body.kind, body.url, body.filename)

    @app.get(f"{API_PREFIX}/kira/studio/app", dependencies=[auth])
    async def kira_studio_app() -> dict:
        # The studio's Node server: found, running, managed by Kira, and the URL it answers on.
        return await run_in_threadpool(engine.studio_server.status)

    @app.post(f"{API_PREFIX}/kira/studio/app/start", dependencies=[auth, confirm])
    async def kira_studio_app_start() -> dict:
        # Spawning is an exec-shaped write: the confirm secret is what separates "open the studio"
        # from a page that a stray click could start on the user's machine.
        return await run_in_threadpool(engine.studio_server.start)

    @app.post(f"{API_PREFIX}/kira/studio/app/stop", dependencies=[auth, confirm])
    async def kira_studio_app_stop() -> dict:
        return await run_in_threadpool(engine.studio_server.stop)

    @app.get(f"{API_PREFIX}/kira/studio/proxy", dependencies=[auth])
    @app.post(f"{API_PREFIX}/kira/studio/proxy", dependencies=[auth])
    async def kira_studio_proxy(request: Request) -> Response:
        # One forwarded request. The studio's API is the feature set (whisper, Kokoro, four model
        # folders, downloads, diagnostics); the allowlist and the loopback-only rule live in
        # `studio_server`, and a delete still asks for the typed confirm secret.
        target = request.query_params.get("path", "")
        if request.method == "POST" and any(word in target for word in ("delete", "stop")):
            require_confirm(request.headers.get("x-kira-confirm"))
        status_code, content_type, payload = await engine.studio_server.proxy(
            request.method,
            target,
            content_type=request.headers.get("content-type"),
            body=await request.body() if request.method == "POST" else b"",
        )
        return Response(content=payload, status_code=status_code, media_type=content_type)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/chat/")

    dist = chat_dist_dir(cfg)
    if (dist / "index.html").exists():
        app.mount("/chat", ChatBundle(directory=str(dist), html=True), name="chat")

    return app
