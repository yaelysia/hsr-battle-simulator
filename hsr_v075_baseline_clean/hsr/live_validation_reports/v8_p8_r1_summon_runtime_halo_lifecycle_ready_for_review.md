# P8-R1 召唤运行时与通用光环生命周期修复：ready_for_review

执行状态：`ready_for_review`。基线：`137167d`。

本报告只提交实现与聚焦证据供验收复核，不代表执行线程自行验收完成。P8 Checklist 未修改，Git 未提交，遗器阶段未开始。

## 本轮修复

- 正式 `ScenarioStateBuilder` 在 provider 注册、启动效果和开局事件之前，通过唯一生产构造器建立当前 schema 的空召唤运行时；scenario 不能注入第二份运行时。
- 召唤 runtime 由共享校验器 fail-closed 校验。缺失、版本错误、索引损坏、active entity 与 UnitState 的 owner / 类型 / 生命周期矛盾、servant 反向索引缺失均不会降级为空集合。
- 召唤 runtime 与场上单位实行完整双向一致性检查：不仅 active 登记必须有单位，任何仍在场的 servant / summoned monster 也必须有 active 登记；active 关系的 owner 与 summoner 必须真实存在，runtime 与 UnitState 的 owner / summoner / team side 必须一致，召唤单位、owner 与 summoner 的实际战斗阵营也必须一致。双方同时伪造不存在的 owner、召唤者错绑或阵营整体篡改均结构化 blocked。
- target 查询区分 resolved-empty 与解析失败。合法空 servant 集合可供条件计算为 false、群体状态形成可审计 no-effect；需要必选目标的动作仍不可用。
- 只有严格布尔 `IsHaloStatus=true` 的真实 AdditionConfig 子效果可建立光环；非法类型 blocked，缺失或 false 保持普通子效果语义。
- 父状态保存唯一、可序列化的 source-backed halo relation；成员子状态只保存投影身份，不复制第二套装备效果 payload。
- 通用 reconciliation 覆盖首次施加、叠层 / 动态值变化、出生、死亡 / 复活、owner 关系变化、离场、父状态移除、snapshot 恢复和孤儿投影清理。
- relation ID、成员 source-stack key、父状态身份、子效果 raw 身份、完整 `IRSource` 证据、目标表达式、目标别名和 `AliveOnly` 均重新从可信 IR / 父状态核对，不能由关系内部字段互相自证。
- 父关系的成员清单与场上实际子状态双向对账。父记录有成员而子状态缺失时从可信关系恢复；重复投影、错 modifier、错 caster、错 source-stack key 或错来源证据一律 fail-closed。
- 离场父单位不再提供有效光环关系；孤儿清理负责移除其全部成员投影。波次替换在新旧单位 mutation 后、波次事件分发前执行同一通用 reconciliation。
- 波次 transition 不再先记录原始光环 lifecycle event、再重复追加 dispatcher 返回的同一事件；正式日志只采用 dispatcher 返回链。事件身份必须唯一，记录数量必须与实际派发数量一致。
- 召唤 spawn / remove 与 halo 对账作为一个原子结果返回；后续关系失败时，前面已计算的 mutation、event、RNG 和非过程 settlement 全部丢弃。
- executor 在统一原子提交前执行通用 halo reconciliation；不可变事件序列不再调用 `extend()`。召唤清理和最终光环 reconciliation 产生的 lifecycle event 均进入正式 dispatcher，callback mutation、settlement、RNG 和节点结果参与同一原子提交。
- `SummonTransitionResult`、能力任务消费和波次 transition 均完整传递光环 RNG；当前真实 12 条光环没有概率字段，概率 fixture 证明 RNG 不会在召唤边界丢失。
- 光环子效果 lowering 保留 `DynamicValues` 等标准 AddModifier 数值字段。首次和后续投影统一读取父状态最终保存的动态值，不再首轮读取调用方原始参数、后续读取状态值。当前 12 条真实光环中 8 条动态值依赖均进入来源矩阵，投影缺口为 0。
- P8-S8 中手写的当前召唤 runtime fixture 已迁移到生产构造器，旧 P3 只读 legacy normalization 负例保持为兼容边界，不进入正式写路径。

