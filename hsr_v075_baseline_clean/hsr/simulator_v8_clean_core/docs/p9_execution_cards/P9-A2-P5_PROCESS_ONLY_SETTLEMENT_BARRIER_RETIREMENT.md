# P9-A2-P5 source-proven process-only settlement barrier retirement

> 固定基线：`8064d5ab01837d1ebb4d8388ca072796c7946634`
>
> pinned TBGD：`14c1d18f91a8101d610e6c523447a7517de3fae1`
> 风险：`STRICT`

## 目标

仅退役 source-proven、`$type`-only `DamagePerformFinish` / `SkillPerformFinish`
settlement barrier 的陈旧 `damage_heal_shield` owner。它们仍是带 exact same-source
`audit_only` EffectIR reference 的 process-only leaf，绝不成为可执行 gameplay effect。

## 唯一 production authority

`tbgd/task_graph_materializer.py`。复用 lowering 的
`_process_only_ability_task_source_blocked_reason(...)` 和已经 emitted 的
`process_only_contract`，复用 control-flow 的实际 `peer_field_names` /
`field_responsibilities`，以及 P3 source-sensitive disposition 结构。

例外必须同时满足：两目标 family、`settlement_barrier`、未 blocked、空 peer fields /
responsibilities、无 branch/template、无 condition/target/ability reference、process-only
`audit_only` task、有唯一同 source audit effect，且 effect contract 的 source fields 精确为
`["$type"]`。任何 settlement payload（`IsFakeAvatarAttack`、`SkipDeathSettlement`、
`SkipAttackSettlement`）继续 deferred 给 S11。

## 非目标

不实现 `DamageByAttackProperty`、伤害、治疗、护盾、HP mutation、settlement、S11 event、
PR11 transport 或 PR9 RNG；不改变 ActionContract；outer action 不要求 executable。

## 验证

聚焦 Fast、P3 regression、scoped compile、A1 Fast、fixed-base diff，以及真实 Direct。Direct
动态重建 A/B/C source denominator，动态发现 action-window `TriggerAbility` 候选，比较基线与
当前 same-owner provenance，并确认 runtime graph/mutation/event/RNG/settlement/replay 均为零。
