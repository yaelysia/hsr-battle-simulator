# P9-S5 目标表达式、实体关系与随机目标闭合执行卡

## 执行配置

- 对应问题：P9-I06；机制包 M04、M16 目标部分。
- 硬前置：P9-S4 已验收并形成检查点。
- 推荐：5.6 Sol / `max` / 普通聚焦。
- 理由：目标错误会把正确效果施加到错误单位，且 owner、战斗事件、body part、离场实体和随机选择跨多个系统。

## 当前事实与阶段结果

当前来源有 23 个目标/上下文族、12,732 次出现，现有 `TargetSystem`、`unit_relation` 和
queue target resolver 可复用。旧 blocked 仍包含目标别名、集合量词、重定向和事件实体关系。

完成后，action definition 持有类型化目标表达式；runtime 从 committed state、事件上下文和
实体关系求得有序目标集合，并严格区分“合法空集合”“解析失败”“目标基数不合法”。随机
目标和 shuffle 使用统一 RNG ledger，可由推演器选择并稳定 replay。

## 详细目标

1. 完整支持当前 alias、query、filter、concat、map、sort、take、sequence、retarget 和 relation 形状。
2. owner/summoner/battle-event/body-part/team/formation/skill-point entity 关系通过类型化 relation 查询。
3. 目标去重、稳定顺序、alive/selectable/team 过滤和 singleton/list 基数在 action contract 校验。
4. target persistence 只消费 S0 投影，不执行客户端锁定操作。
5. RandomSelect/Shuffle 先建立候选集合，再记录稳定 choice identity；候选变化使旧选择失效。
6. 目标表达式缺字段、未知 alias 或关系双向不一致时 fail-closed。

## 本阶段不做

- 不决定敌方 AI 目标；推演器从合法候选中选择。
- 不模拟视觉站位、移动轨迹、相机中心或物理距离，除非已有战斗关系来源。
- 不创建角色专属目标 resolver。
- 不执行目标上的状态/伤害效果。

## 架构与负例

- 合法空召唤/队伍关系返回 resolved empty，损坏关系返回 blocked。
- forged owner、跨队关系、body-part owner 矛盾、重复单位、死亡/不可选目标均拒绝。
- 目标顺序变化不能无意改变非随机效果；随机顺序必须由 RNG ledger 解释。
- 外部提交不在当前候选集、过期 choice ID 或重复选择必须 blocked。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 表达式完整 | 当前 M04 family 均有 typed lowering/resolution | family matrix |
| 关系正确 | owner/team/event/body-part 双向一致 | relation matrix |
| 三态明确 | empty、blocked、基数不合法不混淆 | target outcome matrix |
| 随机可重放 | 候选、choice、RNG、replay 一致 | RNG matrix |
| action 归属正确 | 目标规则来自 action definition | code/source audit |

## 结构化通过谓词

```text
current_target_families_all_typed=true
target_expression_resolution_deterministic=true
empty_and_resolution_failure_distinct=true
entity_relations_bidirectionally_validated=true
target_cardinality_enforced=true
client_target_lock_not_executed=true
random_target_choice_identity_stable=true
stale_or_external_choice_rejected=true
blocked_target_resolution_state_unchanged=true
character_specific_target_handlers=0
```

## Gap 与停止条件

- 目标需要当前模型不存在的真实 relation：建立通用 relation 类型；若会改变单位模型，暂停审查影响范围。
- 只靠角色/技能名称能解释 alias：保持 blocked，不写映射表。
- 随机候选无法在选择前完整确定：阶段阻断，不能让推演器计算候选。
- 视觉位置没有战斗语义：non-gameplay，不实现坐标系统。

## 拟改范围

- `systems/target.py`、`systems/unit_relation.py`、`systems/action_contract.py`。
- `rules/ir.py` / `tbgd/lowering.py` 的目标表达式和关系来源。
- `systems/rng.py` 仅扩展通用选择账本；不改随机策略。
- 主验证 `tools/validate_p9_s5_target_entity_relation_closure.py` 和报告。

## 验证与资源

- 来源层只投影 M04 与随机目标 family，一次最小 RuleBook；不建立完整角色动作目录。
- 使用正式 target query/submit 和一个 RNG 选择链；不手工调用内部 filter 冒充端到端。
- direct 最多 2 项：target 三态、RNG replay，只在对应生产符号实际改变时运行。
- 预算：8 分钟、1 GiB、5 MiB、900 行；不跑 P1-6/P7 全脚本套餐。

## 唯一执行清单

- [ ] 当前目标表达式和关系 family 全部类型化。
- [ ] 空集合、失败和基数不合法三态严格区分。
- [ ] owner/team/event/body-part 等关系双向闭合。
- [ ] 随机目标候选与选择使用统一 RNG ledger 并可 replay。
- [ ] 无 AI、视觉位置或角色专属目标逻辑。
- [ ] 主验证、必要 direct 和资源审计通过并提交 `ready_for_review`。
