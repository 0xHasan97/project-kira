from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace

from .errors import AllProvidersExhausted, BudgetExhausted, ConfigError, ProviderCallError
from .net import HealthLedger
from .overrides import MergedView, build_view, enabled_providers
from .providers.registry import ProviderRegistry
from .store import month_bounds
from .types import ApprovalRequest, Completed, Delta, GenRequest, StreamEvent, ToolCallEvent


@dataclass
class Choice:
    provider: str
    model: str


@dataclass
class Note:
    record: dict


@dataclass
class Plan:
    mode: str
    choices: list[Choice]
    notes: list[dict] = field(default_factory=list)


Routed = StreamEvent | Note | ApprovalRequest


@dataclass
class AttemptState:
    """What served the answer — the caller persists this with the message."""

    chain: list[dict] = field(default_factory=list)
    served_by: str | None = None
    served_model: str | None = None
    failed: bool = False
    # The agent loop calls `events()` once per step with the same plan; the plan's notes are facts
    # about the turn, not about each step, so they are spoken once.
    notes_emitted: bool = False


class Router:
    def __init__(
        self,
        registry: ProviderRegistry,
        ledger: HealthLedger,
        *,
        view_source: Callable[[], MergedView] | None = None,
        spend_source: Callable[[], tuple[str, dict[str, int]]] | None = None,
    ) -> None:
        self.registry = registry
        self.ledger = ledger
        # Without an override store this is exactly the YAML-only router every existing test built.
        self.view_source = view_source or (lambda: build_view(registry.config, None))
        # No store means no known spend, so every cap reads untouched: the same reasoning as above.
        self.spend_source = spend_source or (lambda: (month_bounds()[0], {}))

    def plan(self, *, model: str | None = None, mode: str | None = None, provider: str | None = None) -> Plan:
        chosen_mode = (mode or self.registry.config.default_mode).upper()
        notes: list[dict] = []
        view = self.view_source()
        configs = enabled_providers(view)

        if chosen_mode == "CUSTOM":
            if not provider:
                raise ConfigError("mode CUSTOM requires a 'provider'")
            wanted = view.by_name.get(provider)
            if wanted is None:
                raise ConfigError(f"unknown provider '{provider}'")
            if not wanted.enabled:
                raise ConfigError(f"provider '{provider}' is disabled - switch it on in the dashboard")
            configs = [wanted]
        elif chosen_mode in ("FAST", "POWERFUL"):
            tier = chosen_mode.lower()
            configs = [c for c in configs if c.tier == tier]
            if not configs:
                raise ConfigError(f"mode {chosen_mode}: no provider configured with tier '{tier}'")
        elif chosen_mode != "AUTO":
            raise ConfigError(f"unknown mode '{chosen_mode}'")

        if model:
            offering = [c for c in configs if model in c.models]
            if not offering:
                raise ConfigError(
                    f"no provider in mode {chosen_mode} offers model '{model}'; "
                    f"configured: {[m for c in configs for m in c.models]}"
                )
            if chosen_mode == "AUTO":
                # AUTO is the "you decide" lane, so a model named there is a preference and the providers
                # carrying it merely stand at the front of the queue. Holding the rest in line is what
                # makes cross-provider failover reachable from a picker that can only name models — and
                # the `attempt`/`served` records name the model that actually answered, so a fallback
                # never reads as the pinned one. FAST/POWERFUL/CUSTOM are explicit lanes and stay strict.
                configs = offering + [c for c in configs if model not in c.models]
            else:
                configs = offering

        choices: list[Choice] = []
        for cfg in configs:
            if self.registry.key_for(cfg.name) is None and cfg.key_ref:
                notes.append({"provider": cfg.name, "event": "skipped_missing_key", "reason": f"vault ref '{cfg.key_ref}' empty"})
                continue
            chosen_model = model if model and model in cfg.models else cfg.models[0]
            choices.append(Choice(cfg.name, chosen_model))

        month, spent = self.spend_source()
        within: list[Choice] = []
        over_cap: list[Choice] = []
        for choice in choices:
            cap = view.by_name[choice.provider].monthly_cap
            used = spent.get(choice.provider, 0)
            if cap is not None and used >= cap:
                notes.append(
                    {
                        "provider": choice.provider,
                        "event": "skipped_budget",
                        "reason": f"used {used:,} of {cap:,} tokens in {month}",
                    }
                )
                over_cap.append(choice)
            else:
                within.append(choice)
        choices = within
        # Amendment 7: `budget_exhausted` only when candidates actually reached this check and all of
        # them were dropped here. A list emptied by the key filter above is a different story, and the
        # `if not choices` exhaustion below still tells it.
        if over_cap and not choices:
            names = ", ".join(choice.provider for choice in over_cap)
            raise BudgetExhausted(
                f"mode {chosen_mode}: over the monthly cap for {month} ({names}) - "
                "raise the cap in the dashboard or wait for the reset",
                chain=notes,
            )

        eligible_names = [c.provider for c in choices]
        available, skipped = self.ledger.available(eligible_names)
        notes.extend(skipped)
        choices = [c for c in choices if c.provider in available]

        if not choices:
            # The notes already say why each provider stood down, and a caller reading only the message
            # needs the model it was asked for: "every provider was filtered out" named nothing.
            reasons = "; ".join(
                f"{note.get('provider')}: {note.get('reason') or note.get('event')}" for note in notes
            )
            subject = f" model '{model}'" if model else ""
            raise AllProvidersExhausted(
                f"mode {chosen_mode}: nothing left to ask{subject}"
                + (f" - {reasons}" if reasons else " - no provider is configured"),
                chain=notes,
            )
        return Plan(mode=chosen_mode, choices=choices, notes=notes)

    async def events(self, plan: Plan, req: GenRequest, state: AttemptState) -> AsyncIterator[Routed]:
        if not state.notes_emitted:
            state.notes_emitted = True
            for note_record in plan.notes:
                state.chain.append(note_record)
                yield Note(note_record)

        errors: list[dict] = []
        empties = 0
        for choice in plan.choices:
            started = False
            text_emitted = False
            tool_emitted = False
            try:
                provider = self.registry.build(choice.provider)
            except ConfigError as exc:
                record = {"provider": choice.provider, "event": "skipped_config", "reason": str(exc)}
                state.chain.append(record)
                errors.append(record)
                yield Note(record)
                continue

            attempt = replace(req, model=choice.model)
            begin = {"provider": choice.provider, "model": choice.model, "event": "attempt"}
            state.chain.append(begin)
            yield Note(begin)

            pending_completed: Completed | None = None
            try:
                async for event in provider.stream(attempt):
                    started = True
                    if isinstance(event, Delta) and event.text:
                        text_emitted = True
                    if isinstance(event, ToolCallEvent):
                        tool_emitted = True
                    if isinstance(event, Completed):
                        pending_completed = event
                        continue
                    yield event
            except ProviderCallError as err:
                record = self.ledger.record_failure(err)
                state.chain.append(record)
                errors.append(record)
                yield Note(record)
                if not started:
                    if not err.retryable:
                        # A 4xx is our request being wrong, not the provider being ill.
                        # Failing over would hide a mapping bug behind another provider's answer.
                        state.failed = True
                        raise
                    continue  # nothing reached the client, failover is safe
                if text_emitted:
                    state.failed = True
                    state.chain.append(
                        {"provider": choice.provider, "event": "aborted_mid_stream", "reason": "client already saw text"}
                    )
                    raise
                continue

            if not text_emitted and not tool_emitted:
                # A stream that opens and closes without a character and without a tool call is not
                # an answer. Reasoning models do this when the output budget is smaller than their
                # hidden thinking: measured live, Gemini 3.5 Flash asked for 8 output tokens spent
                # all of them on thinking, and the chain read `served` while the user stared at an
                # empty bubble. Nothing reached the client, so the next provider gets the turn.
                empties += 1
                record = {
                    "provider": choice.provider,
                    "model": choice.model,
                    "event": "empty_answer",
                    "reason": "completed with no text",
                }
                state.chain.append(record)
                yield Note(record)
                continue

            if pending_completed is not None:
                yield pending_completed
            self.ledger.record_success(choice.provider)
            state.served_by = choice.provider
            state.served_model = choice.model
            served = {"provider": choice.provider, "model": choice.model, "event": "served"}
            state.chain.append(served)
            yield Note(served)
            return

        state.failed = True
        if empties == len(plan.choices):
            raise AllProvidersExhausted(
                f"all {len(plan.choices)} provider attempt(s) answered with nothing for mode {plan.mode}",
                chain=state.chain,
            )
        raise AllProvidersExhausted(
            f"all {len(plan.choices)} provider attempt(s) failed for mode {plan.mode}", chain=state.chain
        )
