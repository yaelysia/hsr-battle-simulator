# P9-S5A 目标来源集合与类型化契约执行卡

## 执行配置

- 对应问题：P9-I06 第一部分；机制包 M04 的来源和 IR 边界。
- 代码基线：P9-S4 检查点 `8105090`；规划文档改动不构成新的代码基线。
- 硬前置：P9-S4 已验收；不得同时实施 S5B-S5D。
- 推荐：5.6 Terra / `xhigh` / 普通聚焦。
- 推荐理由：本卡需要严谨迁移共享数据契约，但不设计新战斗语义、不修改动作交互或 RNG；
  架构选择已在本卡固定，适合作为 Terra 的首次执行试点。

## 开工导航

执行线程只读本卡、`README.md`、共享机制归并文档的 M04/M16 段，以及以下起始符号：

- `build_character_ability_scope_projection`
- `TargetExpressionIR`、`TargetExpressionNodeIR`、`ConditionIR`
- `_target_expression_from_raw`、`_target_expression_execution_node`
- `TargetSystem.resolve_target_expression`、`TargetExpressionResult`
- Canonical IR 和 RuleBook 中现有目标表达式集合与查询

最多两轮 CodeGraph 定位。不得先扫描整个项目、通读历史目标验证器或完整 P1-P8 报告。
卡内事实若与当前代码冲突并改变职责或验收，返回 `plan_mismatch`，不要自行改目标。

## 当前事实

- S0 已提供可按 family 过滤、在 IR materialization 前生效的角色能力窄投影；S5 不需要另建
  raw 扫描器，也不能先构建完整 Canonical IR 再过滤。
- 全局目标别名和点操作还来自 `TargetAliasConfig.json` 与 `TargetOperationConfig.json`。它们是
  目标语言来源的一部分，必须和角色节点分别保留字节指纹，不能退化成 Python alias 白名单。
- 当前来源中的目标语法不等于全部 gameplay：`TargetTimeSlow` 和客户端排序等仅属表现；
  `SetTeamLockTarget` 已投影为输入数据；同一 `TargetAlias` family 也分属 gameplay、构筑、
  输入投影、战斗数据投影、待解码和非战斗范围。
- 旧文档中的“23 个 family、12,732 次”不是可复现验收集合。当前来源发生变化时，不能用
  固定数量、文件、角色或 ID 维持旧数字。
- `TargetExpressionNodeIR` 当前以大量可选字段表达不同操作，缺少按操作种类约束的构造边界；
  嵌套 predicate 还可能使用合成来源，不能作为完整来源证据。
- `TargetExpressionResult.ok` 不能从类型上区分“合法空集合”和“解析失败”。动作目标基数属于
  S5C 的提交契约，不应塞进效果目标表达式结果。
- `ActionDefinitionIR` 当前仍以弱字符串提供动作目标信息。S5A 不迁移动作定义；该迁移只在
  S5C 原子完成。

## 阶段结果

完成后，生产 compiler 能从 S0 同一来源闭包生成可复现的“当前目标来源视图”；每个 gameplay
目标表达式都具有递归不可变、按操作严格约束、节点级来源真实的类型化 IR，或者带精确原因
保持 blocked。效果目标求值结果能严格表达 resolved/blocked，resolved 允许空集合。

本阶段不新增目标操作能力，不改变动作目标查询，不修关系生产者，不修改随机语义。

## 已确定的架构决策

### 1. 权威来源集合

生产层新增或提取一个轻量目标来源投影入口，必须复用 S0 snapshot、scope classifier 及全局
目标别名/操作配置的现有读取链：

1. 语法候选为当前观测到的所有 `Target*`、`Retarget` 和 `RandomSelectInTargetList` family。
2. family 名只用于识别语言词汇；最终归属由每条 scope record 的完整分支和
   `effective_scope` 决定，不能按 family 整体强行 admission。
3. gameplay 记录进入 S5A-S5D 责任矩阵；input projection 中的目标持续性归 S5C；
   non-gameplay 保持退役；构筑/战斗数据投影继续由既有消费者负责；decode-required 保持 blocked。
4. 选择规则和责任归属必须位于生产 compiler 模块，验证器只复核结果，不能维护第二份列表。
5. 数量、角色名、固定文件、固定 ID 和当前 hash 都不能成为选择条件或通过条件。
6. 全局 alias/operation 定义必须按配置中的真实身份唯一关联，循环、缺失和多义 blocked；配置
   路径是语言来源，不是角色内容特判。

