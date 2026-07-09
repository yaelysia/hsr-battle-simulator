# v8 P4-S12 combatant data card expansion checkpoint

状态：`accepted_checkpoint`

本报告由 P4-S12 执行线程证据包复核后转为验收 checkpoint。验收线程已复跑 P4 聚合、P1/P2/P3 回归、`compileall` 和空白检查，并已更新 P4 第 22 节 checklist。

## 验收结论

- P4-S1 到 P4-S12 通过验收。
- P4 数据卡扩面底座闭环通过，不代表全角色 / 全怪物 / 装备 / 关卡全正例完成。
- 当前保留 gap 仅为 allowed `admission_gap` / `source_gap_blocked`，没有 `implementation_missing`、`lowering_gap`、`validation_gap` 或 `unclassified`。
- 各阶段 `ready_for_review` 报告作为执行层证据包保留；本 checkpoint 和计划 checklist 作为验收状态来源。

## 阶段执行卡

阶段：P4-S12 P4 聚合验收、报告、交接和后续 backlog。

执行方案：

1. 新增 P4 聚合入口，只在 S0-S11 均已有分步矩阵后运行，不提前替代分步工作。
2. 聚合入口只构建一次 `TBGDLowering` / `RuleBook`，内存复用 S0-S11 子矩阵和 P3 stage results，不写完整 Canonical IR、完整 transition dump 或大体积派生产物。
3. 聚合必须继承分步 gap；`implementation_missing`、`lowering_gap`、`validation_gap`、`unclassified` 任一非零即失败。
4. 对 S12 暴露出的非 allowed gap 回到来源层修正，不在聚合层掩盖。
5. 串行运行 S12 验收集：P4 聚合、`compileall`、P1/P2/P3 聚合、`git diff --check`。

## 实际改动

新增：

- `simulator_v8_clean_core/tools/validate_p4_combatant_data_card_expansion.py`

修正：

- `simulator_v8_clean_core/tools/validate_p4_s0_combatant_source_inventory.py`
  - S0 inventory 新增证据链 token 匹配，用于识别 formula binding / card evidence 中嵌套的真实来源 trace。
  - `BattleTargetConfig` 重新归属为 stage/environment objective out-of-scope，不再伪装成 action target expression lowering gap。
  - `ConfigCharacter/LocalPlayer` 重新归属为 maze/local-player layer out-of-scope，不再作为战斗角色数据卡 lowering gap。
  - `ILBattleMonsterSkill:ParamList` 重新归属为 ILBattle special action layer out-of-scope，不合成无 owner 的 `SkillFormulaBindingIR`。
- `simulator_v8_clean_core/tools/validate_p4_s2_combatant_action_availability.py`
  - S1 继承记录行从 `executable` 调整为 `boundary_only`，避免没有 action choice 的记录行污染 executable availability 样本。
- `simulator_v8_clean_core/tools/validate_p4_combatant_data_card_expansion.py`
  - 来源总矩阵保留全部 58 个 domain 行，只压缩每行内部字段，避免顶层截断。

## P4 聚合结果

执行线程输出目录：

```text
/tmp/hsr_v8_p4_combatant_data_card_expansion
```

验收线程复跑输出目录：

```text
/tmp/hsr_v8_p4_acceptance
```

关键 summary：

```text
ok=True
validation_gate_ok=True
p4_combatant_data_card_phase_complete=True
p4_combatant_data_card_substrate_complete=True
p4_all_executable_complete=False
p4_sources_classified=True
p4_implementation_missing_count=0
p4_lowering_gap_count=0
p4_validation_gap_count=0
p4_unclassified_count=0
p4_admission_gap_count=1333000
p4_source_gap_blocked_count=55
allowed_gap_evidence_summary.all_evidence_ok=True
allowed_gap_evidence_summary.disallowed_gap_count=0
```

最终 gap：

```text
admission_gap=1333000
source_gap_blocked=55
implementation_missing=0
lowering_gap=0
validation_gap=0
unclassified=0
```

这表示 P4 底座闭环可验收；不表示全角色 / 全怪物全正例完成。

## 矩阵覆盖

P4 聚合产物包含：

