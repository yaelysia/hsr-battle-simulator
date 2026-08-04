# P9-S5D 随机目标、shuffle 与 S5 聚合执行卡

## 执行配置

- 对应问题：P9-I06 最后一部分；机制包 M16 目标部分及 M04 聚合。
- 硬前置：P9-S5C 已验收并形成检查点。
- 推荐：5.6 Sol / `xhigh` / 普通聚焦。
- 推荐理由：本卡修改共享 RNG identity、显式选择协议和 replay 证据，错误会污染外部推演的
  可能性树。S5A-S5C 已把其他变量移除，但该边界仍不建议首次交给 Terra 自行实现。

## 开工导航

只读本卡、`README.md` 的 `ready_for_review` 硬门槛、S5A-S5C 最终报告和以下生产链：

- `TargetShuffle`、`Retarget.ByRandom`、`RandomSelectInTargetList` 的 S5A 来源矩阵
- `TargetSystem` 当前随机 helper 和 S5B deterministic candidate 入口
- `RNGRequest`、`RNGOutcome`、`resolve_rng_request`、choice identity 生成
- action transaction 如何携带并原子提交 `rng_events`
- replay 对 RNG event、choice 和候选来源的校验
- S5C action query/selection context

最多两轮 CodeGraph 定位。不得扫描全部 RNG 消费者；先确认 target random 到 atomic commit/replay
的唯一调用链。若共享 RNG 无法表达本卡固定协议，返回 `plan_mismatch`，不要在 target.py 建私有账本。

## 当前事实

- 当前 `_select_random_targets` 为每个候选建立 outcome，但只返回一个目标；`TargetShuffle` 也调用
  该函数，因此没有形成完整 permutation。
- `Retarget.ByRandom` 表示随机化候选处理顺序，`MaxNumber` 是处理上限；当前实现尚未证明完整
  无放回排序及上限截取。`RandomSelectInTargetList` 则是每次任务调用选择一个目标，独立调用
  允许再次选中同一目标，二者不能错误合并成“所有随机都不重复”。
- 当前 choice identity 绑定动作、任务、path 和 event index，但候选池没有进入 identity；候选变化后，
  只要旧目标仍存在，旧 choice 可能被错误接受。
- 外部推演器需要看到当前合法随机 outcome 并选择分支；内核负责候选、抽样语义、事件和 replay。
- S5B 已负责稳定、无重复的确定性候选池，S5C 已负责 action query/submit；本卡不能重做二者。

## 阶段结果

完成后，单次随机选择、随机化重定向顺序和 shuffle 都复用共享 RNG ledger 与同一个基础 draw
原语：候选池由内核先完整确定，每个 draw 都有绑定候选池的稳定 identity，外部推演器只选择
内核公布的 outcome。单次选择可在后续独立任务再次命中同一单位；同一次排序/重定向内部无放回，
shuffle 返回完整排列，所有 RNG event 与 action mutation 原子提交并可 replay。

同时以 S5A 权威来源视图重新归并 S5A-S5D：目标领域自身的 lowering、admission、implementation
和 validation gap 为零；属于 S6/S7 predicate、S9 event producer、S17 独立实体或未来 body-part
内容的依赖单列，不能被计作本卡实现失败或伪装成 executable。

## 已确定的随机协议

### 1. 候选池

- 随机节点必须先调用 S5B 确定性入口，得到 `resolved`、稳定、无重复的候选集合。
- blocked 候选不能创建 RNG request；resolved empty 按具体操作返回空结果或数量拒绝，均不耗 RNG。
- 随机池使用候选实体身份的规范排序建立 fingerprint，不能让 Python 容器顺序改变 choice identity。
- 原始候选顺序可以作为审计信息，但不决定均匀抽样概率。

### 2. 三种来源语义

三类来源共享“从当前池选择一个 outcome”的底层原语，但上层语义必须分开：

1. `RandomSelectInTargetList`：每次 task invocation 从当前上下文列表选一个目标。一次调用只有一个
   draw；不同 invocation 通过各自任务/命中身份区分，允许再次选到同一目标。
2. `Retarget.ByRandom`：将经过 predicate 的整个候选池随机排列且同一次调用内无放回；随后按
   `MaxNumber` 截取。没有 `MaxNumber` 时保留完整随机顺序；上限大于池大小时取全部候选，负数、
   非整数或缺失动态绑定才 blocked。
3. `TargetShuffle`：返回整个候选池的随机排列，同一次调用内无放回，不做截取。

空池上的 `RandomSelectInTargetList` 无法产生选择，应 blocked 且不耗 RNG；Retarget/Shuffle 空池
返回 resolved empty。单元素池都直接确定，不制造没有分支意义的 RNG event。