该入口输出的稳定目录至少能回答：来源记录身份、family、完整来源、scope、负责子阶段和当前
状态；全局 alias/operation 另有来源闭合的语言定义。它不是验证缓存，也不包含 raw ability 副本。
`RandomSelectInTargetList` 在该目录中归 S5D task 语义，不能伪装成效果目标 AST 节点。

### 2. 类型化表达式

目标表达式继续使用一个递归根节点，但节点内容必须成为严格的 tagged contract。当前来源
操作归并为以下语义类别：

- 别名或上下文实体来源。
- 集合合并与顺序流水线。
- 过滤及其类型化条件引用。
- 实体查询与关系映射。
- 稳定排序。
- 截取、索引和反转。
- 重定向。
- 随机抽样或洗牌。

具体可使用严格 payload 类型或等价的 tagged dataclass；不得继续以“一个类加任意可选字段”
接受互相矛盾的组合。每种 tag 只能携带该操作所需成员，错误成员、未知成员、错误子节点数量、
非法数值表达式和未知 tag 在构造/codec 边界拒绝。

每个节点必须拥有稳定身份和自己的真实 `IRSource`。身份绑定来源路径、原始 JSON 位置、操作
种类和子节点身份；重排无序输入不改变身份，改变语义或来源必须改变身份。嵌套 predicate
继承对应 raw 节点的真实位置，禁止继续生成 `CanonicalIR.TargetExpressionIR.node` 一类合成来源。

`audit_raw` 可以保留在 compiler 的临时审计结果中，但 executable IR 和 runtime 都不能读取
任意 raw 字典决定行为。正式 JSON codec 必须 exact-field、递归不可变、输入容器隔离且 round-trip
确定性一致。

### 3. 效果目标结果

建立单一效果目标集合结果契约：

- `resolved`：有一个稳定有序、无重复的目标 tuple；该 tuple 可以为空，blocked reason 必须为空。
- `blocked`：目标 tuple 和 RNG event 必须为空，blocked reason 必须非空。

本结果不表达动作提交是否满足目标数量。动作候选公布、提交拒绝和基数错误属于 S5C 的独立
结果类型。不得再通过 `ok=false + empty` 猜测失败种类。

### 4. 迁移边界

- 当前已经 admitted 的确定性表达式必须原子迁移到新 IR/result contract，行为与顺序不变。
- 不保留新旧节点两条 runtime 分支，不为历史验证器建立兼容 adapter。
- 仍未支持的操作只完成类型化 lowering 和精确 blocked，不得在 S5A 提前实现。
- `ActionDefinitionIR`、动作候选、owner/summoner 关系和 RNG 在本卡保持行为不变。

## 详细目标

1. 建立生产级目标来源投影和稳定责任矩阵，并证明 family/scope 过滤发生在 IR materialization 前。
2. 将当前 gameplay 目标节点全部映射到严格语义类别；随机 task 单独归属，未知或不完整来源
   结构化 blocked。
3. 为根表达式、所有嵌套节点和 predicate 保留精确 raw lineage，不得伪造节点来源。
4. 收紧构造、JSON、不可变性和 fingerprint 边界；外部字典、列表或伪冻结子类不能绕过校验。
5. 将效果目标求值结果迁移为 resolved/blocked；合法空集合不再被误报为解析失败。
6. 保持当前已执行的目标表达式结果、稳定顺序和失败原子性不变。

## 明确不做

- 不实现新的 relation、sort、filter、retarget 或随机操作。
- 不修改动作目标候选、玩家/推演器提交、敌方动作查询或动作执行上下文。
- 不执行 `SetTeamLockTarget` 客户端行为。
- 不实现 S6/S7 条件语义，不为 predicate 合成真/假结果。
- 不新增角色、技能、怪物或召唤物专属目标映射。

## 验收矩阵

| 目标 | 只有满足以下条件才通过 | 权威证据 |
|---|---|---|
| 来源集合可复现 | 目标语法候选全部进入生产视图，并按 record scope 唯一归属 | source ownership matrix |
| 过滤真实 | family/source 过滤先于目标 IR materialization，无完整 lowering | build counter + interception |
| IR 严格 | 每个 gameplay 节点为合法 tagged contract 或精确 blocked | node contract matrix |
| 来源真实 | 根、子节点、predicate 均能反查原 raw 位置 | source closure matrix |
| 结果明确 | resolved empty 与 blocked 为不同合法对象；矛盾对象构造失败 | result invariant matrix |
| 行为未扩张 | 既有 admitted 切片结果与顺序不变，新增操作执行数为零 | focused migration slice |

