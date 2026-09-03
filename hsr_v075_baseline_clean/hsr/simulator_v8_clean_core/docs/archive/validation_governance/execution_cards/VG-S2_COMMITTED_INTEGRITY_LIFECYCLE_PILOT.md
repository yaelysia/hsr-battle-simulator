# VG-S2 Committed Integrity 协议与生命周期试点执行卡

## 执行配置

- 代码基线：`c01ce5c`。
- 前置阶段：`VG-S0`、`VG-S1` 已通过验收。
- 推荐模型：GPT-5.6 Sol。
- 推荐推理等级：`max`。
- 推荐模式：普通模式，单卡执行。
- 执行归属：新的代码执行线程。
- 验证命令工作目录：`hsr_v075_baseline_clean/hsr/`。
- 最终状态上限：`ready_for_review`。
- 禁止执行线程修改本卡 checklist、提交 Git 或开始 `VG-S3`。
- 工作区现有无关 UI 草稿不属于本卡，禁止修改、删除或提交。

## 1. 背景与已确认事实

VG-S1 已经保证 committed `UnitState`、`BattleState` 和 `Snapshot` 不会再被
外部容器别名或原地写入绕过。现在剩余的问题不是“状态会不会被偷偷修改”，而是
“一个结构上合法、业务上自相矛盾的状态能不能被正式提交”。

当前生产代码已经确认存在以下事实：

1. `MutationReducer.apply_all_result()` 会在私有候选状态上顺序应用一批
   Mutation，并保证路径、before/after 和整批冲突原子性。
2. `finalize_selected_execution_graph()` 会重新应用整批 Mutation，并检查
   reducer 结果与系统规划出的候选状态完全一致；但成功发布前没有领域完整性门。
3. executor 和 scheduler 的正式动作、独立能力及调度 transition 都汇入上述
   原子提交边界。
4. status、damage、summon、wave 等系统内部多次调用 reducer 只是为了继续规划
   后续节点。这些中间候选状态不应在每条 Mutation 后被完整性检查阻断。
5. `ScenarioStateBuilder` 在 provider、开局能力、BattleSetup 和开局事件全部完成
   后直接返回初始 `BattleState`，当前没有统一的最终完整性检查。
6. 单位生命周期目前有两套可独立变化的表示：
   - `flags["lifecycle_status"]`；
   - HP 小于等于零时推断为 defeated 的 fallback。
7. 正式伤害击败已经能在同一规划批次产生 HP 归零、defeated 状态和
   `defeat_record`；wave/summon 移除已经能产生 removed 状态和
   `removed_record`。
8. 当前没有已准入的 revive 生产者。`defeated -> active` 只有明确的 blocked
   入口，不能为本阶段虚构复活语义。

已确认可复现的提交漏洞是：

```text
active 单位
  -> 只提交 hp = 0 的 Mutation
  -> reducer 和 candidate 一致
  -> 当前 atomic commit 会发布
  -> 后续 consumer 再分别用 HP 或 flags 猜测生死
```

本阶段要从根因上关闭这个入口。目标不是增加一个更大的验证脚本，而是让生产提交
边界本身拒绝非法 committed state。

## 2. 阶段完成后的具体结果

### 2.1 生命周期只有一个权威字段

完成后，`UnitState` 必须具有类型化字段：

```text
lifecycle_status: active | defeated | removed
```

该字段是 runtime 中单位生命周期的唯一权威来源。具体要求：

- unit flags 顶层的 `lifecycle_status` 和旧别名 `lifecycle_state` 退役并成为
  保留键；任何 UnitState 构造输入、codec payload、spawn payload、
  whole-flags Mutation 或 nested-flags Mutation 试图重新写入它们，都必须
  fail-closed。status instance detail 内自己的 `lifecycle_state` 不属于单位
  生命周期字段，不能误删。
- `hp` 只表达当前生命数值，不再负责推断生命周期。
- target、action、timeline、status、summon、halo、condition、snapshot 等
  consumer 只读取类型化生命周期字段。
- `defeat_record` 和 `removed_record` 仍是审计记录，不是生命周期权威，也不能
  反向替代类型化状态。
- snapshot 继续输出现有 `lifecycle_status`、`defeated`、`removed` 和
  `lifecycle` 视图，但这些都是从类型化字段确定性派生。
- unit codec 必须显式序列化和反序列化类型化生命周期字段。

本阶段采用原子迁移，不保留以下兼容层：

- 不双读 typed field 和 legacy flag。
- 不在缺失 typed field 时根据 HP 推断。
- 不在读取旧 payload 时自动补 `active`。
- 不接受 typed field 与 legacy flag 同时存在后“任选一个”。

普通 `UnitState(...)` 构造可以使用字段默认值 `active`，以避免所有合法活动单位
重复传参；但显式 codec/spawn payload 必须包含该字段，旧 payload 必须因 schema
不完整而拒绝。默认值不能用来吞掉旧 flags 或非法 HP 组合。

### 2.2 UnitState 构造边界与 committed invariant 分离

`UnitState.__post_init__()` 只负责单字段表示合法性：

- 生命周期值必须属于固定枚举。
- legacy lifecycle flag 必须不存在。
- VG-S1 的递归不可变、有限数值容器和类型约束继续成立。

