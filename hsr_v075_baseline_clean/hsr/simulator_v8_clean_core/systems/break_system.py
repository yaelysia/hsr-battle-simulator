from __future__ import annotations

from dataclasses import dataclass, replace

from ..core.model import (
    BattleState, BreakNotificationFact, GameEvent, JSONValue, Mutation, RNGEvent,
    StanceCountDownFact, _BREAK_NOTIFICATION_PRODUCER, _STANCE_COUNT_DOWN_PRODUCER,
)
from ..core.reducer import MutationReducer
from ..core.settlement import SettlementRecord
from ..rules.evaluator import NumericEvaluationContext, NumericEvaluationResult, RuleEvaluator
from ..rules.ir import BreakDamageEmissionIR, BreakStatusEmissionIR, BreakTemplateIR
from ..rules.rulebook import RuleBook
from .damage import DamagePacket, DamageSystem
from .dynamic_values import find_status_detail
from .event_dispatch import EventDispatchSystem, EventNormalization
from .effect import EffectExecutionContext, EffectRegistry
from .status_callbacks import StatusCallbackSystem
from .target import TargetSystem
from .toughness import ToughnessApplicationResult, ToughnessPacket, ToughnessSystem
from .toughness_state import read_toughness_segments
from .unit_relation import TargetEvaluationContext