### 3. 完整 shuffle

`TargetShuffle` 返回候选池的完整 permutation，而不是一个目标：

- 使用同一无放回抽样器依次确定排列；最后只剩一个实体时无需额外随机事件。
- 空池和单元素池直接返回自身，RNG event 数为 0。
- 输入 N 个不同实体，输出必须恰好包含这 N 个实体各一次。

### 4. Choice identity

每个 draw 的 identity 和 choice key 至少绑定：

- 目标表达式/任务的稳定节点身份。
- 当前 action/事件求值上下文身份。
- 原始规范候选池 fingerprint。
- 当前 remaining pool fingerprint。
- draw index 和总请求数量。
- 对单次 task 选择，还必须绑定 task invocation/hit identity，不能把两个独立 bounce 命中合并。

候选成员、数量、上下文、节点来源或前序选择发生变化，后续 choice identity 必须变化。即使旧
selected ID 仍在新池中，也不能接受旧 choice key。

### 5. 显式选择与原子性

- 显式 ledger 模式每次只公布当前第一个未解决 draw 的合法 outcomes；推演器回传 choice 后，
  生产 evaluator 重新验证已有选择并公布下一 draw。
- choices 必须来自 typed RNG/action execution input；不得为了多步选择重新引入自由 event payload。
- 在所有 draw 解决前，不提交任何 RNG event、mutation、settlement 或 action state。
- 全部解决后，按 draw 顺序生成一组 before/after 连续的正式 RNG events，并与 action 原子提交。
- 任一中间 choice 缺失、过期、重复、来源冲突或不在 remaining pool，整次结果 blocked，零部分事件。
- deterministic-seed 模式若仍是正式入口，也必须调用同一 sampler 和 identity，不得有不同语义。

### 6. Replay

replay 必须重新得到相同候选池 fingerprint、draw identity、outcome、顺序和 RNG state 链。篡改候选、
删除/交换 draw、重复目标、改变 source 或把 blocked 尝试写成 event 都必须拒绝。

## 详细目标

1. 把 target random 从单目标 helper 提取为共享 draw 原语和按来源类型化的请求计划。
2. `TargetShuffle`、随机 retarget 和 `RandomSelectInTargetList` 复用 draw/identity/commit 链，但保持
   permutation、cap 和独立单次选择三种上层语义。
3. 候选池和 remaining pool 进入 choice identity，过期选择严格失效。
4. RNG event 与 action transaction、settlement、来源审计和 replay 原子闭合。
5. 从 S5A 权威来源矩阵生成 S5 aggregate，确认每条当前目标记录唯一归属。
6. 只关闭目标领域自身 gap；predicate/event/body-part 等后续生产者依赖保持诚实。

## 明确不做

- 不替外部推演器选择随机结果，不实现概率偏好、AI 或启发式策略。
- 不实现 S6-S8 的概率条件、随机控制流或随机数值；只处理目标随机。
- 不重做 S5B 确定性候选或 S5C action query/submit。
- 不用固定 seed、候选第一项、角色 ID 或验证答案代替 choice ledger。
- 不运行当前 79 条角色完整构筑/战斗聚合；该工作属于 S18-S20。

## 验收矩阵

| 目标 | 只有满足以下条件才通过 | 权威证据 |
|---|---|---|
| 来源语义正确 | task 单选可跨调用重复；retarget 同次无放回并按上限截取 | sampling matrix |
| shuffle 正确 | N 个候选得到完整 N 元排列且成员集合一致 | permutation matrix |
| identity 完整 | 池、remaining、draw、上下文或来源变化使旧 choice 失效 | identity mutation matrix |
| 原子闭合 | 部分选择不产事件；完成后 RNG/action/settlement/replay 同链 | formal transaction slice |
| 来源覆盖 | 当前随机目标来源全部映射到唯一通用语义 | random source matrix |
| S5 收口 | S5A-S5D 每条目标记录唯一归属且目标自有内部 gap 为零 | S5 aggregate |

## 结构化通过谓词

```text
random_target_candidates_resolved_before_rng=true
random_select_task_is_one_draw_per_invocation=true
independent_random_select_invocations_may_repeat=true
retarget_random_order_without_replacement=true
retarget_max_number_clamps_to_available_pool=true
target_shuffle_returns_full_permutation=true
zero_or_singleton_deterministic_cases_consume_no_rng=true
candidate_pool_fingerprint_binds_choice_identity=true
remaining_pool_and_draw_index_bind_choice_identity=true
stale_choice_rejected_even_when_selected_member_remains=true
partial_random_resolution_emits_no_rng_events=true
completed_rng_events_chain_and_commit_atomically=true
target_random_replay_recomputes_candidates=true
target_random_handlers_share_one_sampler=true
external_solver_selects_only_published_outcomes=true
current_target_records_uniquely_owned=true
s5_owned_lowering_gap_count=0
s5_owned_admission_gap_count=0
s5_owned_implementation_missing_count=0
s5_owned_validation_gap_count=0
character_specific_random_handlers=0
```

