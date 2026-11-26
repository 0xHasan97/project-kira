/**
 * One place for what `key_present` plus `needs_key` mean together.
 *
 * The engine reports both because a provider can be missing a key it wants and can be a provider that
 * wants none — a local server on loopback, which roadmap unit 5 ships. Four surfaces used to read
 * `key_present` alone and say "no key" about both, so the rule lives here instead of in four ternaries.
 */
export interface KeyFacts {
  key_present: boolean;
  needs_key: boolean;
}

/** Whether a turn sent to this provider would reach a model that replies. */
export function answersToday(provider: KeyFacts): boolean {
  return !provider.needs_key || provider.key_present;
}

/** What to call that state in one short label, and whether it is a warning or not. */
export function keyBadge(provider: KeyFacts): { text: string; ok: boolean } {
  if (!provider.needs_key) return { text: "no key needed", ok: true };
  return provider.key_present ? { text: "key ok", ok: true } : { text: "no key", ok: false };
}
