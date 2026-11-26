import { useRef, useState } from "react";
import type { KiraClient } from "../api.ts";
import type { CharacterCapability, CharacterList, CharacterProfile, CharacterRow } from "../contracts.ts";
import { AvatarStage } from "../avatar/AvatarStage.tsx";
import { useAsync } from "../useAsync.ts";
import { useWrite } from "../useWrite.ts";

const EMPTY: CharacterList = { characters: [], active: null };

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** A 45 MB archive and a 4 KB texture belong in the same column, so the unit comes from the magnitude. */
function bytes(count: number): string {
  if (count < 1024) return `${count} B`;
  if (count < 1024 * 1024) return `${(count / 1024).toFixed(0)} KB`;
  return `${(count / (1024 * 1024)).toFixed(1)} MB`;
}

const num = (value: number) => value.toLocaleString("en-GB");

export function AvatarScreen({
  client,
  connected,
  pull = 0,
}: {
  client: KiraClient;
  connected: boolean;
  pull?: number;
}) {
  const library = useAsync(() => (connected ? client.characters() : Promise.resolve(EMPTY)), [connected, pull]);
  const [selected, setSelected] = useState<string | null>(null);
  const [importPath, setImportPath] = useState("");
  // The list is a folder name and a measurement; the profile is the walk itself — the texture table, the
  // morph names a mouth needs, and the findings the importer refused to hide.
  const detail = useAsync(
    () => (connected && selected ? client.character(selected) : Promise.resolve(null)),
    [connected, selected, pull],
  );
  const { busy, note, run, quick } = useWrite(() => {
    library.refresh();
    detail.refresh();
  });

  function putOnStage(row: CharacterRow) {
    // No confirm secret: the engine gates this on the bearer token alone, because a pick destroys
    // nothing and the next request can replace it.
    void quick(() => client.setActiveCharacter(row.id));
  }

  function takeOffStage() {
    void quick(() => client.setActiveCharacter(null));
  }

  function remove(row: CharacterRow) {
    void run(
      `remove ${row.display_name} from the library`,
      "its folder goes, and its pick with it — the only way back is the path it was imported from",
      true,
      (secret) => client.removeCharacter(row.id, secret),
    );
  }

  async function importFromPath() {
    const path = importPath.trim();
    if (!path) return;
    const imported = await quick(() =>
      client.importCharacter(path).then((row) => {
        setSelected(row.id);
        return row;
      }),
    );
    if (imported) setImportPath("");
  }

  const activeRow = library.kind === "ready" ? library.data.characters.find((row) => row.id === library.data.active) : undefined;

  // The stage needs the walk rather than the row: the mesh route is keyed by id and the textures by the
  // paths the profile names. When the body on stage is the one the reader already opened, that read is
  // borrowed instead of asked for twice.
  const activeId = library.kind === "ready" ? library.data.active : null;
  const opened = detail.kind === "ready" && detail.data && selected === activeId ? detail.data : null;
  const walked = useAsync(
    () => (connected && activeId && activeId !== selected ? client.character(activeId) : Promise.resolve(null)),
    [connected, activeId, selected, pull],
  );
  const onStage = opened ?? walked.data;
  // This pane has no audio to measure; the meter it hands the stage sits at silence, and the call screen
  // passes its own live one in its place.
  const silence = useRef(0);

  return (
    <section className="screen avatar-screen" aria-label="avatar">
      <h2>Avatar</h2>
      {note && (
        <p className="error" role="alert">
          {note}
        </p>
      )}

      <div className="avatar-body">
        <div className="avatar-library">
          <form
            className="import-row"
            onSubmit={(event) => {
              event.preventDefault();
              void importFromPath();
            }}
          >
            <label className="grow">
              a .pmx or .zip already on this machine
              <input
                name="character_path"
                value={importPath}
                onChange={(event) => setImportPath(event.target.value)}
                placeholder="D:\\models\\ellen.zip"
                spellCheck={false}
                autoComplete="off"
              />
            </label>
            <button type="submit" disabled={busy || importPath.trim() === ""}>
              import
            </button>
          </form>

          {library.kind === "loading" ? <p className="muted">reading the library…</p> : null}
          {library.kind === "error" ? (
            <p className="error" role="alert">
              cannot read the library: {messageOf(library.error)}
            </p>
          ) : null}

          {library.kind === "ready" && (
            <table className="grid">
              <thead>
                <tr>
                  <th>character</th>
                  <th>body</th>
                  <th>textures</th>
                  <th>stage</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {library.data.characters.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <div className="mono">{row.display_name}</div>
                      <div className="muted small">
                        {row.english_name} · {row.source_file_name}
                      </div>
                      <div className="muted mono small">{row.id}</div>
                      {row.license_note && <div className="muted small">licence: {row.license_note}</div>}
                    </td>
                    <td>
                      {row.is_character ? (
                        <>
                          <div className="mono">{num(row.vertices)} vertices</div>
                          <div className="muted small">
                            {row.bones} bones · {row.has_physics ? "physics" : "no physics"} ·{" "}
                            {row.companion_count} prop{row.companion_count === 1 ? "" : "s"}
                          </div>
                        </>
                      ) : (
                        <>
                          <div className="muted">props only</div>
                          <div className="muted small">{row.reason}</div>
                        </>
                      )}
                    </td>
                    <td className="mono small">{row.texture_status ?? "no textures"}</td>
                    <td>
                      {row.id === library.data.active ? (
                        <span className="badge badge-ok">on stage</span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      <div className="row-actions">
                        {row.is_character ? (
                          <button
                            type="button"
                            disabled={busy || row.id === library.data.active}
                            onClick={() => putOnStage(row)}
                          >
                            {`use ${row.display_name}`}
                          </button>
                        ) : (
                          // A dead button explains nothing; this row says why it has no stage at all.
                          <span className="muted small">no body to stage</span>
                        )}
                        <button
                          type="button"
                          aria-expanded={selected === row.id}
                          onClick={() => setSelected(selected === row.id ? null : row.id)}
                        >
                          {selected === row.id ? `hide ${row.display_name}` : `measure ${row.display_name}`}
                        </button>
                        <button type="button" disabled={busy} onClick={() => remove(row)}>
                          {`remove ${row.display_name}`}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {library.data.characters.length === 0 && (
                  <tr>
                    <td colSpan={5} className="empty">
                      no character in the library. Kira ships no model and never will — what goes here is a
                      .pmx or .zip you are licensed to install, typed into the path above, and its licence
                      stays yours to obey.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}

          {selected && detail.kind === "loading" ? <p className="muted">walking that folder…</p> : null}
          {selected && detail.kind === "error" ? (
            <p className="error" role="alert">
              cannot read {selected}: {messageOf(detail.error)}
            </p>
          ) : null}
          {selected && detail.kind === "ready" && detail.data && <Walk profile={detail.data} />}

          {activeRow ? (
            <p className="muted small">
              This is the same body the call speaks with, drawn with the mesh the engine read out of the
              archive and the textures that came with it. The mood on the stage is your pick, not a guess:
              nothing in the chain says how Kira feels about what it just heard, so a face classified by a
              model would be a claim this app cannot prove.
            </p>
          ) : null}
        </div>

        <aside className="stage-pane" aria-label="the stage">
          <h3>the stage</h3>
          {activeRow ? (
            <>
              <p className="mono">{`${activeRow.display_name} · ${activeRow.english_name}`}</p>
              <p className="muted small">
                {num(activeRow.vertices)} vertices · {activeRow.bones} bones ·{" "}
                {activeRow.texture_status ?? "no textures"}
              </p>
              {/* The pane scrolls when its findings list is long, and the 2026-11-02 pass found the only
                  control in it — this button — below that fold. The control comes first now; the drawing
                  and its notes are what may run past the edge. */}
              <button type="button" disabled={busy} onClick={takeOffStage}>
                take everyone off
              </button>
              {onStage ? (
                <AvatarStage source={client} profile={onStage} playbackLevel={silence} />
              ) : (
                <p className="muted small">walking that body so it can stand here…</p>
              )}
            </>
          ) : (
            <p className="empty">Kira has no face yet — nothing is on stage.</p>
          )}
        </aside>
      </div>

      <p className="muted small">
        Importing reads a file from this machine and copies it into Kira's own character folder; nothing here
        reaches out to a website, and a paired phone never sees this screen's writes. A texture that did not
        ship with its model is named rather than replaced — a missing picture is a fact about the archive, not
        a bug to paint over.
      </p>
    </section>
  );
}

function Walk({ profile }: { profile: CharacterProfile }) {
  const body = profile.main;
  return (
    <div className="walk">
      <h3>
        {profile.display_name} — {profile.source.file_name}
      </h3>
      <p className="muted small">
        {bytes(profile.source.bytes)} {profile.source.archive ? "archive" : "bare .pmx"} · imported{" "}
        {profile.imported_at} · {profile.reason}
      </p>
      {profile.license_note && <p className="muted small">licence: {profile.license_note}</p>}

      {body === null ? (
        <p className="empty">
          {/* One string, not a sentence made of expressions: a JSXText line that starts after `{…}`
              loses its leading space, and the UI would print "modelin it". */}
          {`this archive has no body — the ${profile.companions.length} model${
            profile.companions.length === 1 ? "" : "s"
          } in it ${profile.companions.length === 1 ? "is" : "are"} props, so there is nothing to stage.`}
        </p>
      ) : (
        <Capability body={body} />
      )}

      {profile.companions.length > 0 && (
        <p className="muted small">
          carried alongside: {profile.companions.map((each) => `${each.name} (${each.path})`).join(", ")}
        </p>
      )}

      <h3>files</h3>
      <ul className="work-list">
        {profile.files.map((file) => (
          <li key={file.path}>
            <span className="mono">{file.path}</span> — {bytes(file.bytes)}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Every number the walk earned, and the two readings a stage actually stalls on: textures and morphs. */
function Capability({ body }: { body: CharacterCapability }) {
  return (
    <div className="capability">
      <div className="stats">
        <div>
          <div className="mono">{num(body.vertices)}</div>
          <div className="muted small">vertices</div>
        </div>
        <div>
          <div className="mono">{num(body.triangles)}</div>
          <div className="muted small">triangles</div>
        </div>
        <div>
          <div className="mono">{num(body.bones)}</div>
          <div className="muted small">bones</div>
        </div>
        <div>
          <div className="mono">{num(body.counts.material_count ?? 0)}</div>
          <div className="muted small">materials</div>
        </div>
        <div>
          <div className="mono">{num(body.counts.morph_count ?? 0)}</div>
          <div className="muted small">morphs</div>
        </div>
        <div>
          <div className="mono">{body.texture_status}</div>
          <div className="muted small">textures</div>
        </div>
      </div>

      <p className="muted small">
        PMX {body.version} · {body.count_framing} counts · {body.material_framing} materials ·{" "}
        {body.has_physics ? "physics" : "no physics"} · {body.finger_bone_count} finger bones ·{" "}
        {body.ik_bone_count} IK
      </p>

      {body.missing_textures.length > 0 && (
        <p className="error">
          {body.missing_textures.length} texture{body.missing_textures.length === 1 ? "" : "s"} the model names
          and the archive never carried:{" "}
          <span className="mono">{body.missing_textures.join(", ")}</span>
        </p>
      )}

      <h3>textures</h3>
      <table className="grid">
        <thead>
          <tr>
            <th>path in the folder</th>
            <th>declared as</th>
            <th>readable as</th>
            <th>size</th>
          </tr>
        </thead>
        <tbody>
          {body.textures.map((texture) => (
            <tr key={texture.relative}>
              <td className={texture.exists ? "mono" : "mono badge-none"}>{texture.relative}</td>
              <td className="muted mono small">{texture.declared}</td>
              <td>{texture.escapes ? "leaves the folder" : texture.format || "no format"}</td>
              <td className="muted mono">{texture.size === null ? "—" : bytes(texture.size)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {body.morph_names.length > 0 && (
        <p className="muted small">
          morphs: <span className="mono">{body.morph_names.join(", ")}</span>
        </p>
      )}

      {body.findings.length > 0 && (
        <ul className="issues">
          {body.findings.map((finding) => (
            <li key={finding} className="muted small">
              {finding}
            </li>
          ))}
        </ul>
      )}

      {body.unreadable && <p className="error">the walk stopped: {body.unreadable}</p>}
    </div>
  );
}
