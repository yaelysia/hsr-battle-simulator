# P9-S5C2 动作选择查询、提交与执行上下文执行卡

## 执行边界

- 硬前置：P9-S5C1 已验收。
- 本卡原子迁移“候选公布 -> 决策令牌 -> 提交重核 -> scheduler 授权 -> executor 选择上下文”。
- 现有 `TargetPolicy` 同时混合选择关系与 effect impact，不能先删除选择权威、下一阶段再拆
  impact；这种拆法会留下双重权威，因此原 S5C2 与 S5C3 合并。
- 随机抽样、shuffle 和 bounce 后续命中仍归 S5D；本卡只允许它们在独立 impact 边界明确 blocked。

## 闭合地图

| 项目 | 权威契约 |
|---|---|
| 完成分母 | 全部生产 `ActionChoice` 构造者、`EnemyActionCandidate`、外部 `DecisionSystem.submit`、`enqueue_manual_ultimate`、scheduler external/queue 路径和 `CombatExecutor.execute`；timeline tie、standalone ability 与 setup/system transaction 是有代码依据的非战斗动作选择豁免 |
| 输入权威 | S5C1 `ActionTargetContractIR`、committed `BattleState`、S5B lifecycle/relation 事实、动作 admission；effect impact 只读 action event/hit profile/bounce policy 的独立来源 |
| 输出权威 | 严格 query、accepted selection 和递归不可变 `ActionTargetSelectionContext`；已有 `DecisionToken` 是唯一外部查询身份 |
| 生产不变量 | blocked query 无候选；selection 与 action/actor/contract/query 一致；stale/forged token、候选变化、数量/重复错误和外部 context 注入在 phase mutation/action plan/可提交业务 event/RNG 前拒绝；允许保留不进入后继状态的 `process_only` 诊断事件；scheduler 改变阶段后必须重新签发绑定当前执行状态和同一 selection fingerprint 的 action authorization |
| 正式调用者 | normal、summon、enemy、queue/ultimate/extra-turn 的候选公布和执行只读同一选择契约；executor 不再从旧自由 policy 重做选择 |
| 后续归属 | random/shuffle/bounce 后续命中归 S5D；伤害 fallback 归 S11；4 条 client target lock 继续 `projection_only`、零 runtime |
| 最小证据 | 一个真实显式选择 contract、一个真实 automatic contract、一个只证明上下文运输的 validation fixture、一个 queue/internal 路径、一个 enemy 路径、一个 consumer ledger；每条生产不变量一个最小反例 |

## 已确定语义

1. selection 只表示推演器/固定流程选定的主目标集合；blast 相邻、aoe 实际作用集合和 bounce
   后续命中属于 effect impact。
2. explicit 模式公布稳定候选并要求命令提交唯一合法目标；automatic 模式命令不得提交目标，
   由 query 生成规范 auto selection。
3. 已接受 selection 绑定 action、level、actor、contract fingerprint、query fingerprint 和候选集合；
   同一 action 的 phase/task/effect 只消费这个不可变上下文。
4. `choice_revision` 必须覆盖 contract、规范候选和 automatic selection。状态或候选变化使旧 token 失效。
5. enemy 只公布固定动作和候选，不自行选择显式目标；外部推演器负责提交。
6. queue/internal 只能使用封闭授权调用同一 selection producer；不得从 queue metadata 或首项 fallback
   伪造选择。
7. action event 的 target mode 可以定义 impact 形状，不能反向覆盖 S5C1 的选择关系或基数。

## S5C1 字段消费矩阵

S5C2 不得只消费 `TargetType`。S5C1 已类型化的每个 gameplay 字段都必须有唯一运行时归属：

| 字段语义 | S5C2 运行时结果 |
|---|---|
| 候选关系与显式/自动模式 | 决定基础候选、是否接受外部 `target_ids` 及选择数量 |
| 存活或 limbo | 通过 S5B lifecycle 事实过滤候选；不得从 flags 猜测 |
| 友方/敌方召唤物策略 | 只读已校验的 summon runtime；`forbidden` 排除对应 servant，`allow_when_summoner_unselectable` 只有在 summoner 不可选时保留 servant |
| servant 或 summoner、合并选择 | 以 summon runtime 的真实 owner/summoner 关系规范候选；可选 summoner 存在时合并到 summoner，不可选时才保留被明确允许的 servant |
| 避免自身 | 在其他候选规则后移除 actor，并参与 query fingerprint |
| 类型化 TargetFilter | 用 S5B `TargetSystem.resolve_target_expression` 解析后与基础候选求交；blocked 或产生 RNG 时不发布候选，后者归 S5D |
| 最大选择数 | 显式提交必须位于 `selection_min..selection_max`；不允许重复或非候选目标 |
| 相邻/全队 effect 子目标 | 只在 impact resolver 扩展，不改变 primary selection；相邻关系复用 S5B formation 事实 |
| 动态 effect 目标 | 当前 79 条角色来源若非空，必须在本卡给出可执行解释或精确后续归属；不得把字段静默当成普通静态目标 |
| UI 错误文案/图标 | 保持 non-gameplay，不进入 query、token、授权或 executor |

验收器必须从 S5C1 类型字段集合独立重建这张消费矩阵。仅证明旧 `target_policy` 调用消失，
不能证明字段消费完整。

## 阶段目标

1. 建立严格、递归不可变的 query、selection 和 selection context；状态与 payload 在构造边界闭合。
2. normal、summon、enemy 和 queue 候选公布全部通过 S5C1 契约查询 committed state；删除
   `target_policy` 自由字典和旧选择推导的生产读取。
3. `DecisionSystem.submit` 重算当前 query，核对现有 token、choice 和 target IDs；只在通过后签发
   封闭授权，授权完整绑定选择上下文。
