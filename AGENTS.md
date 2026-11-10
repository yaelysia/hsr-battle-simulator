# AGENTS.md - HSR 战斗模拟器项目约束

每次都用简体中文回复。

下文中的 `<core>` 指：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core
```

## 项目定位

本项目构建供人工操作、UI 和外部推演器使用的《崩坏：星穹铁道》战斗模拟器。用户应能配置敌我双方、
构筑、关卡环境和操作路径，并得到与游戏实际战斗一致、确定可重放的战斗过程、快照和结算。

外部推演器的角色类似玩家：查询当前合法动作和目标、提交选择、读取结果。项目不实现敌方 AI，
但必须完整表达敌方单位的合法动作、目标、时机和结算规则，以便推演器控制双方行动。

2026-11-10 用户确认方向矫正，原因与完整定义见 `<core>/PROJECT_GOALS.md`：

- 当前版本终点是 **v1 可用版**：用户确定的有限名单内，内容能打、数值与游戏对得上、速度够
  推演器使用。固定来源目录全量是 v1 之后的扩展，不是当前完成条件，也不产生当前任务。
- 内容的专属行为可以写成该内容卡的专属处理器；只有多个名单内容共用的行为才扩展通用编译器和内核。
- 正确性以游戏实际数值对照衡量；来源审计是可开关的调试与测试能力，不是运行不变量或验收门。
- 性能是验收项，随内容接入持续度量。

项目优先级固定为：

```text
v1 可用 > 与游戏一致 > 推演性能 > 内核简洁 > 来源可查 > 目录覆盖 > 旧版兼容
```

本文件和 `<core>/PROJECT_GOALS.md` 与其它文档冲突时以这两份为准。2026-11-10 之前的计划、
执行说明和报告按历史记录理解；已验收的实现继续复用，不因矫正而重写。

## 架构分层

```text
L3 外部操作层：UI / 推演器 / CLI
L2 内容装配层：角色卡 / 怪物卡 / 召唤物子卡 / 光锥 / 遗器 / 关卡（声明 + 内容专属处理器）
L1 机制执行层：Combat Core / systems / reducer / RuleBook consumers
L0 来源编译层：TBGD / 已采纳机制资料 -> 编译或注册 -> Canonical IR / 数据卡 IR / RuleBook
复盘与调试：结算明细 / replay / 可开关的 source audit
```

- L0 解释和结构化外部数据，但不执行战斗。TBGD 首先是参数来源；是否编译其原生任务图由成本决定。
- L1 只实现通用战斗规则和公共挂点，不按具体角色、怪物或装备的名称与 ID 分支。
- L2 将通用机制、参数和来源装配成具体内容。通用机制表达不了、且只有该内容使用的行为，写成
  该内容卡的专属处理器：经 L1 公共挂点调用，只产生类型化 mutation，数值结算调用 L1 通用函数，
  不复制第二套结算逻辑。
- L3 只查询、选择和展示，不自行计算动作合法性、目标、资源、伤害或状态规则。
- 结算明细、replay 和审计用于解释与复盘，不能反过来成为 runtime 规则输入；逐事务来源审计
  不是执行路径的必经环节。

详细边界以 `<core>/ARCHITECTURE_BOUNDARY_CONTRACT.md` 和 `<core>/FORBIDDEN.md` 为准。

## 正式规则来源

2026-10-12 用户调整来源约束：TBGD 和可靠机制资料均可作为正式规则依据。
经过长期验证、测试条件明确的攻略、数据网站和实测结论可以直接采用，不要求重新逆向或
亲自重做其全部实验，也不以在 TBGD 找到同值、同名回调或原生内部协议为前提。

正式规则接入方向：

```text
TBGD / 已采纳机制资料 -> compiler/lowering、规则注册或内容专属处理器
                   -> Canonical IR / 数据卡 IR / RuleBook -> Combat Core