`UnitState.__post_init__()` 不得直接执行 HP 与生命周期的跨字段 committed
invariant。原因是系统在一个原子事务内部需要允许以下不可见中间态：

```text
先把 HP 写到 0
  -> 再写 defeated
  -> 再写 defeat_record
  -> 整批完成后一次性检查并提交
```

如果在每次 `replace()` 或每条 reducer Mutation 后检查跨字段 invariant，合法的
伤害击败批次反而无法完成。本阶段必须保留“候选可暂时不完整，提交不可不完整”的
边界。

这里的“可以暂时不完整”只允许发生在一个生产者内部组装同一原子子批次时。部分
生命周期批次不得被传给 target、condition、callback、status、halo、summon、
timeline 等其他规则 consumer。实际 damage defeat 调用链必须证明：下游节点
看到目标时，HP、typed status 和 defeat record 已经作为完整子批次应用。若当前
生产顺序会把 `hp=0 + active` 交给其他系统，必须调整批次应用/交接顺序，不能
恢复 HP fallback 掩盖问题。

### 2.3 生命周期最终状态不变量

完整性门检查的每个单位必须先满足：

- `max_hp` 是有限数值且大于零。
- `hp` 是有限数值，且满足 `0 <= hp <= max_hp`。
- `defeat_record` 和 `removed_record` 若存在，必须是非空 JSON object；空对象
  不能冒充已记录。

随后按生命周期状态检查：

| 生命周期 | HP 要求 | 击败记录 | 移除记录 |
|---|---|---|---|
| `active` | `hp > 0` | 不得存在 | 不得存在 |
| `defeated` | `hp == 0` | 必须存在 | 不得存在 |
| `removed` | 仍须在合法 HP 范围内，不强制归零 | 可保留 | 必须存在 |

`removed` 不等于死亡。wave 清场、召唤替换和来源退场可以移除仍有 HP 的单位，
因此禁止写成 `removed -> hp 必须为 0`。

本阶段只验证生命周期记录的存在性、非空性和原子闭合，不重新实现
source audit，也不把 damage/wave/summon 的专属 payload 字段硬编码进 core
完整性规则。

### 2.4 生命周期转换不变量

整批提交除最终状态合法外，还必须满足以下转换规则：

| before | after | 本阶段裁决 |
|---|---|---|
| 不存在 | `active` | 仅合法完整 spawn 可通过 |
| 不存在 | `defeated` / `removed` | 拒绝 |
| `active` | `active` | 允许，最终 HP 必须大于零 |
| `active` | `defeated` | 必须同批触达 HP、typed status、defeat record |
| `active` | `removed` | 必须同批触达 typed status、removed record |
| `defeated` | `defeated` | 允许，最终 invariant 必须继续成立 |
| `defeated` | `removed` | 必须同批触达 typed status、removed record |
| `defeated` | `active` | 拒绝；revive 尚未准入 |
| `removed` | `removed` | 允许，最终 invariant 必须继续成立 |
| `removed` | `active` / `defeated` | 拒绝；re-entry 尚未准入 |
| 任意已存在单位 | 从 `units` 直接删除 | 拒绝；正式移除必须保留 removed 单位审计状态 |

“同批触达”按 canonical Mutation path 判断，不能通过 metadata 文本声称完成：

- 生命周期字段：`("units", unit_id, "lifecycle_status")`
- HP：`("units", unit_id, "hp")`
- 最大 HP：`("units", unit_id, "max_hp")`
- 击败记录：`("units", unit_id, "flags", "defeat_record")`
- 移除记录：`("units", unit_id, "flags", "removed_record")`
- 整体 flags 替换视为同时可能触达两个记录。
- 整体 unit spawn/替换视为触达该单位生命周期全域。

legacy paths `("units", unit_id, "flags", "lifecycle_status")` 和
`("units", unit_id, "flags", "lifecycle_state")` 必须由 reducer 结构化拒绝，
不能等到模型构造异常后崩溃，也不能继续生成移除事件。

### 2.5 机器可读完整性协议

新增窄 core 模块：

```text
core/state_integrity.py
```

至少建立以下等价类型；命名可小幅调整，但职责和 JSON 契约不得弱化：

- `StateIntegrityIssue`
  - `domain`
  - 稳定 `code`
  - `entity_id`
  - 相关 canonical paths
  - 相关 mutation IDs
  - 可选、简洁的 details
- `StateIntegrityScope`
  - domain
  - 被触达的实体 ID
  - 触发该 scope 的 canonical paths
- `StateIntegrityResult`
  - `status: passed | failed | not_run`
  - `check_mode: touched | full | not_run`
  - 实际检查的 domain 和 entity IDs
  - 稳定排序的 issues
- `CommittedStateIntegrityError`
  - 用于初始场景等没有 transition outcome 的正式发布边界；
  - 异常对象必须保留结构化 `StateIntegrityResult`，不能只有一段字符串。
- `CommittedStateIntegrityGate`
  - 检查整批 transition 的 touched domains；
  - 检查场景初态等入口的 full registered domains。

协议要求：