4. scheduler 在任何 phase mutation 前验证 decision authorization、命令与完整 selection context；
   阶段切换后为 executor 签发新的封闭 action authorization，绑定切换后的状态 revision 和原
   selection fingerprint。external 与 internal/queue 使用同一选择 producer，不存在只校验
   action、不校验 target 的授权。
5. executor 只消费已授权 selection context，不从 command metadata 或 action event 重建选择；
   phase/task/effect 共享同一 selection identity。
6. 选择与 effect impact 在类型和调用链上分离。impact 可复用既有 target helper，但其输入关系必须
   来自 selection contract，且不能扩大或改写主选择。
7. 删除旧 `target_policy_for_action` 的生产行为路径；不为历史验证器保留双轨兼容层。
8. `ActionCommand` 在构造边界递归冻结并拒绝顶层 metadata 注入 selection、primary、impact、
   contract、query 或 context；合法调度审计 metadata 不得成为规则输入。

## 明确不做

- 不实现随机目标、shuffle、bounce 后续命中或新的 RNG 规则。
- 不新增第二个 query token，不实现敌方 AI。
- 不把 client target lock 写入 BattleState，不跨 action 保存 selection。
- 不提前关闭 S11 的伤害 fallback，也不修改不消费 action selection 的效果目标表达式。
- 不为本阶段重写 standalone ability 的内部 target list；它不是可选战斗 action，仍由其正式
  queue resolution 负责，不能冒充 S5C2 consumer。
- 不重跑 S5C1 主验证；其目录契约按历史 evidence 继承。

## 五面验收门

| 审查面 | 只有以下结果才通过 |
|---|---|
| 来源范围 | consumer ledger 覆盖全部生产 ActionChoice、enemy candidate、decision、手动终结技入队、scheduler、queue 和 executor 路径；S5C1 每个 gameplay 字段有唯一消费者；全部豁免有代码依据 |
| 生产不变量 | query/selection/context 状态严格；伪 token、伪授权、候选变化、非法数量、重复、自动模式显式目标、metadata context 注入均零业务副作用 |
| 正式调用者 | 所有战斗 action 的选择只来自 S5C1 契约；旧 `target_policy_for_action` 生产调用为零；同一 action context fingerprint 持续到 settlement/replay |
| gap 归属 | S5C1 blocked 不发布候选；random/bounce 明确转交 S5D；任何新增 gameplay gap 有精确阶段，不得混入通用 deferred |
| 验证真实性 | 真实 source-backed contract/slice 只证明 explicit/automatic 查询与接受语义；若下游能力图仍被后续阶段阻断，只能用明确标为 `validation_fixture` 的最小世界证明 Decision -> scheduler -> executor 上下文运输，不能将其报告为真实角色动作可执行；queue/enemy 只做直接调用链最小纵切；总门有假值控制且不复制 executor 规则 |

## 必须负例

- blocked/ambiguous S5C1 契约发布候选或 selection。
- action、level、actor、contract、query、candidate 或 context fingerprint 任一错绑。
- stale token、伪造 token/seal、候选集合改变、非候选目标、重复或数量错误。
- automatic action 携带显式目标，explicit action漏目标或提交多个目标。
- `AliveState`、servant policy、servant/summoner merge、`AvoidSelf`、TargetFilter 或最大选择数任一
  被忽略；selection filter 结果越过基础阵营/生命周期候选。
- command metadata 注入 selection、primary、impact、contract 或 query payload。
- scheduler/executor 在 context 不一致时产生 phase mutation、action plan、RNG、资源扣除或非
  `process_only` 业务事件；只允许保留不进入后继状态的诊断事件/记录。
- scheduler 复用 phase mutation 前的 action authorization，或重新签发的授权没有绑定 selection
  fingerprint。
- queue/internal 未经封闭授权直接执行，enemy 固定序列自行选取显式候选首项。
- effect impact 改写 primary selection 或扩大到不符合来源关系的阵营。

## 验证与成本

- 唯一主入口：`validate_p9_s5c2_action_selection_query_submit_context`。
- 一次真实 action slice 构建，并从同一次来源投影中选择一个 explicit 和一个 automatic contract；
  两者只验证真实来源的查询/接受结果。若真实 action 因后续阶段机制缺口尚不能发布，Decision 到
  executor 的连续性使用同一最小 `validation_fixture` 世界验证，报告必须将两种证据分栏，且不得
  声称 fixture 关闭了真实 gameplay 端到端。queue 和 enemy 使用同一最小世界，不另建完整角色或目录。
- 不重跑 S5C1/S5B 主入口，不构建完整 Canonical IR，不写完整 transition dump。
- 预算：主入口 5 分钟、RSS 800 MiB、evidence 1.5 MiB、验证器可读目标 700 非空行。
- 必跑：聚焦 `compileall`、唯一主入口、`git diff --check`。direct 最多一个，只在公开 scheduler
  或 action authorization codec 实际改变时抽取现行最小切片。

## 唯一执行清单

- [x] query、accepted selection 与 selection context 严格不可变且只有一个生产入口。
- [x] normal、summon、enemy、queue 的候选公布全部迁移到 S5C1 契约。
- [x] S5C1 每个 gameplay 字段均有唯一、可审计的 query 或 impact 消费者，当前范围动态目标诚实归属。
- [x] `DecisionToken` 绑定完整 contract/query/candidate，所有非法提交在 phase mutation 前拒绝。
- [x] external 与 internal/queue 授权都绑定同一 selection context。
- [x] executor、phase、task、effect 只消费已授权 context，selection 与 impact 明确分离。
- [x] 旧自由 target policy 无生产行为读取，client target lock 无 runtime 行为。
- [x] 五面验收、gap 归属和资源门通过。
