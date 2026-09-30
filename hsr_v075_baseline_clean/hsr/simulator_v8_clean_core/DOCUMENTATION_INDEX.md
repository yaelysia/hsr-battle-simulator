# v8 文档索引

本文件说明文档归属和阅读入口，不复制阶段事实。当前进度只在 `../CODEX_HANDOFF.md` 维护。

## 默认入口

| 需求 | 文档 |
|---|---|
| 项目永久约束 | [`../../../AGENTS.md`](../../../AGENTS.md) |
| 当前进度、下一卡和已验收边界 | [`../CODEX_HANDOFF.md`](../CODEX_HANDOFF.md) |
| 核心模块概览 | [`README.md`](README.md) |
| 最终目标和完成层级 | [`PROJECT_GOALS.md`](PROJECT_GOALS.md) |
| 分层、依赖方向和权威边界 | [`ARCHITECTURE_BOUNDARY_CONTRACT.md`](ARCHITECTURE_BOUNDARY_CONTRACT.md) |
| 绝对禁止事项 | [`FORBIDDEN.md`](FORBIDDEN.md) |
| 本地执行与必要验证 | [`docs/AGENT_WORKFLOW_AND_VALIDATION.md` 第 0 节](docs/AGENT_WORKFLOW_AND_VALIDATION.md#0-当前本地工作方式) |

新线程不需要通读这张表。先读 `AGENTS.md` 和交接文档，再按任务补一个主题入口。

## 当前主线

保持四层架构，先完成通用战斗底层，再接入角色、敌人和场地，按具体内容需求实现特殊机制。
特殊机制的架构归属不决定提前施工；底层阶段不以最终产品全部机制完成为终点。现有 CLI MVP
是运行与游戏内对照的载体，已有成果复用，不以角色数量或全目录归零安排施工。

- 后续路线与机制完成条件：
  [P9 总计划第 0 节](P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md#0-当前路线机制优先内容逐步扩充)
- 当前实际进度与下一项：[CODEX_HANDOFF.md](../CODEX_HANDOFF.md)
- 已交付命令行场景与操作：[CLI_MVP.md](CLI_MVP.md)
- 旧执行卡与历史来源导航：[参考索引](docs/p9_execution_cards/README.md)

旧阶段 checklist 保留已完成边界，不再作为唯一当前卡或逐阶段审批链。后续任务只读相关机制
和调用者，不默认通读执行卡目录或恢复 MCP 工作流。

## 内容与专题

| 主题 | 当前入口 |
|---|---|
| 角色能力范围与共享缺口 | [`CHARACTER_ABILITY_SCOPE_CLASSIFICATION.md`](docs/character_execution_cards/CHARACTER_ABILITY_SCOPE_CLASSIFICATION.md)、[`CHARACTER_SHARED_MECHANISM_GAP_PLAN.md`](docs/character_execution_cards/CHARACTER_SHARED_MECHANISM_GAP_PLAN.md) |
| 角色来源范围基线 | [`CHARACTER_ABILITY_SCOPE_LEDGER.md`](docs/character_execution_cards/CHARACTER_ABILITY_SCOPE_LEDGER.md)；只用于追溯 P9 开工分母 |
| 角色目录旧盘点与 CHAR-M1 | [`docs/archive/character/`](docs/archive/character/)；均为历史状态 |
| 怪物卡边界 | [`MONSTER_CARD_SPEC.md`](MONSTER_CARD_SPEC.md) |
| UI 规划 | `../simulator_v8_ui/UI_V2_WORKBENCH_TASK_PLAN.md`，仅在该草案存在且任务涉及 UI 时读取 |

这些专题文档提供领域事实，不是当前阶段 checklist。其结论与当前源码冲突时，以源码、正式来源和
当前阶段验收为准。

## 验收证据

阶段报告位于仓库级 `../live_validation_reports/`。使用规则：

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
| [`docs/archive/validation_governance/`](docs/archive/validation_governance/) | 已结束的验证治理试点计划和执行卡 |
| [`docs/archive/bootstrap_v075/`](docs/archive/bootstrap_v075/) | v0.75 导入、工作区基线和旧 v7 检查记录 |
| [`docs/archive/character/`](docs/archive/character/) | P9 开工前角色目录盘点和已完成 CHAR-M1 执行卡 |
| [`docs/archive/workflow_sources/`](docs/archive/workflow_sources/) | 现行 HSR 工作流吸收过的便携版流程草案 |
| [`docs/archive/`](docs/archive/) | 瘦身前 AGENTS、交接和索引快照 |

旧 v7、`model_pack_v3_0`、早期生成 IR 和旧规格目录仍属于历史实现，不是 v8 runtime 依赖。

## 维护规则

- 当前进度写交接文档；路线写 P9 总计划，历史 checklist 不因新路线自动补勾。
- 稳定架构、目标与工作流文档不记录每张卡的计数和耗时。
- 已完成阶段的详细计划整体归档，不在根目录继续充当活动入口。
- 报告不复述执行卡；执行卡不复述工作流；AGENTS 不承载阶段流水账。
- 移动或替换文档后同步更新本索引、`AGENTS.md` 和交接文档中的有效链接。
