# VG-S1 Committed State 递归不可变与快照隔离执行卡

## 执行配置

- 代码基线：`a11637d`。
- 前置阶段：`VG-S0` 已完成状态权威与验证成本审计。
- 推荐模型：GPT-5.6 Sol。
- 推荐推理等级：`max`。
- 推荐模式：普通模式，单卡执行。
- 执行归属：新的代码执行线程。
- 最终状态上限：`ready_for_review`。
- 禁止执行线程修改本卡 checklist、提交 Git 或开始 `VG-S2`。
- 工作区现有无关 UI 草稿和 VG-S0 文档不属于本卡，禁止修改、删除或提交。

## 1. 背景与已确认事实

`UnitState`、`BattleState` 和 `Snapshot` 当前使用 frozen dataclass，但 frozen
dataclass 只禁止字段重绑定，不会冻结字段内部的 `dict`、`list` 或字典内更深层
容器。

VG-S0 已用纯内存探针确认：

- 修改传入 `UnitState.flags` 的原始嵌套容器，可以反向修改已经创建的
  `UnitState`。
- `Snapshot.to_json()` 直接返回内部 `data`；修改返回值可以修改 Snapshot，
  部分路径还会继续别名到 BattleState。
- `BattleState.units`、`global_flags` 和 `queues` 在构造时没有统一的复制、类型
  校验和递归冻结边界。
- `Mutation` 已经使用 `freeze_json()` / `thaw_json()` 建立不可变输入和可变
  JSON 输出，这套行为可以作为参考。
- 生产系统没有发现对 committed state 这些容器的直接原地写入。当前生产更新
  基本采用“复制容器 -> 修改副本 -> `dataclasses.replace`”或通过
  `MutationReducer` 生成新状态。

因此本阶段不是一次跨系统重构。它只关闭所有后续状态完整性工作的共同绕过入口：

```text
外部输入或序列化返回值
  -> 不能再通过共享容器引用修改 committed state
  -> 所有正式状态更新只能生成新对象
```

本阶段不判断一个状态在游戏规则上是否合理。HP 与生命周期、状态索引、召唤关系、
波次、光环和事件账本等跨字段语义由后续独立阶段处理。

## 2. 阶段完成后的具体结果

### 2.1 UnitState 构造边界

完成后，每次创建或 `replace()` 一个 `UnitState`，都必须在模型边界完成以下
规范化：

- `statuses` 保存为不可变 tuple，并拒绝非字符串成员。
- `shield_instances` 保存为不可变 tuple；每个实例及其嵌套 JSON 容器递归
  不可变，并与调用方传入容器脱离别名。
- `flags` 保存为 dict-compatible 的递归不可变 JSON object；现有
  `.get()`、`.items()`、迭代、`dict(...)` 以及
  `isinstance(nested_value, dict)` 读法继续可用。
- `resources` 保存为 dict-compatible 的不可变映射；key 必须是字符串，value
  必须是有限数值，不能接受 `bool`。
- `stat_pools` 继续保持当前 tuple、唯一属性和确定排序契约。
- 构造后修改任何原始 `dict`、`list` 或其更深层成员，都不能改变 UnitState、
  snapshot 或 fingerprint 类派生结果。
- 对已创建 UnitState 的任意嵌套容器执行赋值、`append`、`update`、`pop`、
  `setdefault` 等写操作必须直接失败，不能静默生成局部可写分支。

这里收紧的是表示合法性和所有权，不新增 HP、能量、韧性、状态、护盾或召唤物的
游戏语义。

### 2.2 BattleState 构造边界

完成后，每次创建或 `replace()` 一个 `BattleState`，都必须满足：

- `units` 与调用方传入字典脱离别名，键必须是非空字符串，值必须是
  `UnitState`，映射本身不可变。
- `global_flags` 是 dict-compatible 的递归不可变 JSON object；未知 Python
  对象、非字符串键和非有限浮点数在构造边界被拒绝。
