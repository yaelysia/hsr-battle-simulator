# v8 工程交接手册

## 当前状态

主线是 `simulator_v8_clean_core`，事实来源固定为：

```text
turnbasedgamedata-main -> compiler/lowering -> Canonical IR -> Combat Core
```

最近已验收生产检查点：

```text
P8-S9 本检查点（父检查点：61c946f）
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
- P8-R1-RUNTIME 与 P8-R2 召唤光环、记忆光锥事件链及当前光锥目录启动收口。
- CHAR-M1 记忆角色与忆灵 owned-combatant 构筑底座。
- VG-R1 P8-S8 task/event 共享证据与 owned-combatant 窄投影试点。

必须保留的限定：

- P3 历史检查点采用 P7 前口径；servant action graph 仍有真实内容缺口，不能称为完整继承。
- P1-P7 完成的是底座和当前准入语义，不代表全角色、全怪物、全关卡和全部特殊模式完成。
- P8-S8 与 R2 已证明当前光锥机制图和 162 张已发布光锥目录启动闭合，不等于所有正式角色构筑、遗器或完整 P8 构筑链已经完成。

## P8-R1 / P8-R2 裁决

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

VG-R1 曾确认两条动态值任务和一条死亡回响事件 family 失败。P8-R2 已完成：

- 两个动态值任务通过正式忆灵动作执行。
- 死亡回响通过连续正式动作、规范死亡事件和通用事件身份链执行。
- 同身份不同内容的事件在提交前 fail-closed，不产生 mutation、event 或 RNG。
- VG-R1 临时允许失败集合已删除，没有留下替代豁免。
- 当前 162 张已发布光锥全部完成正式目录启动，装备失败和外部依赖均为零。
- R2 聚焦验证峰值约 572 MiB；目录启动峰值约 885 MiB，完整 lowering 均为零。

## 当前工作

光锥轨已经推进至 R2 并验收，`P8-S9` 遗器定义卡与 `P8-S10` 遗器实例合法性也已验收。
当前顺序上的下一阶段是 `P8-S11` 主词条合法池与精确数值；S11 至 S17 继续按
`docs/p8_execution_cards/` 中的单阶段执行卡严格推进。

P8-S9 当前事实：

- 已从当前来源完整建立 726 个遗器模板、6 个真实槽位、58 个套装和 90 个套装档位。
- 模板、主副词条组、内外圈域和套装档位均进入类型化 Canonical IR 与 RuleBook，目录引用问题和已发布模板 blocked 均为零。
- 内外圈由套装成员的真实槽位关系推导；特殊模板模式已分类，未知模式 fail-closed。
- 套装档位的静态成员与动态 ability 来源均保留，但 S9 不创建机制图、不执行套装效果。
- 光锥与遗器共用严格能力来源边界，只接受真实 TBGD 来源或显式验证 fixture，派生伪来源会被拒绝。
- 独立验收为 21/21 契约检查、12/12 负例通过；单次聚焦验证约 1.75 秒、峰值约 79 MiB。

P8-S10 当前事实：

- 正式构筑支持零至六件遗器骨架，槽位、等级、实例身份和队伍占用在装配边界 fail-closed。
- `CUSTOM` 只保留在 S9 来源目录中，正式玩家构筑一律拒绝；不实现生成、映射或 BASIC fallback。
- 主副词条合法性仍 deferred 到 S11/S12，因此非空遗器构筑可完成结构装配，但不能进入正式战斗。
- S10 聚焦差量验证峰值约 71 MiB，完整 lowering 为零；不得在后续阶段继续扩张或复制其大型阶段验证器。

2026-07-28 已重新审查并统一改写 S9-S21 的执行与验证口径：

- 每阶段只有一个业务主验证；完整入口最多一次诊断运行和一次最终运行。
- 前序检查点默认继承，direct 只由实际修改的共享调用链触发且最多两项。
- S9-S20 禁止把历史阶段验证当固定套餐；S21 只做一次 preflight 和一次共享 final。
- 每张执行卡均写明墙钟、峰值 RSS、累计验证时间和默认产物硬上限，超限必须暂停重新拆分。
- 详细规则以 `docs/p8_execution_cards/README.md` 第 6 节和当前阶段卡为准，不得恢复旧未过滤、九族或逐阶段重跑路径。

必须保留：

1. 不因光锥目录已闭合而提前宣称 P8 完成；遗器与最终构筑汇合尚未实施。
2. R2 退役的未过滤聚合、九族组合和 VG-S3 registry 路线不得恢复。
3. S18 是光锥与遗器硬汇合点，只有 R2 与 S17 的检查点都在同一分支后才能开始。
4. 若继续验证治理，必须先证明新的真实重复点与现有共享证据具有相同生命周期。

## 仍未完成的大块

- P8-S11 至 S17：遗器主副词条、升级、套装和动态机制。
- P8-S18 至 S21：构筑汇合、正式 scenario、希儿完整示例和当前来源聚合。
- 剩余记忆角色 / 忆灵的属性、时间线和出生来源扩面。
- 全角色、全怪物、全关卡和环境内容卡。
- 目标、波次、召唤、特殊事件源和特殊玩法的剩余真实来源扩面。
- P5/P3/P4 留存的已归因内容 gap。
- 外部推演器和正式 UI 接口。

敌方 AI 不进入 core。外部推演器负责像玩家一样选择敌我双方动作，内核负责给出合法动作、目标和确定性结算。

## 任务入口

不要默认通读所有文档。根据任务选择：

- 当前 P8-S11 执行卡：
  `docs/p8_execution_cards/P8-S11_RELIC_MAIN_AFFIX.md`。
- P8-S9 至 S21 的统一验证预算和执行索引：
  `docs/p8_execution_cards/README.md`。
- 已验收 P8-R2 执行卡与最终差量：
  `docs/p8_execution_cards/P8-R2_MEMORY_LIGHT_CONE_FORMAL_EVENT_CHAIN_CLOSURE.md`、
  `docs/p8_execution_cards/P8-R2_REVIEW_DELTA_AFTER_UNFILTERED_FAILURES.md`。
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
