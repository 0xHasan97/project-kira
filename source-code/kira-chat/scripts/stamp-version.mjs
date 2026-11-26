// Records which API revision the bundle in dist/ was built against.
// `run_kira.py` reads it before serving a pre-built bundle and rebuilds when it disagrees with the
// engine, which is what stops a week-old UI from being opened against a new backend forever.
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const chat = join(dirname(fileURLToPath(import.meta.url)), "..");
const contract = JSON.parse(await readFile(join(chat, "..", "kira-contracts", "contract.json"), "utf-8"));
const stamp = {
  api_version: contract.api_version,
  contract_version: contract.contract_version,
  api_prefix: contract.api_prefix,
};

const out = join(chat, "dist", "kira-build.json");
await mkdir(dirname(out), { recursive: true });
await writeFile(out, `${JSON.stringify(stamp, null, 2)}\n`, "utf-8");
console.log(`[kira] stamped ${out}: ${JSON.stringify(stamp)}`);