@dataclass(frozen=True)
class BreakApplicationResult:
    ok: bool
    after_state: BattleState
    mutations: tuple[Mutation, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()
    events: tuple[GameEvent, ...] = ()
    errors: tuple[str, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    dispatched_event_ids: frozenset[str] = frozenset()
    event_normalizations: tuple[EventNormalization, ...] = ()


class BreakSystem:
    """Weakness-break and intermediate toughness-segment lifecycle boundary.

    The system only consumes Canonical IR admitted through RuleBook. It does
    not infer break behavior from raw task names or display-only fields.
    """

    def __init__(
        self,
        rules: RuleBook,
        effects: EffectRegistry,
        *,
        reducer: MutationReducer | None = None,
        damage: DamageSystem | None = None,
        status_callbacks: StatusCallbackSystem | None = None,
        event_dispatcher: EventDispatchSystem | None = None,
    ) -> None:
        self.rules = rules
        self.effects = effects
        self.reducer = reducer or MutationReducer()
        self.damage = damage or DamageSystem(rules)
        self.toughness = ToughnessSystem(rules)
        self.targets = TargetSystem(rules)
        self.evaluator = RuleEvaluator()
        self.event_dispatcher = event_dispatcher or EventDispatchSystem(
            rules,
            effects,
            reducer=self.reducer,
            damage=self.damage,
            status_callbacks=status_callbacks,
        )

    def enter_if_depleted(
        self, state: BattleState, result: ToughnessApplicationResult,
    ) -> BreakApplicationResult | None:
        if not result.ok or not result.mutations:
            return None
        target = state.units.get(result.packet.target_id)
        if target is None or target.toughness > 0 or bool(target.flags.get("broken", False)):
            return None
        current = state
        mutations: list[Mutation] = []
        records: list[dict[str, JSONValue]] = []
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        dispatched_ids: set[str] = set()
        normalizations: list[EventNormalization] = []
        while current.units[result.packet.target_id].toughness <= 0:
            try:
                segments = read_toughness_segments(current.units[result.packet.target_id])
            except ValueError as exc:
                return _blocked(state, result.packet, str(exc))
            metadata = dict(result.packet.metadata)
            for mutation in result.mutations:
                if mutation.source == "toughness_system":
                    for key in ("numeric_evaluation", "weakness_check", "amount"):
                        if key in mutation.metadata:
                            metadata[key] = mutation.metadata[key]
            packet = replace(result.packet, metadata=metadata)
            layer = (self._enter_stance_count_down(current, packet)
                     if segments.remaining_segments > 1 else self.enter_break(current, packet))
            if not layer.ok:
                return replace(layer, after_state=state, mutations=(), events=(), rng_events=(),
                               dispatched_event_ids=frozenset(), event_normalizations=())
            current = layer.after_state
            mutations.extend(layer.mutations)
            records.extend(layer.records)
            events.extend(layer.events)
            rng_events.extend(layer.rng_events)
            dispatched_ids.update(layer.dispatched_event_ids)
            normalizations.extend(layer.event_normalizations)
            if result.overflow is None:
                break
            result = self.toughness.apply_overflow(current, result.overflow)
            if not result.ok:
                return _blocked(state, packet, ",".join(result.errors))
            reduction = self.reducer.apply_all_result(current, result.mutations)
            if not reduction.ok:
                return _blocked(state, packet, "toughness_overflow_mutation_conflict")
            current = reduction.after_state
            mutations.extend(result.mutations)
            records.extend(result.records)
            for event in result.events:
                dispatched = self.event_dispatcher.dispatch_event(current, event=event)
                if dispatched.errors:
                    return _blocked(state, packet, ",".join(dispatched.errors))
                current = dispatched.after_state
                mutations.extend(dispatched.mutations)
                records.extend(dispatched.records)
                events.extend(dispatched.events)
                rng_events.extend(dispatched.rng_events)
                normalizations.extend(dispatched.event_normalizations)
                dispatched_ids.update(dispatched.dispatched_event_ids)
                dispatched_ids.update(str(item.to_json()["event_id"]) for item in dispatched.events)
        return BreakApplicationResult(
            ok=True, after_state=current, mutations=tuple(mutations), records=tuple(records),
            events=tuple(replace(event, event_id=str(event.to_json()["event_id"]))
                         if str(event.to_json()["event_id"]) in dispatched_ids else event for event in events),
            rng_events=tuple(rng_events),
            dispatched_event_ids=frozenset(dispatched_ids),
            event_normalizations=tuple(normalizations),
        )

    def _enter_stance_count_down(
        self, state: BattleState, packet: ToughnessPacket,
    ) -> BreakApplicationResult:
        target = state.units[packet.target_id]
        segments = read_toughness_segments(target)
        if (segments.remaining_segments <= 1 or target.toughness != 0
                or target.flags.get("broken", False)
                or target.flags.get("weakness_locked", False) or target.flags.get("mute_break", False)):
            return _blocked(state, packet, "stance_count_down_state_invalid")
        template = self.rules.break_template_for_element(packet.element_type, trigger_kind="stance_count_down")
        if (template is None or template.coverage_status != "executable"
                or self.rules.break_status_emissions_for_template(template.template_id)
                or not self.rules.break_damage_emissions_for_template(template.template_id)):
            return _blocked(state, packet, "stance_count_down_template_missing_or_not_executable", template=template)
        metadata = _break_metadata(packet, template)
        metadata["break_lifecycle"] = {
            "operation": "stance_count_down", "reason": "toughness_segment_depleted",
            "event_types": ["OnBeingStanceCountDown", "OnTriggerStanceCountDown"],
            "break_template_id": template.template_id,
        }
        count_mutation = Mutation(
            op="set", path=("units", packet.target_id, "flags", "stance_segments_remaining"),
            before=segments.remaining_segments, after=segments.remaining_segments - 1,
            reason="consume a nonfinal toughness segment", source="break_system", metadata=metadata,
        )
        current = self.reducer.apply_all(state, (count_mutation,))
        mutations = [count_mutation]
        records = list(_lifecycle_records(packet, template, (count_mutation,)))
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []
        for emission in self.rules.break_damage_emissions_for_template(template.template_id):
            result = self._apply_break_damage_emission(current, packet, template, emission)
            if not result.ok:
                return _blocked(state, packet, ",".join(result.errors), template=template)
            current = result.after_state
            mutations.extend(result.mutations)
            records.extend(result.records)
            events.extend(result.events)
            rng_events.extend(result.rng_events)
        if current.units[packet.target_id].toughness != 0:
            return _blocked(state, packet, "stance_count_down_bar_changed_before_refill", template=template)
        refill = Mutation(
            op="set", path=("units", packet.target_id, "toughness"),
            before=current.units[packet.target_id].toughness,
            after=target.max_toughness, reason="expose the next toughness segment",
            source="break_system", metadata=metadata,
        )
        current = self.reducer.apply_all(current, (refill,))
        mutations.append(refill)
        records.extend(_lifecycle_records(packet, template, (refill,)))
        event_id = f"event:{state.event_index}:stance_count_down:{count_mutation.stable_id()}"
        notification = GameEvent(
            "toughness.segment_depleted", source_id=packet.attacker_id, target_id=packet.target_id,
            event_id=event_id, window="toughness_segment", process_only=True,
            payload={"source_trace": metadata["source_trace"]},
            stance_count_down_fact=StanceCountDownFact(
                source_mutation=count_mutation, event_id=event_id, event_index=state.event_index,
                target_id=packet.target_id, attacker_id=packet.attacker_id,
                element_type=packet.element_type, template_id=template.template_id,
                _state=current, _producer_token=_STANCE_COUNT_DOWN_PRODUCER,
            ),
        )
        dispatched_ids: set[str] = set()
        normalizations: list[EventNormalization] = []
        emitted = []
        for event in (*events, notification):
            if str(event.to_json()["event_id"]) in dispatched_ids:
                continue
            dispatched = self.event_dispatcher.dispatch_event(current, event=event)
            if dispatched.errors:
                return _blocked(state, packet, ",".join(dispatched.errors), template=template)
            current = dispatched.after_state
            mutations.extend(dispatched.mutations)
            records.extend(dispatched.records)
            emitted.extend(dispatched.events)
            rng_events.extend(dispatched.rng_events)
            normalizations.extend(dispatched.event_normalizations)
            dispatched_ids.update(dispatched.dispatched_event_ids)
            dispatched_ids.update(str(item.to_json()["event_id"]) for item in dispatched.events)
        return BreakApplicationResult(
            ok=True, after_state=current, mutations=tuple(mutations), records=tuple(records),
            # Preserve the identity already recorded as consumed at this boundary.
            events=tuple(replace(event, event_id=str(event.to_json()["event_id"])) for event in emitted),
            rng_events=tuple(rng_events),
            dispatched_event_ids=frozenset(dispatched_ids),
            event_normalizations=tuple(normalizations),
        )

    def recover_ordinary_before_action(
        self, state: BattleState, *, unit_id: str,
    ) -> BreakApplicationResult | None:
        target = state.units.get(unit_id)
        if (
            target is None or target.side != "enemy"
            or target.lifecycle_status != "active" or target.hp <= 0
            or not target.flags.get("broken", False)
        ):
            return None

        def blocked(reason: str) -> BreakApplicationResult:
            return BreakApplicationResult(
                ok=False, after_state=state,
                records=(SettlementRecord(
                    record_type="break_recovery_blocked", source="break_system",
                    process_only=True, payload={"target_id": unit_id, "reason": reason},
                    trace={},
                ).to_json(),),
                errors=(reason,),
            )

        source = target.flags.get("break_source")
        try:
            segments = read_toughness_segments(target)
        except ValueError as exc:
            return blocked(str(exc))
        if (
            target.max_toughness <= 0 or target.toughness > 0
            or not isinstance(source, dict)
            or segments.maximum_segments > 1 and segments.remaining_segments != 0
        ):
            return blocked("ordinary_break_recovery_state_invalid")
        template_id = source.get("break_template_id")
        emission_id = source.get("toughness_emission_id")
        task_id = source.get("source_task_id")
        profile_id = source.get("hit_profile_id")
        template = self.rules.break_template(template_id) if isinstance(template_id, str) else None
        emission = self.rules.toughness_emission(emission_id) if isinstance(emission_id, str) else None
        if (
            template is None or template.coverage_status != "executable"
            or emission is None or emission.coverage_status != "executable"
            or not isinstance(task_id, str) or not task_id
            or not isinstance(profile_id, str) or not profile_id
        ):
            return blocked("ordinary_break_recovery_source_missing")
        trace: dict[str, JSONValue] = {
            "break_template_source": template.source.to_json(),
            "toughness_source": emission.source.to_json(),
            "original_break_source": source,
        }
        request = GameEvent(
            "break.recovery_requested",
            source_id=unit_id, target_id=unit_id,
            event_id=f"event:{state.event_index}:break_recovery_requested:{unit_id}",
            window="break_recovery", process_only=True,
            payload={
                "callback_events": ["OnEndBreak"],
                "actor_id": unit_id, "target_id": unit_id,
                "break_template_id": template_id, "source_trace": trace,
            },
        )
        dispatched = self.event_dispatcher.dispatch_event(state, event=request)
        if dispatched.errors:
            return blocked("ordinary_break_recovery_callback_blocked:" + ",".join(dispatched.errors))
        current = dispatched.after_state
        current_target = current.units[unit_id]
        if segments.maximum_segments > 1:
            try:
                restored = read_toughness_segments(current_target)
            except ValueError as exc:
                return blocked(str(exc))
            if (restored.remaining_segments != segments.maximum_segments
                    or current_target.toughness != current_target.max_toughness):
                return blocked("multilayer_break_recovery_callbacks_not_committed")
        metadata: dict[str, JSONValue] = {
            "break_template_id": template_id,
            "toughness_emission_id": emission_id,
            "source_task_id": task_id,
            "hit_profile_id": profile_id,
            "source_trace": trace,
            "break_lifecycle": {"operation": "recover", "target_id": unit_id},
            "break_recovery": {
                "kind": "ordinary_before_action",
                "trigger_kind": "next_regular_action",
            },
        }
        changes = (
            (("flags", "broken"), False),
            (("toughness",), current_target.max_toughness),
        )
        mutations: list[Mutation] = []
        for path, after in changes:
            before = current_target.flags.get("broken") if path[0] == "flags" else current_target.toughness
            if before == after:
                continue
            mutations.append(Mutation(
                op="set", path=("units", unit_id, *path),
                before=before, after=after,
                before_exists=(path[1] in current_target.flags if path[0] == "flags" else True),
                reason="recover ordinary weakness break before action",
                source="break_system", metadata=metadata,
            ))
        for key in ("break_element", "break_source"):
            if key not in current_target.flags:
                continue
            mutations.append(Mutation(
                op="delete", path=("units", unit_id, "flags", key),
                before=current_target.flags[key], after=None, after_exists=False,
                reason="clear ordinary weakness break state",
                source="break_system", metadata=metadata,
            ))
        reduction = self.reducer.apply_all_result(current, tuple(mutations))
        if not reduction.ok:
            return blocked("ordinary_break_recovery_mutation_conflict")
        records = tuple(
            SettlementRecord(
                record_type="break_recovery", source="break_system",
                mutation_id=mutation.stable_id(), process_only=False,
                payload={"target_id": unit_id, "field": mutation.path[-1],
                         "trigger_kind": "next_regular_action",
                         "break_template_id": template_id},
                trace=trace,
            ).to_json()
            for mutation in mutations
        )
        return BreakApplicationResult(
            ok=True, after_state=reduction.after_state,
            mutations=(*dispatched.mutations, *mutations),
            events=(*(replace(event, event_id=str(event.to_json()["event_id"])) for event in dispatched.events), GameEvent(
                "break.recovered", source_id=unit_id, target_id=unit_id,
                window="break_recovery", process_only=True,
                payload={"break_template_id": template_id, "source_trace": trace},
            )),
            records=(*dispatched.records, *records),
            rng_events=dispatched.rng_events,
            dispatched_event_ids=dispatched.dispatched_event_ids | {
                str(event.to_json()["event_id"]) for event in dispatched.events
            },
            event_normalizations=dispatched.event_normalizations,
        )

    def enter_break(self, state: BattleState, packet: ToughnessPacket) -> BreakApplicationResult:
        target = state.units.get(packet.target_id)
        if target is None:
            return _blocked(state, packet, "target_missing")
        if target.toughness > 0:
            return _blocked(state, packet, "target_toughness_not_depleted")
        if target.max_toughness <= 0:
            return _blocked(state, packet, "target_has_no_toughness")
        if bool(target.flags.get("broken", False)):
            return _skipped(state, packet, "target_already_broken")
        if bool(target.flags.get("weakness_locked", False)):
            return _skipped(state, packet, "target_weakness_locked")
        if bool(target.flags.get("mute_break", False)):
            return _skipped(state, packet, "target_mute_break")
        try:
            segments = read_toughness_segments(target)
        except ValueError as exc:
            return _blocked(state, packet, str(exc))
        if segments.maximum_segments > 1 and segments.remaining_segments != 1:
            return _blocked(state, packet, "full_break_requires_the_final_toughness_segment")
        template = self.rules.break_template_for_element(packet.element_type)
        if template is None:
            return _blocked(state, packet, "break_template_missing")
        if template.coverage_status != "executable":
            return _blocked(
                state,
                packet,
                template.blocked_reason or f"break_template_not_executable:{template.coverage_status}",
                template=template,
            )

        metadata = _break_metadata(packet, template)
        broken_mutation = Mutation(
            op="set",
            path=("units", packet.target_id, "flags", "broken"),
            before=target.flags.get("broken"),
            after=True,
            reason="enter weakness break state",
            source="break_system",
            before_exists="broken" in target.flags,
            metadata=metadata,
        )
        element_mutation = Mutation(
            op="set",
            path=("units", packet.target_id, "flags", "break_element"),
            before=target.flags.get("break_element"),
            after=packet.element_type,
            reason="record weakness break element",
            source="break_system",
            before_exists="break_element" in target.flags,
            metadata=metadata,
        )
        source_mutation = Mutation(
            op="set",
            path=("units", packet.target_id, "flags", "break_source"),
            before=target.flags.get("break_source"),
            after={
                "attacker_id": packet.attacker_id,
                "toughness_emission_id": packet.toughness_emission_id,
                "source_task_id": packet.source_task_id,
                "hit_profile_id": packet.hit_profile_id,
                "source_trace": packet.source_trace,
                "break_template_id": template.template_id,
                "break_template_source": template.source.to_json(),
            },
            reason="record weakness break source",
            source="break_system",
            before_exists="break_source" in target.flags,
            metadata=metadata,
        )
        lifecycle_mutations = (broken_mutation, element_mutation, source_mutation)
        if segments.maximum_segments > 1:
            lifecycle_mutations += (Mutation(
                op="set", path=("units", packet.target_id, "flags", "stance_segments_remaining"),
                before=1, after=0, reason="consume the final toughness segment",
                source="break_system", metadata=metadata,
            ),)
        current_state = self.reducer.apply_all(state, lifecycle_mutations)
        records: list[dict[str, JSONValue]] = [
            *_lifecycle_records(packet, template, lifecycle_mutations),
            _break_event_record(packet, template),
        ]
        mutations: list[Mutation] = list(lifecycle_mutations)
        events: list[GameEvent] = []
        rng_events: list[RNGEvent] = []

        notification = GameEvent(
            "break.triggered",
            source_id=packet.attacker_id,
            target_id=packet.target_id,
            event_id=f"event:{state.event_index}:break:{source_mutation.stable_id()}",
            window="break",
            process_only=True,
            payload={
                "callback_events": ["OnTriggerBreak", "OnListenBreak"],
                "attacker_id": packet.attacker_id,
                "actor_id": packet.attacker_id,
                "target_id": packet.target_id,
                "current_hit_target_id": packet.target_id,
                "element_type": packet.element_type,
                "break_template_id": template.template_id,
                "source_trace": metadata.get("source_trace", packet.source_trace),
            },
        )
        notification = replace(
            notification,
            break_notification_fact=BreakNotificationFact(
                source_mutation=source_mutation,
                event_id=str(notification.to_json()["event_id"]),
                event_index=state.event_index,
                target_id=packet.target_id,
                _producer_token=_BREAK_NOTIFICATION_PRODUCER,
            ),
        )
        # Install the target's broken-state callbacks before initial break
        # damage, so the hit consumes the post-break reduction state.
        entered = self.event_dispatcher.dispatch_event(
            current_state,
            event=replace(
                notification, event_type="break.entered", window="break_entered",
                event_id=f"{notification.event_id}:entered",
                payload={**notification.payload, "callback_events": ["OnBeingBreak"]},
            ),
        )
        if entered.errors:
            return _blocked(state, packet, ",".join(entered.errors), template=template)
        current_state = entered.after_state
        mutations.extend(entered.mutations)
        records.extend(entered.records)
        events.extend(replace(event, event_id=str(event.to_json()["event_id"])) for event in entered.events)
        rng_events.extend(entered.rng_events)

        for emission in self.rules.break_status_emissions_for_template(template.template_id):
            result = self._apply_status_emission(current_state, packet, template, emission)
            if not result.ok:
                return _blocked(
                    state, packet, ",".join(result.errors) or "break_status_emission_blocked",
                    template=template,
                )
            current_state = result.after_state
            mutations.extend(result.mutations)
            records.extend(result.records)
            events.extend(result.events)
            rng_events.extend(result.rng_events)

        for emission in self.rules.break_damage_emissions_for_template(template.template_id):
            result = self._apply_break_damage_emission(current_state, packet, template, emission)
            if not result.ok:
                return _blocked(
                    state, packet, ",".join(result.errors) or "break_damage_emission_blocked",
                    template=template,
                )
            current_state = result.after_state
            mutations.extend(result.mutations)
            records.extend(result.records)
            events.extend(result.events)
            rng_events.extend(result.rng_events)

        return BreakApplicationResult(
            ok=True,
            after_state=current_state,
            mutations=tuple(mutations),
            records=tuple(records),
            events=(*events, notification),
            rng_events=tuple(rng_events),
            # The dispatcher also returns callback audit markers. They belong
            # to this completed dispatch and must not be dispatched anew.
            dispatched_event_ids=entered.dispatched_event_ids | {
                str(event.to_json()["event_id"]) for event in entered.events
            },
            event_normalizations=entered.event_normalizations,
        )

    def _apply_break_damage_emission(
        self,
        state: BattleState,
        packet: ToughnessPacket,
        template: BreakTemplateIR,
        emission: BreakDamageEmissionIR,
    ) -> BreakApplicationResult:
        if emission.coverage_status != "executable":
            return BreakApplicationResult(
                ok=False,
                after_state=state,
                records=(
                    _break_damage_blocked_record(
                        packet,
                        template,
                        emission,
                        reason=emission.blocked_reason or f"break_damage_not_executable:{emission.coverage_status}",
                    ),
                ),
                errors=(emission.blocked_reason or f"break_damage_not_executable:{emission.coverage_status}",),
            )
        evaluation = self._evaluate_break_damage_amount(state, packet, template, emission)
        if not evaluation.ok or evaluation.value is None:
            return BreakApplicationResult(
                ok=False,
                after_state=state,
                records=(
                    _break_damage_blocked_record(
                        packet,
                        template,
                        emission,
                        reason=evaluation.blocked_reason or "break_damage_numeric_evaluation_failed",
                        evaluation=evaluation,
                    ),
                ),
                errors=(evaluation.blocked_reason or "break_damage_numeric_evaluation_failed",),
            )
        damage_result = self.damage.apply_packet(
            state,
            DamagePacket(
                attacker_id=packet.attacker_id,
                target_id=packet.target_id,
                attack_type="ElementDamage",
                damage_formula_family="break",
                amount=float(evaluation.value),
                amount_stage="family_base",
                element_type=emission.element_type or packet.element_type,
                break_damage_emission_id=emission.break_damage_emission_id,
                break_template_id=template.template_id,
                source_task_id=emission.source_task_id,
                hit_profile_id=packet.hit_profile_id,
                source_trace={
                    "break_damage_source": emission.source.to_json(),
                    "break_template_source": template.source.to_json(),
                    "toughness_source": packet.source_trace,
                },
                metadata={
                    **packet.metadata,
                    "damage_formula_family": "break",
                    "break_damage_emission_id": emission.break_damage_emission_id,
                    "break_template_id": template.template_id,
                    "source_task_id": emission.source_task_id,
                    "toughness_emission_id": packet.toughness_emission_id,
                    "numeric_evaluation": evaluation.to_json(),
                    "break_template_source": template.source.to_json(),
                    "break_damage_source": emission.source.to_json(),
                    "break_base_damage_source": _break_base_source_from_evaluation(evaluation),
                    "source_trace": {
                        "break_damage_source": emission.source.to_json(),
                        "break_template_source": template.source.to_json(),
                        "toughness_source": packet.source_trace,
                    },
                },
            ),
        )
        after_state = self.reducer.apply_all(state, damage_result.mutations)
        return BreakApplicationResult(
            ok=damage_result.ok,
            after_state=after_state,
            mutations=damage_result.mutations,
            records=damage_result.records,
            events=damage_result.events,
            errors=damage_result.errors,
            rng_events=damage_result.rng_events,
        )

    def _evaluate_break_damage_amount(
        self,
        state: BattleState,
        packet: ToughnessPacket,
        template: BreakTemplateIR,
        emission: BreakDamageEmissionIR,
    ) -> NumericEvaluationResult:
        actor = state.units.get(packet.attacker_id)
        target = state.units.get(packet.target_id)
        if actor is None or target is None:
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="break_damage",
                bindings={},
                source_trace=emission.source.to_json(),
                blocked_reason="actor_or_target_missing",
            )
        break_base = self.rules.break_base_damage(actor.level)
        if break_base is None or break_base.coverage_status != "executable":
            return NumericEvaluationResult(
                ok=False,
                value=None,
                expression_kind="break_damage",
                bindings={"actor_level": actor.level},
                source_trace=emission.source.to_json(),
                blocked_reason="break_base_damage_missing_or_not_executable",
            )
        source = _break_damage_binding_source(packet, template, emission, break_base.to_json(), target.max_toughness)
        return RuleEvaluator().evaluate_numeric(
            emission.scaling_expr,
            NumericEvaluationContext(
                binding_sources=(source,),
                source_trace={
                    "break_damage_source": emission.source.to_json(),
                    "break_template_source": template.source.to_json(),
                    "break_base_damage_source": break_base.source.to_json(),
                },
            ),
        )

    def _apply_status_emission(
        self,
        state: BattleState,
        packet: ToughnessPacket,
        template: BreakTemplateIR,
        emission: BreakStatusEmissionIR,
    ) -> BreakApplicationResult:
        effect = self.rules.effect(emission.effect_id)
        if emission.coverage_status != "executable":
            return BreakApplicationResult(
                ok=False,
                after_state=state,
                records=(
                    _break_status_record(
                        packet,
                        template,
                        emission,
                        reason=emission.blocked_reason or f"break_status_not_executable:{emission.coverage_status}",
                    ),
                ),
                errors=(emission.blocked_reason or f"break_status_not_executable:{emission.coverage_status}",),
            )
        if emission.condition_id:
            condition, condition_reason = self.rules.condition_resolution(emission.condition_id)
            if condition is None or condition.coverage_status != "executable" or type(emission.condition_expected) is not bool:
                reason = condition_reason or "break_status_condition_not_executable"
                return BreakApplicationResult(
                    ok=False, after_state=state,
                    records=(_break_status_record(packet, template, emission, reason=reason),),
                    errors=(reason,),
                )
            evaluated = self.evaluator.evaluate_condition_result(
                condition,
                self.targets.condition_evaluation_context(
                    state, condition,
                    context=TargetEvaluationContext(
                        caster_id=packet.attacker_id,
                        effect_owner_id=packet.target_id,
                        parameter_entity_ids=(packet.target_id,),
                        selected_target_ids=(packet.target_id,),
                        current_target_id=packet.target_id,
                    ),
                ),
            )
            if not evaluated.ok or evaluated.result is None:
                reason = evaluated.reason or "break_status_condition_unresolved"
                return BreakApplicationResult(
                    ok=False, after_state=state,
                    records=(_break_status_record(packet, template, emission, reason=reason),),
                    errors=(reason,),
                )
            if evaluated.result is not emission.condition_expected:
                return BreakApplicationResult(
                    ok=True, after_state=state,
                    records=(_break_status_record(packet, template, emission, reason="condition_branch_not_selected"),),
                )
        if effect is None:
            return BreakApplicationResult(
                ok=False,
                after_state=state,
                records=(_break_status_record(packet, template, emission, reason="effect_missing"),),
                errors=("effect_missing",),
            )
        binding_source, binding_error = self._status_binding_source(state, packet, template)
        if binding_error:
            return BreakApplicationResult(
                ok=False, after_state=state,
                records=(_break_status_record(packet, template, emission, reason=binding_error),),
                errors=(binding_error,),
            )
        result = self.effects.execute(
            effect,
            EffectExecutionContext(
                state=state,
                application_instance_id=(
                    f"break_status:{state.event_index}:{packet.attacker_id}:{packet.target_id}:"
                    f"{emission.break_status_emission_id}"
                ),
                caster_id=packet.attacker_id,
                source_id=emission.break_status_emission_id,
                owner_id=packet.target_id,
                param_entity_id=packet.target_id,
                current_action_target_id=packet.target_id,
                binding_sources=(binding_source,) if binding_source else (),
            ),
        )
        if result.unsupported:
            return BreakApplicationResult(
                ok=False, after_state=state, records=result.records,
                errors=tuple(str(item) for item in result.unsupported),
                rng_events=result.rng_events,
            )
        reduction = self.reducer.apply_all_result(state, result.mutations)
        if not reduction.ok:
            return BreakApplicationResult(
                ok=False, after_state=state,
                errors=("break_status_emission_mutation_conflict",),
            )
        after_state = reduction.after_state
        reason = "executed"
        if result.unsupported and result.mutations:
            reason = "executed_partial"
        elif not result.mutations:
            reason = "effect_produced_no_mutation"
        records = [
            _break_status_record(
                packet,
                template,
                emission,
                reason=reason,
                mutation_ids=[mutation.stable_id() for mutation in result.mutations],
            ),
            *result.records,
        ]
        return BreakApplicationResult(
            ok=True,
            after_state=after_state,
            mutations=result.mutations,
            records=tuple(records),
            events=result.events,
            rng_events=result.rng_events,
        )

    def _status_binding_source(
        self, state: BattleState, packet: ToughnessPacket, template: BreakTemplateIR,
    ) -> tuple[dict[str, JSONValue], str]:
        if not template.status_numeric_bindings:
            return {}, ""
        caster = state.units.get(packet.attacker_id)
        target = state.units.get(packet.target_id)
        if caster is None or target is None:
            return {}, "break_status_binding_unit_missing"
        entries: dict[str, JSONValue] = {}
        by_hash: dict[str, JSONValue] = {}
        by_name: dict[str, JSONValue] = {}
        for binding in template.status_numeric_bindings:
            name = binding.get("name")
            hash_key = binding.get("hash")
            source_kind = binding.get("value_source")
            if not isinstance(name, str) or not isinstance(hash_key, str):
                return {}, "break_status_binding_ir_invalid"
            owner_id = packet.target_id
            source_trace: dict[str, JSONValue] = {"break_template_source": template.source.to_json()}
            if source_kind == "target_max_toughness_old_units":
                value = target.max_toughness
            elif source_kind == "caster_level_break_base_damage":
                base = self.rules.break_base_damage(caster.level)
                if base is None or base.coverage_status != "executable":
                    return {}, "break_status_base_damage_missing"
                value = base.break_base_damage
                owner_id = packet.attacker_id
                source_trace["break_base_damage"] = base.to_json()
            elif source_kind == "constant":
                value = binding.get("value")
                if not isinstance(value, (int, float)):
                    return {}, "break_status_unit_base_missing"
            else:
                return {}, "break_status_binding_source_unsupported"
            key = f"binding_{len(entries)}"
            entries[key] = {
                "scope": "break_template", "owner_id": owner_id,
                "name": name, "hash": hash_key, "value": float(value),
                "source_trace": source_trace,
            }
            by_hash[hash_key] = [key]
            by_name[name] = [key]
        return {
            "source_type": "break_template_runtime_value",
            "entries": entries, "by_hash": by_hash, "by_name": by_name,
        }, ""

    def recover_from_break_status(
        self,
        state: BattleState,
        *,
        unit_id: str,
        modifier_name: str,
    ) -> BreakApplicationResult:
        target = state.units.get(unit_id)
        if target is None:
            return BreakApplicationResult(ok=False, after_state=state, errors=("target_missing",))
        detail = find_status_detail(state, unit_id, modifier_name=modifier_name)
        if detail is None:
            return BreakApplicationResult(
                ok=False,
                after_state=state,
                records=(
                    SettlementRecord(
                        record_type="break_recovery_blocked",
                        source="break_system",
                        process_only=True,
                        payload={"reason": "break_status_detail_missing", "target_id": unit_id, "modifier_name": modifier_name},
                        trace={},
                    ).to_json(),
                ),
                errors=("break_status_detail_missing",),
            )
        recovery_contract = _break_recovery_contract(detail)
        emission_id = str(recovery_contract.get("break_status_emission_id") or "")
        if not emission_id:
            reason = "break_recovery_source_missing"
            return BreakApplicationResult(
                ok=False,
                after_state=state,
                records=(
                    SettlementRecord(
                        record_type="break_recovery_blocked",
                        source="break_system",
                        process_only=True,
                        payload={"reason": reason, "target_id": unit_id, "modifier_name": modifier_name},
                        trace=_json_dict(detail.get("source_trace")),
                    ).to_json(),
                ),
                errors=(reason,),
            )
        emission = self.rules.break_status_emission(emission_id)
        if emission is None or emission.coverage_status != "executable":
            reason = "break_status_emission_not_executable_for_recovery"
            return BreakApplicationResult(
                ok=False,
                after_state=state,
                records=(
                    SettlementRecord(
                        record_type="break_recovery_blocked",
                        source="break_system",
                        process_only=True,
                        payload={"reason": reason, "target_id": unit_id, "break_status_emission_id": emission_id},
                        trace=_json_dict(detail.get("source_trace")),
                    ).to_json(),
                ),
                errors=(reason,),
            )
        status_id = str(detail.get("status_id") or f"modifier:{modifier_name}")
        status_details = [
            item
            for item in target.flags.get("status_details", ())
            if not (isinstance(item, dict) and item.get("instance_id") == detail.get("instance_id"))
        ]
        metadata: dict[str, JSONValue] = {
            "break_recovery": {
                "reason": "break_status_expire_or_recovery",
                "break_status_emission_id": emission_id,
                "status_instance_id": str(detail.get("instance_id") or ""),
                "modifier_name": modifier_name,
            },
            "source_trace": {
                "break_status_source": emission.source.to_json(),
                "status_instance_source": _json_dict(detail.get("source_trace")),
            },
        }
        mutations = [
            Mutation(
                op="set",
                path=("units", unit_id, "flags", "broken"),
                before=target.flags.get("broken"),
                after=False,
                reason="recover from weakness break",
                source="break_system",
                before_exists="broken" in target.flags,
                metadata=metadata,
            ),
            Mutation(
                op="delete",
                path=("units", unit_id, "flags", "break_element"),
                before=target.flags.get("break_element"),
                after=None,
                reason="clear break element",
                source="break_system",
                after_exists=False,
                metadata=metadata,
            ),
            Mutation(
                op="delete",
                path=("units", unit_id, "flags", "break_source"),
                before=target.flags.get("break_source"),
                after=None,
                reason="clear break source",
                source="break_system",
                after_exists=False,
                metadata=metadata,
            ),
            Mutation(
                op="set",
                path=("units", unit_id, "toughness"),
                before=target.toughness,
                after=target.max_toughness,
                reason="restore toughness after break recovery",
                source="break_system",
                metadata=metadata,
            ),
            Mutation(
                op="set",
                path=("units", unit_id, "statuses"),
                before=list(target.statuses),
                after=[item for item in target.statuses if item != status_id],
                reason="remove break status on recovery",
                source="break_system",
                metadata=metadata,
            ),
            Mutation(
                op="set",
                path=("units", unit_id, "flags", "status_details"),
                before=list(target.flags.get("status_details", ())) if "status_details" in target.flags else None,
                after=status_details,
                reason="remove break status detail on recovery",
                source="break_system",
                before_exists="status_details" in target.flags,
                metadata=metadata,
            ),
        ]
        after_state = self.reducer.apply_all(state, tuple(mutations))
        records = tuple(
            SettlementRecord(
                record_type="break_recovery",
                source="break_system",
                mutation_id=mutation.stable_id(),
                process_only=False,
                payload={
                    "target_id": unit_id,
                    "field": mutation.path[-1],
                    "break_status_emission_id": emission_id,
                    "status_instance_id": str(detail.get("instance_id") or ""),
                    "modifier_name": modifier_name,
                },
                trace=metadata["source_trace"],
            ).to_json()
            for mutation in mutations
        )
        return BreakApplicationResult(ok=True, after_state=after_state, mutations=tuple(mutations), records=records)


def _break_metadata(packet: ToughnessPacket, template: BreakTemplateIR) -> dict[str, JSONValue]:
    return {
        **packet.to_json(),
        **packet.metadata,
        "break_template_id": template.template_id,
        "break_template_source": template.source.to_json(),
        "source_trace": {
            "toughness_source": packet.source_trace,
            "break_template_source": template.source.to_json(),
        },
        "break_lifecycle": {
            "reason": "toughness_depleted",
            "event_types": ["OnTriggerBreak", "OnBeingBreak"],
            "break_template_id": template.template_id,
            "break_damage_status": "blocked_or_pending_admission",
            "break_status_status": "effect_registry_driven",
        },
    }


def _lifecycle_records(
    packet: ToughnessPacket,
    template: BreakTemplateIR,
    mutations: tuple[Mutation, ...],
) -> tuple[dict[str, JSONValue], ...]:
    records: list[dict[str, JSONValue]] = []
    for mutation in mutations:
        field = mutation.path[-1] if mutation.path else ""
        records.append(
            SettlementRecord(
                record_type="break_lifecycle",
                source="break_system",
                mutation_id=mutation.stable_id(),
                process_only=False,
                payload={
                    "target_id": packet.target_id,
                    "field": field,
                    "event_types": (["OnBeingStanceCountDown", "OnTriggerStanceCountDown"]
                                    if template.trigger_kind == "stance_count_down"
                                    else ["OnTriggerBreak", "OnBeingBreak"]),
                    "toughness_emission_id": packet.toughness_emission_id,
                    "source_task_id": packet.source_task_id,
                    "hit_profile_id": packet.hit_profile_id,
                    "break_element": packet.element_type,
                    "break_template_id": template.template_id,
                    "break_template_source": template.source.to_json(),
                    "break_damage_status": "blocked_or_pending_admission",
                },
                trace={
                    "toughness_source": packet.source_trace,
                    "break_template_source": template.source.to_json(),
                },
            ).to_json()
        )
    return tuple(records)


def _break_event_record(packet: ToughnessPacket, template: BreakTemplateIR) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="break_event",
        source="break_system",
        process_only=True,
        payload={
            "actor_id": packet.attacker_id,
            "target_id": packet.target_id,
            "element_type": packet.element_type,
            "events": ["OnTriggerBreak", "OnBeingBreak"],
            "toughness_emission_id": packet.toughness_emission_id,
            "break_template_id": template.template_id,
            "global_listener_status": "blocked_not_admitted",
            "being_hit_listener_status": "blocked_not_admitted",
            "per_hit_trigger_status": "blocked_not_admitted",
        },
        trace={
            "toughness_source": packet.source_trace,
            "break_template_source": template.source.to_json(),
        },
    ).to_json()


