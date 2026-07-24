# VG-S1 Committed State 递归不可变与快照隔离执行报告

执行交付状态：`ready_for_review`

验收状态：`accepted`

代码基线：`a11637df7f91bea4a406179680cb0bb56b923380`

验收线程独立复核：

- 六条伪造通用冻结 JSON 子类入口均在模型边界被拒绝。
- 合法子类均重建为精确内部冻结类型。
- VG-S1 `29/29`、P7-S2 `14/14`、P7-S3 `9/9`、P7-S18 `5/5`。
- 3000 个嵌套条目、各 100 次标量 `replace()` 的独立探针继续确认未修改子树
  结构共享。

## 1. 范围结论

本轮只实施 VG-S1：

- `UnitState` 的 `statuses`、`shield_instances`、`flags`、`resources` 在构造和
  `dataclasses.replace()` 边界完成校验与递归不可变规范化：普通可变输入复制后
  冻结，已经规范化的不可变子树安全共享。
- `BattleState` 的 `units`、`global_flags`、`queues` 在构造和
  `dataclasses.replace()` 边界采用相同所有权规则；标量 `replace()` 不再复制
  未修改的单位、全局状态和队列。
- `_FrozenResourceDict`、`_FrozenUnitStateDict`、`_FrozenQueueStateDict`
  在自身构造时校验并规范化全部内容；模型只对精确的内部专用类型走 O(1) 复用，
  普通映射或子类仍重新构造并校验。
- `freeze_json()` 只直接复用精确 `FrozenJSONDict`、`FrozenJSONList`；其子类
  必须重新递归冻结和校验。护盾 tuple、护盾 item、队列 tuple 与队列 item 的
  快速复用遵循同一精确类型规则。
- `Snapshot` 对普通可变构造输入复制并递归冻结，只对精确内部冻结 JSON tree
  允许共享；`to_json()` 每次仍返回完全独立的普通可变 JSON tree。
- `unit_state_codec` 和 `MutationReducer` 的现有
  `thaw_json -> copy -> replace` 路径无需生产改动，聚焦验证与直接回归已证明闭环。
- 未发现需要迁移的生产 committed-state 原地写入。
- 未实现 HP/lifecycle、status、summon、halo、wave、phase、window、queue
  内容等任何领域状态不变量。
- 未开始 VG-S2，未修改任何 checklist，未提交 Git。

## 2. 实际修改文件与关键符号

| 文件 | 修改 |
|---|---|
| `simulator_v8_clean_core/core/model.py` | 新增私有 `_FrozenStateDict` 及按字段区分的窄类型冻结映射；三种专用容器在自身构造时校验内容，模型仅复用精确内部类型；收紧 `UnitState.__post_init__`、`BattleState.__post_init__`、`Snapshot.__post_init__`；普通可变输入复制冻结，已规范化冻结子树结构共享；`UnitState.to_snapshot()` 与 `Snapshot.to_json()` 返回脱离副本 |
| `simulator_v8_clean_core/immutable_json.py` | `freeze_json()` 仅共享精确内部冻结类型；冻结容器子类重新递归冻结和校验 |
| `simulator_v8_clean_core/tools/validate_vg_s1_committed_state_immutability.py` | 新增纯内存聚焦验证器，输出 summary 与紧凑矩阵；覆盖结构共享、专用容器伪造及通用冻结 JSON 子类伪造 |
| `simulator_v8_clean_core/tools/validate_p7_s18_compact_semantic_state.py` | validation-only 护盾 fixture 补齐既有 codec schema 要求的 `owner_modifier_name`、`status_instance_id` |
| `live_validation_reports/v8_vg_s1_committed_state_immutability_ready_for_review.md` | 本报告 |

未修改：

- `core/unit_state_codec.py`：现有 `thaw_json()` 输出已经是普通 detached JSON；
  decode 后由新的 `UnitState.__post_init__` 统一冻结。
- `core/reducer.py`：现有 copy + `replace()` 更新路径与 dict-compatible 冻结映射
  兼容。

