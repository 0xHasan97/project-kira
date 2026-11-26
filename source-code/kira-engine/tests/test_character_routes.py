"""The character library over the wire: the same gates as the rest of Kira, the same loopback door.

Three things here are worth the tests they cost.

**The gate splits the way the key routes do.** A read takes the bearer token — a phone that paired with the
desktop is allowed to show the avatar, and showing it means listing it. Adding and choosing are owner-only
and ask for no confirm secret, because the caller is supplying something from their own disk, not
destroying anything. Deleting is owner *and* confirm, like every other delete. A device token that can do
any of the last three is the bug this file looks for.

**The refusals are the importer's refusals.** The route does not re-decide what a bad archive is; it lets
`characters.py` refuse and answers with the status that code means — 409 for a duplicate, 413 for a bomb,
404 for an id the library does not have. A route that softened those would hand the dashboard a different
answer than the CLI gave for the same bytes.

**The file route is the only place a path from a browser reaches this disk.** It is checked against every
shape that has made a static server leak `/etc/passwd`: dot-dot, the URL-encoded one, an absolute path, a
NUL, and a symlink planted inside the character folder that points out of it.
"""

from __future__ import annotations

import io
import os
import zipfile

import pytest
from sample_pmx import write_pmx

from kira.characters import import_character, list_characters, set_active

BODY = dict(
    vertex_count=26_798, face_index_count=1_020, texture_count=2, material_count=1, bone_count=297,
    morph_count=2, frame_count=2, rigid_body_count=2, constraint_count=2,
)
PNG = b"\x89PNG\r\n\x1a\n" + b"pixel"

PREFIX = "/v1/kira/characters"


