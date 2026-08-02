# P9-S6 committed-state 与实体条件族闭合执行卡

## 执行配置

- 对应问题：P9-I07 第一部分；机制包 M05。
- 硬前置：P9-S5 已验收并形成检查点。
- 推荐：5.6 Sol / `xhigh` / Goal 模式。
- 理由：条件数量较多但本卡只处理 committed state、数据卡身份和目标集合可直接提供的 operand，适合按 family 批量闭合。

## 当前事实与阶段结果

当前来源有 86 个条件族，45 个尚未被 evaluator 接纳。它们不能一次混做：一部分只读取
BattleState、数据卡、状态和目标集合；另一部分需要动作、事件、队列、伤害或资源瞬时上下文。

完成后，S6 生成当前指纹下互斥穷尽的 `S6-state/entity` 与 `S7-transient-context` 分区，并
关闭前者。比较生命、角色/怪物身份、命途、队伍关系、目标集合量词、状态、可选/离场和
body-part 等条件通过统一 operand + comparator + quantifier 求值。

## 详细目标

1. 从当前 45 个缺口动态分区；不得手工维护固定名单作为完整性来源。
2. 建立 committed-state operand：属性/生命、角色与怪物卡身份、队伍/实体关系、状态/行为标记、目标集合。
3. 建立 any/all/not/and 等组合和列表量词的短路、空集合和 blocked 语义。
4. 复用 S4 numeric、S5 target/relation，不在 evaluator 复制取值逻辑。
5. 未知 property、错误 operand kind、跨实体身份和关系损坏返回 blocked，不返回 false 掩盖错误。
6. 输出 S7 继承的剩余 family manifest、来源指纹和所需 transient context 字段。

## 本阶段不做

- 不处理当前行动实体、技能窗口、事件 payload、插入队列、伤害窗口或资源变化标签。
- 不处理 build selector；S2 已在 assembly 解析。
- 不为单一低频条件写角色专属分支。
- 不伪造未来死亡/独立实体生产者；只验证已有 committed-state 表达能力。

## 架构与负例

- empty any=false、empty all=true 仅在集合解析成功时成立；解析失败仍 blocked。
- 缺单位、错误卡 kind、伪 body-part owner、未知状态和非有限比较值必须 blocked。
- `false` 是合法业务结果，不能与 `blocked` 合并。
- 条件 payload 未知字段和 source fingerprint 篡改必须拒绝。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 分区完整 | S6/S7 合集等于当前缺口，交集为空 | condition partition |
| S6 family 闭合 | 每族 lowering/evaluator/负例一致 | state-condition matrix |
| 组合语义正确 | any/all/and/not 与 empty/blocked 分离 | quantifier matrix |
| 上下文复用 | operand 由 S4/S5/committed state 提供 | call-path audit |
| S7 依赖清晰 | 每个剩余族记录所需 transient context | handoff manifest |

## 结构化通过谓词

```text
condition_partition_current=true
s6_s7_union_equals_current_missing_conditions=true
s6_s7_intersection_empty=true
s6_state_entity_family_gap_count=0
condition_false_and_blocked_distinct=true
empty_quantifier_semantics_correct=true
numeric_and_target_operands_reused=true
unknown_operand_or_relation_blocked=true
build_selectors_absent_from_runtime_partition=true
character_specific_condition_handlers=0
```

## Gap 与停止条件

- 条件实际需要 transient context：移入 S7 并记录依据，不在 S6手填 context。
- 条件需要当前未实现 committed-state 字段：若属于 S10-S17 生产者，建立类型契约并记录 not-proven；不得伪造生命周期。
- 分区遗漏或同族双归属：阶段阻断。
- evaluator 只能通过返回默认 false 避免 blocked：阶段阻断。

## 拟改范围

- `rules/evaluator.py`、`rules/expression_ir.py`、`rules/ir.py`。
- `tbgd/expression_lowering.py` 的条件 operand/quantifier 投影。
- S4/S5 公共查询只做必要扩展；不改事件/伤害生产者。
- 主验证 `tools/validate_p9_s6_state_entity_condition_closure.py` 和报告。

## 验证与资源

- 一次读取当前条件 family，S6 只构建本分区 IR；S7 行只输出 manifest，不执行。
- 独立 raw oracle 只核对字段投影，不复制生产 evaluator。
- direct 最多 2 项：evaluator 基础契约、target relation；仅实际触达时运行。
- 预算：8 分钟、1 GiB、5 MiB、900 行；不跑全条件/全角色动作聚合。

## 唯一执行清单

- [ ] 当前缺口条件形成 S6/S7 穷尽互斥分区。
- [ ] S6 committed-state/entity/list family 零内部 gap。
- [ ] false、blocked、empty 和组合量词语义正确。
- [ ] 复用 S4/S5 operand 与 relation，无重复取值系统。
- [ ] S7 剩余 manifest 当前、完整、可追溯。
- [ ] 主验证、必要 direct 和资源审计通过并提交 `ready_for_review`。
