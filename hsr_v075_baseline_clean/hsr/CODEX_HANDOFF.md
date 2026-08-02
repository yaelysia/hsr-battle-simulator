# v8 工程交接手册

## 当前状态

主线是 `simulator_v8_clean_core`，事实来源固定为：

```text
turnbasedgamedata-main -> compiler/lowering -> Canonical IR -> Combat Core
```

最近已验收生产基线：

```text
P8-S0 至 P8-S21、P8-R1 和 P8-R2 已通过当前源码最终聚合验收
P8-S20 检查点：afe6f7b
P8 最终结论：live_validation_reports/v8_p8_equipment_build_light_cone_relic_final_checkpoint.md
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
- P8-S9 至 P8-S17 遗器定义、正式实例、主副词条、套装档位统计、统一静态贡献账本、动态能力启动以及当前全部套装 gameplay 机制。
- P8-S18 至 P8-S21 构筑汇合、失败原子性、希儿完整示例和当前来源最终聚合。
- CHAR-M1 记忆角色与忆灵 owned-combatant 构筑底座。
- VG-R1 P8-S8 task/event 共享证据与 owned-combatant 窄投影试点。

必须保留的限定：

- P3 历史检查点采用 P7 前口径；servant action graph 仍有真实内容缺口，不能称为完整继承。
- P1-P7 完成的是底座和当前准入语义，不代表全角色、全怪物、全关卡和全部特殊模式完成。
- P8 完成只表示当前装备来源和战斗消费链闭合；不包含角色动作图扩面、怪物卡、关卡、刷取养成、背包、自动配装或 UI。

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

P9 非记忆、非欢愉角色共享机制收口已完成 P9-S0、P9-S1、P9-S2、P9-S3 验收。当前 79 条已发布目标角色记录
和一份共享角色能力已形成来源字节闭合、分支范围完整、可按 family 过滤的窄目录；10,432 条
非战斗记录已退役，435 条战斗数据/输入/环境投影已类型化，213 条混淆来源继续诚实 blocked。
S1 在同一来源闭包上建立了唯一能力来源图：1,440 个能力定义、440 个战斗动作来源和 79 个
地图普攻退役来源均有类型化身份；1,522 条关系唯一解析，41 条真实关系缺口保留来源并阻断，
`lowering_gap=0`。S2 将 337 个行迹选择和 564 个星魂选择全部闭合为来源可追查的最终构筑
关系，当前关系 gap 为 0；静态贡献、技能等级、动态图根与未准入诊断分通道，正式 runtime
不再解释旧 rank/行迹 flags。S3 动态重算出 7 个待裁决家族、213 条记录：4 个家族、207 条记录
已形成类型化但尚未准入 runtime 的下游责任包，3 个家族、6 条记录继续来源阻断；完整能力包检索
确认 4 个引用无定义候选，另有 6 个既有关系归属缺口继续阻断，未发现来源包截断。动态图执行仍由
S4-S17 负责，因此当前正式构筑会诚实阻止未闭合角色出生。共享 graph 只构建一次，角色卡只引用；
缺失或多义子能力在任何 phase/task 生成前 fail-closed。记忆与欢愉专属机制继续延期。总计划位于
`simulator_v8_clean_core/P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md`，S0-S20 单阶段
执行卡入口位于 `simulator_v8_clean_core/docs/p9_execution_cards/README.md`。下一步只能基于 S3
检查点执行 P9-S4 数值表达式和动态值通用闭合，不能提前实现 S5-S17 runtime 语义。

光锥轨已经推进至 R2 并验收，`P8-S9` 至 `P8-S17` 的遗器定义、实例、词条、套装统计、静态贡献、动态能力启动以及当前全部套装 gameplay 机制也已验收。`P8-S18` 已完成光锥与遗器构筑汇合：角色、光锥、行迹、遗器和套装使用统一贡献账本生成最终面板，正式出生在入场结算后按最终速度初始化时间线。

P8 装备阶段已完成最终收口。当前 source fingerprint `39b5d5d55a5d4d7e9a3739a5de098944b5851593de0f2311ffa661fe384a346a` 下，162 张已发布光锥、720 个普通玩家遗器模板、117 个主词条、48 个副词条、58 套遗器及 90 个套装档位均已进入正式定义、装配、runtime、来源审计和 replay 链；光锥与套装 gameplay gap、unknown 和 partial graph 均为 0。6 个 `CUSTOM` 模板保留真实来源但明确拒绝正式玩家构筑。希儿完整装备纵切通过；其角色动作图仍归后续角色卡内容阶段，不是 P8 缺口。最终结论见 `live_validation_reports/v8_p8_equipment_build_light_cone_relic_final_checkpoint.md`。

P8-S16 / S17 当前事实：

- 已从当前来源完整建立 726 个遗器模板、6 个真实槽位、58 个套装和 90 个套装档位。
- 模板、主副词条组、内外圈域和套装档位均进入类型化 Canonical IR 与 RuleBook，目录引用问题和已发布模板 blocked 均为零。
- 内外圈由套装成员的真实槽位关系推导；特殊模板模式已分类，未知模式 fail-closed。
- 套装档位的静态成员与动态 ability 来源均保留，但 S9 不创建机制图、不执行套装效果。
- 光锥与遗器共用严格能力来源边界，只接受真实 TBGD 来源或显式验证 fixture，派生伪来源会被拒绝。
- 独立验收为 21/21 契约检查、12/12 负例通过；单次聚焦验证约 1.75 秒、峰值约 79 MiB。

P8-S10 当前事实：

- 正式构筑支持零至六件遗器骨架，槽位、等级、实例身份和队伍占用在装配边界 fail-closed。
- `CUSTOM` 只保留在 S9 来源目录中，正式玩家构筑一律拒绝；不实现生成、映射或 BASIC fallback。
- S13 已完成套装档位统计，S14 已将合法主副词条和已激活套装静态项逐项接入统一账本。
- S10 聚焦差量验证峰值约 71 MiB，完整 lowering 为零；不得在后续阶段继续扩张或复制其大型阶段验证器。

P8-S11 当前事实：

- 六部位主词条由模板分组、真实部位池和来源投影的稀有度关系共同准入。
- 主词条按强化等级使用 Decimal 计算完整精度值，结果保留模板、部位、分组和词条来源。
- 身份错配、来源指纹混合、跨槽、跨组和稀有度不一致均结构化 blocked，不产生中间值或正式贡献。
- S11 主验证 16/16，通过 S9 真实目录、S10 level-mode 和 S1 类型 round-trip 定向回归；验证器 898 非空行，完整 lowering 为零。

P8-S12 当前事实：

- 遗器作为自定义成品战斗输入；不模拟掉落、初始词条、强化节点、材料、整件 roll 预算或生成历史。
- 每条副词条由真实定义、整数 count 和累计 step 计算完整精度值；同 affix、同 property、主副同 property、错误分组和第五项均 fail-closed。
- 直接计算入口会从 RuleBook 重新闭合模板与主词条的身份、内容、来源和 fingerprint；同 ID 伪造不能绕过。
- 非空合法遗器形成只读 selection，随后由 S13 统计套装门槛、S14 生成逐项静态贡献；旧 `relic_assembly` 等待语义不再是当前正式装配路径。
- 最终聚焦验证 19/19，通过独立 raw oracle；单次约 0.64 秒、峰值约 67 MiB，完整 Canonical IR 和完整 RuleBook 构建均为零。

P8-S13 当前事实：

- 套装统计只消费完整 admitted 的成品遗器，并从 RuleBook 重新闭合模板、槽位、套装、域和全部门槛定义。
- 外圈四件、2+2、2+1+1、散件，内圈配对、错配和单件部分装备均按数据门槛计算；高门槛不会覆盖已满足低门槛。
- 激活决定保留定义来源和贡献实例，进入装配结果 fingerprint；缺失决定通道、伪造身份、未发布套装和非法实例均原子 blocked。
- 最终差量授权验证 22/22，通过；单次约 0.43 秒、峰值约 63 MiB，目录和 RuleBook 各构建一次。
- S14 已应用套装静态属性；已激活档位中的动态 ability 仍结构化阻断并等待 S15。

P8-S14 当前事实：

- 每个主词条、每条副词条和每个已激活套装静态项分别生成统一 `StaticStatContribution` 与来源账本项，不按属性预合并。
- 未激活档位零贡献；高档激活不覆盖已满足低档；静态与动态并存时只装配静态部分。
- 当前来源出现的 23 类遗器静态属性均已映射到通用属性通道；未知属性会使装配原子 blocked。
- 光锥与遗器贡献、来源和 blocker 通道保持分离；动态套装能力不会在 S14 提前注册或执行。
- 最终聚焦验证全部谓词满足，main 6、sub 6、set 1 的 RuleBook 和 raw 来源逐项反查闭合；约 0.76 秒、峰值约 71 MiB。

P8-S15 当前事实：

- 激活套装档位的真实能力来源和参数已接入与光锥共用的 Canonical graph、参数解析和 provider 注册链，没有遗器专用事件循环或套装 ID 特判。
- active / inactive、二件 / 四件、2+2、多装备者、替换失活和重复启动的身份与幂等边界已闭合；runtime 不重新统计套装件数。
- 冲突定义、重复 provider 身份、伪来源、缺参数和 partial graph 均 fail-closed，不暴露部分动态选择或部分 mutation。
- 当前 62 条动态图中 37 条可执行；其余 25 条按真实 family 和 102 条依赖保留给 S16/S17，属于后续机制实现范围，不是 S15 能力入口缺失。
- 收缩后的唯一聚焦验证保留 15 项业务谓词，798 行非空；单次约 2.7 秒、峰值约 343 MiB、产物约 42 KiB，完整 lowering 为零。

P8-S16 当前事实：

- 当前 62 条套装动态图中 56 条已可执行，剩余 6 条完整图只包含 S17 机制，没有 S16 gap 或 unknown gameplay。
- 764 条 S16 family 与 628 条 S17 family 已按当前来源指纹穷尽、互斥分区；13 个属性 watcher 和 22 个区间进入类型化 Canonical IR。
- 真实 4+2 正例完成速度 `129.292 -> 135.352 -> 129.292`、条件 `false -> true -> false`，覆盖正式状态添加、移除和战中重评。
- 多装备者、队伍目标、owner/caster/source attribution、callback 幂等、原子失败、source audit 和 replay 已闭合。
- mutation-backed 属性变化会重新检查目标单位；watcher mutation 来源篡改和重复 callback 身份在生产边界 fail-closed。
- TBGD `MaxSP` 是角色能量上限，队伍战技点使用 BP；不得将二者混同。
- 替代最终聚焦验证 19 项谓词全绿，约 12.3 秒、峰值约 342 MiB、产物约 50 KiB；验证器 997 非空行，完整 lowering 为零。

P8-S17 当前事实：

- S16 的 764 条 family 与 S17 的 628 条 family 穷尽且互斥；当前 62 条套装动态图全部 executable，已发布普通玩家套装 blocked 和 unknown gameplay 均为零。
- 正式角色动作中的能力任务伤害原生产生 before-hit、damage-hit、after-hit 和 attack-end 事件，监听回调、原子提交、来源审计和 replay 使用同一链路。
- 伤害标签、状态叠层变化、行为标记计数、战斗事件创建和单位离场生命周期进入通用 IR / event / callback 系统。
- 正式动作与独立能力的伤害来源身份已分离；引擎数值绑定只消费 RuleBook 中已准入的类型化规则。
- client-only 相机能力和视觉任务结构化 process-only；套装专用 runtime handler、固定内容 ID 和部分执行均为零。
- 最终聚焦验证 17 项谓词全绿，约 92 秒、峰值约 896 MiB、全部 evidence 约 15 KiB，完整 lowering 为零。

2026-07-30 已重新审查并统一改写 S9-S21 的执行与验证口径：

- 每阶段只有一个业务主验证；完整入口最多一次诊断运行和一次最终运行。
- 前序检查点默认继承，direct 只由实际修改的共享调用链触发且最多两项。
- S9-S20 禁止把历史阶段验证当固定套餐；S21 只做一次 preflight 和一次共享 final。
- 每张执行卡均写明墙钟、峰值 RSS、累计验证时间和默认产物硬上限，超限必须暂停重新拆分。
- 详细规则以 `docs/p8_execution_cards/README.md` 第 6 节和当前阶段卡为准，不得恢复旧未过滤、九族或逐阶段重跑路径。

必须保留：

1. P8-DONE 只覆盖装备定义、合法成品构筑与战斗执行，不能外推为全角色、全怪物或全关卡完成。
2. R2 退役的未过滤聚合、九族组合和 VG-S3 registry 路线不得恢复。
3. S18 已在 R2 与 S17 同一基线上完成硬汇合，后续阶段只能消费这一条装配与出生路径。
4. 若继续验证治理，必须先证明新的真实重复点与现有共享证据具有相同生命周期。

## 仍未完成的大块

- 剩余记忆角色 / 忆灵的属性、时间线和出生来源扩面。
- 全角色、全怪物、全关卡和环境内容卡。
- 目标、波次、召唤、特殊事件源和特殊玩法的剩余真实来源扩面。
- P5/P3/P4 留存的已归因内容 gap。
- 外部推演器和正式 UI 接口。

敌方 AI 不进入 core。外部推演器负责像玩家一样选择敌我双方动作，内核负责给出合法动作、目标和确定性结算。

## 任务入口

不要默认通读所有文档。根据任务选择：

- P9 总计划与唯一 checklist：
  `simulator_v8_clean_core/P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md`。
- P9 单阶段执行入口：`simulator_v8_clean_core/docs/p9_execution_cards/README.md`；新线程只读
  当前阶段卡及卡内直接依赖。
- P8 最终检查点：
  `live_validation_reports/v8_p8_equipment_build_light_cone_relic_final_checkpoint.md`。
- P8-S20 希儿完整构筑检查点：
  `live_validation_reports/P8-S20_SEELE_COMPLETE_BUILD_SLICE_accepted.md`。
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