## 必须覆盖的负例

- 旧 choice 在候选增加、删除、换队、死亡或 relation 改变后仍被接受。
- choice key 绑定原池但未绑定 remaining pool 或 draw index。
- 同一次 retarget/shuffle 重复实体；两个独立 `RandomSelectInTargetList` invocation 被错误共享
  remaining pool，导致第二次不能再次选中同一实体。
- `MaxNumber` 大于候选数被错误 blocked，或负数、非整数、缺动态绑定仍被执行。
- shuffle 只返回一个元素、漏元素、重复元素或保留隐藏确定性顺序。
- 第二个 draw 缺 choice 时第一个 RNG event 已进入 state/replay。
- 交换 draw event、修改 selected index/ID、候选 fingerprint 或来源后 replay 仍通过。
- deterministic seed 与 explicit ledger 对同一候选使用不同抽样语义。
- target evaluator 生成私有随机日志而没有正式 RNG event/settlement。
- S5 aggregate 把 S6/S7 predicate 依赖误报为 S5 executable，或把 S9/S17 producer 依赖算成
  随机实现完成。

## Gap 与停止条件

- 共享 `RNGRequest` 无法表达多 draw 的候选/remaining identity：允许做通用最小扩展；若必须改变
  非目标 RNG 的 replay 语义，先交影响分析并返回 `plan_mismatch`。
- 真实来源表明某操作带权，或与本卡“单次选择/随机顺序/完整排列”分类冲突：暂停并提交完整
  来源，不自行发明第四种语义。
- 随机候选在 choice 前无法由内核完整确定：阶段阻断，不能要求推演器补算候选。
- S5 aggregate 发现 S5A-S5C 责任范围内的新内部 gap：退回对应子阶段，不在 S5D 顺手修复。
- 主验证超过预算或需要完整 lowering：停止并缩窄 source/IR/evidence，不提高限制。

## 拟改范围

- `systems/target.py`：随机 target 节点迁移到共享 sampler。
- `systems/rng.py` 及其正式类型：只做候选池绑定和多 draw 所需的通用最小扩展。
- action atomic commit/replay 的实际生产消费者：只迁移 target RNG event 链。
- `tbgd/lowering.py`、`rules/ir.py`：只补随机 target/task 的类型化映射和责任状态。
- 新增 `tools/validate_p9_s5d_random_target_and_aggregate.py` 与仓库级报告。

禁止修改确定性 relation、动作 contract、条件 evaluator、随机控制流/数值、UI、总 checklist 和
Git 历史。S5 aggregate 是验证视图，不得新增第二套 runtime registry。

## 验证与资源

唯一主入口：

```text
validate_p9_s5d_random_target_and_aggregate
```

- 只读一次 S5 target family 窄投影；完整 lowering 次数为 0。
- 使用一个共享 sampler matrix 覆盖 sample、retarget 和 shuffle，不为每个 family 重建战斗世界。
- 正式 transaction 只保留一条多 draw 正例和对应 replay 篡改负例，产物不写完整 transition dump。
- S5 aggregate 只核对来源归属和四段契约组合，不重跑 S5A-S5C 主矩阵。
- direct 最多 1 项：共享 RNG contract 实际改变时运行轻量 choice/replay 切片。
- 主入口上限 5 分钟；阶段累计 9 分钟；峰值 768 MiB；evidence 2 MiB；新增验证代码 700 非空行。
- 固定顺序：`compileall -> 秒级 sampler/identity 负例 -> 唯一主入口 -> 必要 direct -> git diff --check`。

## 唯一执行清单

- [ ] 单次任务选择、随机重定向顺序和 shuffle 复用 draw 原语且保持各自语义。
- [ ] shuffle 返回完整排列，确定性边界不消耗 RNG。
- [ ] 候选池、remaining pool、draw 和上下文全部绑定 choice identity。
- [ ] 多 draw 与 action 原子提交，settlement、来源审计和 replay 闭合。
- [ ] 当前目标来源全部唯一归属，S5 自有内部 gap 为零。
- [ ] 后续 predicate/event/body-part 依赖没有被伪造为 S5 完成。
- [ ] 主验证、必要 direct、资源审计和 `git diff --check` 通过。
- [ ] 仅提交 `ready_for_review`；未勾总 checklist、未提交 Git、未进入 S6。
