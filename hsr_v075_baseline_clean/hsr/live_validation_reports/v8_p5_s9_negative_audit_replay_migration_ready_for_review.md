# v8 P5-S9 Negative / Audit / Replay Migration Ready For Review

日期：2026-07-09

## 范围

本阶段收口 P5 新增 value resolution 路径的安全边界、source audit、replay 和旧验证迁移：

- 新增 P5 blocked/state-unchanged matrix，复用 S5/S6/S7/S8 的负例证据。
- 新增 value resolution source audit matrix，确认 executable value mutation 可通过 source audit。
- 新增 value resolution replay matrix，确认相关 transition replay 通过。
- 修正 P5 新语义下过时的 P4-S9/v0_231 toughness 样例边界：行动内真实 `SetDynamicValue` 已会写入韧性动态值，旧 helper 不能再靠手工注入值压低真实值；现在按 IR evidence 调整测试目标韧性，不改变 runtime 规则。

## 产物

- `simulator_v8_clean_core/tools/validate_p5_s9_negative_audit_replay_migration.py`
- `simulator_v8_clean_core/tools/validate_v0_231.py`
- `/tmp/hsr_v8_p5_s9_current/validation_summary_p5_s9_negative_audit_replay_migration.json`
- `/tmp/hsr_v8_p5_s9_current/p5_s9_negative_audit_replay_migration_matrix.json`

## 结果

S9 主验证输出：

```text
v8 p5_s9_negative_audit_replay_migration ok=True rows=4 classifications={'boundary_only': 2, 'executable': 2} gap_counts={}
```

summary：

```text
row_count=4
classification_counts={'boundary_only': 2, 'executable': 2}
direct_negative_case_count=5
stage_matrix_count=4
disallowed_gap_count=0
gap_attribution_counts={}
```

## 关键 evidence

- `blocked_state_unchanged_matrix`：缺 binding、缺 context、缺 target/source 类负例均 blocked/state unchanged；直接负例数为 5。
- `value_resolution_source_audit_matrix`：S5 damage/toughness、S6 resource/status callback、S8 eidolon effective level 的 source audit 均通过。
- `value_resolution_replay_matrix`：S5/S6/S7/S8 抽样 transition replay 均通过。
- `legacy_validation_migration_scope`：阶段矩阵无 disallowed gap；旧断言迁移只修验证样例边界，没有保留假执行路径。

## 旧验证迁移说明

P5 接通后，部分行动会通过真实 TBGD 来源的 `SetDynamicValue` 在行动内写入动态值。旧 P4-S9 复用 v0_231 helper 时，把非破韧样例的 dynamic hash 手工注入为较小值；这在 P5 后会被行动内真实写入值覆盖，导致“非破韧样例”实际破韧。

已迁移为：

```text
从 ToughnessEmissionIR source trace / stance evidence 估算真实韧性值
非破韧样例：把目标韧性提高到真实韧性值以上
破韧样例：把目标韧性设为真实韧性值
```

该值只用于验证状态构造，不作为 runtime 公式输入。runtime 仍只消费 Canonical IR / 数据卡 IR / action 内真实 mutation。

## 回归

已运行：

```text
v0_271: ok=True
v0_276: ok=True
P1-9: ok=True, phase1_minimum_battle_slice=True
P2: ok=True, p2_status_substrate_complete=True, p2_all_status_sources_classified=True
P3: validation_gate_ok=True, p3_summon_foundation_closed=True, p3_summon_phase_complete=True, p3_summon_all_executable_complete=False
P4-S9: ok=True rows=11 classifications={'boundary_only': 2, 'executable': 8, 'source_gap_blocked': 1}
P4 aggregate: validation_gate_ok=True, p4_substrate_complete=True, p4_all_executable_complete=False
```

P4 聚合保留 gap：

```text
{'admission_gap': 1333000, 'implementation_missing': 0, 'lowering_gap': 0, 'source_gap_blocked': 55, 'unclassified': 0, 'validation_gap': 0}
```

## 资源口径

```text
S9 output_size=8359/7188 bytes
P4-S9 output_size=29959/28753 bytes
full_ir_written=false
full_rulebook_written=false
full_transition_dump_written=false
large_artifacts_written=false
```

## 验证命令

已运行：

```bash
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p5_s9_negative_audit_replay_migration --output-dir /tmp/hsr_v8_p5_s9_current
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/tools/validate_v0_231.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_s9_data_card_mutation_source_linkage --output-dir /tmp/hsr_v8_p4_s9_after_p5_s9_fix2
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_combatant_data_card_expansion --output-dir /tmp/hsr_v8_p4_after_p5_s9_fix
```

此前本阶段已运行并通过：

```bash
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_v0_271 --output-dir /tmp/hsr_v8_v0_271_after_p5_s9
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_v0_276 --output-dir /tmp/hsr_v8_v0_276_after_p5_s9
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_after_p5_s9
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p2_status_system_complete --output-dir /tmp/hsr_v8_p2_after_p5_s9
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_summon_assistant_servant_complete --output-dir /tmp/hsr_v8_p3_after_p5_s9
```

待 P5-S10 最终聚合统一运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

## 边界

S9 不新增业务机制，不把旧验证失败直接豁免；本阶段只修正验证样例构造，使旧验证在 P5 真实动态值写入语义下继续检查原目标：direct toughness reduction、break lifecycle、source audit 和 replay。
