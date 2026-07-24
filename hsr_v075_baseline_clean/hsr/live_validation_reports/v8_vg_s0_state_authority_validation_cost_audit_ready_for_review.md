# VG-S0 状态权威与验证成本审计报告

## 1. 审计状态

```text
stage=VG-S0
execution_submission_status=ready_for_review
acceptance_status=accepted
baseline_commit=a11637d
production_behavior_changed=false
heavy_validation_run_count=0
```

本轮只修改规划、执行卡和本报告。没有修改生产代码、旧验证器、P8 Checklist
或 UI；没有调用完整 TBGD lowering，也没有构建完整 RuleBook。

## 2. 审计范围

已审计：

- `UnitState`、`BattleState`、`Snapshot`、UnitState codec。
- Mutation reducer、selected graph 原子提交、snapshot/transition contract。
- 生命周期、状态、护盾、资源、时间线、队列、波次、战斗阶段。
- 召唤 runtime、halo 关系、事件 dispatcher、executor、scheduler。
- scenario loader、角色构筑装配进入 runtime 的边界。
- 单体 `TBGDLowering.build()`、当前共享 RuleBook 聚合器、现行 P8/R1 与代表性
  历史验证器。

明确未审计：

- 未逐项复核 177 个验证器的全部业务谓词。仓库目前没有机器可读 registry，
  因而“当前活跃”无法由代码自动判定；本报告完整统计文件集合，并逐项评估当前
  主线、高成本入口和代表性旧入口。
- 未测量完整 lowering、完整 RuleBook 或 catalog 的耗时与峰值。
- 未重新审计 TBGD 语义、角色卡、怪物卡、光锥机制和 R1 的目录完成度。
- 未扫描旧 v7 和 UI。

## 3. 总结结论

当前问题不是“验证脚本太多”一个原因，而是三层问题叠加：

1. **状态对象并非真正不可变。** frozen dataclass 内仍保存普通 `dict/list`，
   snapshot 也返回内部对象。外部消费者可以绕过 Mutation 直接改变正式状态。
2. **reducer 只证明 Mutation 自洽，不证明战斗状态合法。** 原子提交会比较
   candidate 与 reducer 结果，但不会检查生命周期、状态索引、召唤索引、波次
   或队列等领域不变量。
3. **目录构建和机制验证没有分离。** 单体 lowering 被大量验证器重复调用，
   历史聚合器还把旧阶段缺口写成当前通过条件。

因此正确顺序不是先删验证，而是：

```text
先隔离 committed state
  -> 再建立增量提交完整性
  -> 同时建立验证选择入口
  -> 然后逐领域清理重复权威和历史验证
```

## 4. 状态权威矩阵

### 4.1 矩阵

