# P9-S5B 实体关系与确定性效果目标执行卡

## 执行配置

- 对应问题：P9-I06 第二部分；机制包 M04 runtime。
- 硬前置：P9-S5A 已验收并形成检查点。
- 推荐：5.6 Terra / `xhigh` / Goal。
- 推荐理由：改动面较大但语义已固定为“一个关系入口 + 一个确定性表达式入口”；不涉及动作
  提交或 RNG。Goal 只用于持续施工，不允许跳入 S5C。

## 开工导航

只读本卡、`README.md` 的 `ready_for_review` 硬门槛、S5A 最终报告和以下生产起始点：

- `TargetSystem.resolve_target_expression` 及其确定性 helper
- `systems/unit_relation.py`
- `validate_summon_runtime` 和 summon runtime 的 owner/summoner 索引
- `UnitState`、`BattleState` 中队伍、生命周期和队形事实
- S5A 类型化目标节点及目标来源责任矩阵
- 条件系统的公开调用边界；只确认接口，不实现 S6/S7

最多两轮 CodeGraph 定位。不得通读 `target.py` 的历史验证调用者；先由调用图列出本卡实际
迁移的生产消费者。若 S5A 模型或来源矩阵尚未达到本卡前提，返回 `plan_mismatch`。

## 当前事实

- `unit_relation.py` 当前主要复用队伍关系，不是完整实体关系系统。
- owner、summoner、summon members、当前动作目标、事件实体、battle-event entity、队形和部分
  alias 目前在 `target.py` 内分别读取 unit flags、summon runtime 或任意 event payload。
- summon runtime 已对 owner/summoner 正反索引和 UnitState 镜像做严格校验，应成为召唤关系
  权威来源，不能在 target 系统重建第二套索引。
- 当前 79 条来源没有完整 body-part 战斗拓扑生产者；S0 已把 unit topology 记录为外部内容依赖。
  消费者可以类型化，但不能合成 body part gameplay 正例。
- `TargetFilter` 的一般 predicate 属于 S6/S7。S5B 只提供候选集合和调用边界，不复制条件求值。
- 当前随机 helper 同时承担 shuffle 和单目标选择，但本卡禁止触碰；所有随机节点保持明确
  `pending_s5d`，不能用确定性首项 fallback。

## 阶段结果

完成后，所有确定性效果目标都通过同一个 `EntityRelationResolver` 和同一个
`TargetSystem` 表达式入口，从已提交 BattleState、已验证 summon runtime 及严格的目标上下文
求得稳定有序集合。关系不存在可以 resolved empty；关系来源损坏、上下文缺失或正反矛盾必须
blocked。随机节点仍不执行，动作候选和提交仍留给 S5C。

## 已确定的架构决策

### 1. 关系事实的唯一权威

不得向 BattleState 添加一张复制所有关系的通用表。关系解析器按以下权威读取：

| 关系 | 权威事实 |
|---|---|
| self/caster/parameter/current selected target | 严格 `TargetEvaluationContext` |
| 同队、敌对、全队、队友 | committed UnitState 的 combat team |
| 存活、离场、可选状态 | 现有 UnitLifecycleSystem |
| owner、summoner、owned summons | 通过 `validate_summon_runtime` 的 runtime 与其 UnitState 镜像 |
| 队形、左右相邻 | committed formation position；没有位置时 blocked，不按单位 ID 猜顺序 |
| 事件源、事件主体、事件目标 | typed target context；S9 生产者接入前可保持生产者依赖 |
| battle-event/独立行动实体 | 当前正式单位类型与已验证 owner/lifecycle 关系 |
| body part 与 part owner | 预留类型化 relation；当前没有真实生产者时为外部内容依赖 |
| skill-point/其他虚拟实体 | 只能读取当前正式战斗实体或类型化资源实体；不存在时 blocked |

`source_trace`、角色名、技能名、任意 event 字典和未经验证的 flags 不能成为关系依据。某项
关系若在两个权威结构中均有镜像，两侧必须一致；缺一侧、重复或互相矛盾均 fail-closed。

### 2. 严格目标上下文

建立递归不可变的 `TargetEvaluationContext` 或等价类型，明确承载本次求值允许使用的实体身份：
施放者、效果拥有者、参数实体、已选主目标，以及由正式事件生产者提供的事件实体引用。

