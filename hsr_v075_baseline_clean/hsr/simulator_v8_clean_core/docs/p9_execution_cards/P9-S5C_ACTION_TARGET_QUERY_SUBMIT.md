# P9-S5C 动作目标查询、提交与持续性执行卡

## 执行配置

- 对应问题：P9-I06 第三部分；机制包 M04 action contract。
- 硬前置：P9-S5B 已验收并形成检查点。
- 推荐：5.6 Terra / `xhigh` / 普通聚焦。
- 推荐理由：本卡是一次明确的内部接口迁移，涉及 action query、command 和 executor，但不修改
  效果目标算法或 RNG；所有交互语义已在本卡固定。

## 开工导航

只读本卡、`README.md` 的 `ready_for_review` 硬门槛、S5B 最终报告和以下生产链：

- `ActionDefinitionIR` 及 Canonical IR/RuleBook 的 action 查询
- `target_policy_for_action`、`TargetPolicy`
- `ActionChoice` 的正式查询入口和 `systems/decision.py`
- `ActionCommand`、`TargetResolution`、`TargetPlan`
- executor 从 command 到 action plan 的目标调用链
- S0 `target_persistence` projection 的生产消费者
- S5B `TargetEvaluationContext`、关系 resolver 和确定性 target expression 入口

最多两轮 CodeGraph 定位。先形成“定义 -> 查询 -> 外部提交 -> executor -> effect context”的唯一
调用图，再修改。不得扫描历史 action 验证器或按工具调用者数量迁移全部旧 fixture。

## 当前事实

- `ActionDefinitionIR` 当前用 `target_mode` 和 `target_relation` 弱字符串表达动作目标；
  `action_preflight` 再临时拼成 `TargetPolicy`，不是类型化 Canonical IR 契约。
- 当前 policy 同时描述玩家选中的主目标和技能实际影响组；blast/aoe/bounce 的影响目标因此可能
  在动作层和效果图中重复推导。
- `ActionChoice` 对外暴露自由 `target_policy` 字典，`ActionCommand` 只携带目标 ID，不能证明提交
  基于哪一次候选查询；状态改变后旧候选可能被重放。
- `TargetEnumerationResult` 把候选为空直接当 blocked；`TargetResolution` 也没有构造不变量，
  查询失败、提交拒绝和执行成功之间边界不严格。
- S0 的四条 `SetTeamLockTarget` 是 input projection，表示目标在动作阶段间持续，不是 runtime
  应执行的客户端锁定任务。
- 外部推演器应像玩家一样读取动作和候选并提交选择；敌我双方都使用同一接口，不需要 AI。

## 阶段结果

完成后，每个正式 action definition 引用一个来源真实、类型化的动作目标契约。内核公布动作时
同时公布当前合法候选和稳定查询身份；外部推演器只回传查询身份及选择。提交端在当前 committed
state 上重新核对契约和候选，过期、伪造或数量非法的选择在产生 action plan、mutation、event 或
RNG 前拒绝。已选主目标保存在正式动作执行上下文中并按来源跨 phase 使用；实际伤害/状态影响组
仍由效果目标表达式求得。

## 已确定的架构决策

### 1. 动作目标与效果目标分离

新增 `ActionTargetContractIR` 或等价严格模型，并由 `ActionDefinitionIR` 只引用其稳定身份。
契约必须表达：

- 由外部显式选择、由内核自动确定，或动作不需要提交目标。
- 候选关系/候选表达式引用。
- 最少和最多提交数量，以及是否允许重复；当前正式契约默认不允许重复。
- 存活、可选、队伍、场上/后台等来源真实的 targetability 限制。
- 已选主目标在本次 action 内的持续范围。
- 完整 `IRSource`、coverage 和 blocked reason。

动作目标契约只决定“这次动作可以选择谁、需要提交几个”。blast 的相邻目标、aoe 的全体、
bounce 后续目标和任务自身 alias 都是 effect target expression，不得复制进动作选择契约。

`ActionDefinitionIR.target_mode`、`target_relation` 和自由 `TargetPolicy` 在所有生产消费者迁移后
退役，不保留新旧 runtime 双轨。若必须保留原始字段用于审计，只能存入目标契约的来源证据，
不能继续作为第二行为来源。

### 2. 查询结果

动作目标查询结果只有两种状态：

