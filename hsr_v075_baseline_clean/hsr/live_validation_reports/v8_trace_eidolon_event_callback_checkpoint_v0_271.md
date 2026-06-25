# v8 v0_271 Trace / Eidolon / Event Callback Checkpoint

## Scope

This checkpoint closes the generic pre-character-card plumbing needed before adding more character cards:

- Trace static stat bonuses are now executable character-card assembly inputs.
- Eidolon support is limited to generic switch ordering, skill-level bonuses, and event-listener slots.
- Foundational event callback names are exposed through the event dispatch admission layer.

Runtime still consumes Canonical IR only. TextMap, raw TBGD files, and character names remain outside runtime systems.

## Implemented

- `trace_static_stat_bonus` slots now map supported status properties into panel/resource adjustments when the trace node is enabled.
- Scenario state flags record enabled trace node ids, source traces, applied stat terms, resource adjustments, and blocked trace slots.
- Eidolon level configuration remains a single 0-6 value; enabling a higher eidolon activates earlier eidolons.
- Eidolon skill-level bonuses now feed action level / parameter binding as character-card assembly source instead of temporary scenario-only flags.
- Event-listener eidolon slots are admitted only through the existing event dispatch/effect paths; unsupported special slots stay blocked with dependency.
- Event aliases now include action, hit, status lifecycle, turn end, queue/insert, custom, and wave hooks.
- `OnListenTurnEnd` has an explicit admission guard in scheduler state flags, so ordinary scheduler regression does not accidentally execute global turn-end listeners.

## Still Blocked

- `OnCustomEvent` has a stable event shape but no executable custom-event source in this stage.
- `OnWaveMonster` has a stable event shape but remains blocked until the wave system exists.
- Special eidolon mechanics are not auto-generalized. They must be manually interpreted into generic character-card slots when building that character card.
- Trace ability hooks execute only when their linked ability/effect/listener is already admitted.

## Validation

Required validations for this checkpoint:

- `compileall`
- `validate_v0_225`
- `validate_v0_245`
- `validate_v0_266`
- `validate_v0_270`
- `validate_v0_271`
- `git diff --check`

`validate_v0_271` covers trace stat enable/disable, eidolon prefix activation, eidolon skill-level bonus binding, a real admitted turn-end listener callback, runtime boundary checks, settlement traceability, replay, and source audit.
