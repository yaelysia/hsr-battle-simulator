# P9-S8B6 旧任务拓扑退役与聚合审计执行卡

## 执行配置

- 对应问题：P9-I08；原 P9-S8B 的兼容债务清理和最终聚合。
- 硬前置：P9-S8B5 已验收并提交检查点。
- 推荐：5.6 Sol / `high` / 普通聚焦。
- 本卡不新增行为，只删除 B1 迁移期间保留的旧拓扑表示和消费者。
- 开工只读：本卡、B1 的迁移说明，以及 CodeGraph/`rg` 返回的
  `parent_task_id`、`child_task_ids`、`success_task_ids`、`failed_task_ids` 全部生产使用点。
  不读 B1-B5 历史验证器。

## 闭合地图

| 项目 | 本卡权威 |
|---|---|
| 唯一 runtime 拓扑 | S8B1 通用任务图 |
| 待退役对象 | AbilityTaskIR/StatusCallbackTaskIR 旧父子字段、codec、lowering 双写和残余生产消费者 |
| 保留来源 | 原始路径、节点身份和结构审计信息已在任务图来源账本中保留 |
| 聚合结果 | B1-B5 状态与当前旧权威残留审计形成 S8B 唯一完成账本 |
| 后续归属 | S8C 时序/RNG；其他领域 gap 保持原 owner，不在本卡修复 |

## 阶段目标

1. 从 `AbilityTaskIR` 和 `StatusCallbackTaskIR` 的公共模型、JSON codec 与构造器中删除旧
   `parent_task_id`、`child_task_ids`、`success_task_ids`、`failed_task_ids` 拓扑字段；不保留
   兼容别名、默认空字段或双写层。
2. lowering/compiler 只生产 S8B1 任务图拓扑。领域 task 只保留 leaf 执行与来源所需字段，不能
   继续携带另一份可推导父子结构。
3. 迁移或删除所有生产调用者。除 S8B1 materializer 和通用执行器读取任务图自身边外，
   `core/`、`systems/`、RuleBook 与 scenario 不得依据旧字段决定 root、后继、分支或执行状态。
   已知起始点至少包括 `core/executor.py::_ability_task_damage_graph_authoritative` 和
   `systems/status.py::_on_create_define_dynamic_values`；完整分母仍以当前 CodeGraph 结果为准。
4. 旧 JSON 字段必须被 exact-field codec 拒绝，不能静默忽略。历史验证器不是兼容目标；只有仍为
   active contract 且直接触达新模型的最小 fixture 才迁移。
5. 形成 S8B 聚合账本：B1 物化、B2 执行器、B3 ability、B4 status、B5 跨入口均为已验收检查点；
   当前旧拓扑模型/生产消费者为零；S8C 义务仍精确 deferred。

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
legacy_task_topology_model_field_count=0
legacy_task_topology_codec_field_count=0
legacy_task_topology_lowering_write_count=0
legacy_runtime_topology_consumer_count=0
task_graph_source_audit_remains_complete=true
legacy_json_payload_is_rejected=true
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

- [ ] 旧 task 拓扑模型、codec 和 lowering 双写已删除。
- [ ] 全部生产消费者只使用通用任务图权威。
- [ ] 来源审计仍完整，旧 payload 被严格拒绝。
- [ ] S8B 聚合账本闭合，S8C 义务保持诚实。
- [ ] 唯一主验证和资源门通过，提交 `ready_for_review`。