- `source_total_matrix`：58 rows，`admission_gap=37`、`boundary_only=4`、`executable=10`、`out_of_scope=7`，`unclassified=0`。
- `data_card_contract_matrix`：13 rows。
- `action_availability_matrix`：7 rows，`boundary_only=2`、`executable=4`、`source_absent_not_required=1`。
- `formula_dynamic_binding_matrix`：8 rows。
- `target_backlog_matrix`：11 rows。
- `monster_action_passive_matrix`：S5/S6 合并视图。
- `character_action_trace_eidolon_resource_matrix`：S7/S8 合并视图。
- `p3_backlog_recovery_matrix`：14 rows，继承 P3 `admission_gap=2123`、`source_gap_blocked=27`。
- `action_query_contract_matrix`：6 rows。
- `allowed_gap_evidence_matrix`：96 rows，`allowed_gap_count=1333056`、`disallowed_gap_count=0`。
- `scope_exclusion_matrix`：9 rows，全部已分类。
- 正例样本：30。
- blocked/state unchanged 样本：7。
- source audit / replay 样本：4。

## 正例选择

正例仍按结构化谓词选取：

- action availability：来自 `CombatantActionSetIR`、`ActionDefinitionIR`、action event、actor data card source trace，不按角色名/怪物名固定选样。
- formula/runtime：按 formula binding、dynamic hash bound/unbound、runtime mutation/audit/replay 选择。
- target：按 target expression coverage、alias/fetch/sort/retarget/admission 分类选择。
- monster/character：按 action definition、card slot、trace/eidolon/resource hook、listener/passive slot 分类选择。
- action query contract：使用可行动单位查询结果提交 command，core 返回 blocked reason / transition / replay / source audit。

## 负例与边界

负例覆盖：

- 缺 action set、缺 servant runtime state、缺 target candidate、缺 scheduler turn window、缺资源时 blocked/state unchanged。
- BattleTargetConfig、LocalPlayer config、ILBattle ParamList 等非 P4 战斗数据卡来源归入 out-of-scope，不生成 runtime mutation。
- 装备/构筑 hook、stage/environment、AssistantAvatar 等保留明确归属和边界，不塞入角色/怪物 runtime。
- P3 inherited summon target / summoned monster intent gap 保留为 allowed backlog，不被宽域正例覆盖。

## Source Audit / Replay

P4 聚合要求 source audit / replay 样本存在并通过。

S11 action query contract summary：

```text
positive_transition_count=3
blocked_transition_count=1
source_audit_all_ok=True
replay_all_ok=True
planner_implemented=False
enemy_action_auto_selected_by_core=False
```

## 验证命令

均串行运行。

```bash
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_combatant_data_card_expansion --output-dir /tmp/hsr_v8_p4_combatant_data_card_expansion
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_p4_regression
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p2_status_system_complete --output-dir /tmp/hsr_v8_p2_p4_regression
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_summon_assistant_servant_complete --output-dir /tmp/hsr_v8_p3_p4_regression
git diff --check
```

结果：

```text
P4 aggregate: ok=True, validation_gate_ok=True
compileall: passed
P1-9 aggregate: ok=True, phase1_minimum_battle_slice=True
P2 aggregate: ok=True, p2_status_substrate_complete=True
P3 aggregate: validation_gate_ok=True, p3_summon_phase_complete=True, p3_summon_all_executable_complete=False
git diff --check: passed
```

## 没有完成的内容

- `p4_all_executable_complete=False`。
- admission gap 仍有 `1333000`，source-gap blocked 仍有 `55`。
- P4 没有完成全角色、全怪物、光锥、遗器、套装、关卡环境、推演器搜索/评分/路线发现。
- P4 没有把 ILBattle special action、LocalPlayer maze config、BattleTargetConfig objective layer 伪装成当前战斗数据卡 executable。

## 验证实际检查了什么

- S0-S11 分步矩阵当前重新构建并被 P4 聚合继承。
- disallowed gap 归零：implementation/lowering/validation/unclassified 均为 0。
- allowed gap evidence 存在且 `disallowed_gap_count=0`。
- 正例、blocked 样本、source audit/replay 样本存在。
- 资源预算为 summary/matrix/sample，不写完整 IR 或 transition dump。
- P1/P2/P3 直接回归仍通过。

## 验证没有证明什么

- 没证明每个角色/怪物机制都 executable。
- 没证明所有 admission gap 都已具备 runtime 语义。
- 没证明 out-of-scope 的 stage/environment/maze/ILBattle special action 可以由 P4 runtime 执行。
- 没证明未来装备/遗器/关卡/推演器层已经实现。

## 结论

P4-S12 已由验收线程复核通过。P4 数据卡扩面底座闭环通过，且保留 gap 已分类、可追踪、未被聚合掩盖；全正例完成仍是后续 backlog。
