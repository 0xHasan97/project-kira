import type { ChainEvent, ChunkType, Mode } from "./contract.ts";

export type Role = "system" | "user" | "assistant" | "tool";
export type Tier = "fast" | "powerful";
export type ProviderKind = "openai_compat" | "anthropic" | "gemini";
export type TurnStatus = "complete" | "max_steps" | "interrupted" | "failed";

export interface Message {
  role: Role;
  content?: string | null;
  tool_calls?: Record<string, unknown>[] | null;
  tool_call_id?: string | null;
  name?: string | null;
}

export interface ChatRequest {
  model?: string | null;
  messages: Message[];
  stream?: boolean;
  temperature?: number;
  max_tokens?: number | null;
  mode?: Mode;
  provider?: string | null;
  session_id?: string | null;
  tools_enabled?: boolean;
  /** A persona skill name. A method skill is loaded by the model through `use_skill` instead. */
  skill?: string | null;
}

/** One routing decision. The engine never fails over without leaving one of these behind. */
export interface ChainRecord {
  provider?: string;
  model?: string;
  event: ChainEvent;
  reason?: string;
  /** skipped_cooling */
  retry_in_s?: number;
  /** failed */
  cooldown_s?: number;
  /** tool_executed, tool_denied, tool_approval_requested */
  tool?: string;
  call_id?: string;
  ok?: boolean;
  chars?: number;
  risk?: ToolRisk;
  /** tool_executed only */
  summary?: string;
  /** tool_executed for run_command */
  duration_ms?: number;
  exit_code?: number;
  kind?: "command" | "test";
  /** checkpoint_created, tool_executed */
  checkpoint_id?: string;
  /** tool_approval_requested only */
  approval_id?: string;
  /** checkpoint_created only */
  files?: number;
}

export interface WireUsage {
  prompt_tokens: number;
  completion_tokens: number;
  /** true when the provider sent no usage and the engine estimated it. */
  estimated?: boolean;
}

export type ToolRisk = "read" | "write" | "exec" | "network";
export type ToolPolicy = "allow" | "ask" | "deny";

export interface StoredUsage {
  input_tokens: number;
  output_tokens: number;
}

export interface ToolCallWire {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface ChatCompletionChoice {
  index: number;
  message: { role: string; content: string; tool_calls: ToolCallWire[] };
  finish_reason: string;
}

export interface ChatCompletion {
  id: string;
  object: "chat.completion";
  created: number;
  model: string | null;
  provider: string | null;
  session_id: string;
  message_id: number;
  choices: ChatCompletionChoice[];
  usage: WireUsage;
  status: TurnStatus;
  provider_chain: ChainRecord[];
}

export interface ErrorBody {
  code: string;
  message: string;
  provider?: string;
  status: number;
  retryable: boolean;
  /** what a character refusal is about, when it has a name: the archive entry that escaped, the missing id, the path supplied */
  entry?: string;
  provider_chain?: ChainRecord[];
}

export class KiraApiError extends Error {
  constructor(readonly body: ErrorBody, readonly httpStatus: number) {
    super(`${body.code}: ${body.message}`);
    this.name = "KiraApiError";
  }