## 3. 输入别名与内部写入矩阵

| 边界 | 实际探针 | 结果 |
|---|---|---|
| Unit 输入别名 | 构造后修改两层 flags、status list、shield list/dict/deep list、resources dict | state/payload 不变 |
| Unit 内部写入 | 顶层及深层 assignment、append、update、pop、setdefault | 全部明确抛出 `TypeError` 或 `AttributeError` |
| Unit replace | 向 `replace()` 传入新的 mutable statuses/flags/shields/resources，再污染输入 | 新旧 Unit 均不变，替换结果仍不可变 |
| Unit 标量 replace | 只替换 `hp`，检查 flags、shield instances、resources 的对象身份 | 三棵未修改冻结子树全部复用 |
| Battle 输入别名 | 构造后修改 units mapping、global flags 深层值、queue mapping/list/item | snapshot 与 committed state 不变 |
| Battle 内部写入 | units/global_flags/queues 的 assignment/update/pop/setdefault，queue tuple/item 深层写入 | 全部明确失败 |
| Battle replace | 分别替换 units/global_flags/queues 后污染传入容器 | 三条路径均重新规范化且不可变 |
| Battle 标量 replace | 只替换 `skill_points`，检查 units、global_flags、queues 及 queue item 的对象身份 | 所有未修改冻结子树全部复用 |
| 伪造专用冻结容器 | 分别直接构造 NaN resources、非 `UnitState` units、非序列 queue，再尝试进入模型边界 | 三种非法内容均在专用容器构造阶段拒绝 |
| 伪造通用冻结子类 | 伪造 `FrozenJSONDict/List` 子类进入 flags、嵌套 flags、shield、global_flags、queue、Snapshot 六条入口 | 合法子类重建为精确内部类型；携带未知对象的六条负例全部拒绝 |
| 非法 Unit 表示 | 非字符串 key、未知对象、NaN/Infinity、bool resource、非字符串 status、非 object shield | 全部在构造边界拒绝 |
| 非法 Battle 表示 | 空/非字符串 unit id、非 UnitState value、空/非字符串 queue name、非 sequence queue、非法 JSON | 全部在构造边界拒绝 |

聚焦矩阵行统计：

| 矩阵 | 通过 |
|---|---:|
| Unit | 38 行，全部通过 |
| Battle | 39 行，全部通过 |
| Snapshot | 17 行，全部通过 |
| Codec | 3 组，全部通过 |
| Reducer / replay | 18 行，全部通过 |
| Consumer compatibility | 1 组，全部通过 |

## 4. Snapshot、codec、reducer、replay 证据

| 范围 | 实际证据 | 结果 |
|---|---|---|
| Snapshot 构造隔离 | 修改构造输入的顶层、深层 object/list | Snapshot 不变 |
| Snapshot frozen 输入 | 用一个 Snapshot 的冻结 `data` 构造另一个 Snapshot | 安全复用同一不可变 tree |
| Snapshot 内部不可变 | 对 `Snapshot.data` 顶层、深层 object/list 写入 | 全部失败 |
| Snapshot 普通 JSON 输出 | 递归检查 exact built-in `dict/list`，执行 `json.dumps(..., allow_nan=False)` | 通过 |
| Snapshot 多次导出隔离 | 修改第一次 `to_json()` 的顶层与深层值，再读取第二、三次 | 后续导出不变 |
| Battle snapshot 隔离 | 篡改 unit flags、status details、shield、queue、summon runtime、targeting、settlement 深层导出 | BattleState 与新 snapshot 不变 |
| 等价 state snapshot | 用 detached plain JSON 重建等价 BattleState | typed structure/value 相等 |
| Codec detached output | 修改 encoded flags/shield/resources/statuses | UnitState 不变 |
| Codec round-trip | `to_payload -> from_payload -> to_payload` 连续两次 | 确定相等，decode 结果不可变 |
| Reducer set | unit scalar、nested flag、resource、global flag、queue | 成功结果全部不可变，before 不变 |
| Reducer delete | unit flag/resource、global flag、queue | 删除语义保持，成功结果不可变 |
| Reducer spawn | 修改 Mutation 构造前的原始 spawn payload | spawn 结果保持 canonical 且不可变 |
| Reducer conflict | 首条 mutation 可执行、后续 before 冲突 | 返回原 state、applied=0、外部输入与 before 均未污染 |
| Replay | detached expected 成功；只篡改其副本 | 仅产生 snapshot mismatch，不改变 state，随后 replay 仍成功 |

