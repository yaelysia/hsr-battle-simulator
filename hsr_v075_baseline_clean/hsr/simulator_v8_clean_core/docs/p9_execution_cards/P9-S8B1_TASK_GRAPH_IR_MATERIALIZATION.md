# P9-S8B1 任务图 IR 与物化边界执行卡

## 执行配置

- 对应问题：P9-I08；原 P9-S8B 的数据权威部分。
- 硬前置：P9-S8A 检查点 `e513b79`，以及其后发现的
  `P9-S8A-R1_CONTROL_FLOW_DENOMINATOR_COMPLETENESS.md` 必须先验收并提交检查点。
- 推荐：5.6 Sol / `high` / 普通聚焦；不使用长时间 Goal。
- 本卡只建立任务图 IR、物化结果和查询权威，不修改任何 runtime 执行行为。
- 开工只读：本卡、S8A 卡、`rules/control_flow_contract.py`、
  `tbgd/character_control_flow_contracts.py`、`AbilityTaskIR`、`StatusCallbackTaskIR`、
  `CanonicalIR` 和 RuleBook 对应索引。禁止通读旧验证器或恢复 2026-08-12 中间 patch。

## 闭合地图

| 项目 | 本卡权威 |
|---|---|
| 完整分母 | 已验收 `CharacterControlFlowContractCatalog` 中全部直接节点、template、引用及义务 |
| 正式物化输入 | 调用者明确选择的 ability phase 或 status callback entry；不得由验证器手拼第二套来源 |
| 生产输出 | 递归不可变的通用任务图、来源发生账本、正式物化账本、结构化 blocked 结果 |
| 身份 | 来源发生身份与正式图/节点身份分离；同一来源可被不同正式入口引用但不可静默覆盖 |
| 正式调用者 | Canonical IR 序列化、RuleBook 窄查询、后续 S8B2 执行器 |
| 后续归属 | 执行语义归 S8B2；ability/status 迁移归 S8B3/S8B4；命中、随机、parallel、barrier 归 S8C |

## 阶段目标

1. 建立一套领域中立的任务图 IR，表达有序序列、确定性二选一、固定/条件/目标迭代、
   template 实例和子图调用。节点只能引用既有 condition、target、numeric、effect 或 ability
   定义，不能复制其 payload。
2. 建立两种不可混淆的身份：
   - 来源发生身份由来源路径、对象位置、family 和内容指纹决定。
   - 正式物化身份由正式入口、owner、callback/phase 和物化节点位置决定。
3. 建立完整来源责任账本。S8A 完整分母中的每一项必须恰好得到一个结果：已物化、因精确
   下游阶段保留、或因来源/引用矛盾 blocked。账本计数相等不能替代逐项身份闭合。
4. 建立显式 scope：
   - `complete_catalog` 只生成完整责任账本，不伪装成 runtime 图集合。
   - `formal_slice` 只物化调用者明确选择的正式入口，并记录该选择的来源和完整性。
   限量 slice 不得标记为完整目录。
5. Canonical IR 保存任务图及物化账本，RuleBook 提供按图身份、正式入口和节点身份的类型化
   唯一查询。缺失、重复、跨入口冲突和错误类型均结构化 blocked，禁止取第一项。
6. 所有模型递归不可变、exact-field JSON round-trip、稳定排序和稳定 fingerprint；外部容器修改
   不得影响结果。
7. B1-B5 迁移期间，旧 task 的父子字段仅为现有 runtime 的临时只读输入；新任务图必须由同一
   物化结果生成并逐项核对，禁止独立双写。B6 必须删除这组临时拓扑字段和构造路径，B1 不能把
   它们宣布为长期兼容接口。

## 生产边界必须拒绝

- 重复来源发生身份或重复正式物化身份。
- root 缺失、多 root 歧义、悬空 child、同 child 多父、跨图 child、非法自环或递归 template 环。
- 来源指纹、snapshot 身份、入口 owner、callback/phase 与节点来源不一致。
- 未准入的 condition/target/numeric/effect/ability 引用被标成可执行。
- S8C 专属节点被伪装成 S8B 可执行节点。
- `formal_slice` 被序列化为完整目录，或 blocked 图仍携带正式可执行 root。
- 旧任意字典 payload、未知字段、可变嵌套对象和伪造来源。

任一失败都不得返回半成品图或可查询的正式节点集合。

## 本卡明确不做

- 不新增 `systems/task_graph.py`，不执行任何 task，不产生 mutation、event、RNG 或 settlement。
- 不修改 `AbilityTaskSystem`、`StatusCallbackSystem`、scheduler、event dispatcher 或 reducer。
- 不删除现有领域解释器；消费者迁移由 S8B3/S8B4 完成。
- 不实现 projectile、RandomConfig、parallel、Wait/barrier。
- 不改变 S8A 的来源分类。若必须修改 `character_control_flow_contracts.py` 才能施工，返回
  `plan_mismatch`，由规划线程判断 S8A 是否需要重新验收。

## 允许修改的生产范围

- 新增 `rules/task_graph.py`。
- 新增 `tbgd/task_graph_materializer.py`。
- 最小修改 `rules/__init__.py`、`rules/ir.py`、`rules/rulebook.py`、`tbgd/lowering.py`。

如需修改两个以上未列出的生产文件，或需要同时设计 runtime 协议，立即返回 `plan_mismatch`；
不得自行扩大范围。

## 验收谓词

```text
complete_s8a_denominator_has_exactly_one_materialization_disposition=true
source_occurrence_and_formal_materialization_identity_are_distinct=true
formal_slice_cannot_masquerade_as_complete_catalog=true
task_graph_models_are_typed_and_recursively_immutable=true
graph_and_reference_conflicts_fail_closed=true
s8c_nodes_remain_precisely_deferred=true
canonical_ir_round_trip_preserves_task_graphs=true
rulebook_queries_are_unique_and_type_safe=true
runtime_behavior_changed=false
full_canonical_ir_build_count=0
```

## 验证与止损

- 一个主入口：`validate_p9_s8b1_task_graph_ir_materialization.py`。
- 一次 S8A 完整来源目录；正式图只动态选择少量结构不同的 slice，不固定角色、ID 或文件。
- 独立验证分母从 S8A catalog 重建，不从生产物化结果反推。
- 每条新生产不变量只保留一个最小负例；不构造战斗场景，不运行 runtime direct。
- 预算：75 秒、640 MiB、512 KiB evidence、验证器目标不超过 350 非空行。
- 主入口只允许在生产自审完成后运行一次。若只因验证器断言错误需要第二次，先交规划/验收线程
  批准；生产或来源失败不得靠反复主入口调试。
- 开工 30 分钟内完成闭合地图核对，45 分钟内必须形成可编译的模型、一个正式物化正例和一个
  构造边界负例。否则停止并返回 `plan_mismatch` 或 `context_gap`，不得继续长时间探索。

## 唯一执行清单

- [ ] 通用任务图、来源发生身份和正式物化身份完成类型化。
- [ ] 完整 S8A 分母逐项得到唯一、可反查的责任结果。
- [ ] Canonical IR 与 RuleBook 查询完成闭合且冲突 fail-closed。
- [ ] runtime 未改变，S8C 节点未伪执行。
- [ ] 唯一主验证和资源门通过，提交 `ready_for_review`。
