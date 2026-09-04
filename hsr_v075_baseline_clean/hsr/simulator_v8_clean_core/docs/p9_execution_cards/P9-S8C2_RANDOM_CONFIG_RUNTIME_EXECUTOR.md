# P9-S8C2 RandomConfig weighted-selection runtime executor contract

> 状态：`ready_for_execution`
>
> 父阶段：`P9-S8C`
>
> 固定基线：`master@2e8589622c27ebf05c0b021214fddc138e883dbb`
>
> 风险模式：`STRICT`
>
> 本文件是本轮 PR 的唯一执行任务权威。执行层不得从旧对话、聚合说明中的后续目标或相邻阶段自行扩展范围。

## 1. 为什么这是下一张卡

当前唯一 P9 checklist 已确认 `P9-S8C1` 完成而 `P9-S8C` 尚未完成；`P9-S5D2` 明确等待 S8 提供真实动作控制流后再回验，因此不能先于剩余 S8C 执行。

`P9-S8C_HIT_BARRIER_RANDOM_SEQUENCE.md` 又明确要求：S8C1 后的 random / projectile / barrier / parallel 必须按真实来源拆卡，不得重新合并成一张大卡。当前 accepted `TaskGraphIR` 已为每个 `RandomConfig` node 提供严格的 `TaskGraphWeightedSelectionIR`，但共享 `systems/task_graph.py::TaskGraphExecutor` 仍只有 leaf / condition / branch / count / targets / graph hooks；非 success/failed 的 branch 只能走普通 branch hook，尚无能够按 weighted-selection identity 选择恰一条分支并把 RNG 证据纳入 task-graph 原子结果的专用运行时契约。

因此本卡只建立 **共享 task-graph weighted-selection runtime executor contract**。真实 ability/status 调用者如何计算动态权重、如何从现有 RNG ledger 解析选择，留给后续独立纵切卡；本卡不得为了打通调用者而修改第二个生产文件。

## 2. 唯一目标

在现有 `TaskGraphExecutor` 中建立 fail-closed 的 `RandomConfig` / `weighted_single` 选择执行边界，使共享 executor 能：

1. 从当前 graph 中定位当前 node 唯一的 `TaskGraphWeightedSelectionIR`；
2. 通过一个类型化 weighted-selection hook 接收调用者给出的选择结果，而不是复用含糊的普通 branch hook；
3. 校验返回选择与 accepted IR 的 `selection_id / graph_node_id / choice_id / ordinal / branch_id` 一致；
4. 只执行被选 choice 对应 branch 的 child nodes，未选分支不得产生 projection、mutation、event、RNG event 或 settlement；
5. 将该选择对应的单个、身份稳定的 `RNGEvent` 纳入 `TaskGraphExecutionResult.rng_events`，并参与现有 duplicate / atomic rollback 约束；
6. 任一 selection 缺失、歧义、stale choice、branch/ordinal 不一致、hook 缺失/blocked、RNG event 身份冲突时 fail-closed，且 blocked result 不泄漏任何 formal execution channel。

## 3. 明确非目标 / deferred

本卡不做以下事项：

- 不在 runtime 内自行生成随机数、hash roll、全局 random 或 seed policy；
- 不实现动态 weight expression 求值；
- 不读取 `ActionCommand.metadata`、不消费/验证 action/status 的完整 RNG choice ledger；
- 不修改 ability/status/event-dispatch 等真实调用者；
- 不声称真实 ability/status RandomConfig 已可执行；
- 不修改 `rules/task_graph.py`、任何 parser/materializer、S8A/S8B/S8C1 compiler/source ledger；
- 不做 projectile、多 hit identity、barrier、parallel、sequence-select 或 timeline/wait；
- 不推进 `P9-S8C` 聚合完成、`P9-S5D2` 回验、S9-S16；
- 不修改总 checklist、`CODEX_HANDOFF.md`、accepted 历史卡或 checkpoint。