- 构造时验证非空身份、引用角色和互斥字段；未知身份不能通过任意 payload 注入。
- S5B 的原子迁移必须在生产调用者边界创建该对象，resolver 内不再读取自由字典。
- RNG choice、伤害数值和条件临时量不属于该上下文；分别由 S5D、S4、S6/S7 的契约负责。
- S9 尚未提供的 event 字段只能使相关查询 blocked，不能建立 synthetic event producer。

### 3. 关系结果

所有 relation query 复用 S5A 的 resolved/blocked 目标集合契约：

- “某普通单位没有召唤物”“当前不存在 battle-event entity”等合法不存在关系返回 resolved empty。
- runtime 缺失、索引损坏、主体不存在、引用越界或正反矛盾返回 blocked，且不返回部分集合。
- 关系输出有稳定顺序并去重；去重保留第一次合法出现，不能用 set 的偶然顺序。

### 4. 确定性表达式语义

S5A 责任矩阵中归 S5B 的 gameplay 操作必须全部落到以下通用语义之一：

- 别名解析：只消费来源闭合的全局 alias 定义和 typed context，不在 Python 写角色 alias 表。
- 集合组合：concat 保留各子集合先后顺序并首次去重；sequence 将前一步集合传给下一操作。
- 实体查询/映射：只经 `EntityRelationResolver`。
- alive-state filter：只经生命周期系统。
- 一般 filter：目标系统生成候选并调用唯一 condition evaluator；S6/S7 未准入 predicate 时原子 blocked。
- 排序：属性、属性比例、状态层数/数值、怪物等级或正式队形使用现有 committed fact；相同键以
  原输入顺序后再以稳定实体身份消歧，不能读取显示名称。
- take/index/reverse：先完成 S4 数值求值，再执行严格边界；非法索引或非整数 blocked。
- deterministic retarget：先过滤再按来源顺序和数量截取；`ByRandom=true` 必须转交 S5D。

当前来源中只出现于 non-gameplay 分支的操作继续退役；已有通用实现可以保留，但不能把它们
作为当前角色 gameplay 完成证据。

## 详细目标

1. 建立唯一实体关系 resolver，并把 `target.py` 内本卡关系读取迁移到该入口。
2. 用严格上下文替代 owner、param、current target 和 event payload 的自由参数组合。
3. 关闭 S5A 当前矩阵中全部确定性 operator 的 lowering/admission/runtime 缺口。
4. alias 展开必须有来源、循环检测和歧义阻断；禁止安全字符串白名单继续充当内容答案。
5. 所有集合操作保证稳定顺序、无重复和完整失败原子性。
6. predicate、event producer 和 body-part producer 的后续依赖按责任阶段诚实记录，不伪造执行。

## 明确不做

- 不实现动作候选查询、外部目标提交、动作目标基数或 action choice schema。
- 不实现 random select、shuffle、随机 retarget 或 RNG/replay 修改。
- 不实现 S6/S7 条件 family；只调用其公开 evaluator。
- 不为当前来源没有的 body-part、怪物或关卡生产者建立 synthetic UnitState。
- 不把 battle-event、servant、dummy character 或后台召唤物一概当普通场上单位。
- 不实现敌方 AI、客户端锁定、视觉距离或坐标系统。

## 验收矩阵

| 目标 | 只有满足以下条件才通过 | 权威证据 |
|---|---|---|
| 单一关系入口 | 本卡所有关系查询均通过 resolver，生产代码无平行判断链 | call-path audit |
| 权威一致 | team/lifecycle/summon/context 只读对应正式事实，镜像矛盾 blocked | relation matrix |
| 确定性闭合 | S5A 中归 S5B 的 gameplay operator 均 executable 或仅剩明确下游依赖 | operator matrix |
| 集合稳定 | 重排无序输入不改变结果；有序输入语义按来源保留 | metamorphic matrix |
| 空与失败分离 | 无关系为 resolved empty；损坏关系为 blocked 且零部分结果 | outcome matrix |
| 后续依赖诚实 | body-part/event/predicate 无 synthetic gameplay producer | dependency ledger |

## 结构化通过谓词