- 生产 checker 使用固定、显式、确定顺序的领域表；S2 只有 lifecycle checker。
- 不建立动态插件系统、RuleBook registry 或反射扫描框架。
- touched selector 只从 canonical Mutation path 选择 domain 和 unit ID。
- issue 顺序不受 mutation 输入顺序、dict 顺序或 set 顺序影响。
- result 递归不可变并能输出普通 JSON。
- `to_json()` 每次返回独立普通 JSON；修改返回值不能影响 typed result。
- 空 touched-domain 批次返回 `passed`，`checked_domains=()`，不能偷偷全扫 units。
- full 模式扫描当前注册领域的全部相关实体；S2 只在场景最终初态入口使用。
- 完整性 checker 不读取 RuleBook、TBGD、source report、验证 artifact 或 `/tmp`。

建议稳定 issue code 至少能区分：

```text
lifecycle_hp_not_finite
lifecycle_max_hp_invalid
lifecycle_hp_out_of_range
active_unit_hp_not_positive
active_unit_has_defeat_record
active_unit_has_removed_record
defeated_unit_hp_not_zero
defeated_unit_missing_defeat_record
defeated_unit_has_removed_record
removed_unit_missing_removed_record
lifecycle_spawn_state_invalid
lifecycle_transition_not_admitted
defeat_transition_not_atomic
remove_transition_not_atomic
unit_deletion_not_admitted
```

具体 code 可以按实现合并相邻情况，但不得把所有错误压成一个
`lifecycle_invalid`，也不得让 message 文本成为唯一机器判定依据。

### 2.6 原子提交边界

`finalize_selected_execution_graph()` 的顺序必须变为：

```text
检查 preflight / execution nodes
  -> reducer 在私有状态重放整批 Mutation
  -> 比较 reducer 结果与规划 candidate
  -> 根据整批 Mutation 选择 touched domains
  -> 对 reducer.after_state 执行 committed integrity
  -> 通过后才发布
```

明确要求：

- integrity 必须检查 reducer 重新计算出的 `after_state`，不能只信系统传入的
  candidate。
- mutation conflict、candidate mismatch 或 selected graph incomplete 时没有
  可发布候选，integrity result 为 `not_run`。
- `AtomicCommitResult` 必须直接保存 typed `StateIntegrityResult`；coverage
  evidence 由该对象的 detached JSON 生成，不能只保存一份可变字典后丢失 typed
  结果。
- 通过时：
  - `after_state` 为 reducer 结果；
  - planned Mutation 全部成为 committed Mutation；
  - outcome 可以 successor。
- 失败时：
  - `after_state is before_state`；
  - `committed_mutations == ()`；
  - `commit_status == "state_integrity_failed"`；
  - outcome 必须是 `diagnostic`，不是游戏规则 `blocked`；
  - `successor_eligible == false`；
  - node results 增加可定位的 integrity error node；
  - evidence 保留完整结构化 integrity result。

原子提交 evidence schema 已发生变化，必须升级版本；不能继续声称
`p7_s3_atomic_commit_v1`。所有 executor/scheduler 正式调用点必须输出同一新
schema，不允许一部分 transition 有 integrity evidence、另一部分没有。

完整性失败时，规划阶段产生的正式证据不能冒充已提交结果：

- mutation settlement 通过现有原子结果规范化为 `process_only`，并标记
  `planned_only`。
- mutation-derived GameEvent 必须成为 `process_only` 诊断事件，不能继续作为
  committed gameplay event。
- 正式 `rng_events` 输出必须为空；若需要保留诊断，只能在 atomic evidence 中
 记录 planned count/ID，不得表示 RNG 已消费。

这只是 atomic failure artifact 的收口，不在 S2 重写 event dispatcher、
callback closure 或事件 root/child 所有权；后者仍属于 `VG-S4`。

### 2.7 reducer 与 replay 边界

`MutationReducer.apply_all_result()` 继续只负责结构、前置条件和私有候选构造：

- 不在每条 Mutation 后执行 lifecycle checker。
- 不扫描未触达单位。
- 不读取 RuleBook 或其他领域系统。
- 合法击败批次的中间 `hp=0 + active` 候选必须仍可在批次内部存在。

`MutationReducer.replay_snapshot()` 接收的是完整批次，不是中间规划节点，因此
在结构重放成功后必须调用同一个 touched-domain integrity gate，再比较 expected
snapshot：

- 非法生命周期批次即使 expected snapshot 与非法 reducer 结果相同，也不能
  replay `ok=true`。
- replay failure 返回结构化 integrity evidence 或稳定错误码。
- 合法提交批次 replay 结果保持确定。
- reducer 的普通 `apply_all_result()` 不因此变成领域 validator。

完整 unit codec/spawn payload 同样代表一个可独立交换的最终单位，不是局部
Mutation。因此 `unit_state_from_payload()` / `unit_state_to_payload()` 必须复用
生产 lifecycle final-state checker，拒绝自相矛盾的完整 payload；不得在 codec
中复制第二份 HP/lifecycle 规则。

### 2.8 场景初态发布边界

`ScenarioStateBuilder.build()` 必须运行两次 full registered-domain integrity：

1. 基础 `BattleState`、单位、系统实体和初始 runtime 刚构造完成后，在任何
   provider、startup ability 或 BattleSetup consumer 读取前检查一次。
