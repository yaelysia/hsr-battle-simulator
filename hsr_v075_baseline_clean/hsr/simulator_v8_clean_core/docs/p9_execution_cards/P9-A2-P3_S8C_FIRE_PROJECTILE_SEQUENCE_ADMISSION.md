# P9-A2-P3 / S8C FireProjectile sequence admission

> 状态：`planned-revised`
>
> 父阶段：`P9-A2 Route A predecessor chain`
>
> 固定基线：`master@eedebb406b85ab2611e8345b3fe7a75e9a7c53a0`
>
> 风险模式：`STRICT`
>
> 本文件是本轮 PR 的唯一执行任务权威。EXEC 不得从旧卡、聚合 S8C 目标或 PR11 原实现自行扩展范围。

## 0. 本次 replan 修订

EXEC 在原卡只读边界内证明了一个更早的生产事实：`FireProjectile` formal parent 的 `AbilityTaskIR.coverage_status` 在 task-graph materialization 之前已经由 `tbgd/lowering.py` 决定。当前 `_lower_ability_task_tree(...)` 因 `FireProjectile` effect 仍是 unsupported 而把 parent task 置为 blocked；后续 `systems/action_contract.py` 会通过 `ability_task_runtime_blocked_reason(...)` 直接拒绝该 blocked task。因此，只修改 control-flow contract 与 task-graph materializer 无法实现本卡既定 real Direct delta。

PLAN 独立复核后接受该 replan，但不接受扩大 runtime/公共语义权限：

- `tbgd/lowering.py` 与 `character_control_flow_contracts.py`、`task_graph_materializer.py` 同属 L0 的 **character source -> canonical formal task -> formal task-graph** 单一 producer authority；本次只补齐该 producer chain 中遗漏的 structural-parent admission，不新增第二个 runtime consumer。
- 允许 lowering 仅在同一 exact `CharacterControlFlowNodeIR` source identity 已证明为本卡 admitted `FireProjectile/projectile_sequence` shape 时，把对应 formal parent `AbilityTaskIR` 从普通 unsupported-effect leaf 解释为 structural executable task。
- 不允许把通用 `FireProjectile` `EffectIR`、coverage registry 或 effect runtime 标为 executable；parent effect 仍保存原始 unsupported/audit evidence，materializer 对已证明的 structural parent 不建立 effect-execution reference。
- `rules/**`、`systems/**`、effect registry、A1/action admission、PR11/A2、PR9 RNG caller 均继续只读。

若实际实现不能在上述单一 L0 producer authority 内完成，则再次 `needs_replan`；不得继续扩大文件集合。

## 1. 为什么这是当前最早可执行前置

已验收的 Route A 不允许降低 A1 admission，也不允许把 A2 transport 改成 synthetic/旁路 Direct。PR11 只有在最新 merged master 上，同 owner 的普通外层 action 已经不存在更早 source-backed blocker 时才能恢复。

PR14 / `P9-A2-P2_PROCESS_ONLY_TRIGGER_ABILITY_ADMISSION_IDENTITY` 的最终真实 Direct 在 `avatar_skill:100101@1` 上已消除 `ability_task_graph_nested_identity_mismatch`，剩余阻断为：

1. `task_graph_control_requires_domains:hit_random_sequence`
2. `task_graph_definition_not_admitted:effect:audit_only`
3. `effect_coverage_status:unsupported:FireProjectile`
4. `task_graph_definition_not_admitted:effect:unsupported`
5. `task_graph_control_requires_domains:damage_heal_shield`

PR14 squash merge `d1c28c0c0e10ed8b268739b71bab1784574a8d93` 到本卡固定基线 `eedebb406b85ab2611e8345b3fe7a75e9a7c53a0` 之间只有 `CODEX_HANDOFF.md` 治理提交，生产输入未变化，因此上述真实 Direct 的生产 blocker 集可用于 merged-master 归因。

当前源码归因把这 5 个 blocker 分成两个独立 authority：

- `FireProjectile` 的 `MaxNumber / Projectile / WaitProjectileFinish / OnProjectileHit` 在 `character_control_flow_contracts.py` 中都明确归 `p9_s8c`；其 control role 为 `projectile_sequence`。因此 `hit_random_sequence + unsupported:FireProjectile + effect:unsupported` 是同一 **S8C FireProjectile projectile-sequence** 上游缺口。
- `damage_heal_shield + effect:audit_only` 属 `p9_s11`，是后续独立 authority，禁止与本卡打包。