## 结构化通过谓词

```text
authoritative_target_source_projection_exists=true
target_scope_assignment_record_granular=true
stale_family_counts_not_used_as_gate=true
target_filter_applied_before_ir_materialization=true
current_gameplay_target_nodes_typed_or_blocked=true
target_node_contract_exact=true
nested_target_sources_authentic=true
synthetic_target_predicate_source_count=0
target_ir_recursively_immutable=true
resolved_empty_and_blocked_distinct=true
blocked_target_result_has_no_targets_or_rng=true
existing_target_runtime_behavior_changed=false
action_target_runtime_changed=false
random_target_runtime_changed=false
```

## 必须覆盖的负例

- 未知 family 被伪装成当前目标 gameplay family。
- 同 family 的 non-gameplay 或 input projection 记录被整体误准入。
- 节点未知字段、错误操作成员、错误子节点数量、非法数值或未知 tag。
- 可变原始容器或伪冻结子类绕过递归校验。
- 改变节点来源、子节点顺序或语义后 identity/fingerprint 不变。
- predicate 使用合成路径、空 evidence 或父节点来源冒充自身来源。
- resolved 携带 blocked reason；blocked 携带目标或 RNG；合法空集合被拒绝。
- executable IR 仍依赖 `audit_raw` 或任意 payload 决定运行时行为。

## Gap 与停止条件

- 发现语法候选规则会吞入与目标无关的 gameplay 领域：提交 `plan_mismatch`，不得扩大 selector。
- 迁移现有 admitted 节点必须改变其战斗语义：保留旧行为并暂停，交规划线程裁决。
- 需要先决定动作目标选择、实体关系或 RNG 语义：记录到 S5B-S5D，不得在本卡实施。
- 只有完整 Canonical IR 才能形成 evidence：暂停并修正窄投影，不能提高资源上限。
- 当前来源不存在某个预期操作不是 source gap；以实时来源视图为准，不合成样例。

## 拟改范围

- `rules/ir.py`、`rules/rulebook.py`：目标表达式、节点、结果所需的类型化目录和窄查询。
- `tbgd/character_ability_scope.py` 或新的目标投影模块：只建立复用 S0 的生产目标视图。
- `tbgd/lowering.py`：目标节点和 predicate 的来源真实 lowering。
- `systems/target.py`：只做新 IR/result 的原子迁移，不新增操作语义。
- 新增 `tools/validate_p9_s5a_target_source_and_typed_contract.py` 与仓库级报告。

禁止修改 `action_preflight.py`、动作 query/submit、`rng.py`、事件生产者、状态/伤害消费者、UI、
总 checklist 和 Git 历史。若实际调用链要求额外生产文件，先在报告中说明精确原因；不能顺手
扩大到 S5B。

## 验证与资源

唯一主入口：

```text
validate_p9_s5a_target_source_and_typed_contract
```

- 主入口只建立一次角色能力 raw snapshot 和一次目标 family 窄投影；完整 lowering 次数必须为 0。
- 主验证只保留 summary、来源归属、节点契约、来源闭包、负例和一个迁移切片。
- direct 最多 1 项：仅在既有 admitted 目标结果调用链被迁移时，抽取当前 active contract 的
  最小切片；不得运行完整 P1-6、P3-S8 或历史目标套餐。
- 主入口上限 5 分钟；阶段累计验证 9 分钟；峰值 768 MiB；evidence 2 MiB；新增验证代码
  650 非空行。达到任一上限立即停止，不靠压缩可读性绕过。
- 固定顺序：`compileall -> 秒级构造负例 -> 唯一主入口 -> 必要 direct -> git diff --check`。

## 唯一执行清单

- [x] 生产目标来源视图和责任矩阵建立，旧固定数量不再作为验收依据。
- [x] 当前 gameplay 目标节点完成严格类型化或诚实 blocked。
- [x] 根节点、嵌套节点和 predicate 来源真实闭合。
- [x] resolved empty、blocked 和矛盾结果在构造边界严格区分。
- [x] 既有 admitted 行为未改变，动作和随机 runtime 未触达。
- [x] 主验证、必要 direct、资源审计和 `git diff --check` 通过。
- [x] 仅提交 `ready_for_review`；未勾总 checklist、未提交 Git、未进入 S5B。