def _break_status_record(
    packet: ToughnessPacket,
    template: BreakTemplateIR,
    emission: BreakStatusEmissionIR,
    *,
    reason: str,
    mutation_ids: list[str] | None = None,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="break_status",
        source="break_system",
        process_only=True,
        payload={
            "reason": reason,
            "target_id": packet.target_id,
            "break_template_id": template.template_id,
            "break_status_emission_id": emission.break_status_emission_id,
            "effect_id": emission.effect_id,
            "opcode": emission.opcode,
            "modifier_name": emission.modifier_name,
            "coverage_status": emission.coverage_status,
            "mutation_ids": mutation_ids or [],
        },
        trace={
            "break_status_source": emission.source.to_json(),
            "break_template_source": template.source.to_json(),
        },
    ).to_json()


def _break_damage_blocked_record(
    packet: ToughnessPacket,
    template: BreakTemplateIR,
    emission: BreakDamageEmissionIR,
    *,
    reason: str,
    evaluation: NumericEvaluationResult | None = None,
) -> dict[str, JSONValue]:
    return SettlementRecord(
        record_type="break_damage_blocked",
        source="break_system",
        process_only=True,
        payload={
            "reason": reason,
            "target_id": packet.target_id,
            "break_template_id": template.template_id,
            "break_damage_emission_id": emission.break_damage_emission_id,
            "source_task_id": emission.source_task_id,
            "damage_formula_family": emission.damage_formula_family,
            "coverage_status": emission.coverage_status,
            "scaling_expr": emission.scaling_expr,
            "blocking_dependency": reason,
            "numeric_evaluation": evaluation.to_json() if evaluation else {},
        },
        trace={
            "break_damage_source": emission.source.to_json(),
            "break_template_source": template.source.to_json(),
        },
    ).to_json()


