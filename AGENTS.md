# AGENTS.md - HSR 战斗模拟器项目约束

每次都用简体中文回复。

下文中的 `<core>` 指：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core
```

## 项目定位

本项目构建可审计的《崩坏：星穹铁道》战斗模拟器。用户应能配置敌我双方、构筑、关卡环境和
操作路径，并得到规则一致的战斗过程、快照、结算、来源审计和 replay。

外部推演器的角色类似玩家：查询当前合法动作和目标、提交选择、读取结果。项目不实现敌方 AI，
但必须完整表达敌方单位的合法动作、目标、时机和结算规则，以便推演器控制双方行动。

项目优先级固定为：

```text
最终成品完整性 > 内核干净程度 > 来源可追查 > 验证可重复 > 旧版兼容
```

## 架构分层

```text
L3 外部操作层：UI / 推演器 / CLI
L2 内容装配层：角色卡 / 怪物卡 / 召唤物子卡 / 光锥 / 遗器 / 关卡
L1 机制执行层：Combat Core / systems / reducer / RuleBook consumers
L0 来源编译层：TBGD raw -> lowering -> Canonical IR / 数据卡 IR
横切审计层：source audit / settlement / replay / coverage / gap attribution
```

- L0 解释和结构化外部数据，但不执行战斗。
- L1 只实现通用战斗规则，不理解具体角色、怪物或装备名称。
- L2 将通用机制、参数和来源装配成具体内容，不复制第二套结算逻辑。
- L3 只查询、选择和展示，不自行计算动作合法性、目标、资源、伤害或状态规则。
- 审计层观察并证明正式执行链，不能反过来成为 runtime 规则输入。

详细边界以 `<core>/ARCHITECTURE_BOUNDARY_CONTRACT.md` 和 `<core>/FORBIDDEN.md` 为准。

## 唯一事实来源

正式规则来源链只有：

```text
turnbasedgamedata-main -> compiler/lowering -> Canonical IR / 数据卡 IR -> Combat Core
```

- raw TBGD 只能由 compiler、lowering、discovery 和审计工具读取。
- TextMap、名称、技能说明和游戏观测只用于展示、人工理解或验证，不能驱动 runtime 规则。
- 旧 v7 和 `model_pack_v3_0` 只可对照，不是兼容目标，也不能成为 v8 runtime 依赖。
- 内容无法从结构化来源确定时必须保留缺口，不能用旧实现、经验值或手工答案补齐。

## 战斗范围

纳入会改变以下结果的内容：

- 合法战斗配置和入场初始状态；
- 可选动作、目标、时机和资源；
- 单位、召唤物、状态、时间线、队列和波次变化；
- 数值结算、胜负、settlement、snapshot 和 replay。

默认排除获取、掉落、商店、背包、合成、定向生成、养成过程、动画、镜头、音效和纯 UI 表现。
若其最终产物参与战斗，只接收并校验规范化成品，不复刻产物生成过程。

范围不明的真实内容不得自行兼容或静默删除。先保留来源并 fail-closed，记录它在游戏中的作用、
是否影响战斗、实现成本和建议；若会改变公共规则或架构方向，交由用户裁决。

## 内核不变量

- runtime 只能读取 Canonical IR、数据卡 IR、RuleBook 和已装配的正式输入。
- 所有正式状态变化都通过类型化 mutation 和原子提交产生。
- 每次正式动作必须保留 before/after、目标解析、事件、RNG、mutation、settlement 和 replay 所需事实。
- 每个 mutation 必须反查到真实 IR 节点和 TBGD 来源；settlement 必须由执行路径原生生成。
- 瞬时战斗事实只能由对应领域的类型化 producer 提供，不能从日志、普通 payload 或相似字段重建。
- 未知、缺来源、缺条件、缺目标、缺公式或缺上下文必须 fail-closed，且失败不改变状态。
- `audit_only`、`discovered_only`、`blocked` 和 placeholder 不得产生 mutation。
- `source_trace` 只用于审计，不能作为 runtime 行为输入。
- 禁止按角色名、怪物名、技能名、装备名、固定 ID、文件名、hash 或观测答案编写正式逻辑。
- 工程阶段编号只能用于计划、报告和缺口归属，不能进入业务身份或 runtime 分支。
- 禁止复活 `BattleSimulator`、`SimulatorRuntimeAdapter`、`_legacy_effects` 和 `action_ctx`。

## 内容与构筑

- 角色卡和怪物卡聚合自身动作、能力和来源；通用效果仍由 L1 执行。
- 动作归属可行动单位的数据卡，目标规则归属对应动作定义。
- 角色召唤物归属角色卡；怪物召唤物优先复用怪物卡，并记录 owner/summoner 和生命周期。
- 光锥与遗器独立于角色定义，由构筑装配层组合；runtime 不读取 raw 装备规则。
- 装备输入表示已完成的战斗构筑，不模拟强化历史，也不以养成过程约束自定义成品。

## 工作区导航

禁止新线程默认通读全部计划、报告和验证器。按任务读取最小集合：

| 要解决的问题 | 首选入口 |
|---|---|
| 当前进度、下一步、检查点 | `hsr_v075_baseline_clean/hsr/CODEX_HANDOFF.md` |
| 项目目标与完成定义 | `<core>/PROJECT_GOALS.md` |
| 分层、依赖方向、共享内核边界 | `<core>/ARCHITECTURE_BOUNDARY_CONTRACT.md` |
| 禁止事项和历史兼容红线 | `<core>/FORBIDDEN.md` |
| 阶段实施 | 当前阶段执行卡及卡内列出的直接依赖 |
| 规划、验收、验证成本、执行角色 | `<core>/docs/AGENT_WORKFLOW_AND_VALIDATION.md` |
| P9 全角色共享机制 | `<core>/P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md`、`<core>/docs/p9_execution_cards/README.md` |
| 光锥、遗器和构筑历史 | `<core>/docs/archive/p8/P8_EQUIPMENT_BUILD_LIGHT_CONE_RELIC_TASK_PLAN.md`、`<core>/docs/archive/p8/execution_cards/README.md` |
| 状态系统历史 | `<core>/docs/archive/completed_phase_plans/P2_STATUS_SYSTEM_COMPLETE_TASK_PLAN.md` |
| 召唤物、忆灵和 servant 历史 | `<core>/docs/archive/completed_phase_plans/P3_SUMMON_ASSISTANT_SERVANT_COMPLETE_TASK_PLAN.md` |
| 角色卡与怪物卡底座历史 | `<core>/docs/archive/completed_phase_plans/P4_COMBATANT_DATA_CARD_EXPANSION_TASK_PLAN.md` |
| 公式、动态值和参数绑定历史 | `<core>/docs/archive/completed_phase_plans/P5_FORMULA_DYNAMIC_PARAM_BINDING_TASK_PLAN.md` |
| 怪物卡 | `<core>/MONSTER_CARD_SPEC.md` 及对应阶段卡 |
| UI | `hsr_v075_baseline_clean/hsr/simulator_v8_ui/UI_V2_WORKBENCH_TASK_PLAN.md` |
| 当前验收证据 | `hsr_v075_baseline_clean/hsr/live_validation_reports/` 中与当前阶段同名的报告 |
| 完整文档归属和历史档案 | `<core>/DOCUMENTATION_INDEX.md` |

这张表是定位器，不是必读列表。当前状态只相信 `CODEX_HANDOFF.md`；旧计划和报告只用于追溯，
不能代替当前源码和验证结果。

结构和调用链优先使用 CodeGraph；字面文本、路径和日志使用 `rg`。没有 `.codegraph/` 时跳过，
不自行建立索引。历史决策先按关键词搜索，不全量读取归档。

## 工程原则

- 先核对当前代码和数据事实，再制定或执行计划；不要依赖过期报告推断现状。
- 修改前确认生产权威、正式调用者和影响边界，优先根因修复和最小完整纵切。
- 关键信息无法从工作区确定且会改变规则或兼容方向时，暂停并询问用户。
- 新依赖、外部下载、扩大权限、创建或覆盖 uv 环境必须先获得用户同意。
- 不为旧接口污染新内核；可能产生不兼容时先询问是否需要兼容。
- 手工编辑使用 `apply_patch`；临时产物写 `/tmp`，不提交缓存和大体积输出。
- 不回滚用户改动，不混入无关文件，不使用破坏性 Git 命令。

阶段拆分、风险分级、验证成本、执行角色、可选子代理与模型路由均由
`<core>/docs/AGENT_WORKFLOW_AND_VALIDATION.md` 按需规定，不在本文件重复。