- `queues` 与传入映射及队列项脱离别名：
  - queue name 必须是非空字符串；
  - 每个 queue 保存为不可变 tuple；
  - 每个 queue item 是递归不可变 JSON value；
  - 不允许调用方通过保留原始 item 引用改变队列内容。
- 修改构造时传入的 `units`、`global_flags`、`queues` 或任意嵌套成员，不能改变
  BattleState。
- 对 committed BattleState 的映射和队列直接原地写入必须失败。
- `dataclasses.replace()` 仍是合法更新入口；传入的新容器必须重新经过同一套
  复制、校验和冻结，不允许 replace 绕过构造边界。

`freeze_json()` 只适用于 JSON tree，不能用它直接冻结包含 `UnitState` 的
`units` 映射。实现必须为非 JSON 对象映射提供独立、只读且与输入脱离别名的
表示，或采用等价的模型内规范化方案。

### 2.3 Snapshot 隔离边界

完成后：

- `Snapshot` 创建时递归冻结并脱离输入 `data`。
- Snapshot 内部只能保存有限、字符串键的 JSON tree。
- `Snapshot.to_json()` 每次返回新的普通可变 `dict/list` JSON tree。
- 修改任意一次 `to_json()` 的返回值，不影响 Snapshot、原 BattleState 或下一
  次 `to_json()` 的结果。
- `BattleState.snapshot()` 对 `global_flags`、单位 flags、状态详情、护盾、queue
  item、targeting、settlement 等所有嵌套数据都满足上述隔离。
- snapshot 内容和排序语义保持确定；不能因为换成不可变容器而改变现有 JSON
  结构。

Snapshot 是只读证据对象，但 `to_json()` 是外部交换边界，因此返回普通 JSON
副本，而不是把内部冻结容器泄露给调用方。

### 2.4 Codec 与 reducer 闭环

完成后：

- `unit_state_to_payload()` 返回完全脱离 UnitState 的普通 JSON tree。
- `unit_state_from_payload()` 接受普通 JSON，完成现有字段/schema 校验后创建
  递归不可变 UnitState。
- `to_payload -> from_payload -> to_payload` 保持确定性。
- reducer 的 `set`、`delete` 和 `spawn` 仍通过复制和 replace 产生新状态。
- reducer 成功结果中的 UnitState、BattleState 和全部嵌套容器均不可变。
- reducer 失败仍返回原 before state、零 applied mutation，且不能在失败前
  污染 before state。
- mutation replay 的 snapshot 比较保持确定。

本阶段不把 reducer 扩展成领域状态校验器，也不修改 atomic commit 的正式失败
语义。

### 2.5 兼容边界

本阶段保留的内部读接口：

- mapping 的 `.get()`、key 查询、迭代、`.items()`、`.values()` 和 `dict(...)`。
- queue 的迭代、索引、长度和 `list(...)`。
- JSON nested object 继续满足当前生产 consumer 的 dict-style 读取。

本阶段明确不兼容：

- 对 committed state 内部容器原地赋值。
- 对 committed queue、flags、resources、shield instance 直接调用可变方法。
- 依赖 `Snapshot.to_json()` 返回内部同一对象。

这些写法本来就在绕过 Mutation/replace 状态转移边界，禁止为它们新增兼容层或
临时可写代理。

## 3. 本阶段只做

- 收紧 `UnitState`、`BattleState`、`Snapshot` 的构造和序列化所有权边界。
- 复用并在必要时小幅扩充现有 immutable JSON 工具。
- 为包含非 JSON 对象的 state mapping 建立窄不可变表示。
- 原子迁移本卡直接触达的 codec/reducer 读写类型。
- 新增一个不读取 TBGD、不构建 RuleBook 的聚焦验证器。
- 只运行本卡列出的 direct 回归。
- 新增一份 `ready_for_review` 报告。

## 4. 本阶段不做

- 不新增 HP/lifecycle、status、summon、halo、wave、phase、window、queue 内容
  等跨字段完整性规则。