| 领域事实 | 当前表示 | 建议唯一权威 | 其他表示归类 | committed invariant | 当前非法状态能否进入 |
|---|---|---|---|---|---|
| committed state 容器 | `UnitState.flags/resources/shield_instances`、`BattleState.units/global_flags/queues`、`Snapshot.data` | 递归不可变的 `UnitState` / `BattleState` | `Snapshot` 只读投影 | 外部输入和 `to_json()` 返回值不能反向修改 state | **能，最高风险** |
| 单位生命值 | `UnitState.hp/max_hp` | `UnitState.hp/max_hp` | snapshot HP 为展示投影 | 数值有限且满足已定义范围 | **能** |
| 单位生命周期 | `flags.lifecycle_status`，缺失时按 HP 推断；另有 defeat/remove record | 显式类型化生命周期状态 | HP 是独立数值；records 是审计事实 | 正式状态不依赖 fallback；active/defeated/removed 与 HP、record、在场资格一致 | **能** |
| 状态实例 | `flags.status_details` | 完整状态实例集合 | `statuses` 是去重索引；snapshot modifier 视图是派生 | 状态索引等于实例中的有效 status ID；实例身份和来源唯一 | **能** |
| 状态 modifier 展示 | 每个 status detail 内 `modifiers`；另有未见生产写者的 `flags.modifiers` | status detail 内的 modifier | snapshot 顶层 `modifiers` 应重算或退役 | 不允许独立维护第二份 modifier 清单 | **能产生陈旧展示** |
| 护盾 | `shield_instances`；snapshot `shield` 汇总 | source-distinguished shield instances | `shield` 仅为求和视图 | 实例 schema、身份、剩余值、容量和顺序合法；汇总由实例计算 | reducer 路径较严，直接构造仍能 |
| 行动值 | 每个 `UnitState.action_value`；snapshot timeline map | 单位 action value | timeline map 为投影 | 值有限、非负；可行动单位与 timeline admission 一致 | **能** |
| 当前回合 | `active_turn`、`turn_owner_id`、`current_window`、`combat_phase` | typed turn/phase state，迁移前以 `active_turn` 为主记录 | owner/window 为查询投影或同事务字段 | owner 与 active turn actor 一致；窗口和 combat phase 使用合法组合 | **能** |
| 队列 | `BattleState.queues` 中的 JSON entry；`QueueEntry` 只是生产辅助类型 | 队列中的类型化 entry | snapshot 两份 queues 均为投影 | entry schema、身份、状态、排序依据和 owner 引用合法 | **能** |
| 战技点 | `skill_points/max_skill_points`；snapshot 多处复制 | `BattleState` 两个 typed scalar | snapshot copies 为投影 | `0 <= skill_points <= max_skill_points` | **能** |
| 单位能量等资源 | typed energy 字段；`resources` 还混有暴击、抗性和特殊资源 | typed 字段负责通用资源；命名资源由其领域定义负责 | snapshot 为投影；build ledger 不是 runtime 权威 | 每种资源各自定义范围，不能由通用 JSON 默认为合法 | **能** |
| 波次 | `BattleState.wave_index` 与 `global_flags.wave_runtime.current_wave_index` | typed `BattleState.wave_index` | wave runtime 保存定义、成员和历史，重复 index 必须匹配 | 两个 index 一致；当前成员、spawn 历史和生命周期闭合 | **能** |
| 战斗阶段 | `phase`、`combat_phase`、`current_window` | 三者是不同层级事实：战斗生命周期、调度阶段、输入窗口 | 不应把三者误当同义字段 | 每个字段取值合法，并满足已声明的跨字段组合 | **能** |
| 召唤关系 | `summon_runtime.entities`、`by_owner`、`by_unique_group`、`servants`、UnitState flags | 当前过渡期以 `entities` 为关系权威；长期应为 typed summon relation | owner/group/servant 为索引；UnitState 只保留 relation 引用或严格投影 | entity、单位、owner、summoner、team、kind、status 双向一致，索引可由 entity 重建 | reducer 能写坏，consumer 才拒绝 |
| halo | 父 status detail 的 `halo_relations`、member IDs、child projection status | 父状态上的 source-backed relation | 成员清单和 child status 是本次结算的物化投影 | relation 唯一；目标解析结果与 child projections 一致；不得伪造 child | 部分入口会 reconcile，但全局仍能写坏 |
| 事件闭包 | 输入事件、dispatcher `events`、callback emitted events、transition events | dispatcher 返回值应拥有一次完整 dispatch closure | 调用方只拼接 closure，不再手工追加 root | 同一语义 event ID 在一个 closure 中恰好一次，递归派生关系明确 | **当前已确认重复** |
| 构筑装配 | immutable `CharacterBuildAssemblyResult`；UnitState panel/stat pools/flags；fingerprint | 装配结果是 build-time 权威，进入战斗后 UnitState 是 runtime 权威 | fingerprint/source trace 是审计副本 | runtime 不重新解释构筑；审计副本不能改变战斗事实 | 正式入口较严，但最终 state 无统一完整性门 |

### 4.2 关键判断

#### 真正的重复权威

- `status_details` 与可独立写入的 `statuses`。
- `wave_index` 与 wave runtime 内的当前波次。
- summon entity 与多个可独立写入的 relation/index/unit flags。
- root event 与 dispatcher closure 的所有权。

#### 合法派生视图

- shield instances 到 shield 总量。
- UnitState action value 到 snapshot timeline map。
- BattleState skill points 到 snapshot resources。
- UnitState panel 到 snapshot base/derived stats。
- build result 到 runtime UnitState 的一次性装配结果。

