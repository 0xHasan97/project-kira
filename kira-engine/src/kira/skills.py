from __future__ import annotations

import io
import json
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .tools import ToolDef, ToolOutcome, ToolRegistry

NAME = re.compile(r"^[a-z][a-z0-9_-]{2,39}$")
KINDS = ("persona", "method")

#: A skill is text that rides a prompt, not a document. 16 KB is already several pages of
#: instructions; anything larger is a file in the wrong place.
MAX_SKILL_BYTES = 16_384

#: The file inside a skill folder. This is how a skill pack ships — one directory per skill, its
#: instructions in `SKILL.md` — and a flat `*.md` still loads, for a hand-written pack.
PACK_FILE = "SKILL.md"

#: How many method names go into the `use_skill` schema and description. Listing every name is what
#: makes a small pack usable with no search, but a 300-skill pack would put kilobytes of names in
#: front of the model on every turn; past this cap the model is told to search instead.
INLINE_LIMIT = 24

#: One `search_skills` answer: enough names to choose from, and only the start of each description.
SEARCH_LIMIT = 12
SEARCH_DESCRIPTION_CHARS = 240

#: An archive is opened whole to pick its skill folders out, so the ceiling is on the file, not a skill.
MAX_PACK_BYTES = 64 * 1024 * 1024

#: Attribution travels with the copy — MIT and its friends require the notice be included.
LICENSE_FILES = ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING", "COPYING.txt")

#: Frontmatter a donor pack declares that Kira has no field for but must not throw away.
PASSTHROUGH_KEYS = ("license", "homepage", "author", "origin", "metadata")


@dataclass
class Skill:
    name: str
    description: str
    kind: str
    body: str
    source: str
    file: str

    def to_wire(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "kind": self.kind,
            "source": self.source,
            "body_bytes": len(self.body.encode("utf-8")),
        }


@dataclass
class SkillStatus:
    file: str
    name: str
    status: str
    reason: str = ""
    source: str = ""

    def to_wire(self) -> dict:
        return {
            "file": self.file,
            "name": self.name,
            "status": self.status,
            "reason": self.reason,
            "source": self.source,
        }


def builtin_dir() -> Path:
    """`kira-engine/skills` beside the source tree. Read-only: the user's pack lives in data_dir."""
    return Path(__file__).resolve().parents[2] / "skills"


def _split(text: str) -> tuple[dict, str]:
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError("file must start with a --- frontmatter block")
    try:
        close = lines.index("---", 1)
    except ValueError:
        raise ValueError("frontmatter is not closed with a second ---") from None
    try:
        meta = yaml.safe_load("\n".join(lines[1:close])) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"frontmatter is not valid YAML: {exc}") from None
    if not isinstance(meta, dict):
        raise ValueError("frontmatter must be a mapping")
    return meta, "\n".join(lines[close + 1 :]).strip()


def _parse(path: Path, label: str) -> Skill:
    if path.stat().st_size > MAX_SKILL_BYTES:
        raise ValueError(f"file is larger than {MAX_SKILL_BYTES} bytes")
    meta, body = _split(path.read_text(encoding="utf-8"))
    name = str(meta.get("name", ""))
    if not NAME.match(name):
        raise ValueError("name must match ^[a-z][a-z0-9_-]{2,39}$")
    description = str(meta.get("description", "")).strip()
    if not description:
        raise ValueError("description must not be empty")
    kind = str(meta.get("kind", "persona"))
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if not body:
        raise ValueError("body must not be empty")
    return Skill(name=name, description=description, kind=kind, body=body, source="", file=label)


def _safe_name(path: Path) -> str:
    try:
        meta, _ = _split(path.read_text(encoding="utf-8"))
        return str(meta.get("name", path.stem))
    except Exception:
        return path.stem