## 5. 结构化谓词

聚焦 summary：

`/tmp/hsr_v8_vg_s1_committed_state_immutability/validation_summary_vg_s1_committed_state_immutability.json`

| 谓词 | 实际值 |
|---|---:|
| `unit_constructor_detaches_nested_inputs` | `true` |
| `unit_nested_state_recursively_immutable` | `true` |
| `unit_replace_reapplies_normalization` | `true` |
| `battle_constructor_detaches_nested_inputs` | `true` |
| `battle_units_mapping_immutable` | `true` |
| `battle_global_flags_recursively_immutable` | `true` |
| `battle_queues_recursively_immutable` | `true` |
| `battle_replace_reapplies_normalization` | `true` |
| `scalar_replace_reuses_unchanged_frozen_subtrees` | `true` |
| `forged_frozen_containers_cannot_bypass_model_boundary` | `true` |
| `frozen_json_subclasses_revalidated_at_model_boundaries` | `true` |
| `snapshot_constructor_detaches_input` | `true` |
| `snapshot_internal_data_recursively_immutable` | `true` |
| `snapshot_to_json_returns_detached_plain_json` | `true` |
| `snapshot_to_json_calls_are_independent` | `true` |
| `snapshot_mutation_cannot_reach_battle_state` | `true` |
| `unit_codec_output_is_detached_plain_json` | `true` |
| `unit_codec_round_trip_is_deterministic` | `true` |
| `reducer_set_result_is_immutable` | `true` |
| `reducer_delete_result_is_immutable` | `true` |
| `reducer_spawn_result_is_immutable` | `true` |
| `reducer_failure_preserves_before_state` | `true` |
| `replay_snapshot_remains_deterministic` | `true` |
| `invalid_json_value_rejected` | `true` |
| `non_string_json_key_rejected` | `true` |
| `non_finite_json_number_rejected` | `true` |
| `production_behavior_semantics_changed` | `false` |
| `tbgd_read_count` | `0` |
| `full_rulebook_build_count` | `0` |

`predicate_mismatches={}`，29 个结构化期望全部满足；聚焦输出共 `30,026`
bytes。

## 6. 验证命令与资源

资源值均由 `/usr/bin/time` 实测，单位分别为秒和 KiB；未估算。

### 6.1 首轮

| 命令 | exit | elapsed | peak RSS | 结果 |
|---|---:|---:|---:|---|
| `PYTHONPYCACHEPREFIX=/tmp/hsr_v8_vg_s1_pycache python3 -m compileall -q simulator_v8_clean_core` | 0 | 0.86 | 54260 | 通过 |
| `python3 -B -m simulator_v8_clean_core.tools.validate_vg_s1_committed_state_immutability --output-dir /tmp/hsr_v8_vg_s1_committed_state_immutability` | 0 | 0.12 | 23204 | 26/26 |
| `git diff --check` | 0 | 0.00 | 4704 | 通过 |
| `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s2_mutation_reducer_contract --output-dir /tmp/hsr_v8_vg_s1_p7_s2_reducer` | 0 | 0.51 | 49472 | 14/14 |
| `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s3_selected_graph_atomic_commit --output-dir /tmp/hsr_v8_vg_s1_p7_s3_atomic_commit` | 0 | 0.23 | 39584 | 9 cases |
| `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s18_compact_semantic_state --output-dir /tmp/hsr_v8_vg_s1_p7_s18_compact_state` | 1 | 0.26 | 37096 | 基线 validation fixture 缺既有 shield schema 字段 |