  get chain(): ChainRecord[] {
    return this.body.provider_chain ?? [];
  }
}

type ChunkBase = { type: ChunkType; provider_chain?: ChainRecord[] };

export type ChatChunk =
  | (ChunkBase & { type: "delta"; text: string })
  | (ChunkBase & { type: "tool_call"; id: string; name: string; arguments: Record<string, unknown> })
  | (ChunkBase & { type: "chain"; record: ChainRecord })
  | (ChunkBase & {
      type: "approval";
      id: string;
      tool: string;
      risk: ToolRisk;
      arguments: Record<string, unknown>;
    })
  | (ChunkBase & {
      type: "done";
      id: string;
      session_id: string;
      provider: string | null;
      model: string | null;
      finish_reason: string;
      status: TurnStatus;
      usage: WireUsage;
    })
  | (ChunkBase & { type: "error"; error: ErrorBody });

export interface ImageModel {
  name: string;
  filename: string;
  size_bytes: number;
  kind: string;
}

export interface ImageOutput {
  name: string;
  /** The authenticated path the PNG bytes are fetched from. */
  url: string;
  prompt: string;
  negative_prompt: string;
  model: string;
  steps: number;
  cfg_scale: number;
  width: number;
  height: number;
  seed: number;
  sampler: string;
  created_at: string;
  duration_ms: number;
  backend: string;
}

export interface ImagesStatus {
  ready: boolean;
  /** Why nothing can draw yet, in the words the screen shows. */
  reason: string | null;
  backend: "local" | "remote" | null;
  backend_path: string | null;
  remote_url: string | null;
  engine_dir: string;
  model_dir: string;
  output_dir: string;
  models: ImageModel[];
  outputs: ImageOutput[];
}

export interface ImageGenerateRequest {
  prompt: string;
  negative_prompt?: string;
  model?: string | null;
  steps?: number;
  cfg_scale?: number;
  width?: number;
  height?: number;
  /** -1 picks one, and the answer carries it. */
  seed?: number;
  sampler?: string;
}

export interface ImageDeleted {
  deleted: string;
}

export interface StudioModel {
  name: string;
  filename: string;
  size_bytes: number;
  kind: string;
}

export interface StudioPart {
  available: boolean;
  engine: string | null;
  detail: string;
  models: StudioModel[];
}

export interface StudioLlmPart {
  available: boolean;
  engine: string | null;
  detail: string;
  models: StudioModel[];
  running: boolean;
  model: string | null;
  url: string | null;
  model_dir: string;
  engine_dir: string;
  /** Why a start would refuse, in the screen's words. */
  reason: string | null;
}

export interface StudioStatus {
  /** The studio folder, or null when Kira is using its own folders only. */
  root: string | null;
  available: boolean;
  image: StudioPart;
  llm: StudioLlmPart;
  stt: StudioPart;
  tts: StudioPart;
}

/** The studio's Node server as Kira sees it: a child of ours, the user's own, or nothing yet. */
export interface StudioRuntime {
  found: boolean;
  running: boolean;
  managed: boolean;
  external: boolean;
  url: string | null;
  root: string | null;
  pid: number | null;
  error: string | null;
  health: { build: string | null; issues: string[] } | null;
}

/** One file the studio keeps: a transcript, a spoken WAV, a checkpoint. */
export interface StudioFile {
  filename: string;
  url: string;
  text?: string;
  displayName?: string;
  size?: string;
  sizeBytes?: number;
  createdAt?: string;
}

/** A row from the studio's own model folders, which is not the same shape as Kira's StudioModel. */
export interface StudioModelRow {
  filename: string;
  name?: string;
  id?: string;
  size?: string;
  sizeBytes?: number;
  installed?: boolean;
  recommended?: boolean;
  custom?: boolean;
  language?: string;
}

export interface StudioVoice {
  id: string;
  name: string;
  language: string;
  gender: string;
}

export interface StudioLlmRequest {
  model?: string | null;
}

export interface StudioDownloadRequest {
  kind: "llm" | "image" | "stt";
  url: string;
  filename?: string | null;
}

export interface StudioDownloadResult {
  name: string;
  filename: string;
  kind: string;
  bytes: number;
  path: string;
}

export interface ModelInfo {
  id: string;
  object: string;
  owned_by: string;
  provider: string;
  tier: Tier;
  /** False when that provider has no key in the vault: the row exists, but it may not answer. */
  key_present: boolean;
  /** False for a provider that asks for no credential at all, like a local server on loopback. */
  needs_key: boolean;
  /** The model's context window in tokens; null when the provider stanza does not declare it. */
  context_window: number | null;
}

export interface ModelsResponse {
  object: "list";
  data: ModelInfo[];
  live?: ProbeResponse[];
}

export interface ProviderState {
  failures: number;
  successes: number;
  cooling_s: number;
  last_reason: string | null;
}

export interface ConfiguredProvider {
  name: string;
  kind: ProviderKind;
  tier: Tier;
  priority: number;
  models: string[];
  key_present: boolean;
  needs_key: boolean;
}

export interface HealthResponse {
  providers: Record<string, ProviderState>;
  configured: ConfiguredProvider[];
}

export interface HealthzResponse {
  ok: true;
  api_version: number;
  contract_version: number;
  providers_configured: number;
  default_mode: Mode;
}

export type VoiceMode = "local" | "remote" | "off";

export interface VoiceStage {
  mode: VoiceMode;
  available: boolean;
  /** The missing install or provider problem, verbatim — why listening or speaking is off. */
  detail: string;
}

export interface VoiceStatus {
  stt: VoiceStage;
  tts: VoiceStage;
  /** The provider webcam frames would go to; null means no provider takes them and they stay local. */
  vision: { provider: string; model: string } | null;
  limits: { max_utterance_s: number; silence_ms: number };
}

export interface SessionRow {
  id: string;
  mode: Mode;
  created_at: number;
  message_count: number;
  tokens: number;
  last_used_at: number | null;
}

export interface SessionsResponse {
  sessions: SessionRow[];
}

export interface MessagesResponse {
  session_id: string;
  messages: MessageRow[];
}

export interface ErrorResponse {
  error: ErrorBody;
}

export interface MessageRow {
  id: number;
  session_id: string;
  role: Role;
  content: string;
  provider: string | null;
  model: string | null;
  finish_reason: string | null;
  status: TurnStatus;
  created_at: number;
  tool_calls: ToolCallWire[];
  usage: StoredUsage;
  chain: ChainRecord[];
}

export interface FieldStateBool {
  base: boolean;
  override: boolean | null;
  effective: boolean;
}

export interface FieldStateInt {
  base: number;
  override: number | null;
  effective: number;
}

export interface FieldStateStr {
  base: string;
  override: string | null;
  effective: string;
}

/** null means unlimited at every level, so a null `effective` is a decision, not a gap. */
export interface FieldStateCap {
  base: number | null;
  override: number | null;
  effective: number | null;
}

export interface ProviderView {
  name: string;
  kind: ProviderKind;
  base_url: string;
  models: string[];
  key_ref: string;
  key_present: boolean;
  /** False when the stanza declares no `key_ref`: nothing to store, so a dashboard must not read it as broken. */
  needs_key: boolean;
  /** Config.yaml only: whether this endpoint accepts images, so a call knows if it can attach a frame. */
  vision: boolean;
  /** The model's context window in tokens; null when the provider stanza does not declare it. */
  context_window: number | null;
  enabled: FieldStateBool;
  priority: FieldStateInt;
  tier: FieldStateStr;
  monthly_cap: FieldStateCap;
  spend_this_month: number;
  health: ProviderState;
}

export interface ProvidersResponse {
  providers: ProviderView[];
  orphan_settings: string[];
  month: string;
}

export interface TokenSplit {
  input: number;
  output: number;
}

export interface ProviderUsage {
  provider: string;
  turns: number;
  tokens: number;
}

export interface ModelUsage {
  provider: string;
  /** null for a turn that failed before any model answered it. */
  model: string | null;
  turns: number;
  tokens: number;
}

export interface DailyUsage {
  date: string;
  turns: number;
  tokens: number;
}

export interface BudgetRow {
  provider: string;
  cap: number | null;
  used: number;
  remaining: number | null;
}

export interface RecentIssue {
  id: number;
  session_id: string;
  status: TurnStatus;
  provider: string | null;
  model: string | null;
  created_at: number;
  reason: string;
}

export interface RefusalRecord {
  code: string;
  message: string;
  mode: string | null;
  model: string | null;
  created_at: number;
}

export interface RefusalSummary {
  count: number;
  by_code: { code: string; count: number }[];
  recent: RefusalRecord[];
}

export interface OverviewResponse {
  month: string;
  turns: number;
  tokens: TokenSplit;
  /** null when there are no turns: "no data" is not "0% healthy". */
  success_rate: number | null;
  interrupted: number;
  failed: number;
  by_provider: ProviderUsage[];
  by_model: ModelUsage[];
  daily: DailyUsage[];
  budgets: BudgetRow[];
  recent_issues: RecentIssue[];
  refusals: RefusalSummary;
}

export interface ProbeResponse {
  provider: string;
  ok: boolean;
  model_count?: number;
  sample?: string[];
  latency_ms: number | null;
  error: string | null;
}

export interface ProviderSettings {
  enabled: FieldStateBool;
  priority: FieldStateInt;
  tier: FieldStateStr;
  monthly_cap: FieldStateCap;
}

export interface SettingsResponse {
  provider: string;
  settings: ProviderSettings;
}

/** Any subset; `null` deletes that override back to config.yaml. `monthly_cap: 0` is unlimited. */
export interface SettingsRequest {
  enabled?: boolean | null;
  priority?: number | null;
  tier?: string | null;
  monthly_cap?: number | null;
}

export interface KeyRequest {
  key: string;
}

export interface KeyResponse {
  provider: string;
  key_ref: string;
  key_present: boolean;
}

export interface DeletedResponse {
  deleted: number;
  messages: number;
}

export interface ApprovalInfo {
  id: string;
  session_id?: string | null;
  tool: string;
  arguments: Record<string, unknown>;
  risk: ToolRisk;
  status: "pending" | "allowed" | "denied" | "expired";
  reason?: string | null;
  created_at: number;
  expires_at: number;
  decided_at?: number | null;
}

export interface ApprovalsResponse {
  approvals: ApprovalInfo[];
}

export interface ApprovalResponse {
  approval: ApprovalInfo;
}

export interface ApprovalDecision {
  decision: "allow" | "deny";
  reason?: string;
}

export interface CheckpointFile {
  path: string;
  existed: boolean;
  sha256_before?: string | null;
  sha256_after?: string | null;
  size?: number;
  blob?: string | null;
}

export interface CheckpointInfo {
  id: string;
  session_id?: string | null;
  tool: string;
  call_id: string;
  scope?: "files";
  files: CheckpointFile[];
  status: "open" | "complete" | "restored";
  created_at: number;
  finalized_at?: number | null;
  restored_at?: number | null;
}

export interface CheckpointsResponse {
  checkpoints: CheckpointInfo[];
}

export interface DiffFile {
  path: string;
  existed: boolean;
  changed: boolean;
  diff: string;
}

export interface CheckpointDiff {
  checkpoint: CheckpointInfo;
  files: DiffFile[];
}

export interface CheckpointRestore {
  restored: string[];
  conflicts: Record<string, unknown>[];
  checkpoint_id: string;
}

export interface CheckpointRestoreRequest {
  force?: boolean;
}

export interface ToolInfo {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  risk: ToolRisk;
  source: string;
  default_policy: ToolPolicy;
  policy: ToolPolicy;
  overridden: boolean;
}

export interface PluginInfo {
  file: string;
  name: string;
  status: "loaded" | "skipped";
  reason: string;
}

export interface ToolsResponse {
  tools: ToolInfo[];
  plugins: PluginInfo[];
}

/** A persona is pinned to a turn; a method is loaded by the model through `use_skill`. */
export type SkillKind = "persona" | "method";

export interface SkillInfo {
  name: string;
  description: string;
  kind: SkillKind;
  source: "builtin" | "user";
  body_bytes: number;
}

export interface SkillFile {
  file: string;
  name: string;
  status: "loaded" | "skipped" | "shadowed";
  reason: string;
  source: "builtin" | "user";
}

export interface SkillsResponse {
  skills: SkillInfo[];
  files: SkillFile[];
  /**
   * How a model reaches a method: `none` (no method loaded, so no `use_skill`), `inline` (the names are
   * in the tool's schema) or `search` (too many to name every turn — `search_skills` finds one).
   */
  discovery: "none" | "inline" | "search";
}

export interface PairRequest {
  code: string;
  name: string;
}

export interface DeviceInfo {
  id: string;
  name: string;
  created_at: number;
  last_seen_at: number;
}

export interface PairResponse {
  token: string;
  device: DeviceInfo;
}

export interface DevicesResponse {
  devices: DeviceInfo[];
}

export interface DeviceDeleted {
  deleted: string;
}

export interface PairingCodeResponse {
  code: string;
  expires_at: number;
}

export interface ToolPolicyRequest {
  policy?: ToolPolicy | null;
}

export interface ToolPolicyResponse {
  tool: { name: string; policy: ToolPolicy; overridden: boolean };
}

export type MemoryKind = "fact" | "preference" | "note";
export type MemoryOrigin = "user" | "tool" | "auto";
export type MemoryCapture = "off" | "explicit";

export interface MemoryItem {
  id: string;
  kind: MemoryKind;
  text: string;
  pinned: boolean;
  origin: MemoryOrigin;
  session_id?: string | null;
  tokens_spent?: number;
  created_at: number;
  updated_at: number;
  last_used_at?: number | null;
  use_count: number;
}

export interface MemorySettings {
  inject: boolean;
  capture: MemoryCapture;
  extract: boolean;
  /** read-only: trigram on SQLite 3.34+, unicode61 on older builds */
  tokenizer: "trigram" | "unicode61";
}

export interface MemoryList {
  memories: MemoryItem[];
  total: number;
  settings: MemorySettings;
}

export interface MemoryWrite {
  text: string;
  kind?: MemoryKind;
  pinned?: boolean;
}

export interface MemoryPatch {
  text?: string;
  kind?: MemoryKind;
  pinned?: boolean;
}

export interface MemoryHit {
  session_id: string;
  message_id: number;
  role: "user" | "assistant";
  snippet: string;
  created_at: number;
}

export interface MemorySearch {
  hits: MemoryHit[];
}

export interface MemoryExport {
  version: number;
  exported_at: number;
  memories: MemoryItem[];
}

export interface MemorySettingsPatch {
  inject?: boolean;
  capture?: MemoryCapture;
  extract?: boolean;
}

export interface MemoryDeleted {
  deleted: string;
}

/** One texture as the material table declared it, checked against the files that arrived with it. */
export interface TextureFinding {
  /** verbatim from the model, so a windows separator stays a windows separator */
  declared: string;
  /** normalised to posix, relative to the model's own folder */
  relative: string;
  exists: boolean;
  size: number | null;
  /** png/bmp/tga/... read from the bytes; "" when there is nothing to read */
  format: string;
  /** points outside the character folder, so the stage is never told to fetch it */
  escapes: boolean;
}

export type CountFraming = "header" | "inline";
export type MaterialFraming = "draw_and_memos" | "memo_only";

/** One PMX, measured by walking it — the same report the CLI prints and the import writes. */
export interface CharacterCapability {
  /** relative to the character's folder; the body is always `model.pmx` */
  path: string;
  name: string;
  english_name: string;
  file_name: string;
  /** 2.0 or 2.1 — the only two this reader walks */
  version: number;
  count_framing: CountFraming;
  material_framing: MaterialFraming;
  /** each count the walk earned; null when it could not */
  counts: {
    vertex_count: number | null;
    face_index_count: number | null;
    texture_count: number | null;
    material_count: number | null;
    bone_count: number | null;
    morph_count: number | null;
    frame_count: number | null;
    rigid_body_count: number | null;
    constraint_count: number | null;
  };
  vertices: number;
  bones: number;
  triangles: number;
  has_physics: boolean;
  is_character: boolean;
  /** `8/8`, `7/8 — hair.bmp absent`, or `no textures` */
  texture_status: string;
  standard_groups: string[];
  finger_bone_count: number;
  morph_names: string[];
  morph_kinds: number[];
  frame_names: string[];
  textures: TextureFinding[];
  texture_resolved: number;
  missing_textures: string[];
  sphere_texture_refs: number;
  shared_toon_refs: number;
  ik_bone_count: number;
  trailing_bytes: number;
  findings: string[];
  license_note: string | null;
  unreadable: string | null;
}

/** The library list item: enough to choose a character without opening its folder. */
export interface CharacterRow {
  /** `<slug>-<8 hex>` — the folder name, and the id every other character route takes */
  id: string;
  display_name: string;
  english_name: string;
  source_file_name: string;
  /** of the source bytes; importing them again answers `already_imported` */
  sha256: string;
  /** ISO-8601 UTC, second precision */
  imported_at: string;
  /** false when the archive held only props */
  is_character: boolean;
  main_name: string | null;
  path: string | null;
  /** 0 when there is no body */
  vertices: number;
  bones: number;
  has_physics: boolean;
  texture_status: string | null;
  companion_count: number;
  license_note: string | null;
  /** why this model was chosen as the body */
  reason: string;
}

export interface CharacterList {
  characters: CharacterRow[];
  /** who is on stage, or null. A pointer at a folder that is gone reads null, never the stale id */
  active: string | null;
}

/** One character, whole: the body, the props that came with it, and every file in its folder. */
export interface CharacterProfile {
  /** which report fields this profile was made from */
  schema: number;
  id: string;
  display_name: string;
  english_name: string;
  imported_at: string;
  source: {
    file_name: string;
    sha256: string;
    bytes: number;
    /** false for a bare .pmx */
    archive: boolean;
  };
  reason: string;
  license_note: string | null;
  /** the body the stage loads, or null when the archive has none */
  main: CharacterCapability | null;
  companions: CharacterCapability[];
  files: { path: string; bytes: number }[];
}

/** A .pmx or .zip on this machine, typed or picked by the desktop app — never from a device. */
export interface CharacterImportRequest {
  path: string;
}

export interface CharacterActiveRequest {
  /** who goes on stage; null takes everyone off */
  id: string | null;
}

export interface CharacterActiveResponse {
  active: string | null;
}

export interface CharacterDeleted {
  /** the removed character's id; its folder and its pick are both gone */
  deleted: string;
}