所以 PR11 仍不可恢复。本卡只闭合最早、真实命中的 `FireProjectile` source shape；`RandomConfig`、其它 projectile family、barrier、parallel 与 S11 都继续 deferred。

## 2. 唯一目标

建立一条 source-backed、fail-closed 的 **`FireProjectile` formal projectile-sequence** 纵切，使正式 task graph 不再把可证明的 `FireProjectile` 当作普通 unsupported effect，而是把它解释成“按来源给定次数执行 ordered `OnProjectileHit` child graph”的结构节点。

完成后必须同时成立：

1. `FireProjectile.MaxNumber` 由真实来源 lowering 为精确、可求值的 count termination；不得使用默认次数、角色 ID 或观测答案补值。
2. `OnProjectileHit` 使用现有 control-flow child identity 和 source order，正式 graph 中每次 hit 只进入该 source-backed child graph；不得另建第二套 graph walker。
3. `Projectile` 只保留来源身份/审计意义；本卡不模拟坐标、速度、飞行时间、碰撞、动画或客户端 projectile physics。
4. `TargetType / CustomAnchorTarget` 继续消费既有 `p9_s5b` target authority，不在本卡重定义 target legality。
5. 已证明 structural `FireProjectile` parent task 不再产生 `effect_coverage_status:unsupported:FireProjectile`，且 materializer 不再为该 structural parent产生 `task_graph_definition_not_admitted:effect:unsupported`；原 `EffectIR` 本体仍保持真实 unsupported/audit 状态。
6. 共享 `TaskGraphExecutor` / ability formal hooks 必须能够消费本卡产生的既有 typed graph contract；不得通过 caller 特判角色/技能绕过 graph。
7. 任一不能证明的 `FireProjectile` source shape 必须继续 fail-closed，并给精确 blocker；不能为了让代表 action 过门而把整个 `p9_s8c` 标成 closed。

## 3. 本卡允许承认的最小语义

### 3.1 count 与 ordered hit continuation

本卡只承认能够从 raw `MaxNumber` 得到 exact numeric expression 的 `FireProjectile`：

- count 必须是 runtime 可求值的非负整数；
- count 为 `N` 时，`OnProjectileHit` children 的正式执行路径必须产生恰好 `N` 个有稳定 iteration identity 的 ordered hit continuation；
- `N == 0` 不得执行 hit child；
- child 的 damage/status/resource 等语义仍由 child 自身正式 contract 决定，本卡不替它们执行或准入。

允许复用现有 `ControlFlowTerminationIR -> TaskGraphNumericDefinitionIR -> TaskGraphExecutor` 的 count/loop 机制；若该既有链无法忠实表达 source shape，必须 `needs_replan`，不得新增平行 sequence interpreter。

### 3.2 `WaitProjectileFinish`

不得把该字段静默忽略或伪装成纯 presentation：

- 如果当前被 admission 的 source shape 能由现有同步 task-graph parent/child 完成关系完整表达，则保留原始来源证据并证明 continuation 不会早于其 hit child；
- 如果真实来源需要独立 asynchronous/barrier/parallel 语义才能解释 `WaitProjectileFinish`，该 shape 不属于本卡，应保持 fail-closed 并 `needs_replan` 给独立 barrier/parallel predecessor。

本卡不能因此顺带实现全局 barrier、timeline 或 parallel scheduler。

### 3.3 source-shape 而不是固定样例

首个纵切可以从当前真实 `FireProjectile` shape 开始，但完成声明必须覆盖 **当前 formal ability denominator 中所有同形 source occurrences**，按字段形状/语义判定，不得按 actor/action、角色名、文件名、hash 或观测答案白名单 admission。

不同 source shape 若无法由同一不变量证明，应精确列为 deferred/blocked，而不是扩 scope。

## 4. 唯一生产权威与正式消费者

### 4.1 L0 producer / lowering authority

本卡唯一主要生产权威是现有 character source -> canonical formal task -> formal task-graph projection，由三处同层生产文件共同完成：

1. `tbgd/character_control_flow_contracts.py`
   - source field responsibility、`projectile_sequence` shape、count termination 与 ordered `OnProjectileHit` branch 的来源权威。
