"""Keep README.md and the engine in the same sentence.

Docs rot the moment a surface changes and nobody's job was to notice. Every check
here compares README against code that is already the source of truth - the app's
own route table, the published event list, the parser's verbs, the merge's tunable
fields - so a task that adds an endpoint without documenting it fails a test
instead of shipping a wrong README.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from kira.contracts import CHAIN_EVENTS
from kira.__main__ import build_parser
from kira.limits import MAX_OUTPUT_BYTES, MAX_READ_BYTES, MAX_WRITE_BYTES
from kira.overrides import TUNABLE_FIELDS
from kira.policy import POLICIES

README = Path(__file__).resolve().parents[2] / "README.md"


def readme() -> str:
    assert README.is_file(), f"README must sit at the repo root: {README}"
    return README.read_text(encoding="utf-8")


def canon(path: str) -> str:
    """`/v1/kira/sessions/{id}/messages` and `.../{session_id}/...` are the same route."""
    return re.sub(r"\{[^}]+\}", "{}", path)


def _readme_rows() -> set[str]:
    rows: set[str] = set()
    for line in readme().splitlines():
        if not line.strip().startswith("|"):
            continue
        found = re.search(r"`([A-Z]+ /[^`]*)`", line.split("|")[1])
        if not found:
            continue
        method, path = found.group(1).split(" ", 1)
        path = path.rstrip("/")
        if path.startswith("/v1") or path == "/healthz":
            rows.add(f"{method} {canon(path)}")
    return rows


def _leaf_verbs() -> list[str]:
    """Every command a user can actually run: `keys set`, `settings clear`, ..."""
    leaves: list[str] = []

    def walk(parser: argparse.ArgumentParser, prefix: str) -> None:
        actions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        if not actions:
            if prefix.strip():
                leaves.append(prefix.strip())
            return
        for action in actions:
            for name, sub in action.choices.items():
                walk(sub, f"{prefix}{name} ")

    walk(build_parser(), "")
    return leaves


def test_the_readme_endpoint_table_matches_the_app(harness) -> None:
    documented = _readme_rows()
    published = {
        f"{method} {canon(route.path)}"
        for route in harness.app.routes
        if getattr(route, "methods", None) and (route.path.startswith("/v1") or route.path == "/healthz")
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    assert published - documented == set(), f"routes with no README row: {sorted(published - documented)}"
    assert documented - published == set(), f"README rows with no route: {sorted(documented - published)}"


def test_the_readme_names_exactly_the_published_chain_events() -> None:
    named = set(
        re.findall(
            r"`(attempt|served|failed|skipped_[a-z_]+|aborted_mid_stream|empty_answer|tool_executed|"
            r"tool_approval_requested|tool_denied|checkpoint_created|usage_estimated|"
            r"images_attached|images_dropped)`",
            readme(),
        )
    )
    assert named == set(CHAIN_EVENTS), f"missing: {set(CHAIN_EVENTS) - named}; invented: {named - set(CHAIN_EVENTS)}"


def test_every_cli_verb_is_documented() -> None:
    text = readme()
    missing = [verb for verb in _leaf_verbs() if f"kira-engine {verb}" not in text]
    assert missing == [], f"verbs with no README entry: {missing}"


def test_every_tunable_field_is_documented() -> None:
    text = readme()
    missing = [key for key in TUNABLE_FIELDS if f"`{key}`" not in text]
    assert missing == [], f"tunable settings with no README entry: {missing}"


def test_the_readme_documents_the_harness_contract() -> None:
    """The tools section is the only place a user learns what the harness will and
    will not do; each of these is a promise the engine's tests already hold it to."""
    text = readme()
    for policy in POLICIES:
        assert f"`{policy}`" in text, f"policy {policy!r} is not documented"
    for cap in (MAX_READ_BYTES, MAX_WRITE_BYTES, MAX_OUTPUT_BYTES):
        assert f"{cap // 1024} KB" in text, f"cap {cap} bytes is not documented"
    assert "data_dir/workspace" in text, "the workspace default is not documented"
    assert "not checkpointed" in text, "run_command's missing undo is not documented"
    assert "secret_ref" in text, "how a plugin finds its secret is not documented"