这些视图不应被删除，但必须由权威值重算，不能成为第二个写入口。

#### 名称相近但不是同一事实

- `phase` 是高层战斗生命周期。
- `combat_phase` 是 scheduler 状态机。
- `current_window` 是当前输入/监听窗口。

它们需要一致性约束，但不能简单合并成一个字段。

## 5. 非法状态入口矩阵

| 入口 | 当前已有检查 | 缺失检查 | 失败是否原子 | 当前分类 |
|---|---|---|---|---|
| `UnitState(...)` | stat pool 类型、排序、面板重算 | nested JSON 冻结、通用标量范围、生命周期、status index | 构造异常时是；但大量非法值不异常 | 可直接构造非法 committed candidate |
| `BattleState(...)` | 无 `__post_init__` | nested JSON 冻结、skill point、wave、turn、queue、summon | 无统一失败 | 可直接构造非法 state |
| `Snapshot(...)` / `to_json()` | 无 | 递归冻结与返回值隔离 | 否 | 外部可反向修改 snapshot/state |
| UnitState codec | identity、有限数值、shield schema、资源值 | status/lifecycle/summon 等跨字段不变量 | 单次 decode 异常 | 比直接构造严格，但不是完整状态门 |
| `Mutation` | 输入 JSON 递归冻结、stable ID | 不知道领域语义 | 是 | 正确的单变更载体 |
| `MutationReducer.apply_all_result()` | path、op、before/after、类型、同路径链、整批冲突回滚 | batch 完成后的领域不变量 | reducer 冲突时是 | 只能生成 candidate，不足以证明可发布 |
| `finalize_selected_execution_graph()` | 节点完整、reducer 成功、candidate 与 mutation 一致 | committed-state integrity、事件唯一性 | 当前检查失败时是 | 可提交语义非法但 mutation 自洽的状态 |
| Scenario loader | schema、身份镜像、构筑模式、资源初值 | runtime 全领域关系 | 输入异常时是 | 适合输入校验，不应承担 runtime 完整性 |
| Scenario builder | formal build admission、召唤空 runtime、provider/startup/setup、route unit | 最终 state 全局完整性 | 多处 raise，但无统一 issue | 可能返回内部关系不一致的初始 state |
| lifecycle/status/shield/queue/timeline/wave producer | 各自的正常计划路径较严 | 通用 reducer 可绕过；跨系统 batch 关系没有统一门 | 各系统不一致 | producer 正确不等于 state 不可写坏 |
| summon/halo consumer | 读取时严格 validate/reconcile | 非法 state 在到达 consumer 前已存在 | consumer 多数 state unchanged | 发现太晚，常被记成 gameplay blocked |
| dispatcher/executor/scheduler | listener admission、phase、callback 执行 | root/emitted/recursive event ownership | 无统一事件账本门 | 已有正式重复事件路径 |
| replay | mutation 重放与 snapshot 相等 | 重放结果的领域合法性 | mutation 冲突时是 | “一致地重放非法状态”仍可通过 |
| snapshot completeness | 必需路径存在 | 值类型和跨字段语义 | 只返回报告 | 字段齐全的矛盾 snapshot 可通过 |

### 5.1 轻量实证

本轮使用纯内存对象，没有读取 TBGD：

```text
nested_alias_mutates_frozen_unit=true
snapshot_return_aliases_snapshot=true
snapshot_aliases_battle_global_flags=true
snapshot_unit_nested_aliases_state=true
status_index_detail_mismatch_constructed=true
hp_zero_active_reducer_ok=true
hp_zero_active_commit_status=committed
hp_zero_lifecycle=active
malformed_queue_reducer_ok=true
skill_points_over_cap_reducer_ok=true
negative_wave_index_reducer_ok=true
wave_runtime_divergence_reducer_ok=true
```

这些探针证明的是边界能力，不是说正常生产 producer 每次都会生成上述状态。

### 5.2 已确认的事件重复

`EventDispatchSystem` 的 action-window、无 listener 和普通 listener 路径均把输入
event 放入 `EventDispatchResult.events`。但：

