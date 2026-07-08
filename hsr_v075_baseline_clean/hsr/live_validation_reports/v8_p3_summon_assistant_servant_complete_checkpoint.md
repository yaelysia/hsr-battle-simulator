# v8 P3 summon / servant aggregate checkpoint（AssistantAvatar scope exclusion）

日期：2026-07-08

## 结论

P3 当前状态是：底座闭环验收通过，全正例 / 全 admission 清零未完成。

AssistantAvatar / `TurnInsertAssistantAbility` 已从 P3 召唤物/servant 验收范围移出。它保留 raw/IR/RuleBook 审计和 blocked 边界样本，记录在 `p3_summon_scope_exclusions.json`，但 `p3_gap_count=0`，不进入 inherited gap matrix。

聚合器现在明确拆成三层：

- `validation_gate_ok=True`：S0-S11 分步验证、分类完整性、样本审计、replay 和资源预算检查通过，报告本身可信。
- `p3_summon_phase_complete=True` / `p3_summon_substrate_complete=True`：implementation / lowering / validation / unclassified 缺口为 0，剩余 admission/source-gap 均有证据矩阵且不被 aggregate 隐藏。
- `p3_summon_all_executable_complete=False`：仍有 admission/source-gap，不能宣称全正例完成。

聚合入口：

```bash
timeout 240 ionice -c 3 nice -n 15 env PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p3_summon_assistant_servant_complete --output-dir /tmp/hsr_v8_p3_scope_exclusion_assistant_final
```

关键 summary：

```text
ok=True
validation_gate_ok=True
p3_summon_foundation_closed=True
p3_summon_phase_complete=True
p3_summon_acceptance_ok=True
p3_summon_substrate_complete=True
p3_summon_all_executable_complete=False
p3_summon_result_status=foundation_closed_with_admission_or_source_gaps
p3_summon_sources_classified=True
p3_summon_implementation_missing_count=0
p3_summon_source_gap_blocked_count=27
p3_summon_lowering_gap_count=0
p3_summon_admission_gap_count=2123
p3_summon_validation_gap_count=0
p3_summon_unclassified_count=0
p3_summon_scope_exclusion_count=1
```

## 本次更正

- 顶层结果新增 `p3_summon_foundation_closed` 和 `p3_summon_all_executable_complete`，避免把底座闭环和全正例完成混用。
- 新增 `p3_summon_allowed_gap_evidence_matrix.json`。任何 implementation / lowering / validation / unclassified gap 都会阻塞 phase complete；admission/source-gap 只有证据完整时才允许作为底座边界。
- S0 matrix 新增完整 `gap_reason_token_counts` / `gap_reason_layer_counts`，不再只输出 top reason。
- source/mechanism matrix 把 executable 正例和同域 gap 子项拆成不同子行。
- S0/S1/S7/S8 中 AssistantAvatar / `TurnInsertAssistantAbility` / `FriendServantSelect` 均统一归类为 `out_of_scope`，不再计入 P3 admission/lowering gap。
- 新增 `p3_summon_scope_exclusions.json`，记录 AssistantAvatar raw=5、IR=5、RuleBook visible=5、S0/S1/S7 classification 均为 `out_of_scope`。
- S3 unsupported boundary 断言同步新的 source-gap 精确原因。

## Gap 总账

Inherited gap matrix：

```text
row_count=3
gap_count=2150
classification_counts={'admission_gap': 2, 'source_gap_blocked': 1}
```

Allowed gap evidence matrix：

```text
row_count=3
allowed_gap_count=2150
disallowed_gap_count=0
classification_counts={'admission_gap': 2, 'source_gap_blocked': 1}
all_evidence_ok=True
```

明细：

```text
summon_target_expression: admission_gap=342
summoned_monster_intent: admission_gap=1781
summoned_monster_intent: source_gap_blocked=27
```

Scope exclusion：

```text
assistant_avatar_ability_config: out_of_scope, raw=5, ir=5, rulebook_visible=5, p3_gap_count=0
```

`source_gap_blocked` 行只携带 source-gap token，例如 `summon_monster_profile_source_missing`、`summon_monster_data_card_source_missing`、`monster_template_base_stat_missing:DefenceBase`；不再混入 admission token。

## 主矩阵状态

最终 source matrix：

```text
row_count=13
classification_counts={'admission_gap': 2, 'boundary_only': 2, 'executable': 6, 'source_absent_not_required': 2, 'source_gap_blocked': 1}
gap_count=2150
unclassified_count=0
```

最终 mechanism matrix：

```text
row_count=19
classification_counts={'admission_gap': 2, 'boundary_only': 4, 'executable': 11, 'source_absent_not_required': 1, 'source_gap_blocked': 1}
gap_count=2150
unclassified_count=0
```

P3 底座闭环 acceptance 以 inherited gap matrix + allowed gap evidence matrix 为总账；全正例完成仍要求 inherited gap 为 0。

## 样本与审计

```text
failed_stage_count=0
positive_sample_count=8
blocked_sample_count=7
source_audit_sample_count=5
replay_sample_count=8
```

source audit、replay、blocked state unchanged 样本通过，证明当前已 admission 的正例和 blocked 边界可信；剩余 admission/source-gap 保留为非 executable backlog。

## 资源预算

```text
rulebook_build_count=1
static_check_count=1
subprocess_validation_count=0
large_artifacts_written=False
full_ir_written=False
full_transition_dump_written=False
```

本次验证串行限流运行，输出放在 `/tmp`，未并发运行重验证。

## 验证

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m py_compile simulator_v8_clean_core/tools/validate_p3_s0_summon_source_inventory.py simulator_v8_clean_core/tools/validate_p3_summon_assistant_servant_complete.py simulator_v8_clean_core/tools/validate_p3_s7_assistant_queue_execution.py simulator_v8_clean_core/tools/validate_p3_s3_summoned_monster_spawn.py
timeout 240 ionice -c 3 nice -n 15 env PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p3_summon_assistant_servant_complete --output-dir /tmp/hsr_v8_p3_scope_exclusion_assistant_final
git diff --check
```

结果：

- P3-S12 aggregate: `validation_gate_ok=True`。
- P3-S12 foundation: `p3_summon_phase_complete=True`、`p3_summon_substrate_complete=True`。
- P3-S12 all executable: `p3_summon_all_executable_complete=False`。
- P3-S12 inherited gap count: `2150`。
- P3-S12 scope exclusion count: `1`。

未运行全量 P1/P2 aggregate、`validate_v0_209` 或其他重验证；本次只触达 P3 aggregate 口径和相关 P3 分步回归。

## 后续 backlog

- `summon_target_expression`：仍有 342 条 target admission gap，主要是专属 alias、组合 alias、TargetQuery 子项。
- `summoned_monster_intent`：仍有 `admission_gap=1781`，主要是 custom value hash 到名称/数值绑定缺证据、dynamic monster id 未绑定、部分 location type 语义未 admission。
- `summoned_monster_intent`：仍有 `source_gap_blocked=27`，主要是部分 monster profile/card 或模板基础属性真实来源缺失。
- AssistantAvatar / avatar assistant ability：已移出 P3 召唤物/servant验收；后续单独处理，不作为 P3 backlog。

下一步可以进入 P4+，但这些 P3 admission/source-gap 必须作为 backlog 持续收敛，不能误读为 executable。
