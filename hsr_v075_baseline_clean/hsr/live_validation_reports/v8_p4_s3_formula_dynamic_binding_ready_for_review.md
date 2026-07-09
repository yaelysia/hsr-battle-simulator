# v8 P4-S3 Formula / Dynamic Binding Ready For Review

日期：2026-07-08

阶段状态：`ready_for_review`。本报告是执行线程证据包，不修改 `P4_COMBATANT_DATA_CARD_EXPANSION_TASK_PLAN.md` 第 22 节 checklist，不声明 `done`。

## 阶段执行卡

阶段：P4-S3 formula / dynamic / custom value binding matrix。

目标产物：

- 输出技能公式、action hit profile、dynamic hash、combatant profile stat、monster custom parameter、summon intent dynamic gap 的分层矩阵。
- 用真实 runtime 样例证明当前已有公式来源能进入 action execution、mutation、settlement、replay、source audit。
- 用真实 IR dynamic hash 表达式验证 bound 正例和 unbound blocked 负例，不把 hash 映射为硬编码名字或数值。
- 继承 S0/S1/S2 的 gap，不用一个可执行正例覆盖同域内部缺口。

本阶段实际改动文件：

- `simulator_v8_clean_core/tools/validate_p4_s3_formula_dynamic_binding.py`
- `live_validation_reports/v8_p4_s3_formula_dynamic_binding_ready_for_review.md`

本阶段未修改：

- 未改 runtime / reducer / damage / target / queue 语义。
- 未改 RuleBook 查询面。
- 未改 lowering 事实投影。
- 未新增 P4-S12 聚合脚本。
- 未改 P4 第 22 节 checklist。

## 验证脚本行为

新增 S3 验证脚本：

- 构建一次 `TBGDLowering(...).build()` 与 `RuleBook(ir)`。
- 复用 S0 combatant source inventory matrix。
- 通过结构化谓词选择一个已可执行 damage action runtime 样例，并验证 replay 与 source audit。
- 扫描真实 IR 中的 dynamic hash expression，由 `RuleEvaluator.evaluate_numeric` 执行 bound / unbound 检查。
- 通过 P3 summon monster spawn 样例确认 `CombatantProfileIR` stat source 能进入 runtime unit state。
- 对 monster custom parameter blocks、summon dynamic/profile gaps、param index gaps 只归类为 admission gap，不提升为 executable。
- 默认只输出 summary 与 matrix，不写完整 IR、完整 transition dump 或大型派生产物。

输出目录：

```text
/tmp/hsr_v8_p4_s3_formula_dynamic_binding
```

主要文件：

```text
/tmp/hsr_v8_p4_s3_formula_dynamic_binding/validation_summary_p4_s3_formula_dynamic_binding.json
/tmp/hsr_v8_p4_s3_formula_dynamic_binding/p4_s3_formula_dynamic_binding_matrix.json
```

## Matrix 结果

S3 主验证：

```text
ok=True
row_count=8
unclassified_count=0

classification_counts:
  admission_gap=6
  executable=2

gap_attribution_counts:
  admission_gap=265527

runtime_formula_usage_ok=True
dynamic_hash_positive_negative_ok=True
summon_gap_reclassified_count=761
```

行摘要：

```text
action_formula_runtime_usage: executable, raw=1, ir=1, executable=1
dynamic_numeric_evaluator_binding: executable, raw=181512, ir=181512, executable=1
s0_dynamic_formula_source_domains_inherited: admission_gap, raw=59877, ir=346527, executable=92779, admission_gap=256504
skill_formula_binding_to_hit_profile: admission_gap, raw=22868, ir=22868, rulebook_visible=22868, executable=19911, admission_gap=2957
combatant_profile_stat_source: admission_gap, raw=3150, ir=3150, rulebook_visible=3150, executable=2395, admission_gap=216
monster_custom_dynamic_parameter_blocks: admission_gap, raw=738, ir=2544, rulebook_visible=2544, executable=0, admission_gap=5088
summon_intent_dynamic_custom_profile_gap_reclassification: admission_gap, raw=775, ir=775, rulebook_visible=775, executable=14, admission_gap=761
param_index_boundary_scan: admission_gap, raw=22868, ir=11579, admission_gap=1
```

