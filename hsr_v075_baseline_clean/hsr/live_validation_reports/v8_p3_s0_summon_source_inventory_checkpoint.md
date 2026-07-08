# v8 P3-S0 召唤物来源全量盘点和术语归一检查点

日期：2026-07-06
复查更新：2026-07-08

## 本步完成

- 新增 `simulator_v8_clean_core.tools.validate_p3_s0_summon_source_inventory`，只做来源盘点和覆盖矩阵验证，不改变 runtime 行为。
- 输出轻量矩阵到 `/tmp/hsr_v8_p3_s0_summon_source_inventory`：
  - `validation_summary_p3_s0_summon_source_inventory.json`
  - `p3_summon_source_inventory_matrix_s0.json`
- 矩阵覆盖 `SummonMonster`、`SummonUnitData` / `ConfigSummonUnit`、`MonsterConfig.SummonIDList` catalog ref、`AvatarServantConfig`、`AvatarServantSkillConfig`、servant ability files、`TurnInsertAssistantAbility` scope exclusion、召唤/servant target alias 与 operation、owner/remove/expire/wave/actionability lifecycle 候选来源。
- raw TBGD 只在 tools 层读取；runtime 仍只读 Canonical IR / RuleBook。
- 默认输出 summary、domain matrix 和少量 sample source trace，不写完整 Canonical IR、coverage 大产物或 transition dump。

## 关键计数

```text
domain_count=10
unclassified_count=0
classification_counts.executable=4
classification_counts.boundary_only=3
classification_counts.source_absent_not_required=2
classification_counts.out_of_scope=1
source_item_counts.gap_total=2150

summon_monster_raw_count=895
summon_monster_ir_count=775
summon_unit_raw_count=36
summon_unit_ir_count=36
servant_raw_count=6
servant_ir_count=6
assistant_raw_count=5
assistant_resolution_ir_count=5
p3_target_raw_count=8618
p3_target_ir_count=8969
lifecycle_raw_count=14048
lifecycle_ir_count=1109
```

Domain 分类摘要：

```text
summoned_monster_intent: executable, raw=895, ir=775, executable=14, blocked=761
summon_unit_config_catalog: boundary_only, raw=36, ir=36, blocked=36, gap=0
battle_unit_summon_candidate: source_absent_not_required, raw=0, ir=0
client_scene_adventure_summon: source_absent_not_required, raw=36, ir=36, blocked=36
monster_summon_catalog_ref: boundary_only, raw=658, ir=658
servant_definition: executable, raw=6, ir=6, executable=6
servant_skill_and_ability_files: executable, raw=440, ir=440, executable=440
assistant_ability_queue: out_of_scope, raw=5, ir=5, blocked=5, gap=0
summon_target_expression: executable, raw=8618, ir=8969, blocked_gap=342
lifecycle_cleanup_and_actionability_sources: boundary_only, raw=14048, ir=1109, executable=27, blocked=1047, gap=0
```

## 新增或修正的来源分类

- `SummonMonster` 已有 executable 子集，但多数 blocked entry 指向固定 monster id、profile/card、delay admission 等后续缺口；raw occurrence 与 IR intent 不强制一一相等，因为 AbilityTaskIR 会按 action/level/source binding 展开。
- `SummonUnitData` 不能整体视为 battle spawn。经 P3-S4 来源拆分回归后，当前 36 条全部归为 client / visual / adventure / maze / destroy-on-enter-battle / catalog 边界；当前数据库没有可执行 battle runtime trigger。
- `MonsterConfig.SummonIDList` 明确是 catalog ref，不是 runtime trigger。
- servant / 忆灵定义与 servant skill 当前有 executable IR 来源；这只说明定义、动作来源链路已入账，不等于 P3 servant 伤害/资源/生命周期联动全部完成。
- `TurnInsertAssistantAbility` 5 条 raw 均已进入 queue intent / assistant resolution IR；复核后确认其属于 AssistantAvatar / avatar assistant ability 系统，不具备 summon monster、UnitSpawn、servant lifecycle 或 SummonUnit runtime entity 语义，S0 分类改为 `out_of_scope`，不计入 P3 gap。
- summon / servant target 来源已入账，包含全局 `TargetAliasConfig` / `TargetOperationConfig` 中的 `GetServant`、`RemoveServant`、`GetSummoner`、`GetSummonedMinions` 等；当前全量 P3 target 仍有 `admission_gap=342`。`FriendServantSelect` / `AssistantAvatar` 已移出 P3 target gap 矩阵，只在 assistant target boundary 中记录 `out_of_scope`。
- 复查修正：`SummonMonster` 的 pure fixed postfix monster id、unique monster profile/card、DelayRatio、fixed ID 规范化、跨 TriggerKey SkillParam binding 已 admission；剩余 summoned monster 子项按具体 blocked reason 拆为 `admission_gap=1781`、`source_gap_blocked=27`。当前 `lowering_gap=0`、`implementation_missing=0`，不再把缺 profile/card 真实来源或缺 custom hash 绑定误归为 lowering / implementation。
- 复查修正：`OnEnterBattle` 已接入 runtime event source `battle.setup`，`lifecycle_cleanup_and_actionability_sources` 内部 admission gap 清零，当前保持 boundary-only 分类。

## 对最终验收的影响

本报告是来源盘点通过，不是 P3 完成验收。以下 S0 gap 必须被 P3-S12 聚合继承：

```text
summon_target_expression: admission_gap=342
summoned_monster_intent: admission_gap=1781
summoned_monster_intent: source_gap_blocked=27
```

`summoned_monster_intent`、`summon_target_expression` 等 domain 有 executable 正例，但不能用正例代表整个来源域完成；内部未投影/未准入子项仍是 P3 总验收 blocker。

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
ionice -c2 -n7 nice -n 10 python3 -B -m simulator_v8_clean_core.tools.validate_p3_s0_summon_source_inventory --output-dir /tmp/hsr_v8_p3_s0_gap_repair_v4
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

关键输出：

```text
v8 p3_s0_summon_source_inventory validation ok=True
```

## 本步没有完成

- 没有改 runtime schema、spawn/remove/action/target 执行逻辑。
- 没有新增 `SummonUnitData` battle runtime spawn；当前数据库无真实 battle runtime trigger，保持 source-absent / boundary。
- 没有放开 AssistantAvatar / avatar assistant ability execution；它已移出 P3 召唤物/servant 验收范围。
- 没有清零 summoned monster blocked entry 或 target admission gap；当前 source gap blocked 的 summoned monster profile/card 缺口有证据保留，不能改名为 boundary。lifecycle cleanup/actionability 的 S0 admission gap 已清零，但仍只是来源盘点边界，不代表所有 lifecycle 行为完成。

## 后续影响

- P3-S1 应优先基于本矩阵补 IR / RuleBook 契约字段和查询 API，而不是直接改 runtime。
- P3-S4 已把 `SummonUnitData` 的 battle runtime candidate 回正为当前数据库 source absent；后续若数据库新增真实 battle trigger，应先更新来源矩阵和 admission。
- P3-S7 已把 AssistantAvatar queue/window 统一为 out_of_scope + boundary audit。
- P3-S8 已把 `FriendServantSelect` / AssistantAvatar target boundary 统一为 out_of_scope；342 条 summon/servant target admission gap 仍需要后续处理。
