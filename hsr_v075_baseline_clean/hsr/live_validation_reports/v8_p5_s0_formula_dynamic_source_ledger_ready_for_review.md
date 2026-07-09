# v8 P5-S0 Formula / Dynamic Source Ledger Ready For Review

日期：2026-07-09

阶段状态：`ready_for_review`。本报告是执行线程证据包，不修改 `P5_FORMULA_DYNAMIC_PARAM_BINDING_TASK_PLAN.md` 第 19 节 checklist，不声明 `done`。

## 阶段执行卡

阶段：P5-S0 公式 / 动态值 / 自定义值来源总账本与 P4 gap 继承。

目标产物：

- 建立 P5 source-family matrix，覆盖角色技能、怪物技能、servant 技能、召唤怪 intent、状态 callback、资源规则、伤害 / 韧性 / 治疗 / 护盾 / 生命变化 consumer。
- 继承 P4-S3 formula / dynamic / custom value gap，不把 P4 gap 清零，不用 executable 正例覆盖同域 admission gap。
- 输出轻量 summary、matrix、sample source trace 和 gap attribution。

本阶段实际改动文件：

- `simulator_v8_clean_core/tools/validate_p5_s0_formula_dynamic_source_ledger.py`
- `live_validation_reports/v8_p5_s0_formula_dynamic_source_ledger_ready_for_review.md`

本阶段未修改：

- 未改 runtime / reducer / damage / resource / status / summon 执行语义。
- 未改 TBGD lowering 事实投影。
- 未改 RuleBook 查询面。
- 未新增 P5-S10 聚合脚本。
- 未改 P5 第 19 节 checklist。

## 验证脚本行为

新增 S0 验证脚本：

- 构建一次 `TBGDLowering(...).build()` 与 `RuleBook(ir)`。
- 复用当前 P4-S0 source inventory matrix 和 P4-S3 formula/dynamic binding matrix。
- 对 P5 source family 做轻量 IR 容器统计，记录 consumer count、executable count、gap attribution 和 sample source trace。
- 默认只输出 summary、source family matrix、P4 gap inheritance matrix 和 sample trace，不写完整 Canonical IR、完整 RuleBook 或 transition dump。
- 不执行新的数值求值，不新增公式解释器，不构造 synthetic positive case。

实现中曾尝试直接重建完整 P4 aggregate，但该路径对 S0 过重，超过合理等待后中断；最终实现只复用 P4-S0/P4-S3 与必要 IR 统计，符合 S0 总账本范围。

输出目录：

```text
/tmp/hsr_v8_p5_s0_formula_dynamic_source_ledger
```

主要文件：

```text
/tmp/hsr_v8_p5_s0_formula_dynamic_source_ledger/validation_summary_p5_s0_formula_dynamic_source_ledger.json
/tmp/hsr_v8_p5_s0_formula_dynamic_source_ledger/p5_s0_formula_dynamic_source_family_matrix.json
```

## Matrix 结果

S0 主验证：

```text
ok=True
source_family_row_count=8
unclassified_count=0
disallowed_gap_count=0
implementation_missing_count=0
lowering_gap_count=0
validation_gap_count=0
p4_s3_inherited_row_count=8 / 8
sample_source_trace_count=8
```

分类：

```text
classification_counts:
  admission_gap=8

p4_inherited_gap_counts:
  admission_gap=277412
  source_gap_blocked=0
  implementation_missing=0
  lowering_gap=0
  validation_gap=0
  unclassified=0
```

P5 source-family 行摘要：

```text
character_skill_formula_param_sources: admission_gap, raw=13497, ir=291498, consumer=22869, executable=97190
monster_skill_formula_param_sources: admission_gap, raw=6840, ir=222021, consumer=11858, executable=66352
servant_skill_formula_param_sources: admission_gap, raw=467, ir=11202, consumer=440, executable=3402
summon_intent_dynamic_custom_profile_sources: admission_gap, raw=2171, ir=4752, consumer=1550, executable=56
status_callback_dynamic_numeric_sources: admission_gap, raw=4788, ir=43578, consumer=309117, executable=21142
resource_numeric_sources: admission_gap, raw=11252, ir=16200, consumer=8699, executable=16124
damage_toughness_consumer_sources: admission_gap, raw=56736, ir=382860, consumer=39392, executable=140516
heal_shield_hp_loss_consumer_sources: admission_gap, raw=48663, ir=328657, consumer=399146, executable=207553
```

说明：`source_family` gap 总数是按 P5 family 视角统计，来源行会在多个 family 中重复出现，不能当作去重后的全局 gap 总数。P4-S3 继承口径以 `p4_inherited_gap_counts.admission_gap=277412` 为准。

## Gap 继承与归因

- P4-S3 的 8 个行全部进入 `p4_gap_inheritance_matrix`。
- P4-S3 保留的 `admission_gap=277412` 没有被 P5-S0 清零。
- 当前未出现 `implementation_missing`、`lowering_gap`、`validation_gap` 或 `unclassified`。
- 8 个 P5 source family 均为 `admission_gap`，表示 S0 只完成来源总账和继承归因，不宣称数值绑定底座已执行完成。

## 正例与负例口径

本阶段没有新增业务 mutation 正例，也没有新增求值负例；这是 S0 范围刻意限制。

已保留的证据：

- P4-S3 `action_formula_runtime_usage` 仍作为已有 runtime formula 正例，被继承到 gap inheritance matrix。
- P4-S3 `dynamic_numeric_evaluator_binding` 仍保留 dynamic hash bound / unbound blocked 样例。
- P5-S0 每个 source family 都有 sample source trace 或 consumer/source evidence。

未宣称的内容：

- 不宣称任何 dynamic/custom/hash read site 已通用执行。
- 不宣称 heal/shield/hp-loss 已接入 ValueResolver。
- 不宣称 summon intent custom value / dynamic monster id / profile source gap 已解决。

## 实际运行的验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/tools/validate_p5_s0_formula_dynamic_source_ledger.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p5_s0_formula_dynamic_source_ledger --output-dir /tmp/hsr_v8_p5_s0_formula_dynamic_source_ledger
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
rg -n '[[:blank:]]$' hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p5_s0_formula_dynamic_source_ledger.py
```

结果：

- `py_compile` 通过。
- P5-S0 主验证 `ok=True`。
- `compileall` 通过。
- `git diff --check` 通过。
- 新脚本尾随空白检查无命中。

## 跳过的回归

本阶段未运行 P1/P2/P3/P4 聚合回归，因为 S0 只新增账本验证与报告，没有修改 runtime、lowering、RuleBook 或共享执行语义。

P5-S0 主验证本身会重建当前 P4-S0/P4-S3 矩阵，足以证明本阶段的来源总账与 P4 formula/dynamic/custom gap 继承。后续 S1 起如果改 RuleBook、contract、ValueResolver 或任意 consumer，应按 P5 计划触发对应直接回归。

## 当前进度口径

当前做到 P5-S0 `ready_for_review`：来源总账、P4-S3 gap 继承、P5 source family 分类、轻量 evidence 已形成。

距离最小可用战斗纵切：S0 不改变战斗纵切能力，只为后续 S1-S9 提供数值来源和 gap 归因入口。

距离完整复刻：仍缺 ValueBinding contract、静态参数绑定、dynamic/custom read-site 投影、ValueContext / ValueResolver、damage/toughness/heal/shield/hp-loss consumer、resource/status/callback queue consumer、怪物 custom value、召唤参数、角色行迹 / 星魂 / 强化形态绑定，以及 P5-S9/S10 的负例、audit、replay 和聚合验收。
