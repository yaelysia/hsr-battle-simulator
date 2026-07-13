# P7-S16 战斗中召唤与生命周期待验收报告

状态：`ready_for_review=true`。本报告仅作为统一验收证据索引，不宣告阶段完成，不修改 P7 checklist。

## 本阶段结果

- `SummonMonster` ability task 通过真实敌方数据卡动作进入统一决策接口；验证路径为 scheduler 推进、只读动作查询、精确 DecisionToken 提交、selected graph 原子提交，不再直接调用 `execute_summon_monster_task` 冒充战中闭环。
- 复杂敌方 AI 未实现时，`selection_controller=external` 的已类型化卡片动作仍可由外部控制器查询和选择；只有真实 fixed sequence source 才限制候选。core 不替控制器运行复杂 AI。
- `SummonMonsterIntentIR` 与 task 精确绑定，通过 `UnitBirthTemplateIR` 产生 spawn Mutation；召唤单位保留 owner/summoner relation、生命周期来源、自身怪物卡与 action admission。
- `MCommon_Servant.OnCreate -> OwnerEntityAddAbility` 已形成真实 Canonical effect。lowering 只在结构化 `AbilityName` 存在时准入，runtime 以 checked Mutation 将能力注册到状态持有单位；缺值、未知单位和损坏 registry 均 blocked，不把该语义任务伪装成 process-only。
- presence、targetability、actionability、timeline admission 全部来自显式生命周期来源；后场或缺字段单位不能默认成为合法目标或行动者。
- runtime registry 和完整 source trace 不再决定召唤是否 active 或可替换；行为只依赖稳定类型字段，来源详情仅进入审计。
- lowering 从真实 `ByCompareTargetCount(Servant, AliveOnly) + CreateServant` 结构投影 typed replacement policy。只有该 policy admitted 时，已败退的同 owner servant 才会以 remove+spawn 单次原子提交替换；缺 policy、活跃重复、缺失/篡改 birth template 均 blocked/state unchanged。

## 结构化验证证据

最终真实 lowering 与 RuleBook 只构建一次，S16/S17 共享该对象；不序列化完整 IR：

```text
run_validation_with_rules(rules, /tmp/p7_s4_repair_real/s16)
```

结果：`ok=true`、`ready_for_review=true`、`rows=5`、`passed=5`。

五行证据：

- `in_combat_spawn`：真实 action query/token/submit，selected summon task complete，transition committed；实际产生 22 个 Mutation、1 个新单位，replay、transition contract、source audit 全部通过。
- `presence_target_timeline`：前场/后场、可选、可行动和 timeline skip 均由生命周期字段决定，缺 `targetable` 不默认 true。
- `owner_cleanup`：先以真实结构化 replacement policy 原子移除败退旧 servant 并创建新实例，再验证 owner remove policy 对新实例的 cleanup mutation/event/replay；清空 policy 的 `source_path/predicate_path/create_task_path` 后 replacement plan 行为投影完全相同。
- `missing_and_tampered_template`：缺 birth template 与篡改 template 均无 Mutation，原状态不变。
- `summon_action_source`：对出生单位实际调用 `ActionAvailabilitySystem.view`；查询非空，全部 choice 的 actor、owner entity、monster card、target/resource admission 与出生单位自身卡片一致。该行同时确认 `attached_ability_names` Mutation 已提交；缺 `AbilityName`、损坏 attachment registry 均 blocked/zero mutation，重复附着为无 Mutation 幂等成功。

本次结构化选择得到 Svarog 的 summon action，但验证器不按其名称或 ID 选择；谓词是 executable direct `SummonMonster` intent、真实 action binding、executable owner card admission 和最终完整 selected graph。Bronya 候选因真实 `Bronya_SummonMode` binding 缺失而保持 diagnostic/原子回滚，这是保留的负例，不是 fallback。

输出：

- `/tmp/p7_s4_repair_real/s16/validation_summary_p7_s16_in_combat_summon_lifecycle.json`
- `/tmp/p7_s4_repair_real/s16/p7_s16_in_combat_summon_matrix.json`
- `/tmp/p7_s4_repair_real/s16/p7_s16_in_combat_summon_evidence.json`

## 直接回归与资源边界

- P3-S3 summoned monster spawn：`ok=true`，复用 RuleBook，`lowering_build_count=0`。
- P3-S6 summon action：`ok=true`，复用 RuleBook，历史 gap 分类原样保留。
- P3-S9 lifecycle cleanup：`ok=true`，replay/source audit 通过，`rulebook_build_count=0`。
- P7-S3、S6、S8、S10、S11、S14、S15：轻量专项均 `ok=true`。
- 修复过程中两次真实构建分别暴露 stale runtime registry 和 replacement unit id 冲突，修正后最终 S16/S17 共享一次构建；只保留内存 RuleBook，未写完整 CanonicalIR/transition dump，未运行 P4/P5/P6 全聚合或 P1-5。

## 明确未做

- 未实现所有召唤物、忆灵、复杂敌方 AI 或特殊模式正例扩面。
- `OwnerEntityAddAbility` 当前完成的是可审计能力注册状态；未声称所有附着能力的后续触发图都已实现。
- 未为来源缺失的 lifecycle/action/timeline 字段制造默认值。
- 未修改 P7 checklist，未提交 Git 检查点。