2. 以下步骤全部完成后、创建并返回 `ScenarioBuildResult` 前再检查一次：

- 初始单位构造；
- provider 注册；
- startup ability；
- BattleSetup；
- battle setup event；
- route unit 复核。

要求：

- 正式构筑单位和普通 kernel fixture 默认创建为 typed `active`。
- `level:global` 等系统实体同样使用 typed lifecycle，不再写 legacy flag。
- kernel fixture 传入 `hp=0` 但没有合法 defeat closure 时，最终初态必须抛出
  `CommittedStateIntegrityError`。
- 原始 fixture 若已非法，必须在第一次 full check 失败，不能先参与开局规则
  计算后再由末尾检查兜底。
- scenario 不新增“初始 defeated”自由输入；若后续确有真实来源，另行设计
  source-backed 初始化契约。
- 初态失败时不返回 `ScenarioBuildResult`，也不能把非法 snapshot 暴露给 UI、
  推演器或 replay。

## 3. 本阶段只做

- 新增 committed state integrity 的窄类型、touched selector 和 gate。
- 将单位生命周期迁移为 `UnitState` 类型化唯一权威。
- 将 lifecycle consumer 和 producer 原子迁移到 typed field/path。
- 在 atomic commit 成功发布前执行 touched lifecycle integrity。
- 在完整批次 replay 中复用同一 touched integrity。
- 在 ScenarioStateBuilder 的 setup 前和最终返回前执行 full lifecycle integrity。
- 收口 integrity failure 的 mutation settlement、事件和 RNG 输出语义。
- 只迁移生产代码和本卡 direct 验证中会实际构造 legacy lifecycle flag/path 的
  fixture。
- 对其余历史验证只输出待分类清单，不为本阶段逐份维护或运行。
- 新增一个紧凑、不读取 TBGD 的 S2 聚焦验证器。
- 只运行本卡列出的 fast/direct 回归。
- 新增一份 `ready_for_review` 报告。

## 4. 本阶段不做

- 不实现 revive、复活后记录保留、尸体目标等新游戏规则。
- 不把 removed 强制解释为 defeated，也不强制 removed 单位 HP 为零。
- 不实现 status details/粗索引、summon registry、halo relation、wave/queue 等
  其他领域完整性 checker。
- 不在每个 system、每条 Mutation 或每次 `replace()` 后运行全局检查。
- 不让 UnitState 构造器执行 committed 跨字段 invariant。
- 不建立通用动态插件/反射 registry。
- 不重写 event dispatcher 或解决 root event 重复；该工作属于 `VG-S4`。
- 不修改角色卡、怪物卡、光锥、遗器、构筑、Canonical IR、RuleBook 或 lowering。
- 不重写或全量重跑 P1-P8 历史验证。
- 不为了旧 payload、legacy flag 或历史 fixture 保留双轨兼容。
- 不修改 P8 checklist、已验收 VG-S1 checklist 或无关 UI。
- 不新增依赖。
- 不开始 `VG-S3` validator registry。

## 5. 拟修改文件与关键符号

### 5.1 主要生产文件

- 新增 `simulator_v8_clean_core/core/state_integrity.py`
  - integrity issue/scope/result/error；
  - touched-domain selector；
  - lifecycle final-state 和 transition checker；
  - touched/full gate。
- 修改 `simulator_v8_clean_core/core/model.py`
  - `UnitState.lifecycle_status`；
  - 单字段构造校验；
  - snapshot 派生；
  - 删除 HP/flags lifecycle fallback。
- 修改 `simulator_v8_clean_core/core/unit_state_codec.py`
  - typed lifecycle payload；
  - mutable field/path 校验；
  - legacy flag 和旧 payload 拒绝。
- 修改 `simulator_v8_clean_core/core/reducer.py`
  - legacy path 结构化拒绝；
  - replay 完整批次 integrity；
  - 不改变普通 candidate reduction 的职责。
- 修改 `simulator_v8_clean_core/core/atomic_commit.py`
  - integrity gate；
  - typed integrity result；
  - 新 evidence schema；
  - integrity failure outcome；
  - settlement/event/RNG 失败规范化 helper。
- 最小修改 `simulator_v8_clean_core/core/__init__.py`
  - 只导出确实需要的公共 integrity 类型。
- 修改 `simulator_v8_clean_core/core/snapshot_contract.py`
  - 正式 unit snapshot 必须包含 lifecycle status/view；
  - 不在 snapshot validator 中复制 HP/lifecycle invariant。

### 5.2 生命周期 producer/consumer 原子迁移

- `simulator_v8_clean_core/unit_eligibility.py`
- `simulator_v8_clean_core/systems/unit_lifecycle.py`
- `simulator_v8_clean_core/systems/damage.py`
  - 只适配 typed lifecycle Mutation；不改伤害公式。
- `simulator_v8_clean_core/systems/status.py`
- `simulator_v8_clean_core/systems/summon_runtime.py`
- `simulator_v8_clean_core/systems/mutation_events.py`
- `simulator_v8_clean_core/rules/evaluator.py`
- `simulator_v8_clean_core/scenarios/build_state.py`
- `simulator_v8_clean_core/core/executor.py`
- `simulator_v8_clean_core/systems/scheduler.py`

