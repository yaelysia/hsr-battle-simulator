# v8 P2-S5 状态概率、抵抗和免疫检查点

日期：2026-07-05

## 本步完成

- 新增 `validate_p2_s5_status_probability`。
- 修复 `dynamic_values` 未传入 chance admission 的 admission gap，使真实 dynamic `Chance` 可由外部绑定执行。
- 将怪物模板 `StatusResistanceBase.Value` 投影到 `CombatantProfileIR.status_resistance`，并在 wave / summon 单位装配时写入 `resources.effect_resistance`。
- 保留怪物 `DebuffResist` 到单位 flags，作为后续特定 debuff immunity 接入的来源证据。
- 验证真实 dynamic chance 成功、chance 失败、效果命中、效果抵抗、显式状态免疫、dynamic chance 未绑定负例。

## 关键事实

当前 AddModifier chance 来源分布：

```text
missing=26607
dynamic_hash=135
fixed=46
postfix_expr=9
```

本步真实 chance 正例按结构化谓词选择：

```text
EffectIR opcode=AddModifier
Chance kind=dynamic_hash
target_alias=ParamEntity
selected_hash=-894095079
modifier=MCommon_Confine
```

关键断言：

```text
success_applies=True
success_choice_replayed=True
success_source_audit=True
success_replay=True
failure_no_mutation=True
failure_record_type=True
effect_hit_rate_recorded=True
base_success_probability_capped=True
resisted_no_mutation=True
resisted_record_type=True
immunity_no_mutation=True
immunity_no_rng=True
unbound_reason=True
```

来源分类：

```text
effect_resistance executable source_count=2694
specific_debuff_resist boundary_only source_count=959
control_resistance source_absent_not_required source_count=0
control_immunity source_absent_not_required source_count=0
```

`DebuffResist` 当前只保留到单位 flags，不在 S5 中冒充特定状态免疫执行；显式 `status_immunities` runtime source 仍作为 boundary-only 分支验证 no mutation。

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_s5_status_probability --output-dir /tmp/hsr_v8_p2_s5_status_probability
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

关键输出：

```text
v8 p2_s5_status_probability validation ok=True
```

## 剩余范围

- S5 完成概率、效果命中、效果抵抗和免疫边界。
- `DebuffResist` 特定状态免疫仍是后续数据卡 / admission 接入任务，不能在 runtime 中按名称硬补。
- S6 继续覆盖控制状态对行动、队列和时间线的 gating。