P7-S18 首次失败时，`git diff a11637d -- <该验证器>` 为空；基线 fixture 确认缺少
`owner_modifier_name`、`status_instance_id`，而现行
`unit_state_codec._validate_shield_instances()` 已要求这两个字段。只补齐 validation
fixture 后，从最小集开始完整重跑。

### 6.2 Fixture 修正后完整重跑

| 命令 | exit | elapsed | peak RSS | 结果 |
|---|---:|---:|---:|---|
| `PYTHONPYCACHEPREFIX=/tmp/hsr_v8_vg_s1_pycache python3 -m compileall -q simulator_v8_clean_core` | 0 | 0.02 | 12768 | 通过 |
| `python3 -B -m simulator_v8_clean_core.tools.validate_vg_s1_committed_state_immutability --output-dir /tmp/hsr_v8_vg_s1_committed_state_immutability` | 0 | 0.12 | 23360 | 26/26 |
| `git diff --check` | 0 | 0.00 | 4704 | 通过 |
| `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s2_mutation_reducer_contract --output-dir /tmp/hsr_v8_vg_s1_p7_s2_reducer` | 0 | 0.53 | 49480 | 14/14 |
| `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s3_selected_graph_atomic_commit --output-dir /tmp/hsr_v8_vg_s1_p7_s3_atomic_commit` | 0 | 0.26 | 39748 | 9 cases |
| `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s18_compact_semantic_state --output-dir /tmp/hsr_v8_vg_s1_p7_s18_compact_state` | 0 | 0.26 | 28848 | 5/5 rows |

### 6.3 首次交付前强制 detached 重跑（已被验收否决）

交付前自审将 committed-state JSON 规范化统一收紧为
`thaw_json -> freeze_json`，确保即使输入本身已经冻结，也不会复用调用方容器对象；
聚焦验证同步增加 frozen-input identity 探针。该口径虽然通过功能验证，但会让每次
标量 `replace()` 完整复制所有未修改状态，被验收判定为架构级性能阻断；以下仅保留
为问题发现前的历史记录，不代表当前实现或当前验收口径：

| 命令 | exit | elapsed | peak RSS | 结果 |
|---|---:|---:|---:|---|
| `PYTHONPYCACHEPREFIX=/tmp/hsr_v8_vg_s1_pycache python3 -m compileall -q simulator_v8_clean_core` | 0 | 0.03 | 15356 | 通过 |
| `python3 -B -m simulator_v8_clean_core.tools.validate_vg_s1_committed_state_immutability --output-dir /tmp/hsr_v8_vg_s1_committed_state_immutability` | 0 | 0.14 | 23284 | 26/26 |
| `git diff --check` | 0 | 0.00 | 4704 | 通过 |
| `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s2_mutation_reducer_contract --output-dir /tmp/hsr_v8_vg_s1_p7_s2_reducer` | 0 | 0.53 | 49692 | 14/14 |
| `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s3_selected_graph_atomic_commit --output-dir /tmp/hsr_v8_vg_s1_p7_s3_atomic_commit` | 0 | 0.24 | 39620 | 9 cases |
| `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s18_compact_semantic_state --output-dir /tmp/hsr_v8_vg_s1_p7_s18_compact_state` | 0 | 0.20 | 28704 | 5/5 rows |

### 6.4 冻结子树结构共享修复后的重跑（随后发现完整性绕过）

移除 `thaw_json -> freeze_json` 强制深拷贝，将所有权口径修正为“可变输入复制并
冻结，已规范化不可变子树安全共享”，并删除“已冻结对象必须不同身份”的错误要求。
新增标量 `replace()` 结构共享谓词后再次完整串行运行：