## 4. 权威与边界

### 4.1 IR 权威（只读）

- `rules/task_graph.py::TaskGraphIR`
- `TaskGraphWeightedSelectionIR`
- `TaskGraphWeightedChoiceIR`
- `TaskGraphBranchIR`

其中 accepted invariant 已保证每个正式 `RandomConfig` node 恰有一个 weighted selection，choice ordinal 与 branch ordinal 一一对应。本卡只能消费该契约，不能重定义它。

### 4.2 运行时权威

唯一运行时权威是：

- `systems/task_graph.py::TaskGraphExecutor`
- `_TaskGraphRun`
- `TaskGraphExecutionHooks`
- `TaskGraphExecutionResult`

本卡必须把 weighted selection 设计成该共享 executor 的一等运行时选择契约，而不是在某个角色、ability 或 status caller 里私建第二套 graph walker。

### 4.3 RNG 边界（只读参考）

`systems/rng.py` 的 `RNGEvent`/ledger 语义是后续调用者接入的既有 gameplay RNG 权威。本卡只要求 weighted hook 返回一个合法、稳定、可进入 task-graph result 的 RNGEvent；不得修改 `systems/rng.py` 或发明第二套 RNG primitive。

## 5. 允许写集合

执行层只能修改以下两个路径：

1. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/task_graph.py`
   - 仅用于新增/收口 weighted-selection hook/result 类型、RandomConfig selection dispatch、choice/branch identity 校验、RNG event admission 与 fail-closed 原子语义。
2. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_p9_s8c2_random_config_runtime_executor.py`
   - 本卡唯一聚焦测试文件；可新建。

本执行卡由 PLAN 已提交，EXEC 不得修改本卡。

### 允许只读

为理解既有契约，允许读取但禁止修改：

- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py`
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/rng.py`
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability.py`
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-S8C_HIT_BARRIER_RANDOM_SEQUENCE.md`

任何其他生产路径若被证明必须修改，停止并 `needs_replan`。

## 6. 必须成立的实现不变量

### 6.1 类型化选择结果

必须新增一个不可含糊的 weighted-selection hook/result contract。结果至少要能证明：

- 对应当前 `selection_id`；
- 唯一 `choice_id`；
- choice ordinal；
- 对应 `branch_id`；
- 一个合法 `RNGEvent`；
- resolved / blocked 与 blocked reason。

命名可在 `systems/task_graph.py` 内按现有类型风格选择，但不得用裸 dict 或只返回 ordinal/string。

### 6.2 executor 自己校验，不信任 caller

即使 hook 返回 resolved，executor 仍必须由当前 `TaskGraphWeightedSelectionIR` 反查并验证：

- 当前 node 只有一个 selection；
- selection family 为 `RandomConfig`、kind 为 `weighted_single`；
- selected choice 确实属于 selection；
- `choice.graph_node_id == node.graph_node_id`；
- ordinal/branch_id 与 node 同 ordinal branch 完全一致；
- hook 不能通过伪造 branch label/kind 越过 choice identity。

stale、missing、ambiguous、mismatched 一律 blocked。

### 6.3 恰一分支执行

对 weighted-selection node：

- 不再调用普通 `branch` hook 决定 RandomConfig；
- 只递归 selected branch 的 `child_node_ids`；
- 未选 branch 的 descendants 不得出现在 projection 或任何输出 channel；
- selected branch 为空是来源允许的空 continuation 时可完成，但不能因此执行其他 branch。

### 6.4 RNG event admission

选择 hook 返回的 RNG event 必须：

- 使用现有精确 `RNGEvent` 类型；
- 进入 `_TaskGraphRun.rng_events`；
- 复用现有冻结、duplicate identity 与 blocked rollback 规则；
- 不允许携带/伪造 `_RESERVED_IDENTITY_FIELDS`；
- 与既有 leaf RNG event 共享同一 `rng_event_ids` 去重空间。

