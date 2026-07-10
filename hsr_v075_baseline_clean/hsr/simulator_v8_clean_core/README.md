# simulator_v8_clean_core

`simulator_v8_clean_core` 是《崩坏：星穹铁道》战斗模拟器的 v8 主线内核。

v8 是 TBGD-first 的干净重写线，事实来源固定为：

```text
turnbasedgamedata-main -> TBGD compiler/lowering -> Canonical IR / 数据卡 IR -> Combat Core
```

当前最近检查点：

```text
P7-S2 mutation preconditions and reducer conflict detection accepted
最近检查点：P7-S2 Mutation 前置条件与 reducer 冲突检测验收提交
轻量验证入口：python3 -m simulator_v8_clean_core.tools.validate_p7_s2_mutation_reducer_contract
```

当前推荐下一阶段：

```text
P7-S3 selected execution graph atomic commit
计划文档：P7_KERNEL_TRUST_AND_COMBAT_SEMANTICS_REPAIR_TASK_PLAN.md
```

## 文档入口

新线程默认先读：

1. `../../../AGENTS.md`
2. `../CODEX_HANDOFF.md`
3. `ARCHITECTURE_BOUNDARY_CONTRACT.md`
4. `DOCUMENTATION_INDEX.md`
5. `PROJECT_GOALS.md`
6. `FORBIDDEN.md`

阶段细节按需读取：

- `PHASE1_SUMMARY.md`
- `P2_STATUS_SYSTEM_COMPLETE_TASK_PLAN.md`
- `P3_SUMMON_ASSISTANT_SERVANT_COMPLETE_TASK_PLAN.md`
- `P4_COMBATANT_DATA_CARD_EXPANSION_TASK_PLAN.md`
- `P5_FORMULA_DYNAMIC_PARAM_BINDING_TASK_PLAN.md`
- `P6_ARCHITECTURE_BOUNDARY_REFACTOR_TASK_PLAN.md`
- `P7_KERNEL_TRUST_AND_COMBAT_SEMANTICS_REPAIR_TASK_PLAN.md`
- `MONSTER_CARD_SPEC.md`

P1 过程计划和旧过程报告已归档，默认不要作为当前入口。

## 架构边界

v8 当前分层以 `ARCHITECTURE_BOUNDARY_CONTRACT.md` 为准：

```text
L3 外部操作层：UI / 推演器 / CLI
L2 内容装配层：角色卡 / 怪物卡 / 召唤物子卡 / 装备 / 关卡
L1 机制执行层：Combat Core / systems / reducer / RuleBook consumers
L0 来源编译层：TBGD raw -> lowering -> Canonical IR / 数据卡 IR
横切约束：source audit / settlement / replay / coverage / gap attribution
```

关键原则：

- 内容卡不是机制执行层，而是机制装配层。
- 内核不是内容解释层，而是通用机制执行层。
- UI / 推演器不是规则层，而是外部操作层。
- TBGD lowering / 数据卡构建不是 runtime，而是事实来源编译层。

## 基本规则

- runtime 只读取 Canonical IR / 数据卡 IR / RuleBook / BattleState，不读取 raw TBGD、TextMap、旧 v7、旧 model pack。
- TBGD raw schema 只能在 compiler/lowering/discovery/审计工具层读取。
- UI、游戏观测值、TextMap 名称、技能说明只能用于展示、验证或数据卡构建，不能作为 runtime 规则来源。
- 内容卡只能声明机制、参数、来源和触发关系，不能自己执行伤害、目标、状态、资源、队列或波次逻辑。
- 所有状态变化都必须通过 `Mutation` 表达。
- 每次动作必须输出 `BattleTransition`，包含 before/after snapshot、目标解析、mutation、settlement、source audit、replay 信息。
- `blocked`、`audit_only`、`discovered_only`、placeholder 只能产生 process-only 记录，不能产生 mutation。
- 不允许按角色名、怪物名、技能名、固定 ID、固定文件名、固定 hash 或观测数值驱动规则。
- `source_trace` 是审计证据，不应长期承担 runtime 主输入职责。

详细红线见：

- `ARCHITECTURE_BOUNDARY_CONTRACT.md`
- `FORBIDDEN.md`
- `PROJECT_GOALS.md`
- `../CODEX_HANDOFF.md`

## 当前已落地范围

