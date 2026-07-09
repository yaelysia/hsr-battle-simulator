# v8 P4-S6 Monster Passive Listener Wave Ready For Review

日期：2026-07-08

阶段状态：`ready_for_review`。本报告是执行线程证据包，不修改 `P4_COMBATANT_DATA_CARD_EXPANSION_TASK_PLAN.md` 第 22 节 checklist，不声明 `done`。

## 阶段执行卡

阶段：P4-S6 怪物被动、监听、阶段、波次、召唤交叉边界。

目标产物：

- 输出 monster passive/listener/wave matrix，覆盖 startup/on enter、turn/action、hit/damage、death/phase、wave、global listener、summon refs、summon lifecycle relation、stage/environment scope。
- 对已有真实 event source / payload / condition / target / task 的 status callback 保留 executable 统计。
- 对缺 event source、缺 payload、缺 wave runtime、缺 stage/environment 系统、缺 summon lifecycle admission 的路径保留 blocked/process-only/state unchanged 边界。
- 不把 stage/environment 规则伪装成 monster card runtime，不按怪物名、技能文本或固定 ID 识别被动。

本阶段实际改动文件：

- `simulator_v8_clean_core/tools/validate_p4_s6_monster_passive_listener_wave.py`
- `live_validation_reports/v8_p4_s6_monster_passive_listener_wave_ready_for_review.md`

本阶段未修改：

- 未改 runtime / lowering / RuleBook / executor 语义。
- 未新增怪物名、MonsterID、技能 ID 特判。
- 未新增敌方 AI、stage/environment runtime 或 wave runtime fallback。
- 未为怪物召唤物复制特殊技能/属性系统。
- 未改 P4 第 22 节 checklist。
- 未新增 P4-S12 聚合脚本。

## 验证输出

输出目录：

```text
/tmp/hsr_v8_p4_s6_monster_passive_listener_wave
```

主要文件：

```text
/tmp/hsr_v8_p4_s6_monster_passive_listener_wave/validation_summary_p4_s6_monster_passive_listener_wave.json
/tmp/hsr_v8_p4_s6_monster_passive_listener_wave/p4_s6_monster_passive_listener_wave_matrix.json
```

S6 主验证：

```text
ok=True
row_count=9
unclassified_count=0

classification_counts:
  admission_gap=7
  boundary_only=1
  out_of_scope=1

monster_callback_count=6664
monster_passive_slot_count=309
wave_definition_count=28296

gap_attribution_counts:
  admission_gap=10464
```

## Matrix 摘要

```text
monster_status_callback_event_matrix: admission_gap, raw=6664, executable=2518, gap=4146
monster_listener_event_bucket_matrix: admission_gap, raw=4153, executable=2094, gap=2059
monster_global_listener_boundary: admission_gap, raw=781, executable=48, gap=733
monster_passive_slot_matrix: admission_gap, raw=309, executable=0, gap=309
wave_definition_entry_matrix: admission_gap, raw=123800, executable=122714, gap=1086
wave_monster_event_payload_boundary: boundary_only, mutation_count=0, state unchanged
monster_summon_refs_boundary: admission_gap, raw=1370, executable=0, gap=1370
summon_intent_lifecycle_relation_matrix: admission_gap, raw=775, executable=14, gap=761
stage_environment_scope_boundary: out_of_scope, stage_ability_ref_count=6502
```

说明：

- `wave_definition_entry_matrix` 的 `raw` 是 wave definitions 与 wave entries 合计；details 中保留 definition / entry 拆分。
- 样本 ID 只作为验证输出，不作为选择条件。
- 本阶段没有把任何 blocked / out_of_scope source 转成 mutation。

## Callback 与 Listener 归因

怪物 status callbacks：

```text
total=6664
executable=2518
blocked=4146
```

主要 blocked dependency：

