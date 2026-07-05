# v8 P2-S1 状态 IR / RuleBook 来源完整性检查点

日期：2026-07-05

## 本步完成

- 修复状态表 lowering gap：`StatusConfig`、`MonsterStatusConfig`、`ILBattleStatusConfig` 现在与 Avatar/LD 状态表一起投影为 `status` entity。
- 新增 `validate_p2_s1_status_ir_rulebook`，复用 P2 矩阵并额外检查 raw -> Canonical IR -> RuleBook 的来源完整性。
- S1 检查覆盖 status entity、modifier definition、status effect、status callback、status event family、status callback task、status damage emission、action delay emission 的 source trace 与 RuleBook visibility。

## 关键结果

```text
status_definition_total=3711
status_entity_count=3729
status_entities_rulebook_visible=3729
modifier_definition_count=19018
modifier_definitions_rulebook_visible=19018
status_effect_total=69793
status_effect_source_trace_complete=69793
status_callback_count=29078
status_callbacks_rulebook_visible=29078
status_event_family_count=200
status_event_families_rulebook_visible=200
status_damage_emission_count=488
status_damage_source_trace_complete=488
unclassified_count=0
```

`status_entity_count` 大于 `status_definition_total` 是因为 IR 还包含 `AvatarStatusConfigLD` 的 18 行；这不是重复兜底，而是同一 entity table lowering 路径下的独立来源。

字段完整性：

```text
modifier_definition core fields: 19018 / 19018
status entity ModifierName: 3729 / 3729
status entity StatusType: 3729 / 3729
status entity CanDispel: 1115 / 3729
```

`CanDispel` 不是所有 raw 状态表都有字段，S1 只要求缺失被诚实计数，不把缺失字段伪装成默认可驱散。

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_s1_status_ir_rulebook --output-dir /tmp/hsr_v8_p2_s1_status_ir_rulebook
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

关键输出：

```text
v8 p2_s1_status_ir_rulebook validation ok=True
```

## 剩余范围

- S1 只证明来源完整性和 RuleBook 可见性，不新增状态 runtime 语义。
- S2 需要继续验证状态实例身份、默认刷新、默认不可叠层、同名不同来源共存/阻断和负例 state unchanged。
