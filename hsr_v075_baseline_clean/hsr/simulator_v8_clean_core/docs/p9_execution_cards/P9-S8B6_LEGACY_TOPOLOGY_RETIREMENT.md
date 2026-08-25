# P9-S8B6 旧任务拓扑退役与聚合审计执行卡

状态：`accepted`。验收报告见
`live_validation_reports/P9-S8B6_LEGACY_TOPOLOGY_RETIREMENT_ready_for_review.md`。

## 执行配置

- 对应问题：P9-I08；原 P9-S8B 的兼容债务清理和最终聚合。
- 硬前置：P9-S8B5 已验收并提交检查点。
- 推荐：5.6 Sol / `high` / 普通聚焦。
- 本卡不新增行为，只删除 B1 迁移期间保留在 P9 正式角色/状态路径中的旧拓扑写入与消费者。
  公共 task 字段仍被未纳入 S8A 分母的外部内容域使用时不得全局删除；该条件分支以本卡第 2 项
  和 S8B3 已验收边界为准。
- 开工只读：本卡、B1 的迁移说明，以及 CodeGraph/`rg` 返回的
  `parent_task_id`、`child_task_ids`、`success_task_ids`、`failed_task_ids` 全部生产使用点。
  不读 B1-B5 历史验证器。

## 闭合地图

| 项目 | 本卡权威 |
|---|---|
| 唯一 runtime 拓扑 | S8B1 通用任务图 |
| 待退役对象 | P9 角色和状态来源分母中的旧父子权威、lowering 双写和残余生产消费者 |
| 保留来源 | 原始路径、节点身份和结构审计信息已在任务图来源账本中保留 |
| 聚合结果 | B1-B5 状态与当前旧权威残留审计形成 S8B 唯一完成账本 |
| 后续归属 | S8C 时序/RNG；其他领域 gap 保持原 owner，不在本卡修复 |

## 阶段目标

1. 对 S8A 完整角色来源分母和 S8B4 状态分母，移除 runtime 对旧
   `parent_task_id`、`child_task_ids`、`success_task_ids`、`failed_task_ids` 的控制依赖；缺正式图
   必须 blocked，不能回退。
2. 若怪物、关卡或其他未纳入当前来源图的内容仍构造同一公共 task 类型，暂不全局删除公共字段；
   必须形成类型化 `external_content_dependency` 账本，并把最终公共模型删除交给对应内容来源闭包。
   不得为制造“字段为零”而破坏外部内容。
3. 迁移或删除所有生产调用者。除 S8B1 materializer 和通用执行器读取任务图自身边外，
   `core/`、`systems/`、RuleBook 与 scenario 不得依据旧字段决定 root、后继、分支或执行状态。
   已知起始点至少包括 `core/executor.py::_ability_task_damage_graph_authoritative` 和
   `systems/status.py::_on_create_define_dynamic_values`；完整分母仍以当前 CodeGraph 结果为准。
4. P9 正式 task 不再写入旧拓扑字段，正式任务图 exact-field codec 必须拒绝夹带旧拓扑字段的
   payload。公共 task JSON 中仍由外部内容保留的字段必须进入依赖账本，不得伪称已经全局退役。
   历史验证器不是兼容目标；只有仍为 active contract 且直接触达新模型的最小 fixture 才迁移。
5. 形成 S8B 聚合账本：B1、B2、B3A-C、B4、B5 均为已验收检查点；P9 角色/状态旧 runtime
   消费者为零；外部内容字段与消费者有精确来源范围和 owner；S8C 义务仍精确 deferred。

## 本卡明确不做

- 不改变图节点 kind、分支/循环/调用语义或领域 leaf 行为。
- 不修复在审计中暴露的其他领域 gap；按既有 owner 列账。
- 不重跑 B1-B5 主入口，不运行完整 Canonical lowering 或历史聚合。
- 不为了旧工具、旧 fixture 或未使用外部接口保留兼容层。

## 允许修改的生产范围

- `rules/ir.py`、`rules/rulebook.py`
- `tbgd/lowering.py` 和 S8B1 materializer
- CodeGraph 确认仍读旧字段的 `core/`、`systems/` 生产文件，仅限删除/改用既有任务图 API

若审计发现仍需新增任务图语义、跨入口协议或领域 admission，返回对应 B1-B5 的
`plan_mismatch`；不得在清理卡内实现。

## 验收谓词

```text
p9_character_legacy_runtime_fallback_count=0
p9_status_legacy_runtime_fallback_count=0
external_content_legacy_dependency_ledger_complete=true
uncovered_content_domain_was_not_broken=true
task_graph_source_audit_remains_complete=true
formal_task_legacy_topology_population_count=0
task_graph_json_rejects_legacy_topology_payload=true
s8b_substage_ledger_is_complete=true
s8c_obligations_remain_precise_and_unexecuted=true
prior_substage_main_rerun_count=0
```

## 验证与止损

- 一个主入口：`validate_p9_s8b6_legacy_topology_retirement.py`。
- 主证据是公共模型 round-trip、一个旧 payload 拒绝负例、CodeGraph/AST 生产残留审计和 B1-B5
  已验收状态读取；不再构造战斗行为矩阵。
- 预算：30 秒、384 MiB、256 KiB evidence、验证器目标不超过 150 非空行。
- 45 分钟内必须完成模型字段与 lowering 双写删除并通过 compileall；若调用者迁移要求新行为，
  立即停止返回规划线程，不得用兼容字段过渡。

## 唯一执行清单

- [x] P9 正式 task 的旧拓扑 lowering 双写已删除；公共字段仅由账本列明的外部内容保留。
- [x] P9 正式角色/状态生产消费者只使用通用任务图权威；外部旧域均由类型化分流和账本约束。
- [x] 来源审计仍完整，正式任务图旧 payload 被严格拒绝。
- [x] S8B 聚合账本闭合，S8C 义务保持诚实。
- [x] 唯一主验证和资源门通过，提交 `ready_for_review`。
