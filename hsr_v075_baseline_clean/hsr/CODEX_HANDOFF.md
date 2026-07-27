# v8 工程交接手册

## 当前状态

主线是 `simulator_v8_clean_core`，事实来源固定为：

```text
turnbasedgamedata-main -> compiler/lowering -> Canonical IR -> Combat Core
```

最近检查点：

```text
checkpoint(v8): accept VG-S2 committed integrity lifecycle pilot
```

已验收的主要底座：

- P1 最小完整战斗纵切。
- P2 状态系统通用底座。
- P4 角色卡 / 怪物卡数据卡边界。
- P5 公式、动态值和参数绑定通用准入。
- P6 架构边界回正。
- P7-S0 至 P7-S19 内核可信执行与当前准入战斗语义。
- P8-S0 至 P8-S8 光锥定义、实例、装配和机制闭合。
- CHAR-M1 记忆角色与忆灵 owned-combatant 构筑底座。

必须保留的限定：

- P3 历史检查点采用 P7 前口径；servant action graph 仍有真实内容缺口，不能称为完整继承。
- P1-P7 完成的是底座和当前准入语义，不代表全角色、全怪物、全关卡和全部特殊模式完成。
- P8-S8 已证明当前光锥机制图闭合，不等于所有正式角色构筑和完整目录启动都已得到最终证据。

## P8-R1 裁决

P8-R1 的生产修复已完成聚焦验收：

- 正式状态在 provider 和开局事件前具有合法空召唤 runtime。
- 目标系统区分合法空集合与关系损坏。
- 召唤登记与 UnitState 双向核对 owner、summoner、kind、team 和生命周期。
- 通用 halo relation 支持成员加入、离开、波次切换、来源退场、事件派发、settlement、RNG 与 replay。
- 联合伪造归属、缺失召唤者和阵营伪造均 fail-closed。
- 波次光环生命周期事件不再重复，8 条事件对应 8 条派发记录。

已复核：

```text
P8-R1 runtime-only: ok=true
P7-S3: 9/9
P7-S15: 14/14
git diff --check: pass
```

当前已发布光锥的完整正式目录启动因旧验证内存成本过高，按用户决定记为：

```text
deferred / not_proven
```

这不是已确认的生产代码失败，但在新的低内存目录验证完成前，不得宣称 `formal_catalog_startup_complete=true`。P8 总 checklist 中“全部正式启动”的原条目仍不能仅凭聚焦验证打勾。

## 当前工作

当前优先事项是 `VG` 验证治理与状态完整性回正：

1. `VG-S0` 已通过验收，确认 committed state 嵌套别名、原子提交缺少领域
   完整性门、事件 closure 所有权冲突以及重复完整 lowering 是当前主要根因。
2. `VG-S1` 已通过验收：UnitState、BattleState、Snapshot、codec 和 reducer
   的递归不可变、输入别名隔离、独立 JSON 输出与结构共享边界已经闭合。
3. `VG-S2` 已通过验收：单位生命周期已迁移为类型化唯一权威，touched-domain
   integrity gate、完整批次 replay、atomic failure 和场景双 full-check 边界已闭合。
4. `VG-S3` 已通过验收：首批模式级 validator registry、类型化资源需求、纯
   dry-run 选择入口、历史验证隔离和候选构建分组已经闭合；选择过程不会执行
   validator、读取 TBGD 或构建 RuleBook。
5. 下一步只规划并确认 `VG-S4` 事件 closure 所有权回正执行卡；实际共享
   lowering/RuleBook 仍属于 `VG-S6`，不得提前混入 `VG-S4`。
6. 目录验证限峰和共享构建在状态/验证基础边界稳定后推进，再用于后续 P8 遗器
   阶段试点。

遗器轨 P8-S9 至 S17 仍按 `docs/p8_execution_cards/` 中的单阶段执行卡推进。S18 是光锥与遗器汇合阶段。

## 仍未完成的大块

- P8-S9 至 S17：遗器定义、实例、主副词条、升级、套装和动态机制。
- P8-S18 至 S21：构筑汇合、正式 scenario、希儿完整示例和当前来源聚合。
- 剩余记忆角色 / 忆灵的属性、时间线和出生来源扩面。
- 全角色、全怪物、全关卡和环境内容卡。
- 目标、波次、召唤、特殊事件源和特殊玩法的剩余真实来源扩面。
- P5/P3/P4 留存的已归因内容 gap。
- 外部推演器和正式 UI 接口。

敌方 AI 不进入 core。外部推演器负责像玩家一样选择敌我双方动作，内核负责给出合法动作、目标和确定性结算。

## 任务入口

不要默认通读所有文档。根据任务选择：

- 阶段实施：只使用经用户确认的当前执行卡；目前没有已确认的下一阶段执行卡。
- 架构修改：`ARCHITECTURE_BOUNDARY_CONTRACT.md`、`FORBIDDEN.md`。
- 规划、验收、验证治理：`docs/AGENT_WORKFLOW_AND_VALIDATION.md`。
- VG 总方案：`VALIDATION_GOVERNANCE_AND_STATE_INTEGRITY_PLAN.md`。
- VG 已验收基线：`docs/validation_execution_cards/VG-S3_VALIDATOR_REGISTRY_AND_SELECTION_ENTRY.md`。
- VG 下一步：根据总方案编写并确认 `VG-S4` 事件 closure 所有权回正执行卡，
  确认前不修改代码。
- 当前文档导航：`DOCUMENTATION_INDEX.md`。
- P8：`P8_EQUIPMENT_BUILD_LIGHT_CONE_RELIC_TASK_PLAN.md` 和当前阶段卡。
- 历史追溯：对应 checkpoint 或 `docs/archive/`，按关键词读取。

## 工作边界

- runtime 不读 raw TBGD、TextMap、旧 v7 或旧 model pack。
- 内容专属规则进入数据卡和机制图，不进入核心特判。
- 缺来源或语义不完整必须 blocked/state unchanged。
- UI 和推演器不能复刻规则。
- 验收必须看代码和负例，报告与 `ok=true` 只是证据索引。
- 默认只跑当前阶段聚焦验证及直接触达回归；重验证需说明必要性并串行限流。
- 执行线程只提交 `ready_for_review`；验收线程负责裁决、checklist 和检查点提交。

瘦身前的完整交接历史保存在：

```text
simulator_v8_clean_core/docs/archive/CODEX_HANDOFF_PRE_SLIM_2026-07-24.md
```

仅在追溯旧阶段数据和决策时按关键词读取。