- 不修改 `finalize_selected_execution_graph()` 的成功或失败分类。
- 不建立 state-integrity registry、domain selector 或全局扫描器。
- 不修复 dispatcher root event 重复；该问题有后续独立执行卡。
- 不修改角色卡、怪物卡、光锥、遗器、构筑装配、RuleBook 或 lowering。
- 不把 `ActionCommand.metadata`、`GameEvent.payload`、settlement、transition
  evidence 等所有 frozen dataclass 一次性扩成同一轮迁移。
- 不重写或删除历史验证器。
- 不修改 P8 checklist、VG-S0 报告或无关 UI。
- 不新增依赖。
- 不运行完整 TBGD lowering、完整 RuleBook、P1-P8 聚合或 catalog 验证。

## 5. 拟修改文件与符号边界

主要生产修改：

- `simulator_v8_clean_core/core/model.py`
  - `UnitState.__post_init__`
  - 新增 `BattleState.__post_init__`
  - `BattleState.snapshot`
  - `Snapshot.__post_init__`
  - `Snapshot.to_json`
- `simulator_v8_clean_core/core/unit_state_codec.py`
  - `unit_state_to_payload`
  - `unit_state_from_payload`
  - 必要的 canonical value 校验
- `simulator_v8_clean_core/core/reducer.py`
  - 仅在不可变容器类型需要时调整复制、写入和类型注解；
  - 不改变 mutation path、op、before/after 或领域语义。
- `simulator_v8_clean_core/immutable_json.py` 或一个新的窄 core helper
  - 仅增加本卡确实需要的不可变映射能力；
  - 禁止把 `UnitState` 伪装成 JSON value。
- `simulator_v8_clean_core/core/immutable_json.py`
  - 仅在新增 helper 需要统一导出时修改。

聚焦验证和报告：

- 新增
  `simulator_v8_clean_core/tools/validate_vg_s1_committed_state_immutability.py`
- 新增
  `live_validation_reports/v8_vg_s1_committed_state_immutability_ready_for_review.md`

若实现发现必须修改 `systems/**`、`scenarios/**`、`rules/**`、`tbgd/**` 或
`equipment/**` 才能完成，应先判断：

- 只是直接调用方仍在原地写 committed state：允许最小迁移为 copy + replace，
  并在报告列出；
- 涉及新的领域语义、兼容策略或职责变化：停止实施，交回规划线程修订执行卡。

## 6. 类型与构造契约

| 边界 | 输入允许 | 内部保存 | 输出 |
|---|---|---|---|
| Unit flags | 普通 JSON mapping | dict-compatible 递归不可变 JSON object | codec/snapshot 返回脱离副本 |
| Unit resources | 字符串到有限数值 mapping | 不可变 mapping | 普通 JSON object |
| Shield instances | list/tuple of JSON objects | tuple of recursive immutable objects | 普通 JSON array |
| Battle units | mapping of ID to UnitState | 不可变、dict-compatible state mapping | snapshot 普通 JSON object |
| Battle global flags | 普通 JSON mapping | dict-compatible 递归不可变 JSON object | snapshot 脱离副本 |
| Battle queues | mapping of name to list/tuple | 不可变 mapping of immutable tuples | snapshot 普通 JSON arrays |
| Snapshot data | 普通或冻结 JSON object | 递归不可变 JSON object | 每次新建普通 JSON tree |

实现不能仅做浅 `dict(...)` / `tuple(...)`：

- 浅复制无法隔离更深层容器。
- tuple 内仍可能保存可变 dict。
- frozen dataclass 内保存普通 dict 仍可原地修改。

## 7. 必须覆盖的正例与负例

### 7.1 UnitState

聚焦验证至少覆盖：