```text
status_callback_event_not_admitted:OnCreate=487
status_callback_event_not_admitted:OnDestroy=449
status_callback_event_not_admitted:OnBeingBreak=393
status_callback_source_mode_not_admitted=336
status_callback_event_not_admitted:OnEndBreak=136
status_callback_event_not_admitted:OnModifierAdd=115
status_callback_event_not_admitted:OnListenCharacterCreate=114
status_callback_event_not_admitted:OnBeforeDying=110
```

listener bucket 中已有 executable 统计，但同域仍有 admission gap：

```text
startup_or_enter: raw=2411, executable=1740, blocked=671
turn_or_action: raw=199, executable=68, blocked=131
hit_or_damage: raw=225, executable=63, blocked=162
death_phase_wave_resource 等其余 bucket 仍继承 event source / source mode / payload admission gap
```

解释：

- 已有 status callback executable 只证明事件族内存在可执行正例，不代表怪物被动/监听全域完成。
- 缺事件源、缺 payload、unsupported source mode、phase/wave/stage 相关事件均保持 admission gap 或 boundary，不产生 mutation。

## Wave、Summon、Stage 边界

Wave definition / entry：

```text
definition_count=28296
entry_count=95504
executable_total=122714
blocked_total=1086
```

`OnWaveMonster` boundary：

```text
runtime_event_source=wave.monster
fake empty payload dispatch mutation_count=0
fake empty payload state unchanged=true
errors include wave_monster_payload_incomplete
```

Summon refs / lifecycle：

```text
monster cards with summon refs=658
summon_ref_count=1370
refs linked to current summon intent monster ref=135

summon intents total=775
executable=14
blocked=761
```

Stage/environment：

```text
definitions with stage ability refs=4826
stage_ability_ref_count=6502
classification=out_of_scope
future owner=stage/environment layer, not MonsterDataCardIR passive runtime
```

解释：

- `summon_refs` 只作为 spawn/lifecycle relation 来源，不生成怪物专属复制规则。
- 被召唤单位仍必须绑定自身 `MonsterDataCardIR`。
- stage/environment refs 记录为后续归属，不纳入 monster passive runtime。

## 实际运行的验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/tools/validate_p4_s6_monster_passive_listener_wave.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_s6_monster_passive_listener_wave --output-dir /tmp/hsr_v8_p4_s6_monster_passive_listener_wave
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p2_s10_status_callback_coverage --output-dir /tmp/hsr_v8_p2_s10_after_p4_s6
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p1_2_wave_system --output-dir /tmp/hsr_v8_p1_2_after_p4_s6
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_s9_summon_lifecycle_cleanup --output-dir /tmp/hsr_v8_p3_s9_after_p4_s6
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_s3_summoned_monster_spawn --output-dir /tmp/hsr_v8_p3_s3_after_p4_s6
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
rg -n "[[:blank:]]$" simulator_v8_clean_core/tools/validate_p4_s6_monster_passive_listener_wave.py live_validation_reports/v8_p4_s6_monster_passive_listener_wave_ready_for_review.md
```

结果：

- S6 主验证 `ok=True`。
- P2-S10 status callback coverage `ok=True`。
- P1-S2 wave system `ok=True`。
- P3-S9 summon lifecycle cleanup `ok=True`。
- P3-S3 summoned monster spawn `ok=True`。
- `compileall` 通过。
- `git diff --check` 通过。
- S6 新脚本与报告尾随空白检查无匹配。

## 当前进度口径

当前做到 P4-S6 ready_for_review：怪物被动、监听、阶段、波次、召唤交叉边界已形成分层矩阵和负例边界；本阶段没有新增可执行 runtime 语义。

距离最小可用战斗纵切：P1/P2/P3 相关 wave、status callback、summon lifecycle、summoned monster spawn 回归未退化。

距离完整复刻：怪物被动 startup graph、更多 callback event source/source mode、phase/wave payload、stage/environment runtime、summon dynamic/profile admission 仍未完成，后续阶段不能用 S6 的 boundary 结果覆盖这些真实 gap。
