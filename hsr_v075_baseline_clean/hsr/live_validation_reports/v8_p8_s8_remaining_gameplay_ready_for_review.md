# P8-S8 光锥剩余 gameplay 闭环：ready_for_review

执行提交状态：`ready_for_review`。验收状态：`accepted`（2026-07-22）。

本报告只提交验收复核，不代表执行线程自行验收完成。P8 Checklist 未修改，Git 未提交；P8-S9 未开始。记忆角色构筑仍是角色侧外部依赖，本轮没有实现、合成或绕过该依赖。

## 本轮收口结果

- 已发布光锥目录仍为 162 张，机制图 lowering 未引入未知机制。
- 先前唯一的非记忆光锥启动失败已通过同一正式构筑入口定向复核：定义 `21011` 启动成功，装备失败数为 0。
- 14 张记忆命途光锥继续保留为“缺少当前可准入记忆角色构筑”的外部依赖；不计作装备机制失败，也没有通过跨命途样例冒充同命途正式启动。
- 无可执行效果的 executable callback task 现在 fail-closed：`ok=false`、零 mutation、state unchanged，并保留稳定 blocked record。
- 资源事件专项继续使用已经验收的权威契约；完整聚合调用同一 `_authoritative_resource_event_evidence`，不再重新宽松选样。

## 495 个旧证据缺口的闭合方式

旧完整 inventory 的 495 个缺口全部是 `exact_family_evidence_failed`，没有新的 lowering、admission 或未知机制缺口。本轮不再按宽泛路由盖章，而是按精确 family 分片执行：

- 任务：64/64 个精确任务族执行成功。
- 属性消费：23/23 个 `StackProperty` 族分别改变对应消费侧。
- 事件：51/51 个有真实引用的事件族完成 producer → dispatch → callback → mutation/settlement/source audit/replay；`OnListenTurnEnd` 的 1 条来源保持为明确 unreferenced，不伪造生产者。
- 条件：41/41 个条件族、372 条真实来源完成真假与 fail-closed 证据。
- 数值：1,312 条表达式全部求值；8 条零下限规则均证明直接栈操作数关系。

四个任务批次的 family 并集与旧完整 inventory 完全一致，无重复、无缺项；七个事件批次加两个定向修复样例覆盖全部 51 个可执行事件族，剩余 1 个事件族由 unreferenced 清单明确保留。由此，旧 495 条 source row 均能映射到当前精确 family 证据。这里没有声称重新跑过完整聚合；它是对既有完整 inventory 与当前分片证据的无损归并。

## 本轮新增的根因契约

### 状态与动态值

- `ReplaceByCaster` 只允许同 caster 替换；不同 caster 不匹配，尚未结构化表达的 `ReplaceByCasterAbility` 继续 fail-closed。
- 只有能力/状态定义内明确声明的 `Type=None` 内部动态槽可以从 0 开始。
- 外部作用域或未声明 hash 不会因“缺值”被默认成 0；验证同时覆盖错误 runtime hash 不得注入。

### DOT 与自定义事件

- `DamageByAttackProperty` 的 DOT 百分比项直接引用 source-backed attacker attack basis，不再使用无真实绑定的占位 basis。
- `DamageValue` 和 `DamagePercentage × attack` 是两个独立可加基础项；固定值为 0 时也不能吞掉百分比项。
- 百分比 basis 缺失时结果 blocked，最终伤害为 0。
- 真实 `custom.event` 的动态键和值可沿生产事件绑定到对应状态消费 hash，最终产生非零 DOT mutation，并通过 settlement、来源审计与 replay。

## 聚焦证据

所有命令均单进程串行执行，使用 4 GiB 地址空间上限、低 IO/CPU 优先级，且不写完整 CanonicalIR 或 transition dump。