- `published`：契约已解析，包含稳定有序候选、自动目标说明、提交数量、契约 identity/fingerprint
  和本次 `target_query_id`。候选集合允许为空；动作是否可用由 action availability 结合契约判断。
- `blocked`：契约、关系或 committed fact 无法解析；不携带候选、自动目标或可提交 identity。

`target_query_id` 由内核生成，至少绑定 actor、action/level、目标契约 fingerprint、规范候选池和
所有影响目标合法性的 committed facts。不得只绑定 `event_index`，也不得要求推演器自行计算。

### 3. 提交结果

提交结果严格区分：

- `accepted`：查询身份仍有效，选择来自当前候选且数量、重复、生命周期和队伍均合法；生成
  typed `ActionTargetSelection` 和动作执行上下文。
- `rejected`：契约与查询可解析，但外部提交过期、越界、重复、数量错误或身份不匹配；state
  不变且无 action plan/mutation/event/RNG。
- `blocked`：当前状态下契约或候选无法解析；同样零副作用。

提交时必须在当前 BattleState 重新执行同一个生产查询，并核对 query identity；不能信任
`ActionChoice` 中回传的候选列表，也不能仅检查所选 ID 仍然存在。

### 4. 外部命令和动作上下文

- 外部显式选择必须回传内核公布的 `target_query_id`。mandatory/automatic 内部动作仍通过同一
  contract 生成当前选择，不走自由 metadata 绕过。
- `ActionChoice` 对外提供 typed contract/query 摘要，不再暴露可修改的任意 policy 字典。
- `ActionCommand` 或等价正式输入以类型化字段携带 query identity；不得藏在 metadata。
- 动作上下文保存“已选主目标/已提交选择”，效果图再通过 S5B 表达式求 impact group。
- phase 间共享同一个不可变动作目标选择。跨 action 不保留客户端锁定状态，除非未来有真实
  战斗状态来源；S0 target-persistence projection 不产生 BattleState mutation。

### 5. 双方统一接口

玩家角色、怪物、召唤行动实体、queue action 和 ultimate window 只要需要外部决策，都使用同一
query/submit 契约。`enemy_action.py` 可以公布敌方动作和候选，但不能选择目标或实现 AI。

## 详细目标

1. 从真实 action/phase 来源 lower 类型化动作目标契约；冲突、缺失和歧义 fail-closed。
2. `ActionDefinitionIR`、Canonical IR 和 RuleBook 完成目标契约引用与唯一查询。
3. 原子迁移 action availability、decision、enemy action、queue/ultimate query 和 executor 的目标链。
4. 建立 published/blocked 查询及 accepted/rejected/blocked 提交不变量。
5. 外部提交绑定当前查询身份，当前候选变化必然使旧查询失效。
6. selected primary 与 effect impact group 分离，动作 phase 只共享正式 selection context。
7. S0 目标持续性投影被消费为 action-context 语义，客户端操作执行数为零。

## 明确不做

- 不执行伤害、状态或 bounce 目标算法；只把正式 selection context 交给既有效果链。
- 不实现 random target 或 shuffle；随机 effect expression 留 S5D。
- 不实现敌方 AI、自动选最优目标或 UI 规则。
- 不支持外部提交任意候选、target policy、impact group 或 targetability flags。
- 不为旧 `TargetPolicy`、旧 `ActionCommand.metadata` 或历史工具建立兼容层。

## 验收矩阵

| 目标 | 只有满足以下条件才通过 | 权威证据 |
|---|---|---|
| 契约来源闭合 | 当前正式动作均唯一引用真实目标契约；冲突动作 blocked | action contract matrix |
| 查询可信 | published 候选来自当前 committed state 和 S5B resolver | query matrix |
| 提交可信 | submit 重算查询；过期/外部/重复/数量错误全部 rejected | submission matrix |
| 选择与影响分离 | command 只提交 selection，impact 只由 effect target 求得 | call-path audit |
| phase 持续正确 | 同一 action 各 phase 使用同一 selection，后续 action 不继承客户端锁定 | lifecycle slice |
| 双方共用 | ally/enemy/召唤/queue 的外部决策无第二套目标规则 | consumer matrix |

## 结构化通过谓词

