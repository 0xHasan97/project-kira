from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from .workspace import Workspace, WorkspaceError

ToolHandler = Callable[[dict], "str | ToolOutcome | Awaitable[str | ToolOutcome]"]
Summary = Callable[[dict], str]

TEST_PREFIXES = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
    ("py", "-m", "pytest"),
    ("python", "-m", "unittest"),
    ("npm", "test"),
    ("npm", "run", "test"),
    ("pnpm", "test"),
    ("yarn", "test"),
    ("npx", "vitest"),
    ("npx", "jest"),
    ("vitest",),
    ("jest",),
    ("cargo", "test"),
    ("go", "test"),
    ("dotnet", "test"),
)


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict
    handler: ToolHandler
    risk: str = "read"
    default_policy: str | None = None
    source: str = "builtin"
    summary: Summary | None = None
    checkpoint_paths: Callable[[dict], list[str]] | None = None


@dataclass
class ToolOutcome:
    ok: bool
    content: str
    summary: str = ""
    kind: str | None = None
    exit_code: int | None = None
    duration_ms: int | None = None


def _program(words: tuple[str, ...]) -> str:
    """`C:\\...\\python.exe` and `python` must classify the same way."""
    if not words:
        return ""
    return words[0].rsplit("\\", 1)[-1].rsplit("/", 1)[-1].lower().removesuffix(".exe")


def classify_command(argv: list[str]) -> str:
    words = tuple(str(item) for item in argv)
    program = _program(words)
    for prefix in TEST_PREFIXES:
        if words[: len(prefix)] == prefix:
            return "test"
        if program == prefix[0].removesuffix(".exe") and words[1 : len(prefix)] == prefix[1:]:
            return "test"
    return "command"


class ToolRegistry:
    """The one registry every tool lands in: demos, workspace tools, and declarative plugins."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(self, tool: ToolDef) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name '{tool.name}'")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def unregister(self, name: str) -> bool:
        """Remove one tool. Used when a setting makes a tool impossible to call, not for plugins."""
        return self._tools.pop(name, None) is not None

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in (self._tools[name] for name in self.names)
        ]

    def info(self) -> list[dict]:
        out = []
        for name in self.names:
            tool = self._tools[name]
            out.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                    "risk": tool.risk,
                    "source": tool.source,
                    "default_policy": tool.default_policy or ("allow" if tool.risk == "read" else "ask"),
                }
            )
        return out

    async def execute(self, name: str, arguments: dict) -> ToolOutcome:
        tool = self._tools.get(name)
        if tool is None:
            return ToolOutcome(ok=False, content=f"error: unknown tool '{name}'")
        try:
            result = tool.handler(arguments)
            if inspect.isawaitable(result):
                result = await result
        except (WorkspaceError, ValueError) as exc:
            return ToolOutcome(ok=False, content=f"error: {exc}")
        except Exception as exc:  # noqa: BLE001 - the model must see the failure
            return ToolOutcome(ok=False, content=f"error: tool '{name}' raised {type(exc).__name__}: {exc}")
        if isinstance(result, ToolOutcome):
            return result
        if not isinstance(result, str):
            return ToolOutcome(ok=False, content=f"error: tool '{name}' returned {type(result).__name__}, expected str")
        return ToolOutcome(ok=True, content=result, summary=tool.summary(arguments) if tool.summary else "")


def register_demo_tools(registry: ToolRegistry) -> None:
    def echo(args: dict) -> str:
        return str(args.get("text", ""))

    def now(args: dict) -> str:
        moment = datetime.now(timezone.utc)
        return json.dumps({"utc_iso": moment.isoformat(timespec="seconds"), "epoch": int(moment.timestamp())})

    registry.register(
        ToolDef(
            name="echo",
            description="Return the given text unchanged. Proves the tool round-trip.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string", "description": "text to return"}},
                "required": ["text"],
            },
            handler=echo,
            risk="read",
            summary=lambda a: str(a.get("text", ""))[:80],
        )
    )
    registry.register(
        ToolDef(
            name="now",
            description="Return the current UTC time as JSON.",
            parameters={"type": "object", "properties": {}},
            handler=now,
            risk="read",
            summary=lambda _a: "utc now",
        )
    )


def register_workspace_tools(registry: ToolRegistry, workspace: Workspace) -> None:
    def path_of(args: dict, key: str = "path", default: str | None = ".") -> str:
        value = args.get(key, default)
        if not isinstance(value, str):
            raise WorkspaceError(f"{key} must be a string")
        return value

    def list_dir(args: dict) -> str:
        return workspace.list_dir(path_of(args))

    def read_file(args: dict) -> str:
        return workspace.read_text(path_of(args, default=""))

    def search_text(args: dict) -> str:
        query = args.get("query")
        if not isinstance(query, str) or not query:
            raise WorkspaceError("query must be a non-empty string")
        return workspace.search_text(query, path_of(args))

    def write_file(args: dict) -> str:
        content = args.get("content")
        if not isinstance(content, str):
            raise WorkspaceError("content must be a string")
        written = workspace.write_text(path_of(args, default=""), content)
        return json.dumps({"path": path_of(args, default=""), "bytes": written})

    async def run_command(args: dict) -> ToolOutcome:
        argv = args.get("argv")
        if not isinstance(argv, list):
            raise WorkspaceError("argv must be a list of strings")
        cwd = path_of(args, "cwd", ".")
        timeout_s = args.get("timeout_s", 30)
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, int):
            raise WorkspaceError("timeout_s must be an integer")
        result = await workspace.run_command(argv, cwd=cwd, timeout_s=timeout_s)
        return ToolOutcome(
            ok=result["exit_code"] == 0,
            content=json.dumps(result, ensure_ascii=False),
            summary=" ".join(str(item) for item in argv)[:200],
            kind=classify_command(argv),
            exit_code=result["exit_code"],
            duration_ms=result["duration_ms"],
        )

    registry.register(ToolDef(
        name="list_dir",
        description="List one directory inside the workspace.",
        parameters={"type": "object", "properties": {"path": {"type": "string", "default": "."}}},
        handler=list_dir,
        risk="read",
        summary=lambda a: str(a.get("path", ".")),
    ))
    registry.register(ToolDef(
        name="read_file",
        description="Read a UTF-8 text file inside the workspace.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        handler=read_file,
        risk="read",
        summary=lambda a: str(a.get("path", "")),
    ))
    registry.register(ToolDef(
        name="search_text",
        description="Find a literal string in workspace text files.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}, "path": {"type": "string", "default": "."}},
            "required": ["query"],
        },
        handler=search_text,
        risk="read",
        summary=lambda a: f"{a.get('query', '')} in {a.get('path', '.')}",
    ))
    registry.register(ToolDef(
        name="write_file",
        description="Write a UTF-8 text file inside the workspace. A checkpoint is taken first.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
        handler=write_file,
        risk="write",
        summary=lambda a: str(a.get("path", "")),
        checkpoint_paths=lambda a: [str(a.get("path", ""))],
    ))
    registry.register(ToolDef(
        name="run_command",
        description="Run one program with an argv list (no shell) inside the workspace.",
        parameters={
            "type": "object",
            "properties": {
                "argv": {"type": "array", "items": {"type": "string"}},
                "cwd": {"type": "string", "default": "."},
                "timeout_s": {"type": "integer", "default": 30},
            },
            "required": ["argv"],
        },
        handler=run_command,
        risk="exec",
        summary=lambda a: " ".join(str(item) for item in a.get("argv", []))[:200],
    ))