- `core/executor.py:318` 又拼接 `prepare_event` 和 `prepare_result.events`。
- `systems/scheduler.py:1367-1378` 先加入 lifecycle event，再加入包含同一 root
  的 dispatch events。
- callback 递归路径先加入 callback emitted event，再加入以同一 event 派生的
  child dispatch closure，事件身份所有权同样不清晰。

这不是“验证没覆盖”的抽象风险，而是当前代码的明确契约冲突。

## 6. 提交边界分析

### 6.1 reducer 应保持的职责

reducer 适合继续负责：

- Mutation 结构和 path 类型。
- before/after presence 与 typed equality。
- 同一 batch 的顺序和冲突。
- 失败时整批 state unchanged。

不应把每个领域的全局规则塞进单条 `_write_path()`，因为一个合法事务可能先更新
权威记录，再更新派生索引，中间 candidate 暂时不一致。

### 6.2 committed state 完整性应放置的位置

建议建立独立完整性协议：

```text
Mutation paths
  -> touched domains
  -> reducer builds private candidate
  -> only touched-domain integrity checks
  -> atomic publish or before-state rollback
```

完整扫描仅用于：

- scenario 构建结束；
- snapshot/replay load；
- debug 命令；
- 里程碑。

普通动作不能在每次提交后重扫完整 RuleBook、全部来源目录或所有未触达领域。

### 6.3 失败语义

内部完整性失败必须是机器可读 diagnostic/internal invalid：

```text
after_state=before_state
committed_mutations=()
successor_eligible=false
integrity_issue.domain=<domain>
integrity_issue.code=<stable code>
integrity_issue.paths=<affected paths>
```

它不能伪装成“角色当前不能行动”一类游戏规则 blocked。

## 7. 验证器库存与成本

### 7.1 完整静态库存

```text
validator_file_count=177
validator_total_bytes=5806468
validator_total_mib=5.54
files_mentioning_TBGDLowering=149
files_with_direct_TBGDLowering_build=122
files_with_tbgd_root_cli=157
files_with_output_dir_cli=172
files_writing_full_canonical_ir=23
files_writing_coverage_artifact=38
files_writing_fidelity_artifact=23
```

`TBGDLowering.build()` 当前会在一次调用中构建光锥、角色、怪物、动作、全能力
文件、状态、目标、队列、召唤、波次和装备图。即使验证只关心一个局部契约，
直接调用也会承担完整目录成本。

### 7.2 当前最大和关键验证器建议分类

静态体积不是运行成本本身，但大文件通常同时包含大量 fixture、oracle、负例和
聚合编排。以下分类用于后续 registry，不表示现在删除文件。

