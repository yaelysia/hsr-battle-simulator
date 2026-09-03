# Simulator v8 Clean Core

`simulator_v8_clean_core` 是当前战斗模拟器主线。它把外部游戏数据编译为类型化规则和内容卡，
再由通用战斗内核执行确定性的状态转移。

## 核心链路

```text
TurnBasedGameData
        |
        v
discovery / lowering -> Canonical IR / 数据卡 IR
        |
        v
RuleBook -> 构筑装配 -> Scenario
        |
        v
动作与目标查询 -> Combat Core -> settlement / snapshot / replay
```

runtime 不读取 raw TBGD、TextMap、旧 v7 或旧 model pack。角色、怪物和装备的专属差异必须
通过内容 IR 组合通用机制，不能成为核心系统中的名称或固定 ID 特判。

## 目录职责

| 目录 | 职责 |
|---|---|
| `tbgd/` | 来源发现、精确读取、lowering 和数据卡构建 |
| `rules/` | Canonical IR、RuleBook 和类型化查询 |
| `builds/`、`equipment/` | 角色与装备构筑输入、装配结果和贡献账本 |
| `scenarios/` | 战斗配置准入、身份解析和初始状态构建 |
| `core/` | 不可变状态、原子提交、执行入口和 replay 基础 |
| `systems/` | 状态、伤害、目标、队列、召唤等通用领域规则 |
| `queries/` | 面向 UI 和外部推演器的只读查询 |
| `tools/` | 聚焦验证、审计和开发工具，不是 runtime 权威 |
| `docs/` | 执行卡、工作流和历史归档 |

## 对外边界

- UI 和外部推演器只查询合法选择、提交动作并读取结果，不自行计算规则。
- 项目不实现敌方 AI；敌我双方的选择都可由外部推演器控制。
- 内容构筑输入代表已完成的战斗成品，不模拟掉落、背包、强化历史或定向生成。
- 未知来源、未接机制或非法输入必须结构化阻断，并保证状态不变。

## 文档入口

- 当前进度：[`../CODEX_HANDOFF.md`](../CODEX_HANDOFF.md)
- 项目目标：[`PROJECT_GOALS.md`](PROJECT_GOALS.md)
- 架构边界：[`ARCHITECTURE_BOUNDARY_CONTRACT.md`](ARCHITECTURE_BOUNDARY_CONTRACT.md)
- 禁止事项：[`FORBIDDEN.md`](FORBIDDEN.md)
- 文档索引：[`DOCUMENTATION_INDEX.md`](DOCUMENTATION_INDEX.md)
- 执行与验收：[`docs/AGENT_WORKFLOW_AND_VALIDATION.md`](docs/AGENT_WORKFLOW_AND_VALIDATION.md)

阶段状态不在本文件维护，避免 README 随每张执行卡过期。
