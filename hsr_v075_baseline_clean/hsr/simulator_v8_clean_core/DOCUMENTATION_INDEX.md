# v8 文档索引

本文件说明每份文档管什么，不复制状态。当前进度只在 [`../CODEX_HANDOFF.md`](../CODEX_HANDOFF.md) 维护。
新线程先读工作区 `AGENTS.md` 和交接，再按任务补一份主题文档，不需要通读本表。

## 现行文档

| 文档 | 管什么 |
|---|---|
| [`../../../AGENTS.md`](../../../AGENTS.md) | 项目约束、分层、内核不变量、导航 |
| [`../CODEX_HANDOFF.md`](../CODEX_HANDOFF.md) | 当前状态、下一步、待修问题、已验收基线、已知限制 |
| [`PROJECT_GOALS.md`](PROJECT_GOALS.md) | 最终目标、v1 完成定义、数值容差、性能预算、优先级 |
| [`V1_ROUTE.md`](V1_ROUTE.md) | v1 名单、里程碑、内容接入方式、结束条件 |
| [`ARCHITECTURE_BOUNDARY_CONTRACT.md`](ARCHITECTURE_BOUNDARY_CONTRACT.md) | 四层边界；内容专属处理器的挂载接口与书写约定（第 5 节） |
| [`FORBIDDEN.md`](FORBIDDEN.md) | 禁止事项与方向红线 |
| [`docs/AGENT_WORKFLOW_AND_VALIDATION.md`](docs/AGENT_WORKFLOW_AND_VALIDATION.md) | 实施方式、验证选择、成本约定 |
| [`docs/numeric_validation/README.md`](docs/numeric_validation/README.md) | 游戏数值对照的记录格式、规则和现有记录 |
| [`CLI_MVP.md`](CLI_MVP.md) | 命令行与浏览器工作台的用法、示例场景和固定命令 |
| [`tests/README.md`](tests/README.md) | 测试入口与按需检查的命令 |
| [`MONSTER_CARD_SPEC.md`](MONSTER_CARD_SPEC.md) | 怪物卡的职责边界与字段规范 |
| [`scenarios/README.md`](scenarios/README.md) | 正式构筑、初始条件、关卡波次与 `battle_setup` 输入 |
| [`README.md`](README.md) | 核心模块概览与目录职责 |

CLI、场景和测试说明只保留当前接口；整理前逐日期的命令与旧验收口径移至 `docs/archive/usage/`。
当前命令的复核范围以各入口的检查说明为准，未复跑的历史路线不自动标为可运行。

## 历史归档

归档只用于追溯当时的目标、裁决和证据，不是当前事实或任务清单。按关键词定位，不全量读取。

| 归档 | 内容 |
|---|---|
| [`docs/archive/completed_tasks/`](docs/archive/completed_tasks/README.md) | 已完成任务的说明：R05–R07、怪物召唤、击破、希儿路线、I12、两轮性能优化、处理器对照实验 |
| [旧操作与测试命令](docs/archive/usage/CLI_MVP_PRE_REFRESH_2026-11-12.md) | 2026-11-12 更新前的 CLI、测试与场景说明；仅供追溯 |
| [交接快照](docs/archive/README.md) | 2026-11-12 整理前、2026-11-10 矫正前、2026-10-19 和 2026-07-24 的交接原文 |
| [矫正前路线](docs/archive/p9/ENGINEERING_ROUTE_R01_R18_PRE_CORRECTION_2026-11-10.md) | 固定目录全量终点、R01–R18 交付包与并行排程 |
| [P9 历史计划](docs/archive/p9/P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md)、[执行卡](docs/archive/p9/execution_cards/README.md) | 原目录核对、阶段拆分和旧任务约束 |
| [`docs/archive/p8/`](docs/archive/p8/)、[`completed_phase_plans/`](docs/archive/completed_phase_plans/)、[`phase1/`](docs/archive/phase1/) | P1–P8 的阶段计划与执行卡 |
| [`docs/archive/ui/`](docs/archive/ui/UI_V2_WORKBENCH_TASK_PLAN.md) | 2026-10 的 UI v2 工作台草案 |
| [`docs/archive/checkpoints/`](docs/archive/checkpoints/)、[`character/`](docs/archive/character/)、[`validation_governance/`](docs/archive/validation_governance/)、[`workflow_sources/`](docs/archive/workflow_sources/)、[`bootstrap_v075/`](docs/archive/bootstrap_v075/) | 旧缺口快照、角色盘点、验证治理试点、流程草案、v0.75 导入记录 |
| [历史阶段报告](../live_validation_reports/README.md) | 2026-10-21 之前的阶段报告 |

旧 v7、`model_pack_v3_0`、早期生成 IR 和旧规格目录属于历史实现，不是 v8 runtime 依赖。

## 维护规则

- 一件事只在一处维护：状态在交接，范围在路线，目标在项目目标，约束在 `AGENTS.md` 和架构契约。
- 交接保持在 150 行以内，只写现状、下一步和入口；过程经过、逐轮数字和教训不累积，超出时先存快照再精简。
- 任务结束后，它的说明、设计稿和报告移入 `docs/archive/completed_tasks/`，结论写回对应的现行文档。
- 不为单个机制或单轮修复新建长期文档；新增现行文档时在本索引登记。
- 移动或改名文档后，同步修正本索引、`AGENTS.md` 和交接中的路径。