1. 传入含两层以上嵌套结构的 flags，构造后修改原结构，UnitState 不变。
2. 传入 shield list 和 shield dict，构造后修改两者，UnitState 不变。
3. 传入 resources dict，构造后修改原 dict，UnitState 不变。
4. 对 unit flags 的顶层和嵌套值执行赋值、append、update、pop，均抛出
   `TypeError` 或等价明确异常。
5. 对 shield instance 顶层和嵌套值执行写入，均失败。
6. `replace(unit, flags=mutable_input)` 后再次修改 input，不影响新旧任一 unit。
7. 非字符串 JSON key、未知对象、NaN、Infinity、`resources` 中的 bool 或非有限
   数值在构造边界被拒绝。

### 7.2 BattleState

聚焦验证至少覆盖：

1. 修改构造输入 units mapping，不影响 state。
2. 修改构造输入 global flags 的顶层和深层容器，不影响 state。
3. 修改构造输入 queue mapping、queue list 和 queue item，不影响 state。
4. 对 state.units、state.global_flags、state.queues、queue tuple 和 queue item
   直接写入均失败。
5. units 的空 key、非字符串 key、非 UnitState value 被拒绝。
6. queue 的空 name、非字符串 name、非 JSON item 被拒绝。
7. `replace(state, global_flags=...)`、`replace(state, queues=...)` 和
   `replace(state, units=...)` 均重新规范化。

### 7.3 Snapshot

聚焦验证至少覆盖：

1. 修改传入 Snapshot 的原始 data，不影响 Snapshot。
2. Snapshot 内部 data 的顶层和深层写入均失败。
3. 修改第一次 `to_json()` 返回值，不影响第二次返回值。
4. 修改 snapshot 中 unit flags、shield、queue、summon runtime、status details
   等深层路径，不影响 BattleState。
5. `json.dumps(snapshot.to_json(), allow_nan=False)` 成功。
6. 两个未被修改的等价 state 产生 typed-equal snapshot。

### 7.4 Codec、reducer 与 replay

聚焦验证至少覆盖：

1. 修改 `unit_state_to_payload()` 返回值不影响 UnitState。
2. codec round-trip 后 snapshot 相等，round-trip 后对象仍不可变。
3. reducer 对 unit field、nested flag、resource、global flag 和 queue 的 set/delete
   结果不可变。
4. reducer spawn 的新 UnitState 和 units mapping 不可变。
5. reducer 冲突前后 before state 相等，外部输入也未被污染。
6. replay 使用 detached expected snapshot 时仍成功；篡改 expected 副本只导致
   replay mismatch，不会改变 state。

## 8. 目标与验收证据映射

| 目标 | 允许通过 | 必须判阻断 | 证据 |
|---|---|---|---|
| UnitState 无别名 | 所有可变输入均复制并递归冻结 | 仍可通过原始 flags/shield/resources 修改 unit | unit alias matrix |
| BattleState 无别名 | units/global flags/queues 均复制、校验、不可变 | 任一 mapping 或 queue item 可原地改 committed state | battle alias matrix |
| Snapshot 隔离 | 内部冻结，`to_json()` 每次给新副本 | 返回内部 data 或嵌套值仍别名到 state | snapshot isolation matrix |
| 读接口可用 | 当前生产 dict-style/tuple-style 读取继续工作 | 为冻结而迫使 systems 理解新业务对象 | consumer compatibility rows |
| Codec 闭环 | payload 是普通 detached JSON，decode 后冻结 | codec 输出共享 state 内部引用 | codec round-trip rows |
| Reducer 闭环 | set/delete/spawn 结果冻结，失败原子 | reducer 结果可变或失败污染 before | reducer matrix |
| 范围受控 | 不新增任何领域状态语义 | 顺手实现 lifecycle/status/summon 等规则 | diff/code review |
| 成本受控 | focused/direct 验证无需 TBGD/完整 RuleBook | 验证器调用 lowering 或输出大产物 | command log/report |

## 9. 结构化验收谓词

聚焦验证 summary 必须明确给出且全部为 true：

