# P9-A2-P6 emission-backed damage audit-reference admission

> 固定基线：`5f9f909e276811bb36fc3bb6701633dc25e4ff27`
>
> pinned TBGD：`14c1d18f91a8101d610e6c523447a7517de3fae1`
> 风险：`STRICT`

## 目标

仅退役已通过 `ability_task_runtime_blocked_reason(..., task_graph)` 的
`DamageByAttackProperty` task 自身 audit-only EffectIR reference 所产生的重复
ActionContract blocker。EffectIR 和 reference 继续保持 `audit_only` / `deferred`，伤害执行仍只由
既有 DamageEmissionIR、HitProfileIR、ToughnessEmissionIR 和 AbilityTaskSystem 负责。

## 唯一 production authority

`systems/action_contract.py`。例外要求 executable runtime-effect damage task、空
`parent_task_id`、materialized execution-only leaf、唯一 own-effect audit reference、非空 damage
emission，以及 EffectIR source 严格等于 canonical task source 仅加回
`parent_task_id=""`。canonical task source 不得包含 `parent_task_id` 或 `child_task_count`；任意其它
source evidence 差异继续 fail-closed。

## 非目标

不修改 lowering、materializer、AbilityTaskIR、EffectIR、damage runtime、公式、目标、韧性、事件、
settlement、RNG 或 replay；不执行 ActionCommand，不恢复 PR #11。

## 验证

聚焦测试覆盖精确正例和 source/runtime/node/reference 反例；复用 P1、P2、A1 Fast。Direct 复用
P0/P5 raw TriggerAbility 到 source-graph action binding，比较固定基线和当前相同候选的 provenance，
证明只移除三条 damage audit blocker、IR/reference 不变且 runtime channel 全为零。