def ellen_bytes() -> bytes:
    buffer = io.BytesIO()
    # `writestr` stamps each entry with the wall clock at DOS's 2-second resolution, so two calls a tick
    # apart produce different bytes — and the dedupe test below asks for "the same bytes" twice. Pinning
    # the timestamp is what makes this fixture mean what its name says; without it the second import is
    # genuinely a different archive and 201 is the correct answer.
    _STAMP = (2026, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(buffer, "w") as out:
        out.writestr(zipfile.ZipInfo("Ellen.pmx", _STAMP), write_pmx(
            **BODY, name="艾莲", name_en="Ellen", textures=("tex/颜.png", "hair.bmp")
        ))
        out.writestr(zipfile.ZipInfo("tex/颜.png", _STAMP), PNG)
        out.writestr(zipfile.ZipInfo("hair.bmp", _STAMP), b"BM" + b"0" * 8)
    return buffer.getvalue()


def slip_bytes(name: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        out.writestr("model.pmx", write_pmx(**BODY))
        out.writestr(name, b"x")
    return buffer.getvalue()


def written(tmp_path, *, name: str = "ellen.zip", data: bytes | None = None) -> str:
    """Put a source file where the engine can read it, and hand back the path a caller would send."""
    path = tmp_path / name
    path.write_bytes(data if data is not None else ellen_bytes())
    return str(path)


async def imported(harness, tmp_path) -> dict:
    answer = await harness.api.post(PREFIX, headers=harness.auth, json={"path": written(tmp_path)})
    assert answer.status_code == 201, answer.text
    return answer.json()


async def device(harness) -> dict:
    code = (await harness.api.post("/v1/kira/pairing-code", headers=harness.signed)).json()["code"]
    pair = await harness.api.post("/v1/kira/pair", json={"code": code, "name": "phone"})
    return {"Authorization": f"Bearer {pair.json()['token']}"}


# --- the gate -----------------------------------------------------------------------------------------

async def test_the_library_lists_empty_before_anything_is_added(harness):
    answer = await harness.api.get(PREFIX, headers=harness.auth)
    assert answer.status_code == 200
    assert answer.json() == {"characters": [], "active": None}


async def test_a_read_needs_the_bearer_token(harness):
    assert (await harness.api.get(PREFIX)).status_code == 401
    assert (await harness.api.get(PREFIX, headers={"Authorization": "Bearer nope"})).status_code == 401


async def test_a_paired_device_can_list_but_cannot_add_choose_or_delete(harness, tmp_path):
    device_auth = await device(harness)
    assert (await harness.api.get(PREFIX, headers=device_auth)).status_code == 200
    row = await imported(harness, tmp_path)
    for call in (
        harness.api.post(PREFIX, headers=device_auth, json={"path": written(tmp_path, name="second.zip")}),
        harness.api.put(f"{PREFIX}/active", headers=device_auth, json={"id": row["id"]}),
        harness.api.delete(f"{PREFIX}/{row['id']}", headers=device_auth),
    ):
        assert (await call).status_code == 401


async def test_a_delete_needs_the_confirm_secret_on_top_of_the_owner(harness, tmp_path):
    row = await imported(harness, tmp_path)
    #: The bearer token alone says who is asking; it does not say a human typed the secret.
    assert (await harness.api.delete(f"{PREFIX}/{row['id']}", headers=harness.auth)).status_code == 401
    assert (await harness.api.delete(f"{PREFIX}/{row['id']}", headers=harness.signed)).status_code == 200
    assert (await harness.api.get(f"{PREFIX}/{row['id']}", headers=harness.auth)).status_code == 404


async def test_an_import_is_owner_only_and_asks_for_no_secret(harness, tmp_path):
    """The settled key-route shape: supplying a file is not destroying one."""
    answer = await harness.api.post(PREFIX, headers=harness.auth, json={"path": written(tmp_path)})
    assert answer.status_code == 201
    assert answer.json()["display_name"] == "艾莲"


# --- import -------------------------------------------------------------------------------------------

async def test_an_import_lands_in_the_directory_the_engine_reads_and_reads_back(harness, tmp_path):
    row = await imported(harness, tmp_path)
    directory = harness.config.characters_dir / row["id"]
    assert (directory / "model.pmx").is_file()
    assert (directory / "profile.json").is_file()

    listing = (await harness.api.get(PREFIX, headers=harness.auth)).json()
    assert [item["id"] for item in listing["characters"]] == [row["id"]]

    profile = (await harness.api.get(f"{PREFIX}/{row['id']}", headers=harness.auth)).json()
    assert profile["main"]["vertices"] == 26_798
    assert profile["main"]["texture_status"] == "2/2"


async def test_the_same_bytes_twice_answer_409_and_name_the_character_already_here(harness, tmp_path):
    row = await imported(harness, tmp_path)
    answer = await harness.api.post(
        PREFIX, headers=harness.auth, json={"path": written(tmp_path, name="again.zip")}
    )
    assert answer.status_code == 409
    error = answer.json()["error"]
    assert error["code"] == "already_imported" and row["id"] in error["message"]
    assert len(list_characters(harness.config.characters_dir)) == 1


async def test_a_source_that_is_not_a_model_file_is_refused_before_anything_is_written(harness, tmp_path):
    answer = await harness.api.post(PREFIX, headers=harness.auth, json={"path": written(tmp_path, name="notes.txt", data=b"not a model")})
    assert answer.status_code == 400
    assert answer.json()["error"]["code"] == "unsupported_source"
    assert list_characters(harness.config.characters_dir) == ()
    #: Nothing was staged either: the refusal happens before a directory is opened, let alone written to.
    assert not harness.config.characters_dir.exists() or not [
        p for p in harness.config.characters_dir.iterdir() if p.name.startswith(".staging")
    ]


async def test_a_path_that_is_not_there_is_a_refusal_not_a_traceback(harness, tmp_path):
    answer = await harness.api.post(
        PREFIX, headers=harness.auth, json={"path": str(tmp_path / "gone.zip")}
    )
    assert answer.status_code == 400
    assert answer.json()["error"]["code"] == "unsupported_source"


async def test_an_archive_that_trips_the_entry_cap_answers_413_and_leaves_no_character(harness, tmp_path):
    from kira.characters import MAX_ENTRIES

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        out.writestr("model.pmx", write_pmx(**BODY))
        for index in range(MAX_ENTRIES + 1):
            out.writestr(f"e{index}.txt", b"x")
    answer = await harness.api.post(
        PREFIX, headers=harness.auth, json={"path": written(tmp_path, name="bomb.zip", data=buffer.getvalue())}
    )
    assert answer.status_code == 413
    assert answer.json()["error"]["code"] == "too_large"
    assert (await harness.api.get(PREFIX, headers=harness.auth)).json()["characters"] == []


async def test_an_entry_that_climbs_out_answers_400_and_names_the_entry(harness, tmp_path):
    answer = await harness.api.post(
        PREFIX, headers=harness.auth, json={"path": written(tmp_path, name="slip.zip", data=slip_bytes("../escaped.png"))}
    )
    assert answer.status_code == 400
    error = answer.json()["error"]
    assert error["code"] == "unsafe_entry" and error["entry"] == "../escaped.png"


async def test_an_archive_with_no_model_in_it_answers_400(harness, tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        out.writestr("readme.txt", b"no model in here")
    answer = await harness.api.post(
        PREFIX, headers=harness.auth, json={"path": written(tmp_path, name="docs.zip", data=buffer.getvalue())}
    )
    assert answer.status_code == 400
    assert answer.json()["error"]["code"] == "no_pmx_in_archive"


async def test_an_entry_named_profile_json_is_refused_at_any_depth(harness, tmp_path):
    """The importer writes `profile.json`; an archive must not be able to write one too.

    Only the *top-level* profile is rewritten after unpacking, so a nested `<dir>/profile.json` used
    to survive into the installed character and was then served back by the file route as if the
    library had written it — attacker-chosen JSON wearing a trusted filename.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        out.writestr("model.pmx", write_pmx(**BODY))
        out.writestr("evil-deadbeef/profile.json", b'{"schema": 1, "id": "pwned"}')
    answer = await harness.api.post(
        PREFIX, headers=harness.auth, json={"path": written(tmp_path, name="inject.zip", data=buffer.getvalue())}
    )
    assert answer.status_code == 400, answer.text
    error = answer.json()["error"]
    assert error["code"] == "unsafe_entry" and error["entry"] == "evil-deadbeef/profile.json"
    assert (await harness.api.get(PREFIX, headers=harness.auth)).json()["characters"] == []


async def test_an_entry_whose_compression_method_this_build_cannot_read_is_a_400(harness, tmp_path):
    """A zip whose header names a method Python cannot decode must answer `bad_archive`, not 500.

    `zipfile` does not confine itself to `BadZipFile`: an unsupported method raises `NotImplementedError`
    and an encrypted entry raises `RuntimeError`. Both used to escape the importer, which turned a
    truncated or re-compressed download into an unhandled 500 — the one status the contract does not
    document for this route.
    """
    import struct

    good = bytearray(ellen_bytes())

    def rename_method(signature: bytes, offset: int) -> None:
        at = good.find(signature)
        struct.pack_into("<H", good, at + offset, 99)  # 99: no method any Python build implements

    rename_method(b"PK\x03\x04", 8)  # local file header
    rename_method(b"PK\x01\x02", 10)  # central directory
    answer = await harness.api.post(
        PREFIX, headers=harness.auth, json={"path": written(tmp_path, name="odd-method.zip", data=bytes(good))}
    )
    assert answer.status_code == 400, answer.text
    assert answer.json()["error"]["code"] == "bad_archive"
    assert (await harness.api.get(PREFIX, headers=harness.auth)).json()["characters"] == []


async def test_a_body_that_is_not_the_one_object_asked_for_is_a_400_that_names_the_field(harness):
    answer = await harness.api.post(PREFIX, headers=harness.auth, json={"nope": "x"})
    assert answer.status_code == 400
    assert "path" in answer.json()["error"]["message"]


# --- the pick ------------------------------------------------------------------------------------------

async def test_the_active_pick_reads_back_in_the_list(harness, tmp_path):
    row = await imported(harness, tmp_path)
    assert (await harness.api.get(PREFIX, headers=harness.auth)).json()["active"] is None
    assert (await harness.api.put(f"{PREFIX}/active", headers=harness.auth, json={"id": row["id"]})).status_code == 200
    assert (await harness.api.get(PREFIX, headers=harness.auth)).json()["active"] == row["id"]
    assert (await harness.api.put(f"{PREFIX}/active", headers=harness.auth, json={"id": None})).status_code == 200
    assert (await harness.api.get(PREFIX, headers=harness.auth)).json()["active"] is None


async def test_choosing_a_character_the_library_does_not_have_is_refused_and_leaves_the_pick(harness, tmp_path):
    row = await imported(harness, tmp_path)
    await harness.api.put(f"{PREFIX}/active", headers=harness.auth, json={"id": row["id"]})
    answer = await harness.api.put(f"{PREFIX}/active", headers=harness.auth, json={"id": "nobody-00000000"})
    assert answer.status_code == 404
    assert answer.json()["error"]["code"] == "character_not_found"
    assert (await harness.api.get(PREFIX, headers=harness.auth)).json()["active"] == row["id"]


@pytest.mark.parametrize("body", [{}, {"id": 7}, {"id": ["ellen"]}, {"id": "x", "extra": 1}, {"path": "x"}])
async def test_the_pick_takes_a_string_id_or_a_null_and_nothing_else(harness, body):
    answer = await harness.api.put(f"{PREFIX}/active", headers=harness.auth, json=body)
    assert answer.status_code == 400


async def test_a_pick_whose_id_could_never_be_a_folder_is_a_not_found(harness):
    """`../etc` is a well-shaped string, so the body gate lets it through and the library answers.

    Splitting a shape refusal (400) from a membership refusal (404) keeps the same line the CLI draws:
    `characters use ../etc` reports a character that is not here, not a body the user typed wrong.
    """
    answer = await harness.api.put(f"{PREFIX}/active", headers=harness.auth, json={"id": "../etc"})
    assert answer.status_code == 404
    assert answer.json()["error"]["code"] == "character_not_found"


async def test_deleting_the_character_on_stage_takes_it_off_in_the_same_call(harness, tmp_path):
    row = await imported(harness, tmp_path)
    await harness.api.put(f"{PREFIX}/active", headers=harness.auth, json={"id": row["id"]})
    assert (await harness.api.delete(f"{PREFIX}/{row['id']}", headers=harness.signed)).status_code == 200
    #: The stale pointer is the failure this proves absent: a list whose `active` names a folder that is
    #: gone is a screen that cannot open, and the client has no way to ask it nicely.
    assert (await harness.api.get(PREFIX, headers=harness.auth)).json() == {"characters": [], "active": None}


# --- the file route ------------------------------------------------------------------------------------

async def test_the_model_its_textures_and_its_profile_are_served_with_their_media_types(harness, tmp_path):
    row = await imported(harness, tmp_path)

    def ask(path: str):
        return harness.api.get(f"{PREFIX}/{row['id']}/file", headers=harness.auth, params={"path": path})

    model = await ask("model.pmx")
    assert model.status_code == 200 and model.content.startswith(b"PMX ")
    assert model.headers["content-type"].startswith("application/octet-stream")

    texture = await ask("tex/颜.png")
    assert texture.status_code == 200 and texture.content == PNG
    assert texture.headers["content-type"].startswith("image/png")

    profile = await ask("profile.json")
    assert profile.status_code == 200 and profile.json()["id"] == row["id"]


async def test_a_file_needs_the_same_token_as_the_rest(harness, tmp_path):
    row = await imported(harness, tmp_path)
    assert (await harness.api.get(f"{PREFIX}/{row['id']}/file", params={"path": "model.pmx"})).status_code == 401


@pytest.mark.parametrize(
    "path",
    [
        "../profile.json", "..%2Fprofile.json", "%2e%2e/profile.json", "..\\secrets.txt",
        "/etc/passwd", "C:/Windows/win.ini", "tex/../../outside.txt", "model.pmx\x00.txt", "",
    ],
)
async def test_every_shape_that_tries_to_leave_the_character_folder_is_refused(harness, tmp_path, path):
    row = await imported(harness, tmp_path)
    (tmp_path / "outside.txt").write_text("not for the stage", encoding="utf-8")
    answer = await harness.api.get(
        f"{PREFIX}/{row['id']}/file", headers=harness.auth, params={"path": path}
    )
    assert answer.status_code == 400, f"{path!r} answered {answer.status_code}: {answer.text[:120]}"
    assert answer.json()["error"]["code"] == "unsafe_entry"


async def test_a_dot_that_cancels_itself_inside_the_folder_still_serves_the_file(harness, tmp_path):
    """`./tex//颜.png` and `tex/../tex/颜.png` stay home, so they are not refusals.

    A check on the text alone would answer 400 to a path the stage can legitimately ask for, and a loader
    that normalises before it asks — which is what a real path joiner does — would fail for no reason a
    user could name. The refusal is about where the path lands, not about what characters it contains.
    """
    row = await imported(harness, tmp_path)
    for path in ("./tex/颜.png", "tex/../tex/颜.png", "tex//颜.png", "./profile.json"):
        answer = await harness.api.get(
            f"{PREFIX}/{row['id']}/file", headers=harness.auth, params={"path": path}
        )
        assert answer.status_code == 200, f"{path!r} answered {answer.status_code}: {answer.text[:120]}"


async def test_a_symlink_planted_inside_the_folder_that_points_out_of_it_is_refused(harness, tmp_path):
    row = await imported(harness, tmp_path)
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"not yours")
    link = harness.config.characters_dir / row["id"] / "link.png"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):
        pytest.skip("this machine will not let a test make a symlink")
    answer = await harness.api.get(
        f"{PREFIX}/{row['id']}/file", headers=harness.auth, params={"path": "link.png"}
    )
    assert answer.status_code == 400
    assert answer.json()["error"]["code"] == "unsafe_entry"


async def test_a_file_the_character_does_not_have_is_404(harness, tmp_path):
    row = await imported(harness, tmp_path)
    answer = await harness.api.get(
        f"{PREFIX}/{row['id']}/file", headers=harness.auth, params={"path": "tex/gone.png"}
    )
    assert answer.status_code == 404
    assert answer.json()["error"]["code"] == "character_file_not_found"


async def test_an_extension_the_stage_cannot_load_is_refused_before_the_disk_is_touched(harness, tmp_path):
    row = await imported(harness, tmp_path)
    answer = await harness.api.get(
        f"{PREFIX}/{row['id']}/file", headers=harness.auth, params={"path": "usage-rule.html"}
    )
    assert answer.status_code == 400
    assert answer.json()["error"]["code"] == "unsupported_source"


async def test_a_file_of_a_character_that_is_not_in_the_library_is_404(harness):
    answer = await harness.api.get(
        f"{PREFIX}/nobody-00000000/file", headers=harness.auth, params={"path": "model.pmx"}
    )
    assert answer.status_code == 404
    assert answer.json()["error"]["code"] == "character_not_found"


# --- one library, whoever wrote to it --------------------------------------------------------------------

async def test_the_routes_read_the_library_the_cli_writes(harness, tmp_path):
    """`characters_dir` is derived from the data dir, so the terminal and the engine open the same folder.

    This is the seam between the unit's two halves: bytes the CLI put there have to be listable, choosable
    and drawable from the wire with no second import and no restart.
    """
    directory = harness.config.characters_dir
    entry = import_character(directory, ellen_bytes(), source_name="ellen.zip")
    assert [row["id"] for row in list_characters(directory)] == [entry.id]
    assert (await harness.api.get(PREFIX, headers=harness.auth)).json()["characters"][0]["id"] == entry.id

    set_active(directory, entry.id, harness.store)
    assert (await harness.api.get(PREFIX, headers=harness.auth)).json()["active"] == entry.id

    chosen = await harness.api.get(f"{PREFIX}/{entry.id}", headers=harness.auth)
    assert chosen.json()["source"]["file_name"] == "ellen.zip"