样本 ID 是验证输出，不是选择条件。runtime 公式样例由 availability choice、damage emission、hit profile、replay、source audit 等结构化谓词选出；当前输出样本为 `avatar_skill:110907`、`character_data_card:avatar:1109`。dynamic hash 样例来自 `FormulaIR.expression`，当前输出 hash 为 `-1126825319`；验证只检查真实表达式的 bound / unbound 行为，不把该 hash 解释成机制名或固定值。

## Gap 继承与归因

- `s0_dynamic_formula_source_domains_inherited.admission_gap=256504`：继承 S0 对 dynamic/formula 来源域的总账缺口。
- `skill_formula_binding_to_hit_profile.admission_gap=2957`：formula binding 已可由 RuleBook 查询，但仍有非 executable binding，不能被 runtime 正例覆盖。
- `combatant_profile_stat_source.admission_gap=216`：profile 总数 3150，当前有 216 个缺 required stats 或处于 admission gap。
- `monster_custom_dynamic_parameter_blocks.admission_gap=5088`：`monster_config` 与 `template_config` parameter blocks 已盘点且 RuleBook 可见，但没有通用 binding source，不能假执行。
- `summon_intent_dynamic_custom_profile_gap_reclassification.admission_gap=761`：775 个 summon intent 中 14 个 executable，其余按 blocked reason 重分为 `dynamic_or_custom_value=751`、`profile_or_card_source=10`。
- `param_index_boundary_scan.admission_gap=1`：当前 IR 中存在真实 param index admission gap；未构造 synthetic out-of-range 样例。

## 正例与负例

正例：

- `action_formula_runtime_usage` 通过真实 `CombatExecutor` 产生 damage mutation，settlement 存在，`MutationReducer.replay_snapshot` 通过，`RuntimeSourceAuditor.validate_transition` 通过。
- `dynamic_numeric_evaluator_binding` 使用真实 dynamic hash expression，bound 时返回 `1.25` 且保留 source trace，unbound 时 blocked reason 为 `dynamic_hash_unbound:<hash>`。
- `combatant_profile_stat_source` 使用 P3 summoned monster spawn 样例，runtime unit 中保留 `combatant_profile_id` 与 `combatant_profile_source_trace`，并写入 max_hp / attack / defense / speed。

负例 / blocked 边界：

- dynamic hash 缺 binding 时 blocked，不生成默认值。
- monster custom parameter blocks 不因为 raw block 存在就进入 runtime mutation。
- summon intent dynamic/custom/profile 缺口只归 admission gap，不合成召唤正例。
- param index 缺口只记录真实 blocked reason，不制造假边界样例。

## 实际运行的验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/tools/validate_p4_s3_formula_dynamic_binding.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_s3_formula_dynamic_binding --output-dir /tmp/hsr_v8_p4_s3_formula_dynamic_binding
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
if rg -n "[[:blank:]]$" simulator_v8_clean_core/tools/validate_p4_s3_formula_dynamic_binding.py; then exit 1; fi
```

结果：

- S3 主验证 `ok=True`。
- `py_compile` 通过。
- `compileall` 通过。
- `git diff --check` 通过。
- S3 脚本尾随空白检查通过。

## 跳过的直接回归

S3 没有修改 runtime、reducer、RuleBook、lowering 或共享执行语义，因此本阶段未追加 P1/P2/P3 聚合回归。S3 主验证自身已经覆盖一次真实 executor、mutation、settlement、replay、source audit 纵切。剩余风险是后续阶段若修改 target、damage、status、queue、source audit 或 replay 底座，需要按触达范围补跑对应直接回归。

## 当前进度口径

当前做到 P4-S3 ready_for_review：公式和 dynamic/custom value 的来源总账、可执行正例、blocked 负例与继承 gap 已形成矩阵证据。

距离最小可用战斗纵切：P1/P3 纵切不受 S3 改动影响；S3 只补来源和公式绑定账本，不扩大最小纵切定义。

距离完整复刻：仍缺 S4 target query/card boundary、S5 monster action graph、S6 passive/event/wave、S7/S8 角色机制与召唤/servant gap、S9 装备构筑环境真实预留、S10-S12 回归与最终聚合。
