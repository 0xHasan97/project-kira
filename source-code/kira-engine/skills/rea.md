---
name: rea
description: Reverse-engineer shipped binaries, Electron and JavaScript, managed code, firmware and captures from evidence rather than guesses.
kind: method
license: MIT (REA, https://github.com/morluto/rea)
---

Use this when a claim depends on a shipped artifact — a binary, an installer, an ASAR, a managed
assembly, an APK, firmware or a saved capture — and the source is missing, incomplete or a different
version. For ordinary analysis of a full source tree, use the repository and skip this method.

**Route the target before choosing a tool.** An ASAR or extracted Electron tree is JavaScript; an
archive, APK, IPA, MSIX or DMG is a member inventory first; a managed PE/CLI assembly is metadata and
IL; firmware is a region inventory; a saved HAR/SAZ/PCAP is a capture, not live traffic. Name the
format and version, and record the SHA-256 of every artifact the conclusion rests on.

**Work summary-first.** Start with the smallest inventory that answers the question, then follow one
concrete hypothesis. Do not decompile everything because decompiling is possible. Read packaged
resources and configuration alongside code when they change behaviour. A filename, a string match or
a layout guess is a lead, not a finding.

**Label every claim** as one of:

- **seen** — read in the artifact or observed at runtime, with the path, offset, symbol or Evidence
  reference that shows it;
- **inferred** — reasoned from what was seen, with the reasoning stated;
- **unknown** — not established, including a bounded search that found nothing.

Static reading is not observed execution. Do not execute an unknown installer, do not treat a
string as a call, and do not describe a broad search as complete while a required question is open.
If a runtime is needed, state what would be observed and get the authority to run that exact target
before running it.

**If REA tooling is actually available**, use its own tool list and schemas, keep the returned
Evidence IDs, and page a large result rather than repeating the analysis. If it is absent, do not
install engines or rewrite client configuration as a side effect: continue with the format-aware
local tools that are available, and say which part stayed unknown. `npx -y rea-agents@latest` is a
CLI fallback only when package acquisition is in scope and has been agreed.

Finish by answering the question first, then the evidence, then the residual unknowns. Separate
observed donor behaviour from the design choices made in the reimplementation.