```text
action_target_contracts_typed_and_source_backed=true
action_definition_references_target_contract=true
legacy_target_policy_runtime_consumers=0
target_query_published_or_blocked_invariants_hold=true
target_submission_three_way_outcome_invariants_hold=true
target_query_identity_binds_current_candidates=true
stale_query_rejected_before_action_plan=true
external_candidate_or_impact_injection_rejected=true
selection_cardinality_and_duplicates_enforced=true
selected_primary_and_effect_impact_separate=true
action_phase_target_persistence_typed=true
client_target_lock_mutation_count=0
ally_enemy_and_owned_action_queries_share_contract=true
enemy_ai_target_selection_count=0
```

## 必须覆盖的负例

- action definition 缺契约、跨 action 引用、同 identity 多候选或来源冲突。
- query 携带候选但状态为 blocked，或 published 缺 identity/fingerprint。
- 状态改变后提交旧 query ID，即使旧目标仍存活也必须 rejected。
- actor/action/level/contract 不一致，外部目标不在候选中，重复目标，零个/过多个目标。
- 已选目标在 query 后死亡、离场、换队或关系损坏。
- 自动目标动作提交显式目标；显式目标动作省略 query identity。
- 外部在 command/metadata 注入 impact group、targetability 或自由 policy。
- blast/aoe 影响组在 action contract 和 effect expression 被重复应用。
- target-persistence projection 被执行为全局锁定 mutation 或跨 action 泄漏。
- 敌方查询路径自行选取候选第一项。

## Gap 与停止条件

- 真实 action 来源无法唯一决定 selection mode/relation/cardinality：记录来源候选并暂停；不得按
  技能名、攻击类型经验或 UI 表现猜规则。
- 某 action 的 effect impact 目前只能靠旧 action policy 生成，且真实效果图没有对应来源：提交
  精确 source gap/责任分析，不能把旧推导静默保留为第二来源。
- 需要修改共享 action transaction 或 command 公共 schema 之外的业务领域：先交影响范围，
  返回 `plan_mismatch`。
- 查询必须 hash 完整 Snapshot 才能检测过期：先建立目标相关 committed fact 投影，不能让每次
  query 序列化完整战斗状态。

## 拟改范围

- `rules/ir.py`、`rules/rulebook.py`、`tbgd/lowering.py`：动作目标契约及引用。
- `systems/action_preflight.py`、`systems/action_availability.py`、`systems/decision.py`、
  `systems/enemy_action.py`：统一 query/submit 消费。
- `core/model.py`、`core/action_plan.py`、`core/executor.py`：正式 command、selection context 和 plan 迁移。
- `systems/target.py`：动作查询/提交入口；不改 S5B deterministic evaluator。
- S0 target-persistence 的现有生产消费者。
- 新增 `tools/validate_p9_s5c_action_target_query_submit.py` 与仓库级报告。

禁止修改 RNG、条件 evaluator、事件生产者、伤害/状态语义、UI、总 checklist 和 Git 历史。

## 验证与资源

唯一主入口：

```text
validate_p9_s5c_action_target_query_submit
```

- 用结构化规则选择最小真实动作形状：显式单目标、自动目标、不同关系及拥有行动实体；不固定
  角色或动作 ID，不建立完整动作目录。
- 一个 query -> submit -> formal action context 切片证明正例；负例复用同一生产入口。
- direct 最多 1 项：只覆盖实际迁移的 action availability 或 executor 边界，不重跑完整 P4/P7。
- 不重跑 S5A/S5B 主验证；S5C 只调用其生产 API。
- 主入口上限 5 分钟；阶段累计 9 分钟；峰值 768 MiB；evidence 2 MiB；新增验证代码 700 非空行。
- 固定顺序：`compileall -> 秒级 query/submit 构造负例 -> 唯一主入口 -> 必要 direct -> git diff --check`。

## 唯一执行清单

- [ ] 当前正式动作唯一引用类型化目标契约。
- [ ] query/submit 状态、身份、候选和基数不变量全部建立。
- [ ] action selection 与 effect impact 完全分离。
- [ ] 目标在同一 action phase 间持续且不执行客户端锁定。
- [ ] 敌我及拥有行动实体复用同一接口，无 AI 或外部规则注入。
- [ ] 主验证、必要 direct、资源审计和 `git diff --check` 通过。
- [ ] 仅提交 `ready_for_review`；未勾总 checklist、未提交 Git、未进入 S5D。
