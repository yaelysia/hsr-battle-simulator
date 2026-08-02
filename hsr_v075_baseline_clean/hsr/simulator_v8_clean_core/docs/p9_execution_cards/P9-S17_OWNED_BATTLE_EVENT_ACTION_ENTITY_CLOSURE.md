# P9-S17 角色拥有的战斗事件、独立行动实体与事件目录收口执行卡

## 执行配置

- 对应问题：P9-I17、P9-I09 剩余事件；机制包 M15、M07 收口。
- 硬前置：P9-S16 已验收并形成检查点，S9-S16 event evidence 当前。
- 推荐：5.6 Sol / `max` / Goal 模式。
- 理由：独立行动实体跨 owner、出生、离场、queue、wave 和事件目录，并承担125事件族最终归零检查。

## 当前事实与阶段结果

当前 M15 有 3 个顶层来源族、18 次出现，涉及9条目标角色。神君、账账、浮元等来源属于
角色拥有的行动实体或 battle event；表现搭档不是战斗单位。P3/P8 已有 summon/relation/
lifecycle 基础，但不能把 memory servant 或所有 partner 统一套入当前范围。

完成后，当前非记忆/非欢愉角色拥有的独立行动实体通过通用 entity definition、owner relation、
birth/lifecycle、queue 和 action graph 执行。Create/owner-change/depart/wave 等 S17-owned 事件
真实生产。S9-S17 事件分区合集在当前指纹下全部 closed，未知/重复/无 owner 事件为零。

## 详细目标

1. 闭合 CreateBattleEvent、ChangeBattleEventOwner、OwnerEntityAddAbility 及对应 entity source graph。
2. 分类真正独立行动实体、普通召唤单位、角色状态代理和纯表现 partner；只有战斗实体进入生命周期。
3. entity 保存定义、owner/summoner、team、location/topology、action set、timeline/queue 和来源身份。
4. 出生、owner 变化、行动、死亡、离场和波次切换复用 unit_spawn/relation/lifecycle/queue，不建角色 handler。
5. action entity 的可选动作和目标来自自身数据卡/definition，推演器像操作普通单位一样选择。
6. 生产 S17-owned create/owner/depart/wave/entity-action 事件并闭合 callback。
7. 重算 S9-S17 事件合集，要求当前125个 gameplay event family 全部有正式 producer/consumer 或真实 source gap。

## 本阶段不做

- 不处理记忆命途 owned-combatant；它们不是本阶段正例或完成条件。
- 不把演出搭档、模型 partner 或 camera battle event 建成 UnitState。
- 不实现敌方 AI 或实体自动决策。
- 不按神君/账账/浮元名称建立类型。

## 架构与负例

- owner/summoner/team 双向不一致、重复实体身份、伪定义、孤儿 queue item 和错误 wave membership 必须 blocked。
- owner 变化失败时 relation、provider、queue、events 全部不变。
- 表现 partner 的相似 create task 不能进入 gameplay entity。
- 事件合集缺族、双重 producer、同身份冲突或只有验证 fixture producer 均阻断收口。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| M15 来源闭合 | 当前独立实体 family 零内部 gap | entity matrix |
| 生命周期/关系 | birth-owner-action-depart-wave 连续 | lifecycle trace |
| 动作可操作 | query/submit 使用 entity definition | formal action sample |
| 表现排除 | partner 类分支零 UnitState | classification negatives |
| 事件总收口 | S9-S17 union 完整、交集和 gap 为零 | final event matrix |
| replay/source | 实体动作和生命周期可追溯重放 | audit samples |

## 结构化通过谓词

```text
s9_s16_event_evidence_current=true
current_owned_action_entity_family_gap_count=0
combat_entity_and_presentation_partner_distinct=true
entity_owner_relation_bidirectionally_validated=true
entity_birth_action_departure_use_common_routes=true
owner_change_transition_atomic=true
action_entity_query_submit_formal=true
s9_s17_event_union_equals_current_gameplay=true
current_event_family_internal_gap_count=0
fixture_only_event_producer_count=0
character_specific_action_entity_handlers=0
sampled_entity_replay_equal=true
```

## Gap 与停止条件

- 真实来源属于记忆/欢愉：标 deferred，不能计入当前通过或拿来做正例。
- entity 实际复用普通怪物卡/召唤卡：沿现有数据卡关系，不复制定义。
- 当前事件仍缺领域 producer：退回对应 S10-S16，不在 S17 写通用万能 producer。
- event union 只有提高过滤或允许列表才能为零：阶段阻断。

## 拟改范围

- `systems/unit_spawn.py`、`unit_relation.py`、`unit_lifecycle.py`、`queue.py`、`wave.py`。
- `systems/summon.py` / `summon_runtime.py` 仅复用通用关系，不扩记忆专属逻辑。
- battle-event/action-entity IR、角色 lowering 和 RuleBook 查询。
- 主验证 `tools/validate_p9_s17_owned_battle_event_action_entity_closure.py` 和报告。

## 验证与资源

- 一次窄投影 M15 和 S17-owned events；事件最终矩阵重算来源/producer 状态，但不执行 S9-S16 全部案例。
- 正式 spawn/query-submit/action/depart/wave 链；不手工插 UnitState 或 queue item。
- direct 最多 2 项：spawn/relation lifecycle、queue/wave，仅实际触达时运行。
- 预算：10 分钟、1 GiB、8 MiB、1,000 行；不跑 P3 聚合、记忆目录或完整角色目录。

## 唯一执行清单

- [ ] 当前角色独立行动实体和 battle-event 来源零内部 gap。
- [ ] combat entity、普通召唤和表现 partner 分类正确。
- [ ] owner/relation/birth/action/depart/wave 共用现有生产路线。
- [ ] S17-owned 事件及 S9-S17 全事件目录零内部 gap。
- [ ] 无 fixture-only producer、万能事件或角色实体 handler。
- [ ] 主验证、必要 direct 和资源审计通过并提交 `ready_for_review`。