## 聚焦证据

最终合并验证：

```text
/tmp/hsr_p8_r1_relation_event_fix_final
ok=true
mode=combined
full_tbgd_lowering_count=0
catalog_builder_count=1
large_ir_artifact_written=false
artifact_total_size=136K
```

当前光锥来源扫描：

```text
published_definition_count=162
ability_source_file_count=14
published_light_cone_halo_source_count=12
published_light_cone_halo_projection_gap_count=0
halo_dynamic_source_count=8
halo_dynamic_projection_gap_count=0
published_halo_dynamic_values_projected=true
halo_source_flag_strictly_typed=true
equipment_specific_halo_handlers=0
```

runtime 聚焦矩阵全部通过，包含：

```text
formal_state_has_canonical_empty_summon_runtime=true
summon_runtime_initialized_before_provider_and_setup_events=true
missing_or_malformed_summon_runtime_blocked=true
summon_runtime_active_registry_is_bidirectional=true
summon_runtime_relationship_identity_is_bidirectional=true
valid_empty_servant_group_resolved=true
resolved_empty_condition_evaluates_false=true
resolved_empty_group_effect_is_audited_no_effect=true
required_action_with_empty_target_group_unavailable=true
halo_relation_persists_without_current_member=true
late_spawn_receives_active_halo=true
late_spawn_uses_current_parent_stack_and_values=true
halo_reconciliation_idempotent=true
missing_halo_child_is_restored_from_canonical_relation=true
duplicate_halo_child_projection_is_blocked=true
halo_relation_full_source_evidence_is_verified=true
ineligible_member_does_not_retain_halo_child=true
reeligible_member_is_reconciled=true
parent_removal_cleans_halo_children=true
removed_halo_source_cleans_all_children=true
same_named_independent_status_preserved=true
multiple_halo_sources_isolated=true
failed_reconciliation_state_unchanged=true
snapshot_round_trip_preserves_halo_semantics=true
sampled_halo_mutations_source_audited=true
sampled_halo_transitions_replay_equal=true
summon_halo_rng_channel_is_not_dropped=true
wave_transition_reconciles_and_dispatches_halo_lifecycle=true
```

波次轻量正式协调链证明：旧成员投影移除、新成员投影建立，所有 mutation 有 settlement，status lifecycle event 经过 dispatcher，最终 snapshot 可由公开 mutation 完整 replay。本轮生成、派发并最终记录的 lifecycle event 均为 8 条，事件 ID 唯一，没有重复追加。

召唤关系固定负例：

```text
active_entity_owner_unit_missing -> summon_runtime_active_entity_owner_unit_missing
runtime_and_unit_owner_simultaneously_forged -> summon_runtime_active_entity_owner_unit_missing
runtime_unit_summoner_mismatch -> summon_runtime_entity_unit_summoner_mismatch
active_entity_summoner_unit_missing -> summon_runtime_active_entity_summoner_unit_missing
runtime_and_unit_team_side_simultaneously_forged -> summon_runtime_entity_owner_combat_team_mismatch
```

P7 直接回归：

```text
P7-S3 selected graph atomic commit: ok=true, cases=9
P7-S15 RNG identity/replay: ok=true, rows=14
```

`compileall` 在 1 GiB 地址空间上限内通过；`git diff --check` 通过。

## 受资源上限阻断的回归与验收边界

以下入口均已在最终生产修改后串行执行一次，并固定 1.5 GiB 地址空间、低 CPU / IO 优先级；它们都在完整 CanonicalIR lowering 阶段触发 `MemoryError`，未提高上限、未重跑：

```text
P3-S2 summon runtime schema
P3-S8 summon target relations
P3-S9 summon lifecycle cleanup
P7-S17 wave lifecycle events
P8-S8 --catalog-startup-only
```

因此本报告不声明以下目录级谓词已经由当前源码重跑证明：

```text
catalog_started_count
catalog_equipment_failure_count
catalog_external_character_build_dependency_count
formal_catalog_startup_complete
```

按当前复核指令，正式全目录启动证据暂不在本轮修复范围内；本报告继续保持该项未证明，且不得把本次 focused `ok=true` 替代正式目录启动证据。