如果静态扫描发现其他生产 Python 文件实际读写 legacy lifecycle flag/path，也必须
纳入同一原子迁移并在报告列出。TBGD source 字段名、报告文本和 snapshot 输出键
不属于 legacy runtime authority，不得为了 raw 字符串归零而误改。

### 5.3 验证与报告

- 新增
  `simulator_v8_clean_core/tools/validate_vg_s2_committed_integrity_lifecycle.py`
- 最小迁移：
  - `validate_vg_s1_committed_state_immutability.py`
  - `validate_p7_s2_mutation_reducer_contract.py`
  - `validate_p7_s3_selected_graph_atomic_commit.py`
  - P8-R1 runtime-only 所直接依赖的 fixture。
- 其他会构造 legacy flag/path 的历史验证不在 S2 修改；报告输出文件、引用位置
  和建议分类，留给 VG-S3/VG-S8 按触达域迁移。禁止为了让全局 grep 归零而维护
  未运行脚本。
- 新增
  `live_validation_reports/v8_vg_s2_committed_integrity_lifecycle_ready_for_review.md`

## 6. 必须覆盖的正例

聚焦验证至少覆盖以下真实生产边界：

1. typed `active` 单位的非致死 HP 变化可正式 commit。
2. 不触达 lifecycle domain 的 skill point/global flag Mutation 可 commit，且
   integrity evidence 显示未扫描任何单位。
3. 两单位场景中只触达一个单位时，只检查该单位；不得扫描另一个单位。
4. `UnitLifecycleSystem.spawn_mutation()` 生成的完整 active spawn 可 commit。
5. 生产 damage path 生成的合法致死批次同时包含 HP、typed defeated 和
   defeat record，可 commit。
6. 上述合法致死批次在 reducer 内部应用第一条 HP Mutation 后可以暂时形成
   `hp=0 + active` 候选，但该局部候选不会传给任何其他规则 consumer；只在
   整批完成后交接并通过 gate。
7. `UnitLifecycleSystem.remove_mutations()` 生成的 active -> removed 批次可
   commit，且不要求 HP 归零。
8. defeated -> removed 的合法批次可保留 defeat record 并新增 removed record。
9. 合法 spawn、defeat 和 remove 批次均可通过 committed replay。
10. typed removed Mutation 继续生成正式 unit-removed mutation event；
    legacy flags path 不再生成该事件。
11. action/target/status/halo/summon-runtime consumer 对 typed active、defeated、
    removed 的判断保持一致。
12. 最小合法 ScenarioStateBuilder fixture 在 setup 前和 setup 完成后两次通过
    full lifecycle integrity 并返回。
13. snapshot 和 unit codec round-trip 保留 typed lifecycle，JSON 结构确定。
14. SnapshotCompletenessValidator 拒绝缺少 lifecycle status/view 的外部
    snapshot，但不把自身变成第二份生命周期规则。

“生产 damage path”必须调用当前正式 damage system 生成击败 artifacts，不能在
验证器中复制 `_defeat_lifecycle_artifacts()` 的判断逻辑来伪造同构答案。

## 7. 必须覆盖的负例

聚焦验证至少覆盖：

1. active 单位只提交 `hp=0`：reducer 可形成 candidate，但 atomic commit 必须
   diagnostic、before unchanged、零 committed Mutation。
2. active 单位只写 typed defeated：拒绝。
3. active 单位只写 defeat record：拒绝。
4. active -> defeated 缺 HP、status、record 中任一触达：分别拒绝。
5. defeated 单位 HP 非零：拒绝。
6. defeated 单位缺 defeat record 或同时有 removed record：拒绝。
7. active 单位带 defeat/removed record：拒绝。
8. active/defeated 只写 typed removed 而缺 removed record：拒绝。
9. removed 单位缺 removed record：拒绝。
10. removed 单位仍有正 HP：允许，证明没有错误的“移除等于死亡”假设。
11. defeated -> active：拒绝，reason 指向未准入转换而非游戏 blocked。
12. removed -> active/defeated：拒绝。
13. 不存在单位直接 spawn 为 defeated/removed：拒绝。
14. 直接删除已存在 unit：拒绝。
15. HP 为 NaN、Infinity、负数、超过 max HP 或 max HP 非正：拒绝。
16. legacy lifecycle flag 出现在：
    - UnitState 构造；
    - codec payload；
    - spawn payload；
    - whole flags Mutation；
    - nested flags Mutation；
    以上路径全部结构化拒绝，不得崩溃或 fallback。
17. typed lifecycle 值不在枚举中：构造/codec/Mutation 均拒绝。
18. 非法生命周期批次即使 expected snapshot 与非法 reducer 结果相同，
    replay 仍失败。
19. integrity failure 的 settlement 全部 process-only，mutation-derived event
    全部 process-only，正式 RNG event 数为零。
20. integrity failure 不能被分类为 gameplay blocked，不能 successor。
21. kernel fixture 使用 `hp=0 + 默认 active` 时，ScenarioStateBuilder 第一次
    full check 即抛出携带结构化 result 的 `CommittedStateIntegrityError`，且
    provider 与 startup consumer 未运行。
