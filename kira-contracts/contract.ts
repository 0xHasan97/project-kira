export const CONTRACT_VERSION = 2;

// Two numbers with two jobs: API_VERSION is the URL namespace, CONTRACT_VERSION is the revision of the
// fields inside it. Adding a field or an enum value moves neither.
export const API_VERSION = 1;
export const API_PREFIX = "/v1";

export const MODES = ["AUTO", "FAST", "POWERFUL", "CUSTOM"] as const;

export const CHAIN_EVENTS = [
  "attempt",
  "served",
  "failed",
  "skipped_cooling",
  "skipped_missing_key",
  "skipped_config",
  "skipped_budget",
  "aborted_mid_stream",
  "empty_answer",
  "tool_executed",
  "tool_approval_requested",
  "tool_denied",
  "checkpoint_created",
  "usage_estimated",
  "images_attached",
  "images_dropped",
] as const;

export const CHUNK_TYPES = ["delta", "tool_call", "chain", "approval", "done", "error"] as const;

export const ERROR_CODES = [
  "budget_exhausted",
  "config_error",
  "internal_error",
  "model_not_found",
  "pairing_refused",
  "providers_exhausted",
  "rate_limited",
  "secret_store_unavailable",
  "unauthorized",
  "unsupported_version",
  "image_backend_missing",
  "image_generation_failed",
  "image_not_found",
  "image_request_invalid",
  "llm_unavailable",
  "llm_start_failed",
  "download_refused",
  "download_failed",
  // The character library publishes the importer's own refusals, in sorted order because the engine's
  // published list is sorted and drift is compared as a set, not a sequence.
  "already_imported",
  "bad_archive",
  "character_exists",
  "character_file_not_found",
  "character_not_found",
  "no_pmx_in_archive",
  "not_a_pmx",
  "pmx_truncated",
  "pmx_version_unsupported",
  "too_large",
  "unsafe_entry",
  "unsupported_source",
] as const;

export const PROVIDER_ERROR_CODES = [
  "provider_error",
  "rate_limited",
  "provider_5xx",
  "provider_4xx",
  "bad_stream",
  "bad_tool_call",
  "stream_error",
] as const;

export const WIRE_USAGE_FIELDS = ["prompt_tokens", "completion_tokens"] as const;

export const DEFAULT_PORT = 8901;
export const MAX_COOLDOWN_S = 300;

export type Mode = (typeof MODES)[number];
export type ChainEvent = (typeof CHAIN_EVENTS)[number];
export type ChunkType = (typeof CHUNK_TYPES)[number];
