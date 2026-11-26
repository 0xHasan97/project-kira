/**
 * The `#/call` screen: the hook plus the engine's own answer about what it can do.
 *
 * `/v1/kira/voice` is read once on mount, before the socket opens. That order matters — a call should
 * say "piper is not installed" while there is still nothing to cancel, not after the user has been
 * talking into a dead microphone.
 *
 * The face arrives the same way: read once, and only put a body on the call if the library has one on
 * stage. A failed read is the same as an empty library — the voice does not stop working because the
 * avatar route had a bad afternoon — and there is nothing to retry, because #/avatar is where a body is
 * chosen and the user comes back through here after choosing it.
 */
import { useEffect, useState } from "react";
import type { KiraClient } from "../api.ts";
import type { CharacterProfile, Mode, VoiceStatus } from "../contracts.ts";
import { useCall } from "../voice/useCall.ts";
import { AvatarStage } from "../avatar/AvatarStage.tsx";
import { CallView } from "./CallView.tsx";

export function CallScreen({
  client,
  token,
  model,
  mode,
}: {
  client: KiraClient;
  token: string;
  model: string;
  mode: Mode;
}) {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [face, setFace] = useState<CharacterProfile | null>(null);
  const call = useCall({ baseUrl: client.baseUrl, token, model, mode });

  useEffect(() => {
    client.voice().then(setStatus).catch(() => setStatus(null));
  }, [client]);

  useEffect(() => {
    let current = true;
    client
      .characters()
      .then((library) => (library.active ? client.character(library.active) : null))
      .then((profile) => {
        if (current) setFace(profile);
      })
      .catch(() => {
        if (current) setFace(null);
      });
    return () => {
      current = false;
    };
  }, [client]);

  return (
    <CallView
      call={call}
      status={status ?? call.voice}
      stage={face && <AvatarStage source={client} profile={face} playbackLevel={call.playbackLevel} />}
    />
  );
}