22. 修改 `StateIntegrityResult.to_json()` 返回值不能改变 typed result、下一次
    JSON 输出或 atomic result 中保存的 typed integrity。
23. 调换 Mutation 输入顺序或映射顺序后，若语义等价，checked scopes 和 issue
    排序保持确定；若 before 链不等价，仍由 reducer conflict 拒绝。

## 8. 目标与验收证据映射

| 目标 | 允许通过 | 必须判阻断 | 证据 |
|---|---|---|---|
| 生命周期唯一权威 | 所有 runtime consumer/producer 使用 typed field/path | flags 或 HP fallback 仍能决定生命周期 | authority migration matrix + code review |
| 候选与提交分离 | 内部中间态可存在，最终批次才检查 | 每条 Mutation 后全域检查或非法最终态被发布 | intermediate/final matrix |
| touched-domain 增量 | 只检查实际触达单位 | 无关 Mutation 扫描全部 units | checked scope/counter matrix |
| lifecycle final invariant | active/defeated/removed 与 HP/记录一致 | 任一矛盾组合可提交 | final-state negative matrix |
| lifecycle transition closure | defeat/remove/spawn 必要路径同批闭合 | metadata 文本或预存记录冒充闭合 | transition path matrix |
| 原子失败语义 | before unchanged、0 committed、diagnostic | 返回 blocked、部分提交或 successor | atomic failure matrix |
| replay 闭环 | 完整合法批次可重放，非法批次不可 `ok=true` | expected snapshot 可为非法状态背书 | replay matrix |
| 场景初态闭环 | setup 前和最终状态均通过 full check 才继续/返回 | 非法 fixture 先参与开局规则或最终 state 泄露 | scenario matrix |
| 证据不冒充提交 | settlement/event process-only，正式 RNG 为空 | planned artifact 仍表现为已执行 | artifact matrix |
| 成本受控 | 全部 focused/direct 不读 TBGD、不建完整 RuleBook | validator 复制生产规则或进入 catalog | command log + source-size report |

## 9. 结构化验收谓词

S2 聚焦 summary 必须明确给出且全部为 true：

```text
typed_lifecycle_is_single_runtime_authority
legacy_lifecycle_flag_constructor_rejected
legacy_lifecycle_flag_codec_rejected
legacy_lifecycle_flag_mutation_rejected
hp_is_not_used_as_lifecycle_fallback
unit_codec_round_trip_preserves_typed_lifecycle
snapshot_derives_lifecycle_from_typed_field
snapshot_contract_requires_lifecycle_view
touched_domain_selector_is_path_driven
unrelated_mutation_checks_zero_lifecycle_units
touched_lifecycle_checks_only_selected_units
intermediate_candidate_may_be_temporarily_inconsistent
partial_lifecycle_candidate_not_exposed_to_rule_consumers
active_final_state_requires_positive_hp
defeated_final_state_requires_zero_hp_and_record
removed_final_state_requires_record_not_zero_hp
spawn_transition_requires_active_valid_unit
defeat_transition_requires_atomic_closure
remove_transition_requires_atomic_closure
revive_transition_not_admitted
removed_reentry_not_admitted
direct_unit_deletion_not_admitted
legal_damage_defeat_commits
legal_removal_commits
invalid_lifecycle_commit_is_diagnostic
invalid_lifecycle_commit_preserves_before_identity
invalid_lifecycle_commit_has_zero_committed_mutations
invalid_lifecycle_commit_is_not_successor_eligible
integrity_failure_records_are_process_only
integrity_failure_events_are_process_only
integrity_failure_has_zero_formal_rng_events
atomic_evidence_contains_structured_integrity_result
atomic_evidence_schema_version_updated
legal_lifecycle_replay_passes
invalid_lifecycle_replay_fails
scenario_pre_setup_state_runs_full_lifecycle_check
scenario_final_state_runs_full_lifecycle_check
invalid_scenario_initial_state_rejected
issue_order_is_deterministic
integrity_result_recursively_immutable
production_runtime_legacy_lifecycle_authority_refs=0
tbgd_read_count=0
full_rulebook_build_count=0
catalog_validation_count=0
focused_output_bytes_below_1_mib
focused_validator_does_not_duplicate_production_invariants
```

`production_runtime_legacy_lifecycle_authority_refs=0` 只统计 Python runtime 对
legacy flags/path 的读写，不要求删除 TBGD 字段、历史报告文本或 snapshot 的公开
输出键。

聚焦验证器必须以生产 gate 的返回值和稳定 issue code 为 oracle，不能复制一份
HP/lifecycle 判断函数后让两份相同错误互相证明。

## 10. 最小验证与运行顺序

所有验证串行执行。先通过新聚焦验证，再跑 direct 回归。

### 10.1 必跑最小集

```bash
PYTHONPYCACHEPREFIX=/tmp/hsr_v8_vg_s2_pycache \
python3 -m compileall -q simulator_v8_clean_core
```

目的：检查 typed state、integrity 模块和调用方迁移后的语法/导入闭环。

```bash
python3 -B -m simulator_v8_clean_core.tools.validate_vg_s2_committed_integrity_lifecycle \
  --output-dir /tmp/hsr_v8_vg_s2_committed_integrity_lifecycle
```