| 验证器 | 字节 | 当前特点 | 建议分类 | 处置 |
|---|---:|---|---|---|
| `validate_p8_s8_light_cone_remaining_gameplay_closure.py` | 354223 | 完整光锥机制与 startup，多模式，完整 lowering | `catalog_audit/full` | 保留目录证明；抽出可复用 direct 契约 |
| `validate_p8_s7_light_cone_status_condition_listener_closure.py` | 212752 | S7 来源与 runtime 混合 | `catalog_audit` | 不作每阶段回归 |
| `validate_p4_s0_combatant_source_inventory.py` | 135611 | 全角色/怪物来源盘点 | `historical_evidence/catalog_audit` | 仅来源变化触发 |
| `validate_memory_owned_combatant_build_closure.py` | 133596 | 记忆角色目录和构筑闭环 | `catalog_audit` | 记忆目录变化触发 |
| `validate_p8_s2_character_build_base_panel.py` | 121263 | source-only 与 fixture 契约混合 | `direct + catalog` | 保留模式拆分，registry 分开登记 |
| `validate_p1_4_status_system.py` | 102778 | 旧 P1 状态聚合 | `historical_evidence/superseded` | 不作现行默认门 |
| `validate_p8_r1_summon_runtime_halo_lifecycle.py` | 94645 | runtime-only 与 source-catalog-only 已拆 | `direct + catalog` | 作为正向模式保留 |
| `validate_p1_9_phase1_aggregate.py` | 83456 | 第一阶段总聚合 | `historical_evidence` | 里程碑历史证据，不重跑 |
| `validate_p7_s0_kernel_trust_baseline.py` | 81061 | P7 修复前问题基线 | `historical_evidence` | 不用于判断当前树 |
| `validate_p8_s1_equipment_type_contract.py` | 66677 | 小型 RuleBook fixture，装备结构契约 | `active_contract/direct` | 保留 |
| `validate_p3_summon_assistant_servant_complete.py` | 65103 | 旧 P3 聚合并保留历史 gap | `historical_evidence` | 从当前共享门移出 |
| `validate_p8_s5_light_cone_static_contributions.py` | 64795 | 目录来源与装配贡献混合 | `direct + catalog` | 后续拆选择入口，不重写语义 |
| `validate_v0_213.py` | 60910 | 旧阶段完整 IR/coverage/fidelity 路径 | `historical_evidence` | 禁止默认执行 |
| `validate_p1_6_target_system.py` | 60556 | 旧 P1 目标聚合 | `historical_evidence` | 由 P7/R1 窄契约替代默认门 |
| `validate_p6_s2_s3_unit_spawn_birth_plan.py` | 60247 | 当前出生/波次契约但依赖完整 lowering | `active_contract/catalog` | 共享一次 catalog 构建 |
| `validate_p8_s6_light_cone_dynamic_startup.py` | 60119 | 光锥 graph 与 startup 目录 | `catalog_audit` | 装备 graph 变化触发 |
| `validate_p8_s4_light_cone_instance_assembly.py` | 59893 | fixture 装配和目录引用 | `active_contract/direct` | 保留窄模式 |
| `validate_p4_s1_data_card_rulebook_contract.py` | 56980 | P4 数据卡目录底座 | `historical_evidence/catalog` | 数据卡 schema 变化才触发 |
| `validate_p2_s10_status_callback_coverage.py` | 56769 | callback 来源覆盖与 runtime | `catalog_audit` | 事件/status lowering 变化触发 |
| `validate_p3_s0_summon_source_inventory.py` | 54472 | P3 来源盘点 | `historical_evidence/catalog` | 召唤来源 schema 变化触发 |

### 7.3 两个特殊入口

#### `validate_v0_209.py`

该入口同时执行 discovery、完整 lowering、coverage、fidelity、RuleBook、scenario
和 damage transition，并默认写出完整 Canonical IR、coverage 和 fidelity。它还
依赖固定 fixture unit ID。

建议分类：

```text
historical_evidence
current_default_gate=false
reason=full_artifact_writer_and_fixed_historical_fixture
```

其仍有价值的伤害公式谓词应由 P7 当前 direct 验证承接，不能继续运行原脚本来
证明局部伤害改动。

#### `validate_p7_current_tree_shared_regressions.py`

优点：

- 一次构建 RuleBook 后复用多个 runner。
- 串行、首错停止、不写完整 IR。

不能作为当前统一入口的原因：

- 明确要求 P2 仅保留特定 action-delay gap。
- 明确要求 P3 继续存在 servant-action gap。
- 旧缺口若被后续实现关闭，聚合器反而失败。

建议保留“共享构建和串行执行”思路，废弃固定旧 gap 语义。

### 7.4 实际轻量测量

以下是同一工作区本轮单次观察，不是稳定 benchmark：

| 验证 | 模式 | elapsed | max RSS | 结果 |
|---|---|---:|---:|---|
| P7-S2 mutation reducer | direct，无 TBGD | 0.50 s | 49,376 KiB | 14/14 |
| P7-S3 atomic commit | direct，小 fixture | 0.25 s | 39,936 KiB | 9/9 |
| P8-R1 | `--runtime-only` | 1.07 s | 48,792 KiB | ok |

这些结果证明复杂的 reducer、atomic、summon/halo runtime 契约可以在约 50 MiB
量级内验证，不需要完整目录。

### 7.5 已有重验证证据

本轮没有重跑，但已有当前报告记录：

- R1 报告中五个入口在 1.5 GiB 限制下均在完整 CanonicalIR lowering 阶段
  `MemoryError`。