```text
/tmp/hsr_p8_s8_tasks_batch1_current          16/16 task families
/tmp/hsr_p8_s8_tasks_batch2_current3         16/16 task families
/tmp/hsr_p8_s8_tasks_batch3_current          16/16 task families
/tmp/hsr_p8_s8_tasks_batch4_current          16/16 task families
                                               23/23 stack-property consumers

/tmp/hsr_p8_s8_events_batch1_current          8/8 referenced event families
/tmp/hsr_p8_s8_events_batch2_current          7/8；失败项由下方定向证据替换
/tmp/hsr_p8_s8_event_before_break_current     OnBeforeBeingBreak=true
/tmp/hsr_p8_s8_events_batch3_current          7/8；失败项由下方定向证据替换
/tmp/hsr_p8_s8_event_custom_current5          OnCustomEvent=true
/tmp/hsr_p8_s8_events_batch4_current          8/8
/tmp/hsr_p8_s8_events_batch5_current          7/7 + OnListenTurnEnd unreferenced
/tmp/hsr_p8_s8_events_batch6_current          8/8
/tmp/hsr_p8_s8_events_batch7_current          4/4
/tmp/hsr_p8_s8_status_replacement_final       replacement fail-closed=true

/tmp/hsr_p8_s8_conditions_current             41/41 families，372/372 sources
/tmp/hsr_p8_s8_numeric_contract_final         1,312/1,312 expressions
/tmp/hsr_p8_s8_catalog_21011_final             1/1 targeted formal startup
```

数值专项新增谓词：

```text
declared_internal_dynamic_slots_are_fail_closed=true
dot_fixed_and_percentage_terms_are_independently_closed=true
zero_floor_binding_proves_direct_max_operand_relation=true
```

状态替换专项新增谓词：

```text
replace_by_caster_selects_only_same_caster=true
replace_by_caster_rejects_different_caster=true
unmodeled_replacement_namespace_fails_closed=true
```

`compileall`（仅直接触达文件）与 `git diff --check` 均通过。

## 资源控制与未运行项

本轮没有运行完整 P8-S8 聚合、P1-P7 阶段聚合或 `validate_v0_209`。原因是这些命令会重复完整 lowering / RuleBook 构建，与当前定向缺口无额外诊断价值，并且用户已明确要求避免再次打满内存和磁盘 IO。

`validate_p2_s8_status_damage` 与 `validate_v0_263` 已迁移到新的 source-backed DOT basis 口径并通过编译检查，但其入口会再次完整构建 TBGD，因此未作为本轮定向验证执行。DOT 的正负契约已经由 S8 数值专项直接覆盖。

完整 S8 聚合如由验收线程复跑，必须继续串行限流；它应直接消费同一资源专项函数和当前精确 family 函数，不应再维护第二套宽松选样逻辑。

## 验收线程复核

验收线程复查了生产代码、全图准入、callback 原子回滚、资源事件契约、记忆命途外部依赖分类、逐 family 证据映射和 runtime 边界。未发现固定光锥 ID、装备专用 runtime handler、部分图执行、raw runtime 读取或用角色构筑缺口豁免机制覆盖的路径。

当前源码下以 4 GiB 地址空间上限、最低 IO 优先级和低 CPU 优先级串行补跑了一次完整 S8 聚合：

```text
/tmp/hsr_v8_p8_s8_acceptance_full_current
ok=true
published_light_cones=162
started=148
external_character_build_dependency=14
s8_source_rows=3464
s8_remaining_family_gap_count=0
published_light_cone_blocked_graph_count=0
unknown_gameplay_node_count=0
catalog_equipment_failure_count=0
equipment_specific_runtime_handlers=0
runtime_raw_equipment_reads=0
```

直接共享底座回归通过：

```text
P7-S12 damage/toughness: 12/12
P7-S13 HP/shield: 13/13
P7-S10 timeline: 6/6
P7-S15 RNG: 14/14
compileall: passed
git diff --check: passed
```

旧 `validate_p3_s8_summon_target_relations` 在 4 GiB 和 6 GiB 上限下均因完整 TBGD lowering 的既有高峰值 `MemoryError` 退出。为排除 S8 内存回归，验收线程对 P8-S7 检查点 `0648327` 做了同条件只读对照；旧基线在相同 lowering 位置同样 `MemoryError`。因此该结果归为旧验证器资源结构问题，不归为 S8 语义失败；本阶段实际触达的 owner/team/enemy/summon 目标关系已由完整 S8 聚合中的 source-backed target matrix 覆盖。

验收结论：P8-S8 通过。`formal_catalog_startup_complete=false` 继续准确表示 14 张记忆命途光锥尚缺角色侧忆灵构筑，不阻断光锥机制闭环，也不能被解释为 P8 全目录正式入战完成。