def _entries(directory: Path) -> list[tuple[str, Path]]:
    """Every skill file in one root, as (label, path): the flat `*.md` and `<name>/SKILL.md` folders.

    A folder's file is labelled with the folder it is in. 300 rows all called `SKILL.md` would be a
    list of nothing, and the label is the only thing the screen and a status row have to name.
    """
    found = [(path.name, path) for path in directory.glob("*.md")]
    found += [(f"{path.parent.name}/{PACK_FILE}", path) for path in directory.glob(f"*/{PACK_FILE}")]
    return sorted(found)


def load_skills(
    builtin_directory: Path | None, user_directory: Path | None
) -> tuple[list[Skill], list[SkillStatus]]:
    """Every readable skill, with the user's pack overriding the builtin one by name.

    A bad file is reported, never fatal: one typo must not take chat down with it, the same rule
    `load_plugins` follows.
    """
    skills: dict[str, Skill] = {}
    statuses: list[tuple[SkillStatus, Skill | None]] = []
    for source, directory in (("builtin", builtin_directory), ("user", user_directory)):
        directory = Path(directory) if directory else None
        if directory is None or not directory.is_dir():
            continue
        seen_here: set[str] = set()
        for label, path in _entries(directory):
            try:
                skill = _parse(path, label)
                if skill.name in seen_here:
                    raise ValueError(f"duplicate skill name '{skill.name}' in this directory")
                seen_here.add(skill.name)
            except Exception as exc:  # noqa: BLE001 - a bad file must not stop the engine
                statuses.append(
                    (SkillStatus(label, _safe_name(path), "skipped", str(exc), source), None)
                )
                continue
            skill.source = source
            previous = skills.get(skill.name)
            if previous is not None:
                for status, candidate in statuses:
                    if candidate is previous:
                        status.status = "shadowed"
                        status.reason = f"overridden by {source} skill at {label}"
                        break
            skills[skill.name] = skill
            statuses.append((SkillStatus(label, skill.name, "loaded", "", source), skill))
    return [skills[name] for name in sorted(skills)], [status for status, _ in statuses]


def _search(methods: dict[str, Skill], query: str, limit: int) -> list[dict]:
    """Names whose skill name or description carries the query, best match first, name breaking ties."""
    terms = [term for term in query.lower().split() if term]
    scored: list[tuple[int, str, Skill]] = []
    for name, skill in methods.items():
        words = skill.name.replace("_", " ").replace("-", " ").lower().split()
        description = skill.description.lower()
        score = 0
        for term in terms:
            if term in skill.name:
                score += 4
            if any(word.startswith(term) for word in words):
                score += 2
            if term in description:
                score += 1
        if score:
            scored.append((score, name, skill))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [
        {"name": skill.name, "description": skill.description[:SEARCH_DESCRIPTION_CHARS]}
        for _score, _name, skill in scored[:limit]
    ]


def discovery_mode(skills: list[Skill]) -> str:
    """How a model reaches a method, as one word — the same rule `register_skill_tool` applies.

    The dashboard and the CLI both want to say "past 24 the model finds these with search_skills", and a
    limit repeated on the far side of the wire is a limit that quietly changes.
    """
    methods = [skill for skill in skills if skill.kind == "method"]
    if not methods:
        return "none"
    return "inline" if len(methods) <= INLINE_LIMIT else "search"