| 命令 | exit | elapsed | peak RSS | 结果 |
|---|---:|---:|---:|---|
| `PYTHONPYCACHEPREFIX=/tmp/hsr_v8_vg_s1_pycache python3 -m compileall -q simulator_v8_clean_core` | 0 | 0.14 | 15232 | 通过 |
| `python3 -B -m simulator_v8_clean_core.tools.validate_vg_s1_committed_state_immutability --output-dir /tmp/hsr_v8_vg_s1_committed_state_immutability` | 0 | 0.16 | 22848 | 27/27 |
| 纯内存结构共享性能探针（3000 个嵌套条目、各 100 次标量 `replace()`） | 0 | 0.19 | 37276 | Unit `0.000526s`；Battle `0.000210s` |
| `git diff --check` | 0 | 0.01 | 4704 | 通过 |
| `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s2_mutation_reducer_contract --output-dir /tmp/hsr_v8_vg_s1_p7_s2_reducer` | 0 | 0.54 | 49736 | 14/14 |
| `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s3_selected_graph_atomic_commit --output-dir /tmp/hsr_v8_vg_s1_p7_s3_atomic_commit` | 0 | 0.23 | 39988 | 9 cases |
| `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s18_compact_semantic_state --output-dir /tmp/hsr_v8_vg_s1_p7_s18_compact_state` | 0 | 0.19 | 29148 | 5/5 rows |

性能探针同时确认：

- `UnitState` 标量 `replace()` 复用 flags 与 resources。
- `BattleState` 标量 `replace()` 复用 units、global_flags、queues。
- `Snapshot.to_json()` 的两次导出仍为相互独立的普通 JSON。

该轮性能问题已修复，但专用冻结容器尚未在自身构造时校验内容，直接构造的非法
专用容器可绕过模型快路径；因此该轮同样不是当前验收证据。

### 6.5 专用冻结容器完整性修复后的重跑（随后发现通用子类绕过）

三种专用冻结容器的构造器现在分别校验有限数值资源、合法 `UnitState` 映射和合法
队列表示。`UnitState`、`BattleState` 只对精确内部类型走 O(1) 复用，避免通过
自定义子类冒充可信容器。新增三条伪造容器负例后再次完整串行运行：

| 命令 | exit | elapsed | peak RSS | 结果 |
|---|---:|---:|---:|---|
| `PYTHONPYCACHEPREFIX=/tmp/hsr_v8_vg_s1_pycache python3 -m compileall -q simulator_v8_clean_core` | 0 | 0.09 | 15316 | 通过 |
| `python3 -B -m simulator_v8_clean_core.tools.validate_vg_s1_committed_state_immutability --output-dir /tmp/hsr_v8_vg_s1_committed_state_immutability` | 0 | 0.13 | 23316 | 28/28 |
| 纯内存结构共享性能探针（3000 个嵌套条目、各 100 次标量 `replace()`） | 0 | 0.22 | 44652 | Unit `0.000604s`；Battle `0.000205s` |
| `git diff --check` | 0 | 0.00 | 4704 | 通过 |
| `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s2_mutation_reducer_contract --output-dir /tmp/hsr_v8_vg_s1_p7_s2_reducer` | 0 | 0.52 | 49528 | 14/14 |
| `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s3_selected_graph_atomic_commit --output-dir /tmp/hsr_v8_vg_s1_p7_s3_atomic_commit` | 0 | 0.23 | 39716 | 9 cases |
| `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s18_compact_semantic_state --output-dir /tmp/hsr_v8_vg_s1_p7_s18_compact_state` | 0 | 0.19 | 28748 | 5/5 rows |

新增负例的实际异常：

- `_FrozenResourceDict({"bad": NaN})`：`ValueError`。
- `_FrozenUnitStateDict({"ally:forged": object()})`：`TypeError`。
- `_FrozenQueueStateDict({"queue": {"item": "bad"}})`：`TypeError`。

同轮性能探针继续确认未修改冻结子树全部复用，且 `Snapshot.to_json()` 导出相互
独立。

该轮三种专用容器已经闭合，但 `freeze_json()`、护盾与队列仍以 `isinstance()`
信任通用冻结 JSON 子类；伪造子类可携带未知对象进入 committed state，因此该轮
不是当前验收证据。

