# v8 当前交接

本文只维护当前已验收边界、正在推进的阶段和下一入口。历史过程、阶段数字和修复流水账不在这里
重复；需要时从文档索引和 Git 历史按关键词追溯。

## 当前主线

```text
simulator_v8_clean_core
TurnBasedGameData -> compiler/lowering -> Canonical IR / 数据卡 IR -> Combat Core
```

项目不实现敌方 AI。外部推演器像玩家一样控制敌我双方，内核只负责给出合法动作、目标、时机和
确定性结算。

## 已验收边界

- P1-P7 已建立最小战斗循环、状态、召唤、波次、队列、目标、RNG、内容卡、动态参数、架构边界和
  可信状态提交等通用底座。
- P8 已完成当前来源下的光锥、普通玩家遗器、词条、套装、装备装配、构筑汇合、来源审计与 replay
  收口；`CUSTOM` 遗器模板保留来源但明确排除正式玩家构筑。
- CHAR-M1 已建立记忆角色与忆灵 owned-combatant 构筑边界。
- P9-S0 至 P9-S8B6 已验收。角色能力来源、构筑绑定、动态值、目标、条件、任务图 IR、共享原子执行、
  普通动作、独立能力、状态 callback 和跨入口 continuation 已进入统一生产链。
- P9-S5D2 的随机目标基础和弹射目标消费已完成，但其完整动作 transaction/replay 正例明确等待 S8
  随机控制流闭合后回验，因此该聚合项仍未勾选。

“底座已验收”不等于全内容完成。P1-P8 的完成结论只适用于各阶段声明的来源与功能范围。

## 当前工作

当前总计划：

```text
simulator_v8_clean_core/P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md
```

P9 面向当前非记忆、非欢愉已发布角色，优先闭合共享机制，不按角色逐个编写专属处理器。

下一张唯一可执行卡：

```text
simulator_v8_clean_core/docs/p9_execution_cards/
P9-S8C1A_WEIGHTED_SELECTION_IR_CONTRACT.md
```

S8C1A 只建立加权选择的严格 IR、身份、父子来源关系和 codec；不读取 TBGD、不接 materializer、
不执行 RNG、不修改 runtime。真实来源接线和完整来源分母分别由后续 S8C1B、S8C1C 承担，二者尚未
形成可执行卡，不得提前实施。

## 仍未完成

- P9-S8C 及后续角色共享控制流、事件、状态、伤害、资源、队列、死亡、击破、形态和独立行动实体。
- P9 完成后的全角色目录回验，以及记忆、欢愉专属内容增量。
- 全怪物、全召唤内容、全关卡环境和特殊玩法的数据卡扩面。
- 当前阶段已经明确归属的 P3/P4/P5 内容来源缺口。
- 正式 UI、外部推演器和端到端产品流程。

这些缺口不能因为通用底座存在而标记为完成，也不能用 fixture 冒充真实内容可执行。

## 开工入口

新线程只读取与任务直接相关的最小集合：

1. 工作区永久约束：`AGENTS.md`。
2. 当前状态：本文。
3. 当前总计划的阶段依赖与唯一 checklist。
4. `docs/p9_execution_cards/README.md` 和当前唯一执行卡。
5. 执行卡点名的生产符号、调用者和来源。

架构修改再读 `ARCHITECTURE_BOUNDARY_CONTRACT.md`、`FORBIDDEN.md`；规划或验收再读
`docs/AGENT_WORKFLOW_AND_VALIDATION.md`。禁止新线程默认通读全部计划、报告和历史验证器。

## 证据与历史

- P8 最终结论：`live_validation_reports/v8_p8_equipment_build_light_cone_relic_final_checkpoint.md`。
- P9 阶段状态只认总计划 checklist 和已验收 Git 检查点；`ready_for_review` 报告不是最终验收。
- 文档归属与归档：`simulator_v8_clean_core/DOCUMENTATION_INDEX.md`。
- 瘦身前交接全文：`simulator_v8_clean_core/docs/archive/CODEX_HANDOFF_PRE_SLIM_2026-07-24.md`。

## 工作边界

- runtime 不读 raw TBGD、TextMap、旧 v7 或旧 model pack。
- 内容差异进入数据卡与机制图，不进入核心特判。
- 缺来源、缺语义或身份冲突必须 blocked 且 state unchanged。
- UI 和推演器不复制规则。
- 验收必须检查生产代码、正式调用链和最小反例，不能只看 `ok=true`。
- 默认运行 fast 和必要 direct；catalog/full 仅由实际改动面触发。
- 执行线程只提交 `ready_for_review`；验收线程负责 checklist 和检查点。
