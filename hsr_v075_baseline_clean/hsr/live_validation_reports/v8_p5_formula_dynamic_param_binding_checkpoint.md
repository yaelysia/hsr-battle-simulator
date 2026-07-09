# v8 P5 Formula / Dynamic / Param Binding Checkpoint

日期：2026-07-09

## 验收结论

P5 公式 / 动态值 / 参数绑定通用准入底座验收通过。

P5 当前结论是底座闭环完成，不是全角色 / 全怪物 / 全装备 / 全关卡公式正例完成。`p5_all_executable_complete=false` 是预期结果；剩余缺口均归因为 admission gap，没有 implementation、lowering、validation 或 unclassified gap。

## 验收范围

本次验收复核了：

- P5-S0 到 P5-S10 子矩阵全部存在且 stage check 通过。
- `ValueResolver` 只基于 RuleBook / Canonical IR / 数据卡 IR 做准入，不读 raw TBGD / TextMap。
- damage、toughness、resource、status、callback queue、summon、trace/eidolon 消费侧带 `value_resolution` 证据。
- 缺 context、缺 binding、未知 binding kind、缺 profile/card/level source 等负例 blocked 或 process-only，state unchanged。
- source audit、settlement traceability、snapshot replay 的抽样证据存在。
- P1/P2/P3/P4 直接回归仍通过，且 P3/P4 既有 gap 没被 P5 聚合误清零。

## 关键结果

```text
P5 aggregate:
validation_gate_ok=True
p5_formula_dynamic_param_binding_substrate_complete=True
p5_all_executable_complete=False
p5_sources_classified=True
gap_counts={'admission_gap': 1492393, 'implementation_missing': 0, 'lowering_gap': 0, 'source_gap_blocked': 0, 'unclassified': 0, 'validation_gap': 0}
classification_counts={'admission_gap': 17, 'boundary_only': 9, 'executable': 48, 'source_absent_not_required': 1}
```

分阶段摘要：

```text
s0 ok=True classifications={'admission_gap': 8}
s1 ok=True classifications={'admission_gap': 4, 'boundary_only': 2, 'executable': 15}
s2 ok=True classifications={'boundary_only': 1, 'executable': 7}
s3 ok=True classifications={'admission_gap': 3, 'boundary_only': 1, 'executable': 3}
s4 ok=True classifications={'boundary_only': 1, 'executable': 6}
s5 ok=True classifications={'executable': 4, 'source_absent_not_required': 1}
s6 ok=True classifications={'executable': 5}
s7 ok=True classifications={'admission_gap': 1, 'boundary_only': 1, 'executable': 3}
s8 ok=True classifications={'admission_gap': 1, 'boundary_only': 1, 'executable': 3}
s9 ok=True classifications={'boundary_only': 2, 'executable': 2}
```

## 回归结果

本次验收实际运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p5_formula_dynamic_param_binding --output-dir /tmp/hsr_v8_p5_acceptance_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_p5_acceptance_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p2_status_system_complete --output-dir /tmp/hsr_v8_p2_p5_acceptance_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_summon_assistant_servant_complete --output-dir /tmp/hsr_v8_p3_p5_acceptance_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_combatant_data_card_expansion --output-dir /tmp/hsr_v8_p4_p5_acceptance_current
git diff --check
```

结果：

```text
compileall: pass
P5 aggregate: validation_gate_ok=True, p5_substrate_complete=True, p5_all_executable_complete=False
P1-9: ok=True, phase1_minimum_battle_slice=True
P2: ok=True, p2_status_substrate_complete=True, p2_all_status_sources_classified=True
P3: validation_gate_ok=True, p3_summon_foundation_closed=True, p3_summon_phase_complete=True, p3_summon_all_executable_complete=False
P4: validation_gate_ok=True, p4_substrate_complete=True, p4_all_executable_complete=False
git diff --check: pass
P5 untracked trailing whitespace check: pass
```

保留跨阶段 gap：

```text
P3 gap_counts={'admission_gap': 2123, 'implementation_missing': 0, 'lowering_gap': 0, 'source_gap_blocked': 27, 'unclassified': 0, 'validation_gap': 0}
P4 gap_counts={'admission_gap': 1333000, 'implementation_missing': 0, 'lowering_gap': 0, 'source_gap_blocked': 55, 'unclassified': 0, 'validation_gap': 0}
P5 gap_counts={'admission_gap': 1492393, 'implementation_missing': 0, 'lowering_gap': 0, 'source_gap_blocked': 0, 'unclassified': 0, 'validation_gap': 0}
```

## 当前能力

P5 后，v8 已具备公式参数、动态值、自定义值和运行时上下文绑定的通用准入底座：

- 静态技能参数、行动定义数值字段、行动定义列表项可以通过统一 resolver 读取。
- 动态 hash 可以优先从结构化 binding source 解析，未解析时不会返回默认值。
- 资源、伤害、韧性、状态数值、callback queue、召唤怪基础属性、角色行迹 / 星魂等级提升等消费侧已经接入统一解析证据。
- process-only / blocked 路径不会产生 mutation，且 replay/source audit 可复核。

后续仍需继续做全量数据卡、装备 / 构筑、关卡 / 环境、波次 / 阶段、更多目标语义，以及 P5 admission gap 的逐类回收。