本卡不规定 caller 如何生成该 event，但 executor 不得静默吞掉它。

### 6.5 原子性

任何 weighted selection 失败都必须沿现有 `_ExecutionBlocked` 路径使整个 `TaskGraphExecutionResult` blocked；blocked result 必须保持：

- `after_state is before_state`；
- mutations/events/rng_events/settlement_records 为空；
- 已产生但未提交的 branch 结果不得泄漏。

## 7. 聚焦测试

唯一测试文件至少覆盖以下病例：

1. **selected-only positive**：两条及以上 choice，hook 选择中间 choice；只有该 branch descendants 执行。
2. **stable identity positive**：同 graph/context/选择结果重复执行，selection/choice/branch projection 路径和 RNG event identity 保持一致。
3. **stale choice negative**：返回不属于当前 selection 的 choice id，blocked 且零 channel 泄漏。
4. **ordinal/branch mismatch negative**：choice id 合法但返回 ordinal 或 branch_id 不一致，blocked。
5. **missing weighted hook negative**：RandomConfig selection 存在但 hook 缺失，blocked；不得回退普通 branch hook。
6. **duplicate RNG identity negative**：weighted selection RNG event 与同一执行中既有 RNG event identity 冲突时 blocked 且原子回滚。
7. **non-RandomConfig regression**：现有 success/failed branch 或普通 domain branch 行为不被 weighted path 接管。

测试可以构造最小 typed `TaskGraphIR`/BattleState/hook fixture；它只是 executor contract test，不得伪装成真实 action Direct。

## 8. 验证命令与预算

从仓库根目录运行：

```bash
python -m pytest hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_p9_s8c2_random_config_runtime_executor.py -q
python -m compileall -q hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/task_graph.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_p9_s8c2_random_config_runtime_executor.py
git diff --check 2e8589622c27ebf05c0b021214fddc138e883dbb...HEAD
```

预算：

- 总验证时间目标 `< 4 min`；
- 单 pytest 进程 RSS `< 1 GiB`；
- 禁止跑全量 test suite、全量角色 catalog、TBGD 全扫描或 live-validation 大证据；
- 不新增专项 workflow；PR 上已有适用 CI 若自动触发，必须保持绿，但不得为本卡修改 CI 文件。

## 9. stop conditions

出现以下任一情况立即停止并回报 `needs_replan`，不得自行扩大写集合：

1. 实现 weighted selection 必须修改 `rules/task_graph.py` 的 accepted IR/schema/invariant；
2. 必须修改 `systems/ability.py`、status/event-dispatch caller 或 `systems/rng.py` 才能完成本卡定义的 executor contract；
3. 现有 `TaskGraphWeightedSelectionIR` 无法唯一映射到 node branch；
4. 需要把 dynamic weight evaluation 或真实 ledger policy 塞进共享 executor 才能确定选择；
5. 发现 RandomConfig 运行时语义与 `weighted_single` accepted source contract 实质冲突；
6. 为通过测试必须同时实现 projectile/barrier/parallel/sequence 或改变原子事务策略。

真正的 GitHub 权限/基础设施阻断才标 `blocked`；普通测试代码问题由 EXEC 在允许写集合内自行修复。

## 10. ready_for_review 交付

完成后在同一 PR 留结构化交接：

- `[HANDOFF:REVIEW]`
- `role=EXEC`
- `status=ready_for_review`
- `stage=P9-S8C2`
- final head SHA
- 实际 diff（只能是本卡允许的两个执行路径；PLAN 卡提交不计 EXEC 业务 diff）
- 三条验证命令、退出码和资源摘要
- 逐项说明 7 个聚焦病例
- `remaining=` 明确真实 ability/status dynamic-weight + RNG-ledger integration、projectile、barrier、parallel、sequence 仍 deferred
- `next=REVIEW`

EXEC 不勾总 checklist、不接受本卡、不合并 PR、不推进下一子卡。
