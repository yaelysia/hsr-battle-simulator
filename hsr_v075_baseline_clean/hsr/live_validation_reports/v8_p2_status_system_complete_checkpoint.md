# v8 P2 状态系统完成检查点

日期：2026-07-05

口径复核：2026-07-06

## 结论

P2 状态系统底座与当前数据库状态来源闭环已完成，聚合验证入口为：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_status_system_complete --output-dir /tmp/hsr_v8_p2_status_system_complete
```

关键 summary：

```text
ok=True
p2_status_substrate_complete=True
p2_all_status_sources_classified=True
p2_status_implementation_missing_count=0
p2_status_lowering_gap_count=0
p2_status_admission_gap_count=0
p2_status_validation_gap_count=0
p2_status_unclassified_count=0
source_absent_not_required_count=0
```

本报告里的“完成”只指状态系统底座和当前 TBGD / Canonical IR 状态来源分类完成：

- 有真实来源且当前语义可执行的状态路径已有结构化正例、transition、replay、settlement traceability 和 source audit。
- 当前不能执行的状态路径已有明确 blocked/process-only/state unchanged 负例或边界证据。
- 当前没有 implementation/lowering/admission/validation gap 与 unclassified 残留。
- 这不表示全角色、全怪物、光锥、遗器、关卡、特殊模式都已复刻；这些仍属于 P3+ 扩面。

## 聚合范围

`validate_p2_status_system_complete` 串行聚合：

- `validate_p2_s10_status_callback_coverage`
- `validate_p2_s11_full_status_source_closure`

S10 提供正例/负例、source audit、replay、settlement traceability 抽样。S11 提供全量状态来源闭环、来源域矩阵、blocked 验证证据索引和 gap 清零结果。

资源预算：

```text
full_tbgd_lowering_runs=2
large_artifacts_written=False
full_canonical_ir_written=False
full_transition_dump_written=False
```

## 全量矩阵

```text
status_family_count=10
status_family_classification_counts.executable=10
source_domain_classification_counts.executable=6
raw_total=85527
ir_total=270515
executable_total=246885
blocked_total=12305
```

解释：

- `status_family_classification_counts.executable=10` 表示 10 个状态机制族都已经有真实来源正例和通用执行/边界分类能力。
- `source_domain_classification_counts.executable=6` 表示 6 个来源域都已经纳入状态系统矩阵并具备可执行正例。
- `blocked_total=12305` 表示个体来源层仍有被明确阻断的来源；这些来源不是未分类缺口，而是缺事件 payload、缺条件、缺目标、缺公式、unsupported task、缺真实事件源等边界项，必须保持 process-only / state unchanged。

来源域：

```text
avatar executable
monster executable
equipment_lightcone_relic executable
battle_event_stage executable
global_modifier executable
servant_summon executable
```

## 正例样本

S10 聚合的状态 callback mutation 正例覆盖：

```text
AddModifier
RemoveModifier
RemoveSelfModifier
SetDynamicValue
queue insert
action delay
status damage
```

source audit / replay 抽样：

```text
transition_sample_count=7
source_audit_ok_count=7
replay_ok_count=7
settlement_traceability_ok_count=7
```

## 负例样本

S10 聚合的 blocked/state unchanged 负例覆盖：

```text
missing_status
missing_event_source
missing_wave_payload
missing_condition
missing_target
unsupported_task
```

S11 blocked evidence 覆盖：

```text
status_add_sources -> validate_p2_s3_status_application_semantics
status_remove_sources -> validate_p2_s9_status_removal_dispel
status_dispel_sources -> validate_p2_s9_status_removal_dispel
status_numeric_binding_sources -> validate_p2_s7_status_numeric_bindings
status_damage_sources -> validate_p2_s8_status_damage
status_callback_event_families -> validate_p2_s10_status_callback_coverage
```

## 本次文档收口

- 更新 `CODEX_HANDOFF.md`，将入口状态改为 P2 状态系统已完成。
- 更新 `simulator_v8_clean_core/README.md`，加入 P2 聚合验证入口和 P3+ 建议。
- 更新 `P2_STATUS_SYSTEM_COMPLETE_TASK_PLAN.md` checklist。

## 2026-07-06 口径复核

本次复核修正了一个验收口径问题：blocked 状态事件源把 callback / queue intent 降级后，不能留下已经生成的 executable queue 下游 IR。

已确认代码层修复：

- lowering 先根据状态事件族阻断 callback 及派生 queue intent，再生成 queue resolution / queue window / queue lifecycle / extra-action。
- `validate_p2_s10_status_callback_coverage` 新增 queue intent 下游一致性检查，覆盖被阻断事件源对应的 queue intent 及其下游派生产物。
- `validate_p1_5_queue_window_system` 继续检查 executable queue window 必须来自 executable intent。

复核输出：

```text
validate_p1_5_queue_window_system ok=True
all_executable_windows_have_executable_intent=True
blocked_audit_discovered_not_admitted_to_window=True

validate_p1_9_phase1_aggregate ok=True
phase1_minimum_battle_slice=True

validate_p2_status_system_complete ok=True
p2_status_substrate_complete=True
p2_all_status_sources_classified=True

queue_intent_downstream_consistency.ok=True
event_blocked_queue_intent_count=735
executable_downstream_mismatch_count=0
```

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_status_system_complete --output-dir /tmp/hsr_v8_p2_status_system_complete
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

关键输出：

```text
v8 p2_status_system_complete validation ok=True
p2_status_substrate_complete=True
p2_all_status_sources_classified=True
```

## 剩余范围

P2 状态系统底座完成不等于完整游戏复刻完成。P3+ 仍应继续：

- 角色/怪物数据卡扩面。
- 光锥、遗器、环境、关卡机制。
- summon、assistant、servant 完整行为。
- 特殊模式、新事件源、新 target/opcode、未来数据库新增机制。

所有后续机制仍必须按 TBGD-first、IR-first、source audit、replay、blocked/state unchanged 口径推进。
