# P9-S0 范围分类、非战斗退役与战斗数据投影执行卡

## 执行配置

- 对应问题：P9-I01；机制包 M00。
- 硬前置：P8 最终检查点已验收，P9 总计划已确认；记录实际起始 commit。
- 推荐：5.6 Sol / `max` / 普通聚焦。
- 理由：修改角色能力 compiler 的全局入口和范围传播，错误分类会让后续所有阶段产生假缺口或漏执行。

## 当前事实与阶段结果

当前 79 条目标角色加共享能力共 80 份来源，出现 44,700 个类型化节点和 2,462 个事件。
旧 lowering 的 blocked 清单仍混入动画、HUD、客户端 `_CL` 事件和投影节点；规划期分类尚未成为生产 compiler 契约。

完成后，compiler 对每个来源分支给出类型化范围：gameplay、build resolution、battle-data
projection、input projection、environment input、non-gameplay 或 decode-required。分支范围向
子节点传播，表现分支内出现的通用 opcode 不会重新获得 gameplay admission。战斗数据投影
形成正式 IR；原始 UI/客户端操作本身不执行。

## 详细目标

1. 建立角色能力窄发现/投影生产入口，只读取目标角色主文件与共享角色文件，不构建完整 Canonical IR。
2. 将现有范围分类转成单一 compiler 事实源；分类按 opcode 语义和完整分支，不按角色、文件名或固定数量。
3. 将特殊资源定义、目标持续性、单位拓扑和环境依赖投影为类型化 IR，runtime 不执行原始 UI/输入任务。
4. 对 presentation/client/AI/telemetry 分支生成结构化 non-gameplay 记录，零 mutation/event/gameplay RNG。
5. decode-required 保留完整字段、路径和父分支，不能落入 non-gameplay 或 executable。
6. 形成可被后续 S1-S18 复用的当前来源指纹、按 family 过滤的窄目录和小型 coverage summary。

## 本阶段不做

- 不接动作阶段、行迹、星魂或 runtime 效果。
- 不解释六个混淆族。
- 不执行能量条 UI、目标锁定控制器、动画等待或视觉弹道。
- 不建立验证缓存、全项目 registry 或完整 RuleBook。

## 架构与负例

- 同一 `AddModifier` 位于 gameplay 与 camera 分支时，前者保留、后者退役。
- `OnBreakExtendAnim` 若分支实际产生伤害/行动变化，必须保持 gameplay，不能按名称排除。
- `_CL` 事件、AI 和视觉随机不能进入战斗 dispatcher/RNG。
- 投影字段缺失、冲突或候选多义时 blocked，不能取第一项或补默认值。
- generic limit 不得截断角色范围后仍声称目录完整。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 来源闭包完整 | 当前目标角色与共享来源一一进入窄目录 | source inventory |
| 分支分类完整 | 每次类型节点和事件出现都有唯一有效范围 | scope reconciliation |
| 非战斗零副作用 | 排除分支不能进入 executable graph | negative matrix |
| 投影真实 | 每个投影回到 raw 字段且无 UI task 执行 | projection ledger |
| 未知诚实 | decode-required 完整保留且 fail-closed | decode matrix |
| 可复用窄入口 | 后续按 family 查询无需完整 lowering | build counters |

## 结构化通过谓词

```text
target_source_catalog_complete=true
typed_node_and_event_scope_reconciled=true
branch_scope_propagation_correct=true
non_gameplay_nodes_executable_count=0
non_gameplay_rng_consumption=0
battle_data_projection_source_backed=true
input_projection_does_not_execute_client_operation=true
decode_required_preserved=true
narrow_projection_full_lowering_count=0
limited_catalog_cannot_masquerade_as_complete=true
```

## Gap 与停止条件

- 分类只能靠角色/文件特判才能成立：停止，重做通用分类边界。
- 实际来源出现新范围且会改变产品边界：记录 `scope_decision_required` 并交用户裁决。
- 窄入口仍调用完整 `TBGDLowering.build()`：阶段阻断。
- 真实 gameplay 被归 non-gameplay 或投影数据无法闭合：阶段阻断。

## 拟改范围

- 新建或扩展 `tbgd/character_ability_scope.py`、`tbgd/character_cards.py`、`tbgd/lowering.py`。
- 必要时扩展 `rules/ir.py` / `rules/rulebook.py` 的范围与投影类型。
- 新增唯一主验证 `tools/validate_p9_s0_scope_and_projection_contract.py` 和报告。
- 不修改状态、伤害、事件 runtime。

## 验证与资源

- 主入口只读取 80 份目标来源一次，按原始字节计算指纹、按语义解析一次。
- 一个业务主入口；direct 仅在修改既有 projection IR codec 时追加对应小型 round-trip，最多 1 项。
- 预算：8 分钟、1 GiB RSS、5 MiB evidence、900 行验证代码；完整 lowering 0 次。
- 明确不跑 P1-P8 聚合、全角色场景出生、完整 RuleBook 和 runtime/replay。

## 唯一执行清单

- [x] 角色能力窄来源入口和当前指纹完整、确定。
- [x] 所有节点/事件按完整分支唯一分类，零遗漏。
- [x] 非战斗分支退役且零战斗副作用。
- [x] 战斗数据、输入和环境投影类型化且来源可追溯。
- [x] decode-required 与冲突来源保持 blocked。
- [x] 主验证、必要 direct、资源和通用性审计通过并提交 `ready_for_review`。