目的：证明本卡 authority、final invariant、transition closure、atomic failure、
replay、scenario 和增量检查矩阵。

```bash
git diff --check
```

目的：检查 patch 格式；不作为行为完成证明。

### 10.2 直接回归集

```bash
python3 -B -m simulator_v8_clean_core.tools.validate_vg_s1_committed_state_immutability \
  --output-dir /tmp/hsr_v8_vg_s2_vg_s1_immutability
```

目的：确认新增 typed field、integrity result 和 codec 迁移没有重新引入容器别名
或伪 frozen 子类绕过。

```bash
python3 -B -m simulator_v8_clean_core.tools.validate_p7_s2_mutation_reducer_contract \
  --output-dir /tmp/hsr_v8_vg_s2_p7_s2_reducer
```

目的：确认 reducer 的 candidate 构造、before 链、冲突原子性和 spawn codec 未被
领域门污染。

```bash
python3 -B -m simulator_v8_clean_core.tools.validate_p7_s3_selected_graph_atomic_commit \
  --output-dir /tmp/hsr_v8_vg_s2_p7_s3_atomic_commit
```

目的：确认 P7 的 selected-graph 完整性、candidate match 和原有冲突语义仍成立，
并原子迁移到新 atomic evidence schema。

```bash
python3 -B -m simulator_v8_clean_core.tools.validate_p8_r1_summon_runtime_halo_lifecycle \
  --tbgd-root ../../turnbasedgamedata-main \
  --runtime-only \
  --output-dir /tmp/hsr_v8_vg_s2_p8_r1_runtime
```

目的：status/halo/summon-runtime 是本卡直接迁移的 typed lifecycle consumer；
runtime-only 使用小型内存 RuleBook，必须保持 catalog builder count 为零。

### 10.3 条件触发集

默认无。

只有实际 patch 超出拟改范围时，按以下规则处理：

- 若修改 transition consumer/contract：增加 P7-S1 最窄 transition trust direct
  验证；不得因此运行 P7 聚合。
- 若修改 wave 生产逻辑而不只是 typed path：停止并修订卡，不能自动跑完整
  P7-S17 代替范围裁决。
- 若修改 damage 公式、target 规则、status 生命周期算法或 summon relation：
  停止并交回规划线程；这些不是 S2 typed authority 适配。
- 若 P8-R1 runtime-only 意外进入 source/catalog 构建：立即停止，按
  validation regression 处理。

### 10.4 明确不跑

- `validate_p1_1_unit_lifecycle`：它会完整 TBGD lowering；本卡新聚焦矩阵已覆盖
  当前 lifecycle 生产契约。
- `validate_p7_s17_wave_lifecycle_events`：它会完整 TBGD lowering；typed remove
  path 与 event 适配由聚焦正负例证明。
- P1-P8 任一阶段聚合。
- `validate_v0_209`。
- `validate_p7_current_tree_shared_regressions`。
- P8-S8 或 P8-R1 catalog/full 模式。
- 完整 TBGD discovery/lowering。
- 完整 Canonical IR、RuleBook、coverage 或 fidelity 输出。

这些入口不增加对 S2 committed invariant 的证明力，却会重新引入当前正在治理的
内存、IO、时间和 token 成本。未运行不等于其历史内容已重新证明。

## 11. 验证器与资源限制

- 新验证器只创建少量纯内存 UnitState/BattleState/Mutation、小型 RuleBook 和
  最小 Scenario fixture。
- validator 不得复制生产 touched selector、生命周期 invariant 或转换表。
- validator 只声明输入、调用生产 API，并核对稳定结果码/状态。
- 新验证器源码建议控制在 48 KiB 内；超过时必须先说明为何不能复用生产 API 或
  现有小型 fixture，不能通过压缩可读性规避。
- 默认只写 summary、positive matrix、negative matrix 和少量 integrity 样本。
- `/tmp` 总输出必须小于 1 MiB。
- 不写完整 before/after snapshot、RuleBook、transition、settlement 或 replay
  dump；失败时只写最小差异和 issue。
- 所有命令串行运行，不并发。
- focused、VG-S1、P7-S2、P7-S3 单项若超过 30 秒，立即停止查明意外依赖。
- P8-R1 runtime-only 若超过 60 秒或 catalog builder count 非零，立即停止。
- 报告记录每条命令实际耗时和峰值内存；无法测量时写 `not_measured`，不得估算。
- 不为满足限额删减本卡正负例；应删除重复 fixture/重复 oracle 和错误重依赖。

## 12. Gap、阻断与 deferred 口径

以下情况必须停止并报告 blocker：

- 正式 executor/scheduler 存在绕过 atomic commit 的 successor publication。
- lifecycle typed field 无法成为唯一权威，必须保留 HP 或 legacy flag fallback。
- 合法 damage defeat 或 wave/summon remove 无法形成同一完整 Mutation 批次。
- integrity checker 只能放进每条 reducer Mutation 或 UnitState 构造器才能工作。
- ScenarioStateBuilder 无法在返回前获得 setup 完成后的最终 state。
- integrity failure 仍会对外暴露 committed mutation、非 process-only gameplay
  event、正式 RNG 消费或 successor outcome。