def register_skill_tool(registry: ToolRegistry, skills: list[Skill]) -> bool:
    """One tool for every method skill, and none when there is nothing to load.

    A small pack names its methods in the tool, so the model can pick one without a lookup. A large
    one cannot: those names would ride every request, so `use_skill` says how many there are and the
    model finds one with `search_skills` first.
    """
    methods = {skill.name: skill for skill in skills if skill.kind == "method"}
    if not methods:
        return False
    names = sorted(methods)
    inline = len(names) <= INLINE_LIMIT

    def handler(arguments: dict) -> ToolOutcome:
        name = str(arguments.get("name", ""))
        skill = methods.get(name)
        if skill is None:
            if inline:
                return ToolOutcome(
                    False, f"error: no method skill named '{name}'; valid: {', '.join(names)}"
                )
            return ToolOutcome(
                False,
                f"error: no method skill named '{name}'. {len(names)} are installed; call "
                "search_skills(query) to find the right one.",
            )
        return ToolOutcome(True, skill.body, summary=f"use_skill({name})")

    name_schema: dict
    if inline:
        listed = "; ".join(f"{name} — {methods[name].description}" for name in names)
        description = f"Load a reusable procedure when the task matches it. Available: {listed}"
        name_schema = {"type": "string", "enum": names, "description": "A method skill to load."}
    else:
        description = (
            f"Load a reusable procedure by its exact name when the task matches it. {len(names)} "
            "method skills are installed and their names are not listed here: call "
            "search_skills(query) first, then pass back a name it returned."
        )
        name_schema = {
            "type": "string",
            "description": "The exact name of a method skill, as returned by search_skills.",
        }

    registry.register(
        ToolDef(
            name="use_skill",
            description=description,
            parameters={"type": "object", "properties": {"name": name_schema}, "required": ["name"]},
            handler=handler,
            risk="read",
            default_policy="allow",
            source="builtin:skills",
            summary=lambda args: f"use_skill({args.get('name', '')})",
        )
    )

    if inline:
        return True

    def search(arguments: dict) -> ToolOutcome:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return ToolOutcome(False, "error: query must not be empty")
        limit = arguments.get("limit", SEARCH_LIMIT)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            return ToolOutcome(False, f"error: limit must be a positive integer, got {limit!r}")
        found = _search(methods, query, min(limit, SEARCH_LIMIT))
        body = json.dumps(
            {"query": query, "skills": found, "installed": len(names)}, ensure_ascii=False
        )
        return ToolOutcome(True, body, summary=f"search_skills({query})")

    registry.register(
        ToolDef(
            name="search_skills",
            description=(
                f"Find method skills by keyword among the {len(names)} installed. Returns names to "
                "pass to use_skill; it does not load anything."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Words a skill name or description should contain.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"Most results to return (max {SEARCH_LIMIT}).",
                    },
                },
                "required": ["query"],
            },
            handler=search,
            risk="read",
            default_policy="allow",
            source="builtin:skills",
            summary=lambda args: f"search_skills({args.get('query', '')})",
        )
    )
    return True


# --- installing a pack someone else wrote -------------------------------------------------------


@dataclass
class _Folder:
    """One skill folder inside a source, with its files read on demand and never executed.

    `sizes` is every file sitting directly in the folder — the archive or the directory answers that
    without decompressing anything, which is what makes a 40 KB skill refusible before it is read.
    """

    name: str
    sizes: dict[str, int]
    read: Callable[[str], bytes]
    extra: list[str] = field(default_factory=list)


@dataclass
class InstallRow:
    name: str
    status: str
    reason: str = ""
    bytes: int = 0

    def to_wire(self) -> dict:
        row = {"name": self.name, "status": self.status}
        if self.reason:
            row["reason"] = self.reason
        if self.bytes:
            row["bytes"] = self.bytes
        return row


def normalise_skill(text: str, fallback_kind: str = "method") -> tuple[dict, str]:
    """A donor file's (fields, body), ready to write down as a Kira skill.

    Packs declare `name`, `description` and sometimes `license`; none of them declare `kind`, which
    Kira needs to know whether the text is a voice to pin or a procedure to pull. What ships inside
    a `skills/<name>/` folder is a procedure, so that is what an import writes down — and a file that
    already chose a kind keeps its own answer.
    """
    meta, body = _split(text)
    name = str(meta.get("name", ""))
    if not NAME.match(name):
        raise ValueError(f"'{name}' is not a Kira skill name (^[a-z][a-z0-9_-]{2,39}$)")
    if not str(meta.get("description", "")).strip():
        raise ValueError("description must not be empty")
    if not body:
        raise ValueError("body must not be empty")
    kind = str(meta.get("kind", fallback_kind))
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    return meta, body


