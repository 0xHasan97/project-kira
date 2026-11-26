#!/usr/bin/env node
/**
 * Drift gate for the Kira contract.
 *
 * The engine owns the truth: `kira-engine contracts --out ../kira-contracts` regenerates
 * openapi.json + contract.json + VERSION. This script fails when the hand-written
 * TypeScript mirror disagrees with any of them, so the front end cannot silently keep
 * stale field names after an engine change.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
// `core.autocrlf=true` on Windows hands back CRLF text, and tsBlock() ends a
// `type X = …` match at a blank line — `\r\n\r\n` is not `\n\n`, so a checkout would
// report drift that no diff contains. Normalise at the read; the bytes on disk stay as git
// wrote them.
const read = (name) => readFileSync(join(here, name), "utf8").replace(/\r\n/g, "\n");

const openapi = JSON.parse(read("openapi.json"));
const facts = JSON.parse(read("contract.json"));
const versionFile = read("VERSION").trim();
const contractTs = await import(new URL("./contract.ts", import.meta.url));
const typesTs = read("types.ts");

const problems = [];
const check = (ok, message) => {
  if (!ok) problems.push(message);
};

check(
  String(openapi.info.version) === versionFile &&
    String(facts.contract_version) === versionFile &&
    String(contractTs.CONTRACT_VERSION) === versionFile,
  `contract version disagreement: openapi=${openapi.info.version} VERSION=${versionFile} contract.json=${facts.contract_version} contract.ts=${contractTs.CONTRACT_VERSION}`,
);

const TS_CONSTANTS = {
  modes: "MODES",
  chain_events: "CHAIN_EVENTS",
  chunk_types: "CHUNK_TYPES",
  error_codes: "ERROR_CODES",
  provider_error_codes: "PROVIDER_ERROR_CODES",
  wire_usage_fields: "WIRE_USAGE_FIELDS",
};
const sameSet = (a, b) =>
  Array.isArray(a) && Array.isArray(b) && JSON.stringify([...a].sort()) === JSON.stringify([...b].sort());

for (const [fact, constant] of Object.entries(TS_CONSTANTS)) {
  const mine = contractTs[constant];
  check(Array.isArray(mine), `contract.ts does not export ${constant}`);
  check(sameSet(mine, facts[fact]), `${constant} drifted from contract.json ${fact}: ts=${JSON.stringify(mine)} engine=${JSON.stringify(facts[fact])}`);
}
check(contractTs.DEFAULT_PORT === facts.default_port, `DEFAULT_PORT ${contractTs.DEFAULT_PORT} != ${facts.default_port}`);
check(contractTs.MAX_COOLDOWN_S === facts.max_cooldown_s, `MAX_COOLDOWN_S ${contractTs.MAX_COOLDOWN_S} != ${facts.max_cooldown_s}`);

// The version namespace. Nothing above looks at `paths` except for status codes, so a prefix renamed on
// one side of the wire used to pass this gate while every caller built against the old one 404'd.
check(contractTs.API_PREFIX === facts.api_prefix, `API_PREFIX ${contractTs.API_PREFIX} != contract.json api_prefix ${facts.api_prefix}`);
check(contractTs.API_VERSION === facts.api_version, `API_VERSION ${contractTs.API_VERSION} != contract.json api_version ${facts.api_version}`);
check(
  facts.api_prefix === `/v${facts.api_version}`,
  `api_prefix ${facts.api_prefix} disagrees with api_version ${facts.api_version}; one derives from the other`,
);
const outsideNamespace = Object.keys(openapi.paths).filter((path) => !path.startsWith(`${facts.api_prefix}/`));
check(
  JSON.stringify([...outsideNamespace].sort()) === JSON.stringify(["/healthz"]),
  `only /healthz may live outside ${facts.api_prefix}, found ${JSON.stringify(outsideNamespace.sort())}`,
);
check(
  contractTs.ERROR_CODES.includes("unsupported_version"),
  "ERROR_CODES must publish unsupported_version: it is the answer a wrong namespace gets",
);

const schemas = openapi.components.schemas;
const enumOf = (name, key) => schemas[name].properties[key].enum ?? [];
check(sameSet(enumOf("ChatRequest", "mode"), facts.modes), "openapi ChatRequest.mode != contract.json modes");
check(sameSet(enumOf("ChatChunk", "type"), facts.chunk_types), "openapi ChatChunk.type != contract.json chunk_types");
check(sameSet(enumOf("ChainRecord", "event"), facts.chain_events), "openapi ChainRecord.event != contract.json chain_events");
check(
  !("enum" in schemas.ErrorBody.properties.code),
  "openapi ErrorBody.code must stay open-ended: providers send their own code strings",
);

function tsBlock(name, seen = new Set()) {
  if (seen.has(name)) return null;
  seen.add(name);
  const patterns = [
    new RegExp(`(?:export )?interface ${name} \\{([\\s\\S]*?)\\n\\}`),
    new RegExp(`(?:export )?type ${name} =([\\s\\S]*?)\\n\\n`),
    new RegExp(`(?:export )?class ${name}(?: extends [A-Za-z]+)? \\{([\\s\\S]*?)\\n\\}`),
  ];
  let block = null;
  for (const pattern of patterns) {
    const match = typesTs.match(pattern);
    if (match) {
      block = match[1];
      break;
    }
  }
  if (block === null) return null;
  // A union built from a shared helper type (e.g. `ChunkBase & {...}`) documents its
  // fields across both declarations, so resolve one level of local aliases.
  let merged = block;
  for (const alias of block.matchAll(/\b([A-Z][A-Za-z0-9]*)\s*&/g)) {
    const extra = tsBlock(alias[1], seen);
    if (extra) merged += `\n${extra}`;
  }
  return merged;
}

for (const [schemaName, schema] of Object.entries(schemas)) {
  const tsName = schemaName;
  const block = tsBlock(tsName);
  check(block !== null, `types.ts has no \`${tsName}\` for openapi schema ${schemaName}`);
  if (block === null) continue;
  for (const property of Object.keys(schema.properties ?? {})) {
    check(
      new RegExp(`\\b${property}[?:]`).test(block),
      `${tsName} is missing documented field \`${property}\` (from ${schemaName})`,
    );
  }
  for (const required of schema.required ?? []) {
    check(
      new RegExp(`\\b${required}[?:]`).test(block),
      `${tsName} is missing required field \`${required}\` (from ${schemaName})`,
    );
  }
}

function resolveRef(ref) {
  let node = openapi;
  for (const part of ref.replace(/^#\//, "").split("/")) {
    node = node?.[part];
    if (node === undefined) return null;
  }
  return node;
}

function collectRefs(node, out = []) {
  if (Array.isArray(node)) {
    for (const item of node) collectRefs(item, out);
  } else if (node && typeof node === "object") {
    for (const [key, value] of Object.entries(node)) {
      if (key === "$ref" && typeof value === "string") out.push(value);
      else collectRefs(value, out);
    }
  }
  return out;
}

const refs = collectRefs(openapi);
check(refs.length > 0, "openapi.json declares no $ref at all — response schemas are missing");
for (const ref of refs) {
  check(ref.startsWith("#/") && resolveRef(ref) !== null, `openapi has an unresolved $ref: ${ref}`);
}

const documented = new Set(
  Object.values(openapi.paths)
    .flatMap((spec) => Object.entries(spec))
    .flatMap(([, op]) => Object.keys(op.responses ?? {})),
);
check(
  documented.has("401") && documented.has("503"),
  "openapi must document the auth and exhaustion statuses the chat client has to handle",
);

if (problems.length) {
  console.error(`kira-contracts drift: ${problems.length} problem(s)`);
  for (const problem of problems) console.error(`  - ${problem}`);
  console.error("\nregenerate with: kira-engine contracts --out ../kira-contracts, then update the TypeScript mirror.");
  process.exit(1);
}
console.log(
  `kira-contracts OK — v${versionFile}, ${Object.keys(schemas).length} schemas, ${facts.chunk_types.length} chunk types, ${facts.chain_events.length} chain events`,
);