```text
unit_constructor_detaches_nested_inputs
unit_nested_state_recursively_immutable
unit_replace_reapplies_normalization
battle_constructor_detaches_nested_inputs
battle_units_mapping_immutable
battle_global_flags_recursively_immutable
battle_queues_recursively_immutable
battle_replace_reapplies_normalization
snapshot_constructor_detaches_input
snapshot_internal_data_recursively_immutable
snapshot_to_json_returns_detached_plain_json
snapshot_to_json_calls_are_independent
snapshot_mutation_cannot_reach_battle_state
unit_codec_output_is_detached_plain_json
unit_codec_round_trip_is_deterministic
reducer_set_result_is_immutable
reducer_delete_result_is_immutable
reducer_spawn_result_is_immutable
reducer_failure_preserves_before_state
replay_snapshot_remains_deterministic
invalid_json_value_rejected
non_string_json_key_rejected
non_finite_json_number_rejected
production_behavior_semantics_changed=false
tbgd_read_count=0
full_rulebook_build_count=0
```

谓词不能只通过检查类型名成立，必须实际执行外部别名修改和内部写入负例。

## 10. 最小验证与运行顺序

所有命令串行执行。先通过新聚焦验证，再运行直接回归。

### 10.1 必跑最小集

```bash
PYTHONPYCACHEPREFIX=/tmp/hsr_v8_vg_s1_pycache \
python3 -m compileall -q simulator_v8_clean_core
```

目的：检查本卡修改后的 Python 语法和导入闭环。不得把 pycache 写入仓库。

```bash
python3 -B -m simulator_v8_clean_core.tools.validate_vg_s1_committed_state_immutability \
  --output-dir /tmp/hsr_v8_vg_s1_committed_state_immutability
```

目的：证明本卡全部 alias、immutability、codec、reducer 和 snapshot 谓词。

```bash
git diff --check
```

目的：检查 patch 格式。该命令不代表行为验收。

### 10.2 直接回归集

```bash
python3 -B -m simulator_v8_clean_core.tools.validate_p7_s2_mutation_reducer_contract \
  --output-dir /tmp/hsr_v8_vg_s1_p7_s2_reducer
```

目的：确认 Mutation path、before/after、set/delete/spawn 和冲突原子性未退化。

```bash
python3 -B -m simulator_v8_clean_core.tools.validate_p7_s3_selected_graph_atomic_commit \
  --output-dir /tmp/hsr_v8_vg_s1_p7_s3_atomic_commit
```

目的：确认现有 atomic commit 在状态表示收紧后仍能发布合法 reducer 结果，并在
原有冲突条件下保持 state unchanged。本卡不改变其领域完整性语义。

```bash
python3 -B -m simulator_v8_clean_core.tools.validate_p7_s18_compact_semantic_state \
  --output-dir /tmp/hsr_v8_vg_s1_p7_s18_compact_state
```

目的：确认 compact state 的冻结、复制、semantic key 和 snapshot materialization
没有被新 state 容器破坏。

### 10.3 条件触发集

默认无。

只有实际 patch 修改了以下范围时，才增加对应最窄 direct 验证：

- 修改 replay 实现：增加当前最窄的 replay contract 验证。
- 修改 queue producer/consumer：增加 P7-S11 queue direct 验证。
- 修改 scenario builder：增加不读取 TBGD 的 scenario focused 验证。
- 修改 lifecycle/status/summon 系统：说明已超出本卡，原则上应停止并修订卡，
  不能自行扩大成系统重构。

### 10.4 明确不跑

- P1-P8 任一阶段聚合。
- `validate_v0_209`。
- `validate_p7_current_tree_shared_regressions`。
- P8-S8、P8-R1 catalog 模式。
- 任何完整 TBGD discovery/lowering。
- 任何完整 Canonical IR、RuleBook、coverage 或 fidelity 输出。

原因：这些入口不增加对递归不可变边界的证明力，却会重新引入本治理轨道正在消除
的内存、IO 和时间成本。