```

- 采用资料时简记链接、结论及适用版本/条件；版本不明时如实记录，只核对影响当前实现的差异。
  来源评估与验证成本按 `<core>/docs/AGENT_WORKFLOW_AND_VALIDATION.md` 执行，不另建审批流程。
- raw TBGD 只能由 compiler、lowering、discovery 和审计工具读取。
- `turnbasedgamedata-main` 是固定提交的 Git submodule。普通功能任务不得更新其指针；来源升级必须
  独立规划，并重建来源指纹、目录差异和受影响证据。
- runtime 不直接解释网页、TextMap、技能说明或观测记录；已从可靠资料确定的公式、参数和
  触发规则可以人工整理为正式类型化输入或内容专属处理器，在定义处注明实际来源，不伪装成 TBGD 来源。
- 旧 v7 和 `model_pack_v3_0` 只可对照，不是兼容目标，也不能成为 v8 runtime 依赖。
- TBGD 缺项不等于规则未知。资料仍不足或有影响当前行为的未决冲突时，只阻断实际依赖；
  不用无依据的经验值或固定结算答案补齐。

## 战斗范围

当前版本只做 v1 名单（见 `<core>/P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md`）。名单外的
内容在准入时明确拒绝即可，不是缺陷，不列入待办；名单的增减由用户决定。

名单内纳入会改变以下结果的内容：

- 合法战斗配置和入场初始状态；
- 可选动作、目标、时机和资源；
- 单位、召唤物、状态、时间线、队列和波次变化；
- 数值结算、胜负、settlement、snapshot 和 replay。

默认排除获取、掉落、商店、背包、合成、定向生成、养成过程、动画、镜头、音效和纯 UI 表现。
若其最终产物参与战斗，只接收并校验规范化成品，不复刻产物生成过程。

范围不明的真实内容不得自行兼容或静默删除。先保留来源并 fail-closed，记录它在游戏中的作用、
是否影响战斗、实现成本和建议；若会改变公共规则或架构方向，交由用户裁决。

## 内核不变量

- runtime 只能读取 Canonical IR、数据卡 IR、RuleBook 和已装配的正式输入（含已装配的内容专属
  处理器），不读取 raw TBGD、TextMap、网页或观测记录。
- 所有正式状态变化都通过类型化 mutation 和原子提交产生；失败请求不改变状态、队列和 RNG。
- 同一初始状态、命令序列和 RNG 输入得到同一结果；每次正式动作保留 replay 所需的命令、RNG
  与 mutation，以及用户和推演器可读的结算明细。
- 瞬时战斗事实由对应领域的类型化 producer 提供，不从日志、普通 payload 或相似字段重建。
- 名单外、未实现或依据不足的内容在准入或执行边界明确拒绝并说明原因，不用经验值、默认行为
  或固定答案补齐。拒绝本身不要求另建防伪检查或逐机制反例矩阵。
- 规则和处理器在定义处注明实际来源及适用条件，这是来源可查的全部要求；不要求每个 mutation
  在运行时反查到来源节点，也不为研究规则伪造 raw 节点。
- `audit_only`、`discovered_only`、`blocked` 和 placeholder 不得产生 mutation。
- `source_trace` 只用于审计，不能作为 runtime 行为输入。
- L1 核心系统禁止按角色名、怪物名、技能名、装备名、固定 ID、文件名或 hash 分支；专属行为只能
  经内容卡装配挂载。任何层都禁止用观测答案、固定结算结果或为拟合单个数值的修正项充当规则。
- 工程阶段编号只能用于计划、报告和缺口归属，不能进入业务身份或 runtime 分支。
- 禁止复活 `BattleSimulator`、`SimulatorRuntimeAdapter`、`_legacy_effects` 和 `action_ctx`。

## 内容与构筑

- 角色卡和怪物卡聚合自身动作、能力、专属处理器和来源；通用效果仍由 L1 执行。
- 接入一个内容时按成本最低的方式选择：现有通用机制加参数能表达就声明式装配；多个名单内容
  共用的新行为扩展通用机制一次；只有一个内容使用的行为写专属处理器，出现第二个使用者再提升。
  处理器边界见 `<core>/ARCHITECTURE_BOUNDARY_CONTRACT.md`。
- 动作归属可行动单位的数据卡，目标规则归属对应动作定义。
- 角色召唤物归属角色卡；怪物召唤物优先复用怪物卡，并记录 owner/summoner 和生命周期。
- 光锥与遗器独立于角色定义，由构筑装配层组合；runtime 不读取 raw 装备规则。
- 装备输入表示已完成的战斗构筑，不模拟强化历史，也不以养成过程约束自定义成品。

## 工作区导航

禁止新线程默认通读全部计划、报告和验证器。按任务读取最小集合：

| 要解决的问题 | 首选入口 |
|---|---|
| 当前进度、下一步、检查点 | `hsr_v075_baseline_clean/hsr/CODEX_HANDOFF.md` |
| 项目目标、v1 完成定义、数值容差与性能预算 | `<core>/PROJECT_GOALS.md` |
| v1 名单、里程碑与结束条件 | `<core>/P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md` |
| 分层、依赖方向、内容专属处理器边界 | `<core>/ARCHITECTURE_BOUNDARY_CONTRACT.md` |
| 禁止事项和历史兼容红线 | `<core>/FORBIDDEN.md` |
| 阶段实施 | 当前阶段执行卡及卡内列出的直接依赖 |
| 规划、验收、验证成本、执行角色 | `<core>/docs/AGENT_WORKFLOW_AND_VALIDATION.md` |
| 矫正前路线（R01–R18）与 P9 历史 | `<core>/docs/archive/p9/ENGINEERING_ROUTE_R01_R18_PRE_CORRECTION_2026-11-10.md`；旧卡仅追溯时读 `<core>/docs/archive/p9/execution_cards/README.md` |
| 光锥、遗器和构筑历史 | `<core>/docs/archive/p8/P8_EQUIPMENT_BUILD_LIGHT_CONE_RELIC_TASK_PLAN.md`、`<core>/docs/archive/p8/execution_cards/README.md` |
| 状态系统历史 | `<core>/docs/archive/completed_phase_plans/P2_STATUS_SYSTEM_COMPLETE_TASK_PLAN.md` |
| 召唤物、忆灵和 servant 历史 | `<core>/docs/archive/completed_phase_plans/P3_SUMMON_ASSISTANT_SERVANT_COMPLETE_TASK_PLAN.md` |
| 角色卡与怪物卡底座历史 | `<core>/docs/archive/completed_phase_plans/P4_COMBATANT_DATA_CARD_EXPANSION_TASK_PLAN.md` |
| 公式、动态值和参数绑定历史 | `<core>/docs/archive/completed_phase_plans/P5_FORMULA_DYNAMIC_PARAM_BINDING_TASK_PLAN.md` |
| 怪物卡 | `<core>/MONSTER_CARD_SPEC.md` 及对应阶段卡 |
| UI | `hsr_v075_baseline_clean/hsr/simulator_v8_ui/UI_V2_WORKBENCH_TASK_PLAN.md` |
| 当前验收证据与历史报告 | `hsr_v075_baseline_clean/hsr/live_validation_reports/README.md`；只按当前交接点名读取 |
| 完整文档归属和历史档案 | `<core>/DOCUMENTATION_INDEX.md` |

这张表是定位器，不是必读列表。当前状态只相信 `CODEX_HANDOFF.md`；旧计划和报告只用于追溯，
不能代替当前源码和验证结果。

结构和调用链优先使用 CodeGraph；字面文本、路径和日志使用 `rg`。没有 `.codegraph/` 时跳过，
不自行建立索引。历史决策先按关键词搜索，不全量读取归档。

## 工程原则

- 先核对当前代码和数据事实，再制定或执行计划；不要依赖过期报告推断现状。
- 交付以完成的 v1 名单条目计量：可战斗且数值已对照。新增验证器、契约、反例矩阵、报告或
  文档本身不算交付，也不因“动了共享文件”而追加。
- 同一机制在通用路径上两轮仍未打通时，停止扩展通用路径，改写专属处理器或交用户裁决。
- 改动执行热点后跑固定性能基准；明显变慢的改动先说明原因再合入。
- 修改前确认生产权威、正式调用者和影响边界，优先根因修复和最小完整纵切。
- 工作区缺规则时先复用可靠外部资料；符合上述条件的规则由工程侧采用，无需逐条询问用户。
  只有无法消解且影响实现的规则争议、范围取舍或兼容方向才询问用户。
- 新依赖、外部下载、扩大权限、创建或覆盖 uv 环境必须先获得用户同意。
- 不为旧接口污染新内核；可能产生不兼容时先询问是否需要兼容。
- 手工编辑使用 `apply_patch`；临时产物写 `/tmp`，不提交缓存和大体积输出。
- 不回滚用户改动，不混入无关文件，不使用破坏性 Git 命令。

阶段拆分、风险分级、验证成本、执行角色、可选子代理与模型路由均由
`<core>/docs/AGENT_WORKFLOW_AND_VALIDATION.md` 按需规定，不在本文件重复。