def _break_damage_binding_source(
    packet: ToughnessPacket,
    template: BreakTemplateIR,
    emission: BreakDamageEmissionIR,
    break_base_damage: dict[str, JSONValue],
    target_stance: float,
) -> dict[str, JSONValue]:
    entries: dict[str, JSONValue] = {}
    if emission.base_damage_hash:
        entries["break_base_damage"] = {
            "scope": "break_template",
            "owner_id": packet.attacker_id,
            "name": "CasterBreakBaseDamage",
            "hash": emission.base_damage_hash,
            "value": float(break_base_damage.get("break_base_damage") or 0.0),
            "source_trace": {
                "dynamic_key": "CasterBreakBaseDamage",
                "break_base_damage": break_base_damage,
                "break_template_source": template.source.to_json(),
            },
        }
    if emission.target_toughness_hash:
        entries["target_stance"] = {
            "scope": "break_template",
            "owner_id": packet.target_id,
            "name": "TargetStance",
            "hash": emission.target_toughness_hash,
            "value": float(target_stance),
            "source_trace": {
                "dynamic_key": "TargetStance",
                "target_field": "max_toughness",
                "toughness_source": packet.source_trace,
                "break_template_source": template.source.to_json(),
            },
        }
    return {
        "source_type": "break_template_runtime_value",
        "entries": entries,
        "by_hash": {
            str(item["hash"]): [key]
            for key, item in entries.items()
            if isinstance(item, dict) and isinstance(item.get("hash"), str)
        },
        "by_name": {
            str(item["name"]): [key]
            for key, item in entries.items()
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        },
    }