## 11. 资源限制

- 新聚焦验证只创建少量纯内存 UnitState/BattleState/Mutation fixture。
- 不读取 `turnbasedgamedata-main`。
- 不实例化生产完整 RuleBook；P7-S3 现有小型 fixture RuleBook 可运行。
- 不写完整 snapshot/replay dump；默认只写 summary 和紧凑矩阵。
- `/tmp` 产物建议控制在 1 MiB 内。
- 不并发运行任何验证。
- 若任一聚焦命令超过 30 秒或明显进入来源扫描，立即停止并查明意外依赖。
- 不为通过资源限制删减本卡正负例；应移除错误的重依赖。

## 12. Gap、阻断与 deferred 口径

以下情况必须停止并报告 blocker：

- 发现生产代码依赖对 committed state 的直接原地写入，且无法用局部
  copy + replace 原子迁移。
- `global_flags`、queue item 或 shield instance 中存在正式需要但非 JSON 的
  runtime 对象。
- 保持现有 dict-style 只读接口需要引入业务系统专用兼容层。
- 实现不可避免地改变 lifecycle、status、summon、wave 或 event 语义。
- Snapshot 隔离只能通过删减字段、降低 snapshot 完整性或跳过深层值实现。

以下明确 deferred，不影响本卡通过：

- HP 与 lifecycle 的 committed invariant。
- status IDs 与 status details 的唯一权威迁移。
- summon/halo/wave/queue 的领域一致性。
- atomic commit 的 touched-domain integrity protocol。
- event dispatch closure 的 root/child 所有权。
- 其余 frozen dataclass 的递归不可变迁移。
- catalog/shared RuleBook 构建优化。

deferred 不能用来豁免本卡定义的 UnitState、BattleState 或 Snapshot 路径。

## 13. 交付物与报告要求

执行线程提交：

```text
live_validation_reports/v8_vg_s1_committed_state_immutability_ready_for_review.md
```

报告至少包含：

- 实际修改文件和关键符号。
- 输入别名、内部写入、Snapshot 隔离、codec、reducer、replay 矩阵。
- 每个结构化谓词的实际值。
- 所有验证命令、退出状态、实际耗时和峰值内存；无法测量时写
  `not_measured`，不能估算。
- 是否发现并迁移生产原地写入。
- 明确说明未实现任何领域状态不变量。
- 明确列出未运行的 catalog/full 验证及原因。
- 当前剩余风险和 deferred。
- 状态只能写 `ready_for_review`。

执行线程不得：

- 把本卡 checklist 改为完成。
- 宣称 VG-S1 `done` 或 `accepted`。
- 提交 Git。
- 开始 VG-S2。

## 14. 唯一执行清单（仅验收线程可勾）

- [x] UnitState 的 statuses、shield instances、flags、resources 已在构造和 replace 边界递归不可变并脱离输入别名。
- [x] BattleState 的 units、global flags、queues 已在构造和 replace 边界不可变并脱离输入别名。
- [x] Snapshot 内部已递归不可变，`to_json()` 每次返回独立普通 JSON 副本。
- [x] Unit codec 的普通 JSON 输出、确定 round-trip 和不可变 decode 结果已闭环。
- [x] Reducer set/delete/spawn 结果不可变，冲突失败仍保持 before state。
- [x] 非法 JSON、非字符串 key、非有限数值和错误 state mapping 成员已 fail-closed。
- [x] 现有 dict-style/tuple-style 只读 consumer 未被破坏，未新增可写兼容层。
- [x] 新聚焦验证与 P7-S2、P7-S3、P7-S18 直接回归全部通过。
- [x] 未读取 TBGD、未构建完整 RuleBook、未运行 catalog/full 聚合、未写大产物。
- [x] 未修改领域战斗语义、P8 checklist、VG-S0 证据或无关 UI。
- [x] `ready_for_review` 报告完整、诚实且所有本阶段谓词可由实际证据复核。