- P8-S8 验收记录完整 S8 聚合在 4 GiB 上限内通过，但没有记录实际峰值和耗时。
- 旧 P3-S8 在 4 GiB 和 6 GiB 上限下均在完整 lowering 位置 `MemoryError`，
  且旧基线同样复现。

因此当前主要资源根因已定位为单体目录构建和重复构建，不是 direct runtime
fixture 本身。

未实测项统一标记：

```text
complete_lowering_elapsed=not_measured
complete_lowering_peak_rss=not_measured
complete_rulebook_elapsed=not_measured
complete_rulebook_peak_rss=not_measured
catalog_io_bytes=not_measured
```

## 8. 已确认问题、非问题和待后续决定

### 8.1 已确认问题

1. nested state 和 snapshot 存在外部别名写入。
2. mutation 自洽的非法领域状态可被 atomic commit 发布。
3. status index/detail、wave index/runtime、summon registry/index 均有多写入口。
4. dispatcher event ownership不一致，已有重复 root event。
5. snapshot completeness 只检查路径存在，不能证明语义。
6. 122 个验证文件直接构建单体 lowering。
7. 当前共享聚合器把历史 gap 写成通过条件。
8. `validate_v0_209` 一类旧入口默认写完整大产物。

### 8.2 当前不是问题

- shield 总量与 shield instances 同时出现在 snapshot：前者是合法派生汇总。
- `phase`、`combat_phase`、`current_window` 并存：它们不是同一概念，问题是
  缺少 typed relation 和组合不变量。
- CharacterBuildAssemblyResult 与 UnitState 同时存在：前者是 build-time
  权威和审计证据，后者是 runtime 权威，不应在战斗中重算构筑。
- halo 缺失投影可由同一事务 reconcile：事务内临时不一致合法；发布后的
  committed state 不应继续不一致。

### 8.3 尚未决定

- 生命周期是否允许未来 revive，以及 defeated record 的永久保留规则。
- summon relation 最终进入 `BattleState` typed field，还是保留在一个独立
  runtime domain object。
- status 粗索引是删除、提交时重算，还是保留只读缓存。
- event dispatch closure 是否保留 root event。当前兼容性最好的方向是保留，
  但递归 callback 的 emitted/redispatched 身份需要单独执行卡确认。

这些问题不能由执行线程自行假设。

## 9. 首批三个实施优先级

### 9.1 VG-S1 递归不可变 state 与 detached snapshot

**根因**

dataclass 的 `frozen=True` 只阻止字段重绑定，不能冻结内部容器；snapshot 又浅复制
并直接返回内部 `data`。

**为什么最先做**

这是所有领域共享的绕过入口。只要外部还能直接改 state，后续完整性 validator、
replay 和 UI 审计都没有可信输入。

**精确触达**

- `core/model.py`
  - `UnitState.__post_init__`
  - 新增 `BattleState.__post_init__`
  - `BattleState.snapshot`
  - `Snapshot`
- `core/unit_state_codec.py`
- 复用 `immutable_json.freeze_json/thaw_json`

**本卡不做**

- 不定义 HP/lifecycle、status、summon、wave 的跨字段语义。
- 不修改 reducer 或 dispatcher。
- 不迁移旧验证器。

**必须证明**

- 修改任何构造输入容器不影响 state。
- 直接修改 state nested value 抛错。
- 修改 `Snapshot.to_json()` 返回值不影响 Snapshot 或 BattleState。
- codec、Mutation、reducer 和 replay 的 JSON round-trip 保持确定。
- 无 TBGD、无 RuleBook、无完整 artifact。

**建议执行配置**

```text
model=GPT-5.6 Sol
reasoning=max
mode=normal
```

### 9.2 VG-S2 committed integrity 协议与生命周期单域试点

**根因**

atomic commit 只检查 mutation 和 candidate 一致，无法区分“合法 candidate”和
“一致地构造出的非法 candidate”。

**为什么第二**

需要先有真正不可变的 state，完整性结论才稳定。生命周期是调用范围广、事实关系
清楚且已经有明确反例的最小试点。

**精确触达**

- 新增窄 `core/state_integrity.py`，定义 issue/result/domain check protocol。
- `core/atomic_commit.py`
  - 根据 mutation path 选择 touched domain。
  - integrity failure 不发布 candidate。