def _break_base_source_from_evaluation(evaluation: NumericEvaluationResult) -> dict[str, JSONValue]:
    bindings = evaluation.bindings
    operands = bindings.get("dynamic_operands") if isinstance(bindings, dict) else None
    if not isinstance(operands, list):
        return {}
    for operand in operands:
        if not isinstance(operand, dict):
            continue
        binding = operand.get("bindings")
        if not isinstance(binding, dict):
            continue
        entry = binding.get("entry")
        if not isinstance(entry, dict) or entry.get("name") != "CasterBreakBaseDamage":
            continue
        source_trace = entry.get("source_trace")
        if isinstance(source_trace, dict):
            break_base = source_trace.get("break_base_damage")
            return break_base if isinstance(break_base, dict) else source_trace
    return {}


def _break_recovery_contract(detail: dict[str, JSONValue]) -> dict[str, JSONValue]:
    emission_id = detail.get("break_status_emission_id")
    if not isinstance(emission_id, str) or not emission_id:
        return {}
    source_trace = _json_dict(detail.get("source_trace"))
    return {
        "break_status_emission_id": emission_id,
        "source_trace": source_trace,
    }


def _json_dict(value: object) -> dict[str, JSONValue]:
    return value if isinstance(value, dict) else {}


def _blocked(
    state: BattleState,
    packet: ToughnessPacket,
    reason: str,
    *,
    template: BreakTemplateIR | None = None,
) -> BreakApplicationResult:
    return BreakApplicationResult(
        ok=False,
        after_state=state,
        records=(
            SettlementRecord(
                record_type="break_lifecycle_blocked",
                source="break_system",
                process_only=True,
                payload={
                    "reason": reason,
                    "target_id": packet.target_id,
                    "element_type": packet.element_type,
                    "toughness_emission_id": packet.toughness_emission_id,
                    "break_template_id": template.template_id if template else "",
                },
                trace={
                    "toughness_source": packet.source_trace,
                    "break_template_source": template.source.to_json() if template else {},
                },
            ).to_json(),
        ),
        errors=(reason,),
    )


def _skipped(state: BattleState, packet: ToughnessPacket, reason: str) -> BreakApplicationResult:
    return BreakApplicationResult(
        ok=True,
        after_state=state,
        records=(
            SettlementRecord(
                record_type="break_lifecycle_skipped",
                source="break_system",
                process_only=True,
                payload={
                    "reason": reason,
                    "target_id": packet.target_id,
                    "element_type": packet.element_type,
                    "toughness_emission_id": packet.toughness_emission_id,
                },
                trace=packet.source_trace,
            ).to_json(),
        ),
    )
