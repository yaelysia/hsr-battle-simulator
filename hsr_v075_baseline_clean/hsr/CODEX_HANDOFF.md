# v8 工程交接手册

## 当前状态

主线是 `simulator_v8_clean_core`，事实来源固定为：

```text
turnbasedgamedata-main -> compiler/lowering -> Canonical IR -> Combat Core
```

最近已验收生产检查点：

```text
d29b34b checkpoint(v8): accept VG-S2 committed integrity lifecycle pilot
```

验证治理路线回正：

```text
9c8ac45 Revert "checkpoint(v8): accept VG-S3 validator registry and selection"
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
- VG-R1 P8-S8 task/event 共享证据与 owned-combatant 窄投影试点。

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

VG-R1 的低内存未过滤组合已经首次在当前源码上完整进入 task/event 业务谓词。
目录状态不再只是“未运行”：

```text
P8-R1 runtime-only = accepted
P8-R1 catalog = confirmed incomplete
```

当前失败集中在两条动态值任务 family 和一条死亡回响事件 family，对应 CHAR-M1
曾记录的记忆光锥 / 忆灵正式场景缺口。它们不是 VG-R1 窄投影制造的新回归，也
不能再记为单纯 `not_proven`。P8-R1 中“三张真实光锥与完整目录收口”继续未完成，
后续必须单独修复；P8 总 checklist 不得打勾。

## 当前工作

当前优先事项是 `VG` 验证治理与状态完整性回正：

1. `VG-S0` 已通过验收，确认 committed state 嵌套别名、原子提交缺少领域
   完整性门、事件 closure 所有权冲突以及重复完整 lowering 是当前主要根因。
2. `VG-S1` 已通过验收：UnitState、BattleState、Snapshot、codec 和 reducer
   的递归不可变、输入别名隔离、独立 JSON 输出与结构共享边界已经闭合。
3. `VG-S2` 已通过验收：单位生命周期已迁移为类型化唯一权威，touched-domain
   integrity gate、完整批次 replay、atomic failure 和场景双 full-check 边界已闭合。
4. 原 `VG-S3` validator registry 路线已撤销。它新增 5,110 行治理与元验证代码，
   却没有同轮减少真实重构建和历史脚本，不能恢复或继续扩展。
5. `VG-R1` 已通过验收：task/event 不再调用完整 `TBGDLowering.build()`，五类
   servant 准入数据改走来源真实的窄投影。
6. 窄投影、focused bundle 和公共证据均只构建 1 次；最终未过滤组合峰值
   588,188 KiB，旧完整 build 的 4,137,552 KiB `MemoryError` 保留为成本基线。
7. 验证 Python 净减少 3 行，production 与 validation 总净增长 320 行；没有
   恢复深冻结、来源审计、registry、selector 或元验证框架。
8. CLI 只按业务 `ok` 退出；`governance_ok` 不能把业务失败标绿。已知 P8-R1
   缺口只作为失败上限，允许后续减少至零。
9. 未过滤组合暴露的三类 P8-R1 业务失败只做归因，不在 VG-R1 中修改游戏语义。
10. 当前没有自动衔接的第二张治理执行卡。若继续治理，必须先选择第二个真实重复点
    并证明其与 VG-R1 具有相同生命周期，不能直接规划全项目框架。

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

- VG-R1 已验收执行卡：
  `docs/validation_execution_cards/VG-R1_P8_S8_TASK_EVENT_SHARED_EVIDENCE_PILOT.md`。
- 架构修改：`ARCHITECTURE_BOUNDARY_CONTRACT.md`、`FORBIDDEN.md`。
- 规划、验收、验证治理：`docs/AGENT_WORKFLOW_AND_VALIDATION.md`。
- VG 总方案：`VALIDATION_GOVERNANCE_AND_STATE_INTEGRITY_PLAN.md`。
- VG 已验收基线：`docs/validation_execution_cards/VG-S2_COMMITTED_INTEGRITY_LIFECYCLE_PILOT.md`。
- VG-R1 验收报告：
  `live_validation_reports/v8_vg_r1_p8_s8_task_event_shared_evidence_ready_for_review.md`。
- 已撤销路线：原 VG-S3 registry/selector/meta-validator，不得恢复。
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