2. `tbgd/lowering.py`
   - canonical `AbilityTaskIR` 的 formal source identity 与 coverage producer；仅负责在 exact admitted control node 事实完整时把 `FireProjectile` parent task 标为 structural executable。
3. `tbgd/task_graph_materializer.py`
   - 把上述 admitted structural task 投影到既有 typed `loop/count/task_list` task-graph contract，并避免给 structural parent建立错误 effect reference。

这三处必须使用同一 source path/json path/content fingerprint/family/control-node identity；lowering 不能自己重新解释 raw `FireProjectile` 字段形成第二套 shape 判定。

允许的生产改动只用于：

- 给 `FireProjectile` 建立 source-backed count termination；
- 在不关闭其它 `p9_s8c` role 的前提下，精确 admission 已证明的 `projectile_sequence` shape；
- 在 formal lowering 中基于同一 exact control node 提升 structural parent task，而不是改变通用 effect coverage；
- 把 `projectile_hit` source branch 投影到现有 task-graph 可执行的 ordered counted-sequence contract；
- 对 structural `FireProjectile` parent 不再建立错误的 effect-execution requirement，同时保持 child effect reference 原样。

### 4.2 正式 consumer（只读）

本卡必须直接复用且禁止修改：

- `systems/action_contract.py` 的现有 A1 formal projection/admission；
- `systems/ability_task_contract.py::ability_task_runtime_blocked_reason`；
- `systems/task_graph.py::TaskGraphExecutor`；
- `systems/ability.py::AbilityTaskSystem` 现有 formal `count / target / leaf` hooks；
- `rules/task_graph.py` 现有 `TaskGraphNodeIR / TaskGraphNumericDefinitionIR / branch / termination` schema；
- effect registry / coverage runtime authority。

如果正确实现必须修改任一上述 consumer/schema/coverage authority，说明当前单一 L0 producer 纵切仍不完整，停止 `needs_replan`；不要顺手迁移第二个共享 authority。

## 5. 允许写集合

EXEC 只能修改以下路径：

### 生产

1. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/character_control_flow_contracts.py`
2. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py`
3. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py`

### 聚焦测试 / Direct evidence

4. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_p9_a2_p3_fire_projectile_sequence_admission.py`
5. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p3_fire_projectile_sequence_admission.py`
6. `hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2-P3_S8C_FIRE_PROJECTILE_SEQUENCE_ADMISSION_execution_report.md`

本执行卡由 PLAN 提交，EXEC 不得修改本卡。

允许只读：`rules/control_flow_contract.py`、`rules/task_graph.py`、`systems/action_contract.py`、`systems/task_graph.py`、`systems/ability.py`、`systems/ability_task_contract.py`、`tbgd/coverage.py`、P2 validator/report、P9 checklist/aggregate cards、TBGD pinned raw source。

任何**额外**生产路径被证明必须修改时，先停止并 `needs_replan`；不得自行继续扩大写集合。

## 6. 生产不变量与最小反例

### 6.1 不关闭整个 S8C

`RandomConfig`、`FireMultiProjectiles`、`FireWaveProjectile`、`NewFireProjectile`、parallel templates、wait/barrier family 等原有 `hit_random_sequence` obligations 必须保持其当前 disposition，除非它们本来已由其它 accepted authority materialized。

**反例**：构造/选择一个非 `FireProjectile` 的仍-open S8C source occurrence，P3 后仍必须 deferred/blocked；若它因本卡一起 materialized，测试失败。

### 6.2 source count 必须可逆

正式 numeric termination 必须能回到同一 source path/content hash/`MaxNumber` 字段，且禁止 hard-coded default。

**反例**：缺失、非数值或不能 lower 为 exact numeric expression 的 `MaxNumber` 必须 fail-closed，不能变成 1。

### 6.3 child order/identity 不可伪造

每个 `OnProjectileHit` child 的 formal identity 必须来自 control-flow branch ledger；执行 iteration 只能复用该 child identity并附加稳定 iteration path。

**反例**：篡改/缺失 child mapping 或 branch identity 时，materialization/runtime 必须 blocked，不能跳过或落到其它 continuation。

### 6.4 parent structural、effect evidence 与 child semantic 分离

已证明 source shape 的 `FireProjectile` parent 可以成为 structural executable task，但只能因为它将由 task graph 的 counted sequence 解释；不能因为 opcode 名称本身或 effect registry 变化而提升。

必须同时成立：

- parent `AbilityTaskIR.coverage_status` 的提升可反查到 exact admitted `CharacterControlFlowNodeIR`；
- parent 对应 `EffectIR` 仍保持原始 unsupported/audit evidence，不得被本卡标成 executable；
- materializer 不为 structural parent建立 effect reference；
- child damage/status 等 effect 不得因 parent structural admission 被升级为 executable。

**反例**：相同 opcode 但缺 count、source identity 不一致、非 admitted `WaitProjectileFinish` shape 或没有 exact control node 的 task 必须继续 blocked。

### 6.5 S11 boundary 必须保留

PR14 同一真实 action 在本卡后仍应保留 S11 的：

- `task_graph_definition_not_admitted:effect:audit_only`
- `task_graph_control_requires_domains:damage_heal_shield`

两者若被本卡消掉，视为越界失败。

### 6.6 fail-closed / zero leakage

当 projectile parent 已能 materialize、但 child 在 S11 boundary blocked 时，真实 formal task-graph 执行必须保持已有原子语义：blocked result 的 state 不变，不泄漏 mutation/event/RNG/settlement。P3 不得通过 process-only 假成功绕过 child blocker。

## 7. Fast 验证

从仓库根目录串行运行：

```bash
python -m pytest hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_p9_a2_p3_fire_projectile_sequence_admission.py -q
python -m compileall -q hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/character_control_flow_contracts.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_p9_a2_p3_fire_projectile_sequence_admission.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p3_fire_projectile_sequence_admission.py
git diff --check eedebb406b85ab2611e8345b3fe7a75e9a7c53a0...HEAD
```

聚焦 pytest 至少覆盖：

1. exact `MaxNumber` + ordered `OnProjectileHit` positive；
2. `MaxNumber == 0` 不执行 child；
3. missing/non-exact count negative；
4. child identity/order mismatch negative；
5. unproven `WaitProjectileFinish` shape fail-closed；
6. non-FireProjectile S8C role 不被本卡误 admission；
7. exact structural parent 可提升 task coverage，但对应 `EffectIR` 仍非 executable；
8. parent structural 后 child audit-only/unsupported 仍按 child authority blocked；
9. canonical round-trip / source identity 稳定。

## 8. 必须运行的真实 Direct

运行：

```bash
python hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p3_fire_projectile_sequence_admission.py
```

该 validator 必须调用现有生产 builders/lowering/materializer/RuleBook/正式 action admission 与 task-graph executor，不得自己重写 projectile 或 action 语义。报告至少证明：

### 8.1 source-shape denominator

- 列出当前 formal ability denominator 中 `FireProjectile` occurrence 总数与 shape 分组；
- admission 的 shape 全部由同一字段/termination/branch 不变量证明；
- source occurrence -> control node -> formal task/effect -> graph node/numeric definition/branch identities 双向闭合；
- 未 admission shape 逐个给精确 owner/reason；不能用空集算通过。

### 8.2 S8C sibling isolation

证明本卡没有把其它 `p9_s8c` projectile/random/barrier/parallel source disposition 误标为 materialized，也没有通过 lowering 的 structural-parent逻辑提升其它 family/opcode。

### 8.3 PR14 真实 blocker delta

复用 PR14 同一生产构建链和同 owner 普通 action 选择规则；不得硬编码“正确答案”。对真实 `CombatExecutor.execute(ActionCommand)` / 其正式 admission 证据，P3 只允许出现以下变化：

必须消失：

- `task_graph_control_requires_domains:hit_random_sequence`（仅该 action 上由已 admission `FireProjectile` 导致的实例）
- `effect_coverage_status:unsupported:FireProjectile`
- `task_graph_definition_not_admitted:effect:unsupported`

必须仍存在：

- `task_graph_definition_not_admitted:effect:audit_only`
- `task_graph_control_requires_domains:damage_heal_shield`

同时必须证明 `FireProjectile` `EffectIR` 本体并未被提升为 executable；消失的是 structural parent task/admission blocker，而不是 effect coverage truth 被改写。

因此 **本卡完成不等于 PR11 可恢复**。真实 outer action 预期仍因 S11 fail-closed。

### 8.4 formal runtime boundary

对同一真实 materialized graph 做窄 runtime probe，必须证明 execution 已进入 `FireProjectile` 的 counted ordered hit continuation，随后只因尚未闭合的 child authority（预期 S11）blocked；整个 blocked result state unchanged 且无 formal channel 泄漏。

若无法在不修改只读 runtime consumer 的前提下做到这一点，必须 `needs_replan`，不能把仅静态 admission 当作生产完成。

## 9. 资源预算

- fast + Direct 目标总墙钟 `< 8 min`；
- 单进程峰值 RSS 目标 `< 3 GiB`；
- evidence 默认写 `/tmp`，只提交精简 execution report；
- 不跑 full suite、全量 catalog、全角色大 dump；只有 validator 为证明本卡 FireProjectile denominator 所必需的 scoped source build 可运行；
- 不新增 workflow、依赖、缓存层或并列验证框架。

达到预算约 70% 时先缩窄到本卡 formal ability / FireProjectile denominator，不得通过扩大工具系统解决验证成本。

## 10. stop conditions

出现任一情况立即 `needs_replan`：

1. `FireProjectile` 正确语义需要修改 `rules/task_graph.py` schema 或 `systems/task_graph.py` executor 才能表达；
2. 必须修改 `systems/action_contract.py`、`systems/ability_task_contract.py`、`systems/ability.py`、effect/damage/RNG/event caller 或 coverage registry 才能闭合本卡；
3. lowering 无法仅凭 exact source/control-node contract 区分 structural parent，必须按 opcode/角色/文件做全局例外；
4. `WaitProjectileFinish` 在真实命中 shape 上需要独立 barrier/parallel/timeline authority；
5. 当前真实 blocker 实际来自 `RandomConfig`、其它 projectile family 或第二个 S8C authority，而不是本卡 source shape；
6. 要消掉 P3 blocker 必须同时消掉 S11 audit-only/damage-heal-shield；
7. 同形 `FireProjectile` denominator 出现互相冲突、无法由同一 source-backed invariant 表达的语义；
8. 需要 hard-code actor/action/source file/hash 才能让 real Direct 前进；
9. 除本卡三处 L0 生产文件外还需要新的生产写路径；
10. 首次集中自审发现三个以上新的系统性问题类别。

只有真实 GitHub 权限、缺失 pinned source、不可用环境等外部问题才标 `blocked`。普通代码/测试/CI问题由 EXEC 在本卡范围内自行处理。

## 11. ready_for_review 交付

EXEC 完成后在本 PR 留：

- `[HANDOFF:REVIEW]`
- `role=EXEC`
- `status=ready_for_review`
- `stage=P9-A2-P3`
- `dispatch_id=<收到的正式 EXEC dispatch id>`
- `final_head=<实际 SHA>`
- `fast=` 各命令/exit code
- `direct=` validator/exit code + blocker delta
- `denominator=` FireProjectile source-shape 分母/闭合/未闭合计数
- `remaining=` 精确写明 S11 `damage_heal_shield + audit_only` 仍阻断 PR11；其它 S8C sibling 仍 deferred
- `next=REVIEW`

execution report 必须给出真实 head、实际 passed/skipped/未运行项和残余风险。EXEC 不勾总 checklist、不合并、不恢复 PR11、不启动 S11 或下一卡。

## 12. REVIEW 验收边界

REVIEW 必须独立核对：

- 生产 diff 只建立 `FireProjectile` projectile-sequence L0 producer authority，没有把 `p9_s8c` 整域标 closed；
- structural parent task 的 coverage 提升严格绑定 exact source/control-node identity，`EffectIR` 本体仍保持真实非 executable evidence；
- source-shape denominator 与 real Direct 都不是固定角色/固定答案夹具；
- parent structural admission 有真实 runtime 到 child boundary 的证据，而非只改 coverage 字符串；
- S11 两个 blocker 仍存在且 state/channel fail-closed；
- 其它 S8C sibling disposition 未漂移；
- final head 的适用 CI/本卡 Fast/Direct 证据一致。

通过后只接受 P3，不得宣告 A2/PR11/P9 完成。P3 合并后由下一轮 PLAN 从最新 merged master 重新归因；只有剩余前置链为空才恢复现有 PR11。
