# P9-A2-P6 execution report

固定基线为 `5f9f909e276811bb36fc3bb6701633dc25e4ff27`，pinned TBGD 为
`14c1d18f91a8101d610e6c523447a7517de3fae1`。

## 实现

`ActionContract` 在既有 `ability_task_runtime_blocked_reason(..., task_graph)` 返回空之后，识别唯一
emission-backed damage audit reference。谓词要求 executable `DamageByAttackProperty`、非空 damage
emission、materialized execution-only leaf、唯一 deferred own-effect reference，以及 EffectIR source
严格等于 canonical task source 仅增加 `parent_task_id=""`。canonical source 含拓扑键、任意额外
evidence 差异、额外 reference 或 runtime support 失败时均保持阻断。

没有修改 task、effect、emission、profile、toughness emission 或 task-graph reference；没有新增伤害
执行语义。

## Direct evidence

Direct 通过 P0/P5 raw TriggerAbility occurrence → scope record → source-graph binding 动态发现：

- action：`avatar_skill:1100601`，level `1`，definition
  `action_def:avatar_skill:1100601:1`；
- owner avatar：`1006`；
- scope record：`character_ability_scope:43c60262eef2491525e997e3`；
- source graph binding：
  `character_ability_binding:b5221d35c1cbbf6baf36ed0e31abfb312238fbc8bef4389fe2e4828c5e031fff`。

完整 target task denominator 为：

1. `ability_task:ability_phase:avatar_skill:1100601:1:1:Avatar_Advanced_Silwolf_00_Skill01_Phase02:OnStart:OnStart[1]:DamageByAttackProperty`
2. `ability_task:ability_phase:avatar_skill:1100601:1:1:Avatar_Advanced_Silwolf_00_Skill01_Phase02:OnStart:OnStart[3]:DamageByAttackProperty`
3. `ability_task:ability_phase:avatar_skill:1100601:1:1:Avatar_Advanced_Silwolf_00_Skill01_Phase02:OnStart:OnStart[5]:DamageByAttackProperty`

三项 task 均为 `executable`、空 blocked reason、空 runtime-support reason。每项各有一条 executable
DamageEmissionIR 和一条匹配的 executable ToughnessEmissionIR，共用 executable profile
`hit_profile:avatar_skill:1100601:1:0:selected:slot:0`，action/level/phase 绑定闭合。

三项 canonical task source 均不含 `parent_task_id` / `child_task_count`。每项 EffectIR source 的
source_path/raw_type/raw_id 与 task 相同，evidence delta 均精确为新增 `parent_task_id=""`：无删除、无
值变化、无其它新增键。EffectIR 仍为 `audit_only`，唯一 reference 仍为 `deferred` 且 blocker 字段仍为
`task_graph_definition_not_admitted:effect:audit_only`。

固定基线的 blocker provenance 恰有上述三项 graph-reference rows；当前只移除这三项，added rows 为
0，所有 task/effect/node/reference/emission/profile/toughness 对象与基线相同。当前 remaining blockers
为空，`ActionContract.ok=true`，`predecessor_chain_empty=true`。

task graph execute、condition evaluation、RNG、mutation、event、settlement 和 replay channel 全为 0。
Direct wall `40.852493s`，peak RSS `455856 KiB`。

## 验证结果

- P6 focused pytest：19 passed。
- scoped compile：通过。
- A1 Fast：11 cases，`ok=true`。
- P6 Direct：`ok=true`。
- P1 source-identity functional Fast：按 AMEND-9 仅隔离历史 fixed-base governance，完整
  `run_fast()` functional matrix 及嵌入 A1 Fast 执行，19 predicates 全部为 true，`ok=true`。
- P2 process-only TriggerAbility functional Fast：按 AMEND-9 仅隔离历史 fixed-base governance，完整
  `run_fast()` functional matrix 及嵌入 A1 Fast 执行，8 predicates 全部为 true，`ok=true`。
- fixed-base `git diff --check`：通过。

全部 Required Validation 已按 AMEND-9 的验证目标、参数、模式和 evidence semantics 执行并通过。
