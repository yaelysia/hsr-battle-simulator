# v8 文档索引

本文件说明文档归属和阅读入口，不复制阶段事实。当前进度只在 `../CODEX_HANDOFF.md` 维护。

## 默认入口

| 需求 | 文档 |
|---|---|
| 项目永久约束 | [`../../../AGENTS.md`](../../../AGENTS.md) |
| 当前进度、下一项工作和已验收边界 | [`../CODEX_HANDOFF.md`](../CODEX_HANDOFF.md) |
| 核心模块概览 | [`README.md`](README.md) |
| 最终目标和完成层级 | [`PROJECT_GOALS.md`](PROJECT_GOALS.md) |
| 分层、依赖方向和权威边界 | [`ARCHITECTURE_BOUNDARY_CONTRACT.md`](ARCHITECTURE_BOUNDARY_CONTRACT.md) |
| 绝对禁止事项 | [`FORBIDDEN.md`](FORBIDDEN.md) |
| 本地执行与必要验证 | [`docs/AGENT_WORKFLOW_AND_VALIDATION.md` 第 0 节](docs/AGENT_WORKFLOW_AND_VALIDATION.md#0-当前本地工作方式) |

新线程不需要通读这张表。先读 `AGENTS.md` 和交接文档，再按任务补一个主题入口。

## 当前主线

工程路线维护产品终点、交付顺序与结束条件；当前已验收行为、剩余限制和下一批只看交接。
旧目录数量、编译阻断、阶段勾选与审查状态均在归档中，不能作为当前剩余任务统计。

- 工程终点、里程碑与新增需求处理：
  [工程完结路线](P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md#0-工程完结路线)
- 当前实际进度与下一项：[CODEX_HANDOFF.md](../CODEX_HANDOFF.md)
- 已交付命令行场景与操作：[CLI_MVP.md](CLI_MVP.md)

旧阶段 checklist 保留已完成边界，不再作为唯一当前卡或逐阶段审批链。后续任务只读相关机制
和调用者，不默认通读执行卡目录或恢复 MCP 工作流。

## 内容与专题

| 主题 | 当前入口 |
|---|---|
| 怪物卡边界 | [`MONSTER_CARD_SPEC.md`](MONSTER_CARD_SPEC.md) |
| 战斗中怪物自然召唤 | [真实入口、共享调用链与集中验收约束](docs/MONSTER_SUMMON_NATURAL_ROUTE_CLOSURE.md)；当前进度仍见交接 |
| 独立伤害逐任务绑定 | [已验收批次的绑定契约](docs/archive/completed_tasks/I12_STANDALONE_DAMAGE_BINDING.md)；当前进度仍见交接 |
| V2 五元素普通击破自然路线 | [执行说明、五行结果与验收证据](docs/V2_ORDINARY_ELEMENT_BREAK_ROUTES.md)；当前进度仍见交接 |
| 技能后置监听行动事实 | [自然路线、实现边界与固定命令](docs/SEELE_POST_ATTACK_LISTENER_ROUTE.md) |
| 自动插入行动完整执行链 | [自然路线、实现边界与固定命令](docs/SEELE_AUTOMATIC_INSERT_ACTION_ROUTE.md) |
| 编译与执行耗时 | [第二轮性能定位与集中优化约束](docs/COMPILE_AND_RUNTIME_PROFILE_OPTIMIZATION.md)、[第一轮编译与测试提速](docs/COMPILE_AND_TEST_COST_REDUCTION.md) |
| UI 规划 | `../simulator_v8_ui/UI_V2_WORKBENCH_TASK_PLAN.md`，仅在该草案存在且任务涉及 UI 时读取 |

这些专题文档提供领域事实，不是当前阶段 checklist。其结论与当前源码冲突时，以源码、正式来源和
当前阶段验收为准。

## 验收证据

阶段报告与历史报告入口见 [`../live_validation_reports/README.md`](../live_validation_reports/README.md)。使用规则：

- 交接文档或当前执行卡点名的报告才是默认入口；
- `ready_for_review` 只是执行交付，不等于已验收；
- 当前能力以源码、实际运行证据与交接为准；历史 checklist/Git 检查点只证明当时声明的范围；
- 历史报告按阶段或关键词搜索，不全量读取；
- `/tmp` 中的详细 evidence 不属于长期项目文档。

## 历史归档

归档文档用于追溯当时的目标和裁决，不能当作当前事实或默认执行入口。

| 归档 | 内容 |
|---|---|
| [`docs/archive/phase1/`](docs/archive/phase1/) | P1 总结、执行计划和最终报告导航 |
| [`docs/archive/completed_phase_plans/`](docs/archive/completed_phase_plans/) | 已完成的 P2-P7 总计划 |
| [`docs/archive/p8/`](docs/archive/p8/) | P8 装备总计划和全部执行卡 |
| [P9 历史计划](docs/archive/p9/P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md)、[执行卡索引](docs/archive/p9/execution_cards/README.md) | 原目录核对、阶段拆分、勾选和旧任务约束；不作为当前施工计划 |
| [`docs/archive/completed_tasks/`](docs/archive/completed_tasks/README.md) | I12、后置监听与自动插入行动的已验收任务说明 |
| [`docs/archive/checkpoints/`](docs/archive/checkpoints/) | 旧 MVP 缺口与 PR #8 事实对账；状态均为历史快照 |
| [历史阶段报告](../live_validation_reports/archive/pre_2026_10_21/README.md) | 2026-10-21 整理时迁出的旧报告，保留原验收状态 |
| [`docs/archive/validation_governance/`](docs/archive/validation_governance/) | 已结束的验证治理试点计划和执行卡 |
| [`docs/archive/bootstrap_v075/`](docs/archive/bootstrap_v075/) | v0.75 导入、工作区基线和旧 v7 检查记录 |
| [`docs/archive/character/`](docs/archive/character/) | P9 开工前角色目录盘点和已完成 CHAR-M1 执行卡 |
| [`docs/archive/workflow_sources/`](docs/archive/workflow_sources/) | 现行 HSR 工作流吸收过的便携版流程草案 |
| [2026-10-19 交接历史快照](docs/archive/CODEX_HANDOFF_PRE_SLIM_2026-10-19.md) | 瘦身前的验收记录、机制证据与历史检查点；不作为当前状态 |
| [`docs/archive/`](docs/archive/) | 瘦身前 AGENTS、交接和索引快照 |

旧 v7、`model_pack_v3_0`、早期生成 IR 和旧规格目录仍属于历史实现，不是 v8 runtime 依赖。

## 维护规则

- 交接只维护当前任务、已验收基线、阻断、下一步与入口，目标 150 行以内；覆盖更新对应条目，
  不逐轮追加修复经过、测试耗时或历史计划。较长契约放对应任务说明，历史按 Git 或归档追溯。
- 工程路线只写 P9 总计划第 0 节，历史 checklist 不因新路线自动补勾；不为每轮修复新增快照。
- 稳定架构、目标与工作流文档不记录每张卡的计数和耗时。
- 已完成阶段的详细计划整体归档，不在根目录继续充当活动入口。
- 报告不复述执行卡；执行卡不复述工作流；AGENTS 不承载阶段流水账。
- 移动或替换文档后同步更新本索引、`AGENTS.md` 和交接文档中的有效链接。