- 完成 S2 必须读取 RuleBook/TBGD 或引入内容 ID 特判。
- 发现真实已准入 revive/re-entry 生产链，导致本卡转换表与当前事实冲突。
- typed authority 迁移需要长期双轨兼容，而不能原子迁移当前生产调用方。
- damage 或其他 producer 会把部分 lifecycle 子批次交给下游规则 consumer，且
  无法在本阶段内通过局部调整交接顺序闭合。

以下明确 deferred，不影响 S2 通过：

- 复活及复活后的 defeat record 保留策略。
- 初始 defeated 单位的 source-backed scenario 输入。
- status details/粗索引完整性。
- summon registry/UnitState 双向完整性迁入统一 gate。
- halo 父子状态完整性迁入统一 gate。
- wave/turn/queue/window 完整性。
- snapshot 文件载入边界的 full-domain 检查。
- 事件 root/child closure 所有权。
- validator registry、共享 RuleBook 和 catalog 缓存。
- 未运行的历史 catalog/full 验证，统一记为 `not_proven`，不能写成通过。
- 未运行历史验证中的 legacy lifecycle fixture 迁移，交由 VG-S3/VG-S8 分类后
  按触达域处理；它们不能反向要求生产保留 legacy flag。

deferred 不能用来豁免本卡定义的 typed lifecycle 唯一权威、atomic gate、replay
或场景最终初态检查。

## 13. 交付物与报告要求

执行线程提交：

```text
live_validation_reports/v8_vg_s2_committed_integrity_lifecycle_ready_for_review.md
```

报告至少包含：

- 实际修改文件和关键符号。
- typed lifecycle authority 迁移清单。
- lifecycle final-state、transition、atomic failure、replay 和 scenario 矩阵。
- touched scope 的实际 checked domain/unit/path 证据。
- 每个结构化谓词的实际值。
- legacy runtime authority 静态扫描结果；区分 runtime 引用、snapshot 输出键和
  TBGD/source 文本。
- 新验证器源码字节数和输出总字节数。
- 所有验证命令、退出状态、实际耗时和峰值内存。
- 所有未运行的 catalog/full 验证及原因。
- 未迁移历史 fixture 的结构化清单和后续分类建议；不得声称这些验证已通过。
- 当前剩余风险、deferred 和 `not_proven`。
- 状态只能写 `ready_for_review`。

执行线程不得：

- 把本卡 checklist 改为完成。
- 宣称 VG-S2 `done`、`accepted` 或整个 VG 已完成。
- 提交 Git。
- 开始 VG-S3。

## 14. 唯一执行清单（仅验收线程可勾）

- [x] `UnitState.lifecycle_status` 已成为唯一 runtime 生命周期权威，legacy flag 和 HP fallback 已退役。
- [x] UnitState、codec、spawn 和 Mutation 边界已结构化拒绝 legacy lifecycle flag/path 与非法 typed 值。
- [x] lifecycle final-state invariant 已覆盖 active、defeated、removed 的 HP 和记录关系，且没有把 removed 错当成死亡。
- [x] lifecycle transition invariant 已覆盖 spawn、defeat、remove、非法 revive/re-entry 和直接 unit deletion。
- [x] committed integrity issue/scope/result/error/gate 已机器可读、递归不可变、确定排序且不依赖 RuleBook/TBGD。
- [x] touched selector 只检查本批次触达领域和单位；无关 Mutation 不触发全局 lifecycle 扫描。
- [x] reducer 中间候选仍可暂时不完整，完整性检查只发生在完整批次 replay/commit 或场景 full 边界。
- [x] 部分 lifecycle 子批次不会暴露给其他规则 consumer，合法 damage defeat 的内部交接顺序已复核。
- [x] atomic commit 只在 reducer 结果与 candidate 一致且 integrity 通过后发布。
- [x] integrity failure 保持 before state、零 committed Mutation、diagnostic outcome、不可 successor，并携带结构化 evidence。
- [x] integrity failure 的 settlement/event/RNG 不会冒充已提交 gameplay 结果。
- [x] 完整批次 replay 对合法 lifecycle 成功、对非法 lifecycle fail-closed。
- [x] ScenarioStateBuilder 在 setup 前和最终返回前各运行一次 full lifecycle integrity，非法基础状态不会先参与开局规则。
- [x] unit codec/spawn payload 与 snapshot contract 已复用或消费同一 lifecycle authority，没有复制第二套 invariant。
- [x] target/action/status/halo/summon-runtime/snapshot/mutation-event 等生产 consumer/producer 已原子迁移到 typed lifecycle。
- [x] 聚焦验证未复制生产 invariant，全部结构化谓词和正负例均由真实生产 API 证明。
- [x] VG-S1、P7-S2、P7-S3 和 P8-R1 runtime-only 直接回归通过，且 catalog builder count 为零。
- [x] 未运行完整 TBGD lowering、阶段聚合、catalog/full 验证，未写大产物或修改无关 UI/P8 checklist。
- [x] 未为本阶段维护未运行的历史验证；遗留 legacy fixture 已列入 VG-S3/VG-S8 待分类清单。
- [x] `ready_for_review` 报告完整、诚实，并区分已证明、deferred 与 not-proven。