- Canonical IR、RuleBook、snapshot/replay、settlement/source audit。
- action/event/ability task/effect/status callback/queue/timeline 等核心骨架。
- direct、DoT、hp loss、break、break DoT、super-break、弹射、目标组、多段、击杀归因等伤害底座的当前可信范围。
- 普通状态生命周期、buff/debuff 共用生命周期、概率 / 抵抗 / 免疫、驱散、状态伤害、动态值绑定、资源、队列、额外行动语义、事件分发。
- 角色数据卡边界、加强版希儿示例卡、行迹 / 星魂通用接口。
- 怪物卡规范、`MonsterDataCardIR`、普通怪物技能动作、固定序列行动候选、怪物技能附带状态。
- 状态监听事件族矩阵、mutation-backed 事件源、银鬃尉官基础反击纵切。
- 目标表达式 IR 与安全解析子集：简单别名、明确群体、上下文目标列表、`TargetSequence`、`TargetFilter`、确定性 `Retarget`。
- P1 最小完整战斗纵切通过。
- P2 状态系统底座通过。
- P3 召唤物 / 忆灵底座通过；`p3_summon_all_executable_complete=false` 是已归因 backlog。
- P4 角色卡 / 怪物卡数据卡扩面底座通过；`p4_all_executable_complete=false` 是已归因 backlog。
- P5 公式 / 动态值 / 参数绑定通用准入底座通过；`p5_all_executable_complete=false` 是已归因 backlog。
- P6 架构边界回正通过；一等出生模板、显式计算入口和访问边界已经收口。
- P7-S0 问题基线通过；24 项问题仍全部 `confirmed_open`，S0 只固化复现和结构证据，没有修改 runtime。
- P7-S1 Transition 可信结果契约通过；只有 `committed` 可作为正式后继，blocked / diagnostic / unclassified 均不可推进外部状态。
- 本地 UI 测试台 `simulator_v8_ui/`，作为测试编排与审计展示层，不作为规则系统。

## 当前仍未完整落地的大块

- 完整目标系统：更多排序、随机、fetch、相邻目标、唯一实体、召唤物 / servant 目标、特殊玩法目标。
- 波次 / 战斗开局 / 关卡结构：多波次、开局事件、换波、怪物生成、关卡环境、波次清理、`OnWaveMonster` 等事件源。
- 行动窗口 / 队列 / 事件调度进一步收敛：复杂追击、反击、插队、终结技窗口、召唤物行动、波次事件。
- 完整角色面板装配：晋阶、全量角色行迹、光锥、内圈 / 外圈遗器及套装效果。
- 大量角色卡、怪物卡、召唤物子卡人工解释、结构化 admission 和验证。
- P3/P4/P5 保留的 admission/source gap 逐类回收。
- 非 direct damage 的完整消费侧：治疗、护盾、生命变化、部分 break/super-break/DoT/状态伤害/附加伤害。
- 资源与特殊资源统一模型：角色特殊资源、怪物资源、召唤物资源、装备资源、场地资源。
- 关卡、环境、敌人组、波次倍率和特殊玩法机制。

## 推荐验证

在 `hsr_v075_baseline_clean/hsr` 下运行。按触达范围选择，不要无脑全量：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p2_status_system_complete --output-dir /tmp/hsr_v8_p2_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_summon_assistant_servant_complete --output-dir /tmp/hsr_v8_p3_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_combatant_data_card_expansion --output-dir /tmp/hsr_v8_p4_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p5_formula_dynamic_param_binding --output-dir /tmp/hsr_v8_p5_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p6_architecture_boundary_refactor --output-dir /tmp/hsr_v8_p6_current
PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p7_s0_kernel_trust_baseline --output-dir /tmp/hsr_v8_p7_s0_current
PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p7_s1_transition_trust_contract --output-dir /tmp/hsr_v8_p7_s1_current
git diff --check
```

当前期望：

- `compileall` 通过。
- P1/P2/P3/P4/P5/P6 聚合输出 `ok=true`；P7-S0/P7-S1/P7-S2 轻量验证输出 `ok=true`。
- P3/P4/P5 当前全正例期望仍是 `*_all_executable_complete=false`，不能把已归因 gap 误读为失败，也不能把底座通过误读为全正例完成。
- replay/source audit/settlement traceability 通过。
- unsupported、blocked、audit-only、discovered-only 不产生 mutation。
- runtime/core/systems 不引用 UI，不读取 raw TBGD/TextMap/旧 v7/旧 model pack。

重验证必须串行运行，输出到 `/tmp`，默认不写完整 Canonical IR、完整 RuleBook 或全量 transition dump。

## 下一阶段建议

下一步只执行 P7-S3 所选执行图原子提交。S3 经独立验收前不得提前执行 S4-S19，也不继续大规模内容扩面。阶段开始前先提交详细执行卡；执行线程只能提交 `ready_for_review`，由验收线程检查代码、谓词和 evidence 后勾选唯一 checklist。
