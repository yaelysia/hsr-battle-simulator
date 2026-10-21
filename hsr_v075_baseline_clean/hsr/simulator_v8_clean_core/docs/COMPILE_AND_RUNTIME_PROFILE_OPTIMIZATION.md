# 第二轮编译与执行集中优化

2026-10-21，诊断基线 `5c1625c`。实现：dsh / DeepSeek；范围、约束与集中验收：Codex。
本说明完成性能定位；下列四项已按本节约束进入生产实现，交付证据见文末
[第二轮实施与交付](#第二轮实施与交付2026-10-21)。第一轮结果见
[编译与测试耗时优化](COMPILE_AND_TEST_COST_REDUCTION.md)。

## 实测结论

固定 `examples/cli/seele_automatic_insert_natural{,.commands}.json`，正式构筑和来源波次，
九次公开 advance/submit，包含自动插入排空及后续公开行动，18 条操作全部成功。
使用已有 `.venv`，串行加锁；没有运行默认全目录编译或全量回归。

无剖析参考：冷编译约 38–48 s、首次会话初始化约 8.9 s、九步执行约 75 s。
本轮 cProfile 分别为 90.88 / 35.23 / 191.37 s；递归调用受剖析器放大，
这些秒数只用于定位，不能从 75 s 中直接扣除，嵌套累计时间也不能相加。

| 热点 | 证据 | 判断 |
| --- | --- | --- |
| 执行中的 `thaw_json` | 约 1.04 亿次递归调用，累计 121.95 s，约占剖析执行时间 64% | 首先消除内部重复深复制 |
| reducer | 1408 次 `_apply_checked` 累计 101.75 s；严格比较 47.42 s，写入路径 34.37 s | 修共享比较、读取和写入，不能减少提交检查 |
| `Snapshot.to_json` | 294 次调用，累计 42.58 s；大头为五处状态摘要 | 摘要直接消费已有只读表示 |
| 最终快照转换 | JSON 为 6,728,641 字节；默认转换新分配约 12.3 MiB，只读转换峰值 88 字节；编码摘要相同 | 已有机制足够，无需新快照系统 |
| 同一 state 的重复决策 | 41 次查询中重复 18 次，累计重复约 10.29 s，约占 5.4%，且包含上述复制 | 优先级低于复制，不先建决策缓存 |
| 冷编译来源解析 | `_package_index` 累计 26.07 s，完整扫描 2844 文件；大量证据创建后丢弃 | 保持完整扫描，只省无效对象构造 |
| 冷编译任务图目录 | 两次目录构造累计 16.73 s，其中逐碎片 JSON 编码/哈希约 13.68 s | 保持校验，改变相同字节流的编码批次 |
| 首次规则身份 | canonical 指纹累计 25.95 s；无剖析既有测量约 6.4 s | 本批保留算法，后续再评估 |

额外做了两类局部原型，均未修改生产函数：

- 来源证据：`_equivalent_evidence` 构造 185448 → 408 次，`_package_index` 8.31 → 3.54 s；
  manifest、文件大小、候选和保留证据的完整返回值相等。输入为 Hook / 希儿 / 一个缺失能力的
  三个请求名，仍读取全包 2844 文件；该数字不是完整冷编译的收益。
- 任务图目录：同一个 51,167,833 字节身份，原逐碎片哈希 2.33 s；整份编码约 0.35 s，
  但新分配峰值约 97.6 MiB。改成按顶层数组成员分块后 0.30 s、新分配峰值约 2.6 MiB，
  最大成员编码约 479 KiB；目录 ID 完全相同。空数组、嵌套值、Unicode、转义和不同标量形状
  的三个组件输入也与原字节流一致。微测与整场收益分开报告。

## 同批实施的四项

### 1. reducer 保留冻结子树，去掉比较和写入中的往返复制

入口：`core/reducer.py` 的 `_apply_checked → _read_path / _typed_equal / _write_path`，
以及 `_mapping_value / _json_value / _write_mapping`；单位字段与 spawn 还经过
`core/unit_state_codec.py`。按所有正式调用者核对，不只修改自然路线触发的 flags 路径。

目前读取会递归复制；比较又把两侧 thaw 后递归比较；写入先 thaw，映射分支再 thaw，
最后模型构造重新 freeze。复用已有不可变 JSON 和路径上的外层容器复制，消除这些往返。
优先局部修改 reducer，不改变全局 `freeze_json / thaw_json` 的公开语义。

一次性约束：

- 保留 before/after 存在性、严格值比较、操作/路径/类型检查、写入后校验、完整原子提交。
  同批连续 mutation 仍按候选状态顺序应用；后项失败返回原状态，RNG、队列与生命周期不泄漏。
- JSON 容器比较须等价于原来的 thaw 后比较：Frozen/普通 dict 对应 object，list/tuple
  对应 array；标量继续严格区分 `True`、`1`、`1.0`，区分缺失和 `None`，顺序与键集合不变。
  不得用普通 `==` 代替全部严格比较。
- 原有非有限数字、非字符串键、非法 JSON、字段值及 spawn payload 拒绝行为保留。
  只对已经过正式验证的精确内部冻结类型共享；不能把任意子类或普通可变容器当成可信输入，
  也不能用未经验证的 identity 快路绕过检查。
- 覆盖全局 flags、单位 flags/resources、队列、statuses、shield_instances 与 spawn；
  保留字段 codec、tuple/list 的规范化结果和冲突 code/path/expected/actual。
  不改变失败导出或公开导出的隔离性。
- 只新建变化路径需要的容器；其它冻结子树可以共享，旧 state、Mutation 和调用方原始输入
  均不被修改。不新增状态容器框架、全局缓存或给生产代码增加测试专用入口。

### 2. 五处内部摘要使用已有只读快照

下列函数均只读快照并编码哈希，显式使用 `snapshot().to_json(detach=False)`：

| 文件 | 函数 |
| --- | --- |
| `systems/action_selection.py` | `action_target_state_revision` |
| `systems/decision.py` | `_state_revision` |
| `systems/action_contract.py` | `_action_state_revision` |
| `systems/scheduler.py` | `_scheduler_state_revision` |
| `systems/dynamic_values.py` | `dynamic_value_state_fingerprint` |

保留各自 ensure_ascii、allow_nan、sort_keys、separators、前缀和摘要截断长度，不能顺手统一
成另一套 hash。外部 `to_json()` 默认仍返回独立可变数据；不机械替换其它导出调用。
不使用 event_index 单独缓存摘要，不复用其它状态的 token、计划或类型化凭据。

### 3. 来源证据桶确定收满后停止构造弃用证据

入口：`tbgd/character_source_resolution.py:_package_index` 的 `walk → _equivalent_evidence`。
仅当该 raw_type 已保留 16 条，且首条已满足对应 required_roles 时，跳过本节点的证据构造。
不在桶未兼容时提前停止：即使已满 16 条，后续首个兼容证据仍须触发原清空/晋升逻辑。

本节点的 `AbilityList` 候选发现及所有子节点递归继续执行。保留完整文件范围、读取、SHA、
manifest、候选排序与首 16 条证据选择；不得提前 return 整个 walk、跳过文件或扩大裁剪。
沿用现有 16 条容量和兼容性定义，不引入第二份含义不同的容量规则。

### 4. 任务图目录身份按成员编码，保持相同哈希

入口：`rules/task_graph.py:TaskGraphCatalogIR.__post_init__` 最后 identity 编码/哈希部分。
保留前面全部来源、引用、双向 ledger、选中条目等闭包校验。

仅针对这个已知形状的 identity 对象，保持顶层键排序、标点与编码选项；顶层数组/tuple
逐成员交给现有 JSONEncoder 编码后更新 digest，其它字段按现有编码器处理。
不得对完整约 49 MiB 目录一次性 dumps，也不编写通用 JSON 编码框架或修改 catalog_id 协议。
相同合法输入必须产生逐字节相同的哈希输入与目录 ID。

内存上限随最大单个成员增长，不能称为常数内存。按 ponytail 约定用注释说明该上限及未来
单成员过大时的流式退路；不为尚不存在的大成员现在增加另一套分块框架。
保留编码器对 default/to_json、Unicode、转义、浮点数和空容器的处理。

## 验证与交付

先集中完成组件验证，再合并跑一次自然路线。不要每改一个函数都冷编译或重跑八步前置。

1. 复用 `tests/test_snapshot_export_sharing.py`；按实际差异补最小 reducer 回归，锁住严格
   标量与容器比较、共享后的旧状态/导出隔离，以及队列/单位字段/spawn 的有效和失败路径。
   已有 `tools/validate_vg_s1_committed_state_immutability.py` 的相关检查可复用，
   不因此运行整套历史阶段验证器。原子性负例和相邻字段不变不能只靠最终 HP 证明。
2. 五个摘要函数与基线在同一状态上的结果相同；同 event_index 的不同状态仍产生不同摘要。
   复用目标上下文、动态值计划和归档的现有快测，保持 stale/篡改计划和 token 的拒绝。
3. 来源解析补一个小组件检查，涵盖“未兼容桶已满，后续兼容证据晋升”及“满兼容桶节点下
   仍能发现候选/子节点”；原型完整返回值等价检查可复用。任务图哈希补最小字节等价检查，
   复用正式目录 ID 核对，不仅核对目录条目数量。
4. 四项稳定后，同场景只做一次限定冷构建，比较完整 Canonical IR 指纹、目录 ID 与来源
   目录内容；不生成默认全目录。随后复用得到的 RuleBook 测一次初始化与九步公开操作，
   或与下列共享 integration 前置合并，不能为分段计时重复生成相同战斗。
   记录无 cProfile / tracemalloc 干扰的分段墙钟和峰值 RSS；cold、warm hit、startup、
   runtime 与导出分别计时，不把本批代码导致的缓存重建记为热加载退化。
5. 原 integration 模块四项一起跑一次，继续共享一次规则准备、一次会话和一次八步前置；
   保留成功、取消、晚期回滚、审计、资源、插入身份及隔离断言。该次结果可同时承担上项
   的自然路线证据，不另跑 CLI 生成同一条战斗：

   ```bash
   flock /tmp/hsr-v8-validation.lock /usr/bin/time -f 'elapsed=%e max_rss_kib=%M' \
     .venv/bin/python -B -m pytest -o addopts='' -q -m integration --durations=5 \
     hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_automatic_insert_action_closure.py
   ```

6. reducer 执行路径改变，复用已有九步归档在独立进程 replay 一次，确认 19 步 0 错误；
   无需再生成一条完整战斗。比较正式操作、事件、mutation、settlement、RNG 和前后快照，
   不靠相同最终血量替代过程等价。保留已有审计事实和归档格式。

交付必须区分组件收益和整条路线收益，并报告峰值；复制/证据构造的次数或分配量应能说明
浪费确已消除。无需另造常驻性能平台、全局计数器或用机器相关耗时断言做普通单测。
达到上述证据即交回集中验收，不默认扩大到全量回归；不提交、不推送、不改 submodule、
依赖或环境，不混入其它功能修复。

## 暂不纳入

- 决策/token 缓存：收益被上述复制占据，先优化后再测，避免增加状态失效问题。
- 首次 canonical 指纹算法、持久化中间缓存、分片增量编译和并行：本批不改身份或缓存语义。
- `DynamicValueExecutionContext`、`TaskGraphSettlementRecord` 内部序列化仍有复制，但涉及
  可变返回值消费者；先完成四项，再按剩余占比决定，不把全部 `to_json` 一律改成共享。
- 不删 trace、来源证明、mutation、审计、replay 或提交校验来换耗时和体积。

## 诊断证据

长期结论以上表为准；以下为本次临时可运行脚本与详细输出，不要求长期保留 `/tmp`：

- `/tmp/hsr_deep_profile_5c1625c.py`、同前缀 `.json/.log` 及 `_cold/_startup/_runtime.pstats`：
  一次限定冷编译及九步剖析，墙钟 322.90 s、峰值 RSS 976944 KiB。
- `/tmp/hsr_cold_microprobes_5c1625c.py` 及同前缀 `.json/.log`：证据容量和目录编码原型，
  墙钟 19.47 s、峰值 RSS 661964 KiB。
- `/tmp/hsr_catalog_bounded_probe_5c1625c.py` 及同前缀 `.json/.log`：有界目录编码原型，
  墙钟 7.11 s、峰值 RSS 580920 KiB。tracemalloc 的 2.6 MiB 为编码新分配，非进程总内存。

## 第二轮实施与交付（2026-10-21）

实施：dsh / DeepSeek。按上文范围与一次性约束完成四项；未提交、未推送、未更新 submodule、
未新增依赖或环境，未混入其它功能修复。默认导出、公开接口和归档格式不变。

### 改动

| 项 | 入口 | 做法 |
| --- | --- | --- |
| 1. reducer 共享冻结子树 | `core/reducer.py`，配合 `core/unit_state_codec.py` | 读取只共享精确的内部冻结容器；严格比较按 object/array 结构递归，保留标量类型与缺失/None 区别；写入只复制变化路径的外层容器，映射写入直接产出冻结映射；spawn 与整字段校验增加 `detach=False` 只读路径。默认导出仍返回独立可变 JSON。 |
| 2. 五处内部摘要 | `systems/{action_selection,decision,action_contract,scheduler,dynamic_values}.py` | 改为 `snapshot().to_json(detach=False)`；各自的 ensure_ascii、allow_nan、排序、分隔符、前缀与截断长度不变。外部 `to_json()` 默认仍分离。 |
| 3. 来源证据桶 | `tbgd/character_source_resolution.py:_package_index` | 仅当该 raw_type 已保留 16 条且首条满足 required_roles 时跳过本节点证据构造；候选发现、子节点递归、文件读取、SHA、manifest 与首 16 条选择不变，未兼容桶仍会晋升后续兼容证据。 |
| 4. 任务图目录身份 | `rules/task_graph.py` | 顶层数组/tuple 逐成员交给同一 JSONEncoder 编码后更新 digest，其它字段沿用编码器；不一次性 dumps 整份目录，不改 catalog_id 协议。 |

### 组件证据（同机、同场景、同命令）

- reducer（希儿自动插入九步公开操作，运行时计数）：`_json_value` 递归调用
  15,420,856 → 4,670；reducer 内 `thaw_json` 7,528 → 0；`_typed_equal` 顶层调用 2,657 次，
  递归节点比较 8,015 次中 7,297 次由共享 identity 直接判定；九步耗时 63.1 s → 26.4–26.6 s
  （计数包装在改动后的对照中差异 <0.2 s）。最终快照 sha256、18 条操作、技能点、能量与 RNG 状态
  与 `5c1625c` 相同。
- 五处摘要：每个函数对同一状态与 `to_json()` 基线编码逐字节相同；同 event_index 的不同状态仍
  产生不同摘要；九步中 294 次内部摘要共享只读快照，外部导出仍只有 1 次分离转换。
- 来源证据：同一三请求名（Hook / 希儿 / 一个缺失能力），`_equivalent_evidence` 构造
  185,448 → 408，`_package_index` 7.195 s → 2.947 s；完整返回值、2844 文件范围、manifest、
  候选与保留 16 条证据相等；submodule 仍为 `14c1d18`。
- 任务图目录：同一 51,167,833 字节身份，目录 ID 与基线相同；最大单成员编码 490,128 字节，
  编码新分配峰值 2,704,247 字节，整份约 0.30 s。
- 不可变性复用 `tools/validate_vg_s1_committed_state_immutability.py`：29/29 通过
  （含 reducer set/delete/spawn、失败保留、伪造冻结容器与非法 JSON 拒绝）。

### 整条路线（无 cProfile / tracemalloc）

| 阶段 | `5c1625c` 参考 | 本批冷启动 | 本批热命中 |
| --- | ---: | ---: | ---: |
| 规则构建 | 38–48 s | 26.9 s | 2.7 s |
| 会话初始化 | 8.9 s | 7.5 s | 7.2 s |
| 九次 advance/submit | 75 s | 27.1 s | 26.6 s |
| 最终快照转换 | — | 0.057 s | 0.052 s |
| 本次进程墙钟 | — | 64.1 s | 38.8 s |
| 峰值 RSS | 976,944 KiB（剖析运行） | 843,236 KiB | 849,192 KiB |

冷构建的完整 Canonical IR 指纹 `76b88cce…`、任务图目录 ID 与最终快照（6,728,641 字节）均与
基线相同；未生成默认全目录。交付前因注释级修改再发布一次缓存（27.7 s，同一指纹与目录 ID），
之后的验收运行可直接命中热缓存。九步执行从 75 s 降到 26.6 s 主要由第一项承担：只完成第二、三、四项、
reducer 未改时同一路线为 63.1 s（本批热加载 2.60 → 2.66 s，加载路径本批未改）。

集成模块四项一次运行：4 passed，42.66 s、峰值 841,896 KiB（第一轮参考 122.54 s）。
九步归档在独立进程 replay：`ok=true, step_count=19, errors=[]`，51.00 s、峰值 594,312 KiB；
逐项比较正式操作、事件、mutation、settlement、RNG 与前后快照，不靠最终血量替代过程等价。

### 验证入口

- `tests/test_snapshot_export_sharing.py`：原共享导出检查 + 6 项 reducer 回归（严格标量与容器比较、
  共享后旧状态/导出隔离、全局 flags、单位 flags/resources、队列、statuses、shield_instances、
  spawn 成功与失败、批次原子与候选状态顺序、相邻字段共享）。
- `tests/test_internal_state_revision_digests.py`：五处摘要与基线的同一状态逐字节相等；
  同 event_index 的不同状态给出不同摘要。
- `tests/test_character_source_evidence_bucket.py`：未兼容桶满后仍晋升后续兼容证据；
  满兼容桶不再构造证据、仍继续发现同节点与嵌套子节点的候选。
- `tests/test_task_graph_catalog_identity.py`：空容器、Unicode、转义、浮点、嵌套与多成员等
  形状的完整字节等价；正式目录 ID 由 `test_p9_a2_p3_wait_anim_state_process_only_barrier_retirement.py::test_catalog_streamed_fingerprint_matches_the_complete_json` 核对。

### 保留限制

- 只共享已经过正式验证的精确内部冻结类型；普通容器、子类与伪造冻结容器继续走分离/校验路径，
  identity 快速通道没有放宽到普通容器或子类。
- 目录身份内存上界仍随最大单个成员增长（本场景 490 KiB），未提前编写分块框架。
- 决策/token 缓存、canonical 指纹算法、持久化中间缓存、并行与分片增量编译仍不在本批。
- 未运行默认全目录编译或全量回归；限定冷构建、最终代码态缓存发布及自然路线运行次数见上文。
- 顺带发现 `tests/test_character_passive_startup.py::test_source_lifecycle_without_listener_remains_observable`
  在 `5c1625c` 基线代码的独立快照上同样失败（`OnAddModifierSuc` 家族已存在）；该集成用例为既有
  陈旧断言，与本批无关，未纳入本批修复。

### Codex 集中验收

2026-10-21：未发现需要返修的问题，四项验收通过。88 项定向检查通过；另用 1205 组组件输入
对比 `5c1625c` 的 reducer 与单位 codec，结果、快照标量类型、冲突详情及回滚身份一致。
四项集成改按取消→晚期失败→成功→准备复用的顺序，一次运行全部通过，48.88 s，
进程墙钟 49.20 s、峰值 RSS 840748 KiB，确认共享前置未被分支污染。
复用交付的冷构建与独立 replay 证据，未再重建 IR 或生成相同路线；`git diff --check` 通过。
本轮详单：`/tmp/hsr_perf_round2_codex_review_{fast,integration}.log`、
`/tmp/hsr_perf_round2_reducer_differential.{py,json}`。以上均为临时证据，验收结论以本节为准。