def _frontmatter(meta: dict) -> str:
    ordered = {
        "name": str(meta.get("name", "")),
        "description": str(meta.get("description", "")).strip(),
        "kind": str(meta.get("kind", "method")),
    }
    for key in PASSTHROUGH_KEYS:
        if key in meta:
            ordered[key] = meta[key]
    return yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True, width=1_000_000).strip()


def render_skill(meta: dict, body: str) -> str:
    return f"---\n{_frontmatter(meta)}\n---\n\n{body}\n"


def _folders_in_directory(root: Path) -> list[_Folder]:
    directory = root / "skills" if (root / "skills").is_dir() else root
    found: list[_Folder] = []
    for path in sorted(directory.iterdir()):
        if not path.is_dir():
            continue
        entries = {item.name: item for item in path.iterdir() if item.is_file()}
        if PACK_FILE not in entries:
            continue
        sizes = {name: item.stat().st_size for name, item in entries.items()}
        found.append(
            _Folder(
                name=path.name,
                sizes=sizes,
                read=lambda name, entries=entries: entries[name].read_bytes(),
                extra=sorted(set(sizes) - {PACK_FILE}),
            )
        )
    return found


def _folders_in_archive(data: bytes) -> list[_Folder]:
    """`skills/<name>/...` folders, at any depth under one top folder, from a zip.

    A pack carries the same skill once per host harness — `.claude`, `.cursor`, `.kiro`, and so on —
    plus translated documentation. Only `<top>/skills/<name>/` is read: the depth is the whole test,
    because `ECC-main/skills/t/SKILL.md` and `ECC-main/.agents/skills/t/SKILL.md` differ only in how
    deep the `skills` folder sits, and two installed copies of one skill would be two rows claiming
    the same name.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        files: dict[str, dict[str, zipfile.ZipInfo]] = {}
        for info in archive.infolist():
            if info.is_dir():
                continue
            parts = info.filename.replace("\\", "/").split("/")
            if len(parts) not in (3, 4) or parts[len(parts) - 3] != "skills":
                continue
            files.setdefault(parts[-2], {})[parts[-1]] = info
        found: list[_Folder] = []
        for name in sorted(files):
            infos = files[name]
            if PACK_FILE not in infos:
                continue
            # Read what is going to be installed while the archive is still open, and leave the rest:
            # a 40 KB SKILL.md is refused on its size and never decompressed.
            keep = {
                file_name: archive.read(info)
                for file_name, info in infos.items()
                if info.file_size <= MAX_SKILL_BYTES
                and (file_name == PACK_FILE or file_name in LICENSE_FILES)
            }
            found.append(
                _Folder(
                    name=name,
                    sizes={file_name: int(info.file_size) for file_name, info in infos.items()},
                    read=lambda file_name, keep=keep: keep[file_name],
                    extra=sorted(set(infos) - {PACK_FILE}),
                )
            )
        return found


def _pack_licence(data: bytes | None, root: Path | None) -> str | None:
    if data is not None:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                parts = info.filename.replace("\\", "/").split("/")
                if len(parts) == 2 and parts[1] in LICENSE_FILES:
                    return archive.read(info).decode("utf-8", "replace")
        return None
    if root is None:
        return None
    # `<top>/skills/<name>/` and `<top>/LICENSE` are siblings, so the licence is either beside the
    # folder that was named or one up, when the named folder *is* the `skills` directory.
    for directory in (root, root.parent):
        for file_name in LICENSE_FILES:
            path = directory / file_name
            if path.is_file():
                return path.read_text(encoding="utf-8", errors="replace")
    return None


def install_pack(
    pack_dir: Path, source: Path, force: bool = False, dry_run: bool = False
) -> dict:
    """Copy one donor pack into the user's skill directory, as Kira needs it written.

    The source is a `.zip` or a folder; only `skills/<name>/SKILL.md` and that folder's licence file
    are read. Nothing in a pack is executed, and nothing is written outside `pack_dir`.
    """
    source = Path(source)
    data: bytes | None = None
    folders: list[_Folder]
    if source.is_file():
        if source.suffix.lower() != ".zip":
            raise ValueError(f"'{source.name}' is not a .zip and not a folder")
        if source.stat().st_size > MAX_PACK_BYTES:
            raise ValueError(f"archive is larger than {MAX_PACK_BYTES} bytes")
        data = source.read_bytes()
        folders = _folders_in_archive(data)
    elif source.is_dir():
        folders = _folders_in_directory(source)
    else:
        raise ValueError(f"nothing at '{source}' to install from")
    if not folders:
        raise ValueError(f"no skills/<name>/{PACK_FILE} folders found in '{source.name}'")

    rows: list[InstallRow] = []
    for folder in folders:
        if not NAME.match(folder.name):
            # The name is the only part of the written path that came from the source, so refusing it
            # here is also the traversal guard: nothing below can escape `pack_dir`.
            rows.append(InstallRow(folder.name, "skipped", "folder name is not a Kira skill name"))
            continue
        target = pack_dir / folder.name / PACK_FILE
        size = folder.sizes[PACK_FILE]
        if size > MAX_SKILL_BYTES:
            rows.append(
                InstallRow(folder.name, "skipped", f"{PACK_FILE} is {size} bytes, over the {MAX_SKILL_BYTES}")
            )
            continue
        try:
            text = folder.read(PACK_FILE).decode("utf-8", "replace")
            meta, body = normalise_skill(text)
        except ValueError as exc:
            rows.append(InstallRow(folder.name, "skipped", str(exc)))
            continue
        except Exception as exc:  # noqa: BLE001 - one unreadable file must not stop the pack
            rows.append(InstallRow(folder.name, "skipped", f"unreadable: {type(exc).__name__}: {exc}"))
            continue
        rendered = render_skill(meta, body)
        payload = rendered.encode("utf-8")
        if len(payload) > MAX_SKILL_BYTES:
            # The source file fit but the copy does not: installing adds Kira's own fields on top.
            rows.append(
                InstallRow(
                    folder.name,
                    "skipped",
                    f"the installed copy would be {len(payload)} bytes, over the {MAX_SKILL_BYTES}",
                )
            )
            continue
        if target.exists() and target.read_bytes() == payload and not force:
            rows.append(InstallRow(folder.name, "unchanged", "", len(payload)))
            continue
        if target.exists() and not force:
            rows.append(InstallRow(folder.name, "skipped", "already installed; use --force to overwrite"))
            continue
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            for file_name in folder.extra:
                notice = target.parent / file_name
                if (
                    file_name in LICENSE_FILES
                    and folder.sizes[file_name] <= MAX_SKILL_BYTES
                    and not notice.exists()
                ):
                    notice.write_bytes(folder.read(file_name))
        note = ""
        sidecar = [name for name in folder.extra if name not in LICENSE_FILES]
        if sidecar:
            note = f"comes with {len(sidecar)} file(s) Kira does not load: {', '.join(sidecar[:4])}"
        rows.append(InstallRow(folder.name, "installed", note, len(payload)))

    licence = _pack_licence(data, source if data is None else None)
    if not licence:
        licence_note = "none found"
    elif (pack_dir / "LICENSE").exists():
        licence_note = "already there"
    elif dry_run:
        # Nothing has been written yet, so "already there" would be a lie a user acts on.
        licence_note = "would write"
    else:
        path = pack_dir / "LICENSE"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(licence, encoding="utf-8")
        licence_note = "written"

    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return {
        "source": str(source),
        "pack_dir": str(pack_dir),
        "counts": counts,
        "rows": [row.to_wire() for row in rows],
        "licence": licence_note,
        "dry_run": dry_run,
    }