```text
single_entity_relation_resolver=true
relation_sources_are_committed_and_typed=true
freeform_event_payload_relation_reads=0
summon_relation_uses_validated_runtime=true
relation_mirror_conflicts_fail_closed=true
deterministic_target_operators_owned_by_s5b_closed=true
target_aliases_source_backed=true
target_alias_cycles_or_ambiguities_blocked=true
target_order_stable_and_duplicates_removed=true
legal_missing_relation_resolves_empty=true
damaged_relation_returns_no_partial_targets=true
predicate_evaluator_not_duplicated=true
body_part_synthetic_producer_count=0
random_target_execution_count=0
character_specific_relation_handlers=0
```

## 必须覆盖的负例

- summon runtime 与 UnitState 的 owner、summoner 或索引不一致。
- forged owner、跨队关系、未知主体、重复关系成员和离场/不可选身份误入结果。
- event payload 直接注入不存在单位，或绕过 typed context 提供 event entity。
- alias 循环、多候选、未知 operation、按角色/技能名称补答案。
- concat/sequence 因 set 或输入字典顺序产生不稳定结果。
- sort 键缺失、非有限、来源不合法或 tie breaker 不稳定。
- take/index 数值非整数、越界、缺绑定；retarget predicate 失败后仍返回部分集合。
- `ByRandom`、shuffle 或随机任务走首项/固定顺序 fallback。
- body-part 无生产者时通过 validation fixture 冒充当前角色真实正例。

## Gap 与停止条件

- 某关系要求新增持久战斗状态而不能从现有权威推导：先提交影响分析，返回 `plan_mismatch`。
- 发现当前 79 条来源存在真实 body-part gameplay producer：暂停并补生产者归属，不按本卡旧事实延期。
- 一般 predicate 的失败根因属于条件 evaluator：记录 S6/S7 精确 family 和来源，本卡不得修条件。
- event relation 缺失正式生产者：记录 S9/S17 依赖；消费者必须 typed blocked。
- 确定性主入口需要完整 Canonical IR 或超过预算：暂停并在来源/IR 前缩窄，不提高上限。

## 拟改范围

- `systems/unit_relation.py` 或同领域新模块：通用 entity relation resolver。
- `systems/target.py`：确定性表达式统一迁移和自由上下文退役。
- `systems/summon_runtime.py`：仅在复用公开验证/查询接口确有必要时做最小通用扩展。
- `rules/ir.py`、`tbgd/lowering.py`：只补 S5B operator/relation typed lowering。
- 实际生产调用者：只迁移创建严格目标上下文所需的最小集合。
- 新增 `tools/validate_p9_s5b_entity_relation_deterministic_target.py` 与仓库级报告。

禁止修改动作 target contract、`ActionChoice` schema、RNG、事件生产者、条件 evaluator 语义、UI、
总 checklist 和 Git 历史。

## 验证与资源

唯一主入口：

```text
validate_p9_s5b_entity_relation_deterministic_target
```

- 由 S5A 矩阵选择互不重复的最小真实来源形状；source filter 必须在 ability read 前生效。
- 一个正式 resolver 入口和一个正式 expression 入口证明全部关系/operator；不得为每个 alias
  建一个手工场景。
- direct 最多 1 项：仅当 summon runtime 的公开查询/校验接口改变时运行对应轻量 active contract。
- 不重跑 S5A 主验证，不跑历史 P1-6/P3-S8 聚合。
- 主入口上限 5 分钟；阶段累计 9 分钟；峰值 768 MiB；evidence 2 MiB；新增验证代码 700 非空行。
- 固定顺序：`compileall -> 秒级关系负例 -> 唯一主入口 -> 必要 direct -> git diff --check`。

## 唯一执行清单

- [ ] 实体关系全部迁移到单一 resolver 和明确权威来源。
- [ ] 自由 event/owner 参数迁移为严格目标上下文。
- [ ] S5B 负责的确定性 operator 全部闭合。
- [ ] 空关系、损坏关系和下游生产者依赖诚实区分。
- [ ] 无随机、动作提交、条件副本或 synthetic body-part 实现。
- [ ] 主验证、必要 direct、资源审计和 `git diff --check` 通过。
- [ ] 仅提交 `ready_for_review`；未勾总 checklist、未提交 Git、未进入 S5C。