### 6.6 通用冻结 JSON 子类完整性修复后的当前完整重跑

`freeze_json()`、护盾和队列的共享判定统一收紧为精确内部类型。合法子类会重新
递归冻结为精确 `FrozenJSONDict/FrozenJSONList`，携带未知对象的子类会在进入
committed state 前失败。增加六条边界负例及合法子类重建检查后完整串行运行：

| 命令 | exit | elapsed | peak RSS | 结果 |
|---|---:|---:|---:|---|
| `PYTHONPYCACHEPREFIX=/tmp/hsr_v8_vg_s1_pycache python3 -m compileall -q simulator_v8_clean_core` | 0 | 0.04 | 15544 | 通过 |
| `python3 -B -m simulator_v8_clean_core.tools.validate_vg_s1_committed_state_immutability --output-dir /tmp/hsr_v8_vg_s1_committed_state_immutability` | 0 | 0.13 | 23264 | 29/29 |
| 纯内存结构共享性能探针（3000 个嵌套条目、各 100 次标量 `replace()`） | 0 | 0.21 | 44872 | Unit `0.000553s`；Battle `0.000203s` |
| `git diff --check` | 0 | 0.00 | 4704 | 通过 |
| `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s2_mutation_reducer_contract --output-dir /tmp/hsr_v8_vg_s1_p7_s2_reducer` | 0 | 0.50 | 49732 | 14/14 |
| `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s3_selected_graph_atomic_commit --output-dir /tmp/hsr_v8_vg_s1_p7_s3_atomic_commit` | 0 | 0.25 | 39768 | 9 cases |
| `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s18_compact_semantic_state --output-dir /tmp/hsr_v8_vg_s1_p7_s18_compact_state` | 0 | 0.19 | 28800 | 5/5 rows |

六条伪造子类负例覆盖：

- `UnitState.flags` 的伪造字典根和嵌套伪造列表。
- `UnitState.shield_instances` 的伪造字典 item。
- `BattleState.global_flags` 的伪造字典根。
- `BattleState.queues` 的伪造列表 item。
- `Snapshot.data` 的伪造字典根。

同轮正例确认上述边界会将合法子类重建为精确内部冻结类型且不复用子类身份；性能
探针则确认精确内部冻结子树仍保持 O(1) 共享。

## 7. 未运行验证

按执行卡明确未运行：

- P1-P8 任一阶段聚合。
- `validate_v0_209`。
- `validate_p7_current_tree_shared_regressions`。
- P8-S8、P8-R1 catalog 模式。
- 完整 TBGD discovery/lowering。
- 完整 Canonical IR、RuleBook、coverage、fidelity 输出。

原因：本轮只修改 committed-state 表示与所有权边界；上述 catalog/full 入口不会增加
对递归不可变、别名隔离、codec/reducer/replay 的直接证明力，并会扩大 IO、内存和
历史验证成本。

## 8. 剩余风险与 deferred

当前风险：

- 只运行了执行卡规定的 fast + direct 范围；未以 catalog/full 证明全部历史
  consumer，但 dict-style/tuple-style 实际读接口、codec、reducer、atomic
  commit、compact state 已覆盖。
- P7-S18 基线 fixture 漂移已最小修正；该改动仅属于验证数据，不改变生产 schema
  或战斗语义。
- VG-S1 聚焦验证器当前为 1,835 行、64,309 bytes；运行成本低，但维护和审查成本
  偏高。按验收意见记录为非 S1 阻断，留待后续验证治理阶段精简。

继续 deferred，未由本阶段实现或豁免：

- HP 与 lifecycle committed invariant。
- status IDs 与 status details 的唯一权威迁移。
- summon/halo/wave/queue 的领域一致性。
- atomic commit touched-domain integrity protocol。
- event dispatch closure 的 root/child 所有权。
- 其余 frozen dataclass 的递归不可变迁移。
- catalog/shared RuleBook 构建优化。

无新增依赖，无 TBGD 读取，无完整 RuleBook 构建，无大体积产物。