- `scenarios/build_state.py`
  - initial state 返回前运行一次完整已注册 domain check。
- 必要时最小调整 `systems/unit_lifecycle.py` 和正式 state 构造点。

**本卡只覆盖**

- integrity result 和稳定错误码。
- lifecycle 显式状态与 HP/在场资格的当前可证明关系。
- 失败时 before state、零 committed mutation、diagnostic outcome。

**本卡不做**

- 不同时收 status、summon、halo、wave、queue 和 event。
- 不在 reducer 每条 mutation 后全局扫描。
- 不扫描 RuleBook 或 TBGD。
- 不自行设计 revive。

**必须证明**

- HP 归零但 lifecycle 仍 active 的完整 batch 被拒绝。
- 合法伤害致死 batch 可提交。
- 合法事务的中间 candidate 可暂时不一致。
- 非 lifecycle mutation 不触发无关 domain scan。
- scenario 初始 state 不满足 lifecycle invariant 时 fail-closed。

**建议执行配置**

```text
model=GPT-5.6 Sol
reasoning=max
mode=normal
```

### 9.3 VG-S3 最小 validator registry 与选择入口

**根因**

当前没有机器可读信息说明一个验证器是 direct、catalog、historical 还是
superseded，执行线程只能靠文件名和旧计划猜测，最终倾向于全跑。

**为什么进入首批**

它不依赖后续所有领域回正，但可以立刻限制 S1/S2 和 P8 后续阶段的验证集合，
降低每轮 token、IO 和误修旧验证的成本。

**精确触达**

- 新增机器可读 registry 模块或静态数据文件。
- 新增统一的 dry-run/selection CLI。
- 首批只登记：
  - VG-S1/S2 direct；
  - P7-S2/S3/S15；
  - P8-S1/S2 分模式；
  - P8-R1 runtime/catalog 分模式；
  - P8-S8 catalog；
  - P7 shared aggregate、P1/P2/P3 aggregate、`validate_v0_209` 的历史分类。
- 更新 `docs/AGENT_WORKFLOW_AND_VALIDATION.md` 的命令入口。

**本卡不做**

- 不重写 177 个验证器。
- 不实现完整 lowering 缓存。
- 不根据 Git diff 自动猜测所有依赖。
- 不运行 registry 中的 catalog/full 项来验证 registry。

**必须证明**

- 每个登记项有唯一 ID、分类、domain、资源等级、TBGD/RuleBook 需求和触发条件。
- `--dry-run` 只输出选择，不执行。
- direct 选择不会包含 catalog/full/historical。
- historical gap 不能作为 current contract predicate。
- 未登记或歧义选择 fail-closed。

**建议执行配置**

```text
model=GPT-5.6 Terra
reasoning=xhigh
mode=normal
```

## 10. 首批之后的顺序

首批三项通过后，下一张卡应优先处理事件 closure 所有权，因为当前已有确定重复。
随后才按单域推进：

```text
status instance/index
  -> summon relation/index
  -> halo projection
  -> wave/turn/queue
  -> shared catalog build
  -> historical validator migration
```

这只是依赖建议，不是可打勾的第二套执行清单。每项仍需单独制卡。

## 11. 结构化结论

```text
state_authority_matrix_complete=true
committed_state_integrity_gap_located=true
external_alias_mutation_boundary_classified=true
domain_invariants_not_global_scan=true
validator_inventory_complete=true
full_lowering_call_sites_counted=true
shared_rulebook_prototype_assessed=true
stale_validation_contracts_located=true
dynamic_measurements_are_observed_only=true
first_implementation_batch_bounded=true
production_behavior_changed=false
heavy_validation_run_count=0
```

## 12. 验收边界

VG-S0 可以通过的含义：

- 已知道首批代码应从哪里开始。
- 已知道哪些问题属于状态权威、事务提交、事件账本或验证治理。
- 已有足够证据编写 VG-S1 执行卡。

VG-S0 不代表：

- 当前 committed state 已安全。
- 事件重复已修复。
- R1 或 P8 catalog 已重验。
- 177 个历史验证器已迁移。
- 完整 lowering 的峰值已经解决。
