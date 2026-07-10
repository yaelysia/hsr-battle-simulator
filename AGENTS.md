# AGENTS.md - HSR 工作区入口目录

每次都用简体中文回复。

本工作区目标是构建一个严谨的《崩坏：星穹铁道》战斗模拟器，用于在不打开游戏的情况下设定敌我双方、战斗环境和路线输入，并得到尽可能与游戏一致的完整战斗过程、快照、结算和来源审计。

## 当前主线

当前主线是 v8 clean core：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/
```

v8 是 TBGD-first 重写基线。旧 v7 不是兼容目标，只能作为参考、对照和回归验证来源。

v8 事实来源固定为：

```text
turnbasedgamedata-main -> TBGD compiler/lowering -> Canonical IR -> Combat Core
```

项目优先级固定为：

```text
最终成品完整性 > 内核干净程度 > 来源可追查 > 验证可重复 > 旧版兼容
```

旧版兼容不是目标。旧 v7、旧 model pack、旧 CLI、旧 JSON、旧 Python API 都不能阻碍 v8 形成干净内核。

## 当前状态

最近检查点：

```text
P7 kernel trust and combat semantics repair
最近代码检查点：P7-S2 Mutation 前置条件与 reducer 冲突检测验收提交
当前规划主线：P7 内核可信执行与战斗语义回正；下一步只执行 P7-S3 所选执行图原子提交
```

当前 v8 已建立的底层范围包括：

- Canonical IR、RuleBook、snapshot/replay、settlement/source audit。
- action/event/ability task/effect/status callback/queue/timeline 等核心骨架。
- direct、DoT、break、super-break、hp loss、弹射、目标组、多段、击杀归因等伤害底座的当前可信范围。
- 普通状态生命周期、buff/debuff 共用生命周期、动态值绑定、资源、队列、额外行动语义、事件分发。
- 角色数据卡边界与加强版希儿示例卡，包含行迹、星魂通用开关/等级提升/监听接口。
- 怪物卡规范、`MonsterDataCardIR`、普通怪物技能动作、固定序列行动候选、怪物技能附带状态。
- 状态监听事件族矩阵、mutation-backed 事件源、银鬃尉官基础反击纵切。
- 目标表达式 IR 与安全解析子集：简单别名、明确群体、上下文目标列表、`TargetSequence`、`TargetFilter`、确定性 `Retarget`。
- 第一阶段 P1 最小完整战斗纵切已经完成，P1-9 聚合输出 `phase1_minimum_battle_slice=true` 且 blocker 为空。
- P2 状态系统底座已经完成，状态生命周期、概率/抵抗/免疫、驱散、DoT/状态伤害、callback queue、dynamic value 等当前闭环可验收；这不等于全角色、全怪物、装备和关卡状态机制都已复刻。
- P3 召唤物 / 忆灵底座闭环已经完成，summoned monster spawn、servant lifecycle/action/status/BattleSetup、target relation、source audit/replay 可验证；P3 是底座闭环通过，不是全正例完成。
- P4 角色卡 / 怪物卡数据卡扩面底座已经完成，action/query contract、data card source trace、formula/dynamic/target/passive/action gap 总账、P3 backlog 继承和聚合验收可验证；P4 是底座闭环通过，不是全角色 / 全怪物 / 全装备 / 全关卡正例完成。
- P5 公式 / 动态值 / 参数绑定通用准入底座已经完成，ValueResolver、静态参数、dynamic/custom 投影、damage/toughness/resource/status/callback queue/summon/trace/eidolon 消费侧、负例、source audit/replay 和聚合验收可验证；P5 是底座闭环通过，不是全角色 / 全怪物 / 全装备 / 全关卡公式正例完成。
- P6 架构边界回正已经完成，伤害 / 削韧显式计算入口、一等 `UnitBirthTemplateIR`、请求绑定出生单、Stage / HardLevelGroup 波次等级来源、RuleBook 窄访问边界和聚合阻断口径均已验收；P6 是职责边界闭环通过，不是全部机制扩面完成。
- P6 后深度代码复审已建立 P7 问题计划：当前 skeleton 可保留，但 transition 可信门、Mutation 前置校验、动作 / 目标 / 调度闭环、回合阶段、伤害、护盾、状态概率、RNG、召唤和波次等语义仍需逐项回正。旧聚合通过不能被解释为这些问题已解决。
- P7-S0 问题基线已经独立验收：P7-I01 至 P7-I24 均有唯一 `confirmed_open` 记录，十项轻量 runtime probe 实际复现当前缺陷，I20/I21/I23 具备全包 AST 结构证据；S0 没有修改 runtime，也不表示任何问题已经修复。
- P7-S1 Transition 可信结果契约已经独立验收：`committed`、`blocked`、`diagnostic` 三类结果机器可读，未知、矛盾或不完整结果不可作为正式后继；executor、scheduler 和 UI consumer 已接入 outcome。S1 不等于原子提交完成，diagnostic candidate 的内部 mutation 收口仍归 P7-S3。
- P7-S2 Mutation 前置条件与 reducer 冲突检测已经独立验收：Mutation 显式区分路径缺失与 null，before/op/after 和同路径链由生产 reducer 强制校验，冲突整批 state unchanged；Mutation JSON 在创建边界递归冻结、stable ID 固定，写状态前防御性解别名；UnitState 完整 payload 统一由 core codec 编解码。S2 不等于完整动作原子提交，所选执行图任一节点失败时的统一回滚仍归 P7-S3。
- `simulator_v8_ui/` 本地 UI 测试台，用于 scenario 编排和审计展示，不进入规则系统。

当前仍未完整实现的大块：

- 完整角色面板装配：晋阶、全量角色行迹、光锥、内圈/外圈遗器及套装效果。
- P5 保留的 admission gap 逐类回收：公式参数、动态值、自定义值、召唤参数、状态数值、资源和数据卡上下文的全正例扩面。
- 大量角色卡人工解释与验证。
- 状态系统长线扩面：全角色、全怪物、装备、关卡带来的新状态来源和特殊事件源。
- 目标系统剩余部分：更多排序、随机、fetch、相邻目标、唯一实体、召唤物/servant 扩展目标、特殊玩法目标。
- 全怪物技能、全怪物被动、阶段切换、召唤、波次、关卡倍率。
- 敌方行动候选扩面、波次系统扩面、P3 inherited summon/target gaps、servant damage formula、特殊战斗模式；敌方 AI 不进入 core，由外部推演器控制。
- 光锥、遗器、环境、关卡机制。
- `OnCustomEvent`、`OnWaveMonster` 等需要真实事件源或波次系统的回调。

## 工作区目录

- `turnbasedgamedata-main/`
  - 星穹铁道 TurnBasedGameData 数据库。
  - v8 规则来源必须能追溯到这里。

- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/`
  - 当前新模拟器主线。
  - 新机制、新框架、新验证优先在这里实现。

- `hsr_v075_baseline_clean/hsr/simulator_v8_ui/`
  - 本地 Web UI 测试台。
  - 只能做 scenario 编排、观测对照、审计展示，不能成为规则来源。

- `hsr_v075_baseline_clean/hsr/simulator_v7_7/`
  - 旧模拟器与旧验证基线。
  - 只作参考和数值对照，不作为 v8 runtime 依赖。

- `hsr_v075_baseline_clean/hsr/model_pack_v3_0/`
  - 旧 model pack。
  - v8 不以它为规则事实来源。

- `hsr_v075_baseline_clean/hsr/live_validation_reports/`
  - 阶段检查点报告。
  - 有意义的结构或机制变更需要新增或更新报告。

## 必读文档

v8 当前只保留少数高密度长期文档，避免文档膨胀影响索引和上下文检索。

下一线程优先读：

1. `hsr_v075_baseline_clean/hsr/CODEX_HANDOFF.md`
2. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/README.md`
3. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/ARCHITECTURE_BOUNDARY_CONTRACT.md`
4. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/DOCUMENTATION_INDEX.md`
5. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/PROJECT_GOALS.md`
6. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/FORBIDDEN.md`
7. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/MONSTER_CARD_SPEC.md`
8. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/PHASE1_SUMMARY.md`
9. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/P2_STATUS_SYSTEM_COMPLETE_TASK_PLAN.md`
10. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/P3_SUMMON_ASSISTANT_SERVANT_COMPLETE_TASK_PLAN.md`
11. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/P4_COMBATANT_DATA_CARD_EXPANSION_TASK_PLAN.md`
12. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/P5_FORMULA_DYNAMIC_PARAM_BINDING_TASK_PLAN.md`
13. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/P6_ARCHITECTURE_BOUNDARY_REFACTOR_TASK_PLAN.md`
14. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/P7_KERNEL_TRUST_AND_COMBAT_SEMANTICS_REPAIR_TASK_PLAN.md`
15. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_p5_formula_dynamic_param_binding_checkpoint.md`
16. `hsr_v075_baseline_clean/hsr/live_validation_reports/archive/phase1/v8_p1_final_acceptance_checkpoint_v0_292.md`
17. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_status_target_event_database_audit_checkpoint_v0_287.md`
18. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_target_expression_ir_checkpoint_v0_288.md`
19. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_target_expression_sequence_filter_retarget_checkpoint_v0_289.md`

P1 过程计划和中间报告已经归档，默认不要作为当前线程入口：

1. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/archive/phase1/`
2. `hsr_v075_baseline_clean/hsr/live_validation_reports/archive/phase1/`

只在需要对照旧行为时读：

1. `hsr_v075_baseline_clean/hsr/simulator_v7_7/ENGINE_ARCHITECTURE_v7_0.md`
2. `hsr_v075_baseline_clean/hsr/live_validation_reports/foundation_audit_layer_v0_75.md`
3. `hsr_v075_baseline_clean/hsr/live_validation_reports/simulator_workflow_audit_v0_74.md`
4. `hsr_v075_baseline_clean/hsr/model_pack_v3_0/MANIFEST.yaml`

## v8 硬约束摘要

详细红线见：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/FORBIDDEN.md
```

核心约束：

- runtime 只能读取 Canonical IR / 数据卡 IR，不能直接读取 TBGD raw schema。
- TBGD raw schema 只能进入 compiler/lowering/discovery/审计工具层。
- 不允许使用 `model_pack_v3_0` 补齐 v8 规则。
- 不允许复活 `BattleSimulator` 作为 v8 核心对象。
- 不允许引入或复活 `SimulatorRuntimeAdapter`、`_legacy_effects`、`action_ctx`。
- 不允许为了旧 CLI、旧 JSON、旧 compiled case、旧 Python API 污染 v8 内核。
- 不允许角色、敌人、遗器、关卡、路线硬编码特判进入核心系统。
- 不允许用观测伤害、旧模拟器输出、手工答案作为规则输入。
- 不允许从日志事后反推 settlement。
- 不允许只记录 applied term，不记录 skipped term。
- 不允许跳过未知 opcode 后仍标记为 supported。
- 不允许 `audit_only` 被当成 executable。
- 不允许 runtime 读取 TextMap 或技能文本。
- 不允许在内核中解析角色/怪物机制文本；文本解释只允许在数据卡构建或 UI 展示层发生。
- 不允许把 `engine_convention` 伪装成 TBGD 来源。
- 不允许验证主路径靠固定角色名、固定怪物名、固定技能 ID、固定文件名、固定 hash 或固定观测答案运转。
- 不允许目标表达式 fallback 到名称、路径或默认目标；缺目标、缺 payload、缺排序规则、缺条件时必须 blocked/state unchanged。

## 架构归属和推演器边界

推演器定位是“像玩家一样操作和看结果”的外部控制器，不是第二套战斗系统。它只能读取状态、查询合法动作和目标、选择 action command、指定或枚举可控 RNG 分支、读取 transition 和判断目标是否达成。它不能负责技能可用性、目标解析、状态结算、伤害公式、敌方 AI、机制默认值或 blocked reason 绕过。

规则归属必须靠近来源：

- 角色卡负责角色自身：基础面板、技能、行迹、星魂、特殊资源、角色召唤物入口。
- 怪物卡负责怪物自身：面板、技能、被动、阶段、弱点、抗性、召唤怪入口。
- 装备与构筑输入主要作为角色卡装配输入；怪物等级、模板、阶段和特殊覆盖作为怪物卡或环境装配输入。P4 只预留 hook，不完整实现光锥、遗器、套装和关卡机制。
- 角色召唤物归属角色卡。servant / 忆灵这类有独立属性、技能、行动和生命周期的单位，应通过角色卡子卡或派生 combatant card 接入。
- 怪物召唤物优先复用已有怪物卡。召唤者只提供 spawn intent、owner/summoner relation、生命周期和清理策略；被召唤单位自身规则仍来自怪物卡。
- 动作查询归属可行动单位的数据卡或子卡；目标查询归属 action definition。每个 action 自己声明合法目标、目标选择规则和实际打击范围。
- 关卡、环境、战斗事件是独立后续层，不能为了当前阶段完成而伪装成角色或怪物机制。

“真实预留”不是空字段。后续计划中如果要求预留装备、构筑、召唤物、环境或推演器接口，必须同时有明确归属、稳定 slot/hook、admission 边界、blocked/state unchanged 负例验证和后续归属记录。

UI 可以提前设计最终形态的入口和信息架构，用来倒查底层接口缺口；但不能为了 UI 层牺牲底层内核质量。UI view model 可以做适配，core / IR / RuleBook / runtime 不能为了界面方便引入硬编码、伪来源、默认 fallback 或不通用字段。若 UI 需求和内核通用性、来源审计、数据归属冲突，执行线程必须暂停并询问用户决定方向。

UI 只能消费 core/API 输出的战斗事实、合法动作、合法目标、资源门、blocked reason、transition 和审计结果；不能在前端或 UI API 层复刻战斗规则。战技点、能量、行动条、技能可用性、目标范围、状态变化、装备效果等都可能存在角色/机制例外，UI 不能按“常见规则”自行推导或修正，只能展示 runtime 给出的结果并提交用户选择。

当前 `turnbasedgamedata-main` 是 release data dump，包含角色、怪物、技能、状态、装备、遗器、召唤物、关卡和战斗事件等配置；目前没有发现可直接调用的完整 battle engine。v8 仍应以 TBGD 配置为事实来源，经 lowering 进入 Canonical IR，再由 runtime 做可审计状态转移。

## v8 审查红线

每次例行审查、结构回正或新增机制时，必须按以下红线检查，不能只看验证是否绿：

- 任何 runtime `Mutation` 都必须能反向追溯到 Canonical IR 中的真实 TBGD 机制节点，例如 action definition、ability binding、ability phase、ability task、effect、condition、formula、damage emission、status definition、target expression。
- 只有 `source_trace` 不等于来源正确；必须确认 source trace 指向的 IR 节点本身不是为了 runtime 方便伪造出来的占位。
- `derived`、`audit_only`、`discovered_only`、`blocked`、placeholder 只能生成 process-only settlement，不能产生状态 mutation。
- 缺少真实来源时，runtime 必须显式 blocked，并保持 state unchanged；不能为了让 smoke case 可跑而 fallback 到旧推导或默认执行。
- Canonical IR 必须诚实表达 TBGD 中发现的事实；禁止为了补 runtime 输入而制造不存在的规则事实。
- 每个新增可执行机制都必须有 negative validation：证明缺少真实来源、unsupported condition、unsupported target、unsupported formula、缺 event payload 时不会假执行。
- 每个新增 mutation 类机制都必须至少抽一条样例，从 mutation metadata 反查到 settlement，再反查到 Canonical IR，再反查到 TBGD source path/evidence。
- 验证样例必须优先按结构化谓词选择，例如 opcode、coverage_status、source_mode、target_mode、payload 可执行性；禁止按角色名、怪物名、固定 action id、固定文件名、固定 hash 选择主样例。
- 旧验证如果因为来源边界变严而失败，优先升级验证输入到真实来源链路；禁止为了旧 smoke 继续保留假执行路径。
- 审查结论必须区分“字段完整 / replay 通过”和“机制来源真实 / 语义正确”。前者不能替代后者。
- 每个阶段必须回头检查本次修改是否正确，不要给后续审查纠偏添加压力。
- 每次阶段汇报必须说明：当前做到哪里、距离最小可用战斗纵切还缺什么、距离完整复刻还缺哪些大模块。

## 规划与验收口径

后续计划文档必须降低执行线程的注意力负担，不能只写一个大而全的总目标。大型目标应拆成严格顺序阶段，每个阶段都要有：

- 阶段目标：必须详细说明本阶段完成后系统新增或改变的具体能力、要消除的具体错误职责、明确不追求的相邻目标；不能只写一句话概括。
- 本阶段只做：明确当前阶段允许实现的范围。
- 本阶段不做：明确后续阶段内容，防止执行线程提前展开。
- 完成标记：用可直接勾选的 `[ ]` 子项列出交付物、代码/文档/验证结果。
- 阶段红线：列出常见误判，防止“看起来可用”冒充完成。
- 最小验证：只列本阶段必须跑的验证和触发条件。

计划必须显式要求一次只执行一个阶段。后续阶段只能作为背景，不允许提前实现、提前打勾或把后续目标混进当前阶段。若阶段内容太多，应继续拆子阶段，而不是把大量目标塞进一个阶段。

每个阶段开始前必须先产出阶段执行卡，并等待确认后再改文件。执行卡必须具体到详细阶段目标、验收标准、目标与证据映射、目标产物、拟改文件、拟新增或修改的函数/脚本/页面、结构化判定谓词、blocked/gap/deferred 条件、验证命令、明确不跑的验证及理由、资源限峰值措施、最终 evidence。执行卡不能只是复述计划条款。

执行卡里的目标和验收必须写细。目标要说明“完成后系统应变成什么样”，验收要逐条说明“做到什么才算通过、出现什么不能通过、用哪份代码/验证/报告证明”。禁止只写一句话目标，也禁止用“验证通过”“边界收紧”“契约优化”这类抽象说法替代可检查标准。

执行线程和验收线程的职责必须分开。执行线程最多只能提交 `ready_for_review`，不能自称 `done`，不能修改 checklist，不能把 `[ ]` 改成 `[x]`。阶段完成标记和总 checklist 只能由验收线程在复核真实代码、真实验证输出、真实矩阵/summary、source/audit evidence 后更新。未完成项必须保留 `[ ]` 并记录 blocker / gap / deferred，不能用“后续会补”打勾。

`ok=true` 不是完成证明。验收时必须说明验证实际检查了什么、没检查什么、predicate 是否过宽、是否把 gap 用 executable 正例覆盖、报告引用的 evidence 是否真实存在。报告不是完成证据本身，只能作为证据索引。

资源控制是限制峰值，不是跳过必要验证。必要长验证可以串行、低优先级、输出到 `/tmp` 运行；禁止并行重验证、默认写大产物或跑无关全量。

计划文档只能有一套执行清单。背景、设计原则、页面规划、契约说明、风险矩阵只能作为参考资料，不能再写成另一套“完成要求 / 验收要求 / 防漏验收”清单；否则执行线程会在多个清单之间失焦。需要验收或打标的内容必须集中到对应阶段小节。

P4 的执行质量明显改善，后续大型计划应沿用这个正向模式：先用背景和约束建立方向，但把可执行内容压缩到唯一阶段清单；每阶段只做一个目标，先提交阶段执行卡，再产出 `ready_for_review` 证据包；最终聚合只能在所有分步验收后实现，且必须继承分步矩阵中的 gap。这个结构能显著降低执行线程偷跑、漏做、自勾和用聚合脚本掩盖分步问题的概率。

本项目是未完成模拟器，计划和验收不能把目标写得过大过泛。每个阶段、每个 checklist 项都应先按来源和实现状态拆成三态：

- `executable`：当前 RuleBook / Canonical IR 中存在真实来源，runtime mutation、settlement、source audit、replay 均通过。
- `source_gap_blocked`：runtime 可以有通用 admission/blocked 分支或未来预留路径，但当前 TBGD / IR 结构化扫描没有真实可执行来源；只能验证 coverage gap、blocked、state unchanged，不能合成正例 mutation。
- `implementation_missing`：当前存在真实来源，但 runtime 没有正确 admission / mutation / settlement / replay，这才是需要继续编码修复的缺口。

规划时必须把“需要编码实现”和“需要 discovery/coverage-gap 验证”分开。不能要求执行线程为当前数据库不存在的机制造 synthetic case；不能为了勾 checklist 把无真实来源的路径标成 executable。

标记 `source_gap_blocked` 前必须先区分三种情况：

- raw TBGD 确实没有对应结构化来源。
- raw TBGD 有来源，但 lowering 没有投影到 Canonical IR。
- Canonical IR 有来源，但验证脚本或 runtime admission 谓词过窄，没有选出正例。

只有第一种才是真正的 source gap。后两种应记录为 lowering/admission/validation gap，并进入实现或验收修正；不能把“当前检查脚本没扫到”直接等同于“数据库没有来源”。

这个分层定位适用于所有机制，不只是状态系统。任何 action、damage、status、target、RNG、queue、wave、summon、resource、character card、monster card、environment/stage 机制，在规划和验收时都必须先回答：

- raw TBGD 是否有结构化来源。
- lowering 是否把来源完整投影到 Canonical IR / 数据卡 IR。
- RuleBook 是否保留了可审计 source trace 和 admission 所需字段。
- runtime 是否只基于 IR 做通用 admission / mutation / settlement。
- validation 是否用足够准确的结构化谓词选样，而不是因为谓词过窄误报 source gap。

只有完成这层审计后，才能把缺口归类为 `source_gap_blocked`、`lowering_gap`、`admission_gap`、`validation_gap` 或 `implementation_missing`。

验收时应优先检查：

- 当前数据库/IR 有真实来源的机制是否都有正例 executable validation。
- 当前数据库/IR 无真实来源的机制是否明确记录为 source gap，并有 negative validation 证明不会产生 mutation。
- runtime 是否保持通用 admission、blocked/process-only、source audit 和 replay 口径。
- 是否存在硬编码角色/怪物/技能 ID、验证专用路径、伪 source trace、默认 fallback。

阶段完成口径应尽量拆成两层：

- 阶段底座可验收：有来源的机制已 executable；无来源的机制已 source-gap/blocked 且 state unchanged；后续阶段可以继续推进。
- 全正例 DONE：所有列项都存在真实来源正例并通过 executable validation。只有来源确实存在时才允许使用这个口径。

后续计划必须包含“分层验证范围”，避免执行线程无脑全量验证：

- 必跑最小集：`compileall`、本阶段新增/修改的主验证脚本、`git diff --check`。
- 直接回归集：只跑与本次改动触达系统有调用链或数据契约关系的旧验证，例如改 queue/window 才跑 queue、scheduler、extra-turn、mutation/source audit 相关验证。
- 条件触发集：只有改到 shared reducer、snapshot/replay、source audit、target、RNG、damage、status lifecycle、wave/timeline 等共享底座时，才扩大到对应跨阶段验证。
- 全量验证集：只在阶段验收、结构性大改、提交前高风险检查或用户明确要求时运行；计划中必须说明为什么需要全量。

计划文档中每个验证命令旁应标注目的和触发条件。验收时如果为了节省时间跳过无关验证，也要说明跳过理由和剩余风险；不能用少跑验证掩盖与本次改动直接相关的回归风险。

资源重验证要额外标注并串行运行。凡是会全量 TBGD discovery/lowering、构建完整 RuleBook、写出大体积 `canonical_ir` / coverage / fidelity JSON 的脚本，都不能和其他重验证并行跑；怀疑资源问题时先只读脚本确认输出规模，再决定是否运行。`validate_v0_209` 已知会全量构建并写出完整 canonical/coverage/fidelity，默认不作为普通小改的直接回归，只有改到 direct damage/crit/RNGEvent schema 且 P1 主验证无法覆盖时才串行运行，并优先输出到 `/tmp`。

验证该跑还是要跑，但高负荷验证必须手动限流，避免把磁盘 IO 和内存打满。凡是会全量读取 TBGD、重复 build lowering / RuleBook、执行阶段聚合或写较大 `/tmp` 产物的验证，都按重验证处理：一次只跑一个命令；不要和 `compileall`、其他 validation 或报告生成并行；优先跑本阶段主验证和最小直接回归，确需多项重验证时分批串行并在每项结束后确认结果；默认不写大产物，已有 summary 足够时只读取 summary；如果预计会造成明显 IO / 内存峰值，先向用户说明并等待确认。

新增或重写验证脚本必须有资源预算。默认只输出 summary、matrix、抽样 case 和必要审计记录；禁止默认写完整 `CanonicalIR.to_json()`、完整 coverage/fidelity、完整 RuleBook 派生大对象或全量 transition dump。确实需要大产物时必须加显式开关，例如 `--write-large-artifacts` / `--full-artifacts`，默认关闭，并在计划文档标注预计资源风险。主验证脚本应优先按结构化谓词抽样真实来源，而不是为了覆盖率全量序列化数据库。

如果在工作中形成新的长期经验、红线或流程约定，应及时更新本 `AGENTS.md`，避免后续线程重复踩坑。

## 近期经验教训

- 数据库里有答案时，不能用自造默认值、固定映射、观测数值或旧版经验替代。
- 没有 admission 的机制不能先做成 executable，后面再补来源；应先 blocked/process-only。
- 同类机制必须合并到底层通用系统，例如 buff/debuff 普通生命周期、伤害 source frame、队列 window、事件 listener、资源 mutation、目标表达式解析。
- “能跑”和“机制正确”不是一回事。验证通过只能说明当前样例通过，不能替代来源审计和语义对照。
- 角色/怪物机制不能进入核心系统特判。专属内容进入数据卡机制槽位，再接通用系统。
- 技能文本与参数解释只允许在数据卡构建层或 UI 展示层发生；runtime 只读 Canonical IR/数据卡 IR。
- 额外回合、终结技连续段、追击/反击不是同一类机制，不能只靠名字或文本命中归类。
- 击杀收益必须按具体伤害来源归因，不只是 actor；同一主行动序列可继续结算，派生/DoT/附加伤害遇到已死目标必须跳过。
- 怪物 `AbilityNameList` 只是怪物机制入口之一，不等于完整被动；技能挂状态、状态 callback、队列插入也可能是真实被动链路的一部分。
- 如果外部资料或用户机制说明与当前实现冲突，应回到 TBGD/数据卡来源链路重新审查，不能硬补 runtime 特例。
- 带结构化 key/name 的 target fetch 或 registry 读取，必须验证精确 key 命中、缺 key、错 key、默认 registry 同时存在等负例；默认项不能冒充命名来源。
- 目标系统判断 source gap 时不能只按 raw `$type` 名称搜索。`AllEnemy.SortByFormation`、`AllEnemy.SortByStance` 等 dot alias 语义来自 `TargetAliasConfig.AliasDict` 的 base alias 与 `TargetOperationConfig.OperationDict` 的 operation 组合；若验证找不到正例，先检查全局目标配置是否已投影到 Canonical IR。
- RNG choice ledger 的推演器/验收主路径应优先使用精确 `choice_key` 或 `event_id`；`rng_type` / `default` 只能作为人工驱动或兼容兜底，不能冒充某个具体随机分支的来源。
- 如果游戏机制直觉与验证脚本的 source gap 结论冲突，优先审查检查谓词和 lowering 投影。比如状态叠层/刷新不能只看 AddModifier task 里的 `MaxLayer` / `LayerAddWhenStack` / `IsRefresh`，还要确认 modifier definition 的 `Stacking`、`Count`、`LifeTime`、`StackProperty` 等 raw 字段是否已经被正确投影和 admission。
- 阶段验收不能把“blocked/no mutation 边界验证通过”当成“机制完成”。如果任务目标写的是 servant/召唤物、队列 family、状态生命周期等可执行机制，就必须有真实来源正例；只有计划明确写成 discovery/boundary 阶段时，blocked 才能算该子项通过。后续复核要逐项对照原计划目标，而不是只看聚合脚本 `ok=true`。
- 队列 family 缺口不能只按 `QueueWindowIR.window_family` 统计。反击/追击等游戏语义可能先以通用 `insert_ability` / `insert_action` 承载，并在 `window_policy.source_basis.text_hints`、ability name、callback event、priority key 或 action definition 中保留语义线索；验收若只看 family 为 0 就标 `source_absent_not_required`，会漏掉真实来源，应归为 validation/admission gap 或补正例。
- lowering 生成派生产物后如果又把上游节点改成 blocked，必须同步重算或阻断所有依赖产物。例如先生成 queue window，再按状态事件源缺失把 callback queue intent 改成 blocked，会留下“blocked intent 对应 executable window”的 IR 不一致；阶段验收必须跑触达系统的直接回归来抓这种问题。
- 最终聚合验收必须继承所有分步矩阵中的真实 gap。最终手写 source/mechanism matrix 的主行 `gap=0` 不能覆盖 S0/S1/S8 等分步报告里仍存在的 `lowering_gap`、`admission_gap`、`validation_gap` 或内部子项 gap；如果一个来源域有 executable 正例但内部仍有未投影/未准入子项，必须拆子行继承到总缺口，不能用“有一个正例跑通”代表整域完成。
- 推演器不能承担底层规则。它只像玩家一样查询、选择、提交和读取结果；技能可用性、目标范围、状态结算、伤害公式、敌方动作候选、blocked reason 都必须由 core / 数据卡 / RuleBook 给出。
- 动作属于可行动单位的数据卡或子卡，目标属于 action definition。不要让 UI、scenario、route 或未来推演器猜测 action/target 规则。
- 角色召唤物归属角色卡，servant / 忆灵应通过角色卡子卡或派生 combatant card 表达；怪物召唤物优先绑定已有怪物卡，只额外记录召唤者、owner/summoner relation 和生命周期。
- 装备、构筑、关卡、环境等未来接入点在当前阶段只能做真实预留：必须有归属、slot/hook、blocked 负例和后续阶段记录；空字段或 placeholder 不算预留完成。
- UI 早期可以做完整入口和 mock 视觉，但所有入口必须标 readiness；mock only 不能保存成正式 scenario、不能导出 route、不能参与验收。
- UI 是倒查内部接口的工作台，不是内核设计的上级约束。为了 UI 体验牺牲 core 通用性、来源追溯或 runtime 干净度时，必须停下询问。
- `turnbasedgamedata-main` 当前是配置数据来源，不是可直接调用的 battle engine。不能因为看到 battle/ability 配置就假设存在现成状态转移系统，也不能反过来用自造规则替代 lowering。
- P4 的正面经验：执行质量提升不是因为目标写得更大，而是因为目标被拆成严格顺序、每阶段只有一个清晰完成口径、执行线程只能提交 evidence、验收线程负责勾选和提交。后续计划优先复用这种结构，尤其是角色/怪物全量扩面、动态公式、目标系统、波次/关卡环境这类长线任务。
- transition/replay/source audit 自洽不等于战斗语义完整。每个结果必须有权威可信类别；只有所选执行图完整、Mutation 前置条件成立且原子提交的结果才能作为推演器下一状态，partial / blocked / diagnostic 必须 state unchanged。
- 动作查询与提交必须满足 round trip：同一决策状态中，查询给出的每个动作和目标都可原样提交，未给出的命令必须被拒绝；只读查询不得推进时间线、重复触发回合开始或改变当前行动者。
- `source_trace`、source/evidence 和审计 payload 只能用于解释来源，不能作为 runtime 行为输入。边界静态检查必须覆盖“从审计信息取规则”的行为路径，不能只检查 raw import 或敏感 token。
- 内核验收必须包含通用不变量，至少覆盖动作所有权、目标基数、护盾吸收、回合 / DoT / 控制顺序、独立 RNG 身份、Mutation before 冲突、队列前进保证和 partial no-mutation；阶段聚合 `ok=true` 不能替代这些检查。
- `@dataclass(frozen=True)` 只冻结字段重新绑定，不会冻结嵌套 dict/list。Mutation、RNG choice、queue intent 等可信指令若包含可变 JSON，必须在创建边界递归防御性冻结或复制，并在写入 state 前再次解别名；stable ID 必须在指令创建后保持不变，验证要包含原始输入、指令内部容器和序列化副本的别名污染负例。
- UnitState、spawn payload、snapshot entity 等共享状态结构的字段集合、数字规范和编解码必须只有一个 core 层契约；reducer、lifecycle、spawn/setup 只能复用，不能各自复制一套默认值和字段校验，否则新增字段时必然分叉。

## 快照与结算目标摘要

详细目标见：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/PROJECT_GOALS.md
```

每个动作最终必须产生完整 `BattleTransition`，至少包含：

- 动作输入。
- before snapshot。
- after snapshot。
- target resolution。
- trigger windows。
- state mutations。
- process events。
- rng events。
- settlement。
- coverage 状态。
- source audit 与 replay 信息。

所有状态变化必须通过 `Mutation` 表达。

最终必须满足：

```text
before snapshot + action input + Canonical IR + RNG events + mutations == after snapshot
```

settlement record 必须能追溯到 mutation，或明确标记为 process-only event。

## v8 当前验证命令

按触达范围运行验证，不要无脑全量。当前稳定聚合入口如下，在 `hsr_v075_baseline_clean/hsr` 下运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p2_status_system_complete --output-dir /tmp/hsr_v8_p2_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_summon_assistant_servant_complete --output-dir /tmp/hsr_v8_p3_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_combatant_data_card_expansion --output-dir /tmp/hsr_v8_p4_current
git diff --check
```

P4 角色卡 / 怪物卡数据卡扩面底座已验收通过。P4 聚合期望 `ok=true`、`validation_gate_ok=true`、`p4_combatant_data_card_substrate_complete=true`、`p4_all_executable_complete=false`；保留 gap 只能是已归因的 `admission_gap` / `source_gap_blocked`，不能出现 `implementation_missing`、`lowering_gap`、`validation_gap` 或 `unclassified`。

当前期望：

- compileall 通过。
- P1/P2/P3/P4 聚合输出 `ok=true`。
- P3 聚合是底座闭环通过，当前全正例期望仍是 `p3_summon_all_executable_complete=false`，不能把 inherited gaps 误读为失败或完成。
- P4 聚合是数据卡扩面底座闭环通过，当前全正例期望仍是 `p4_all_executable_complete=false`，不能把 admission/source-gap 误读为失败或完成。
- static checks 通过。
- snapshot replay 通过。
- source audit 通过。
- blocked/audit-only/discovered-only 不产生 mutation。
- v8 runtime 不引用旧 simulator、旧 model pack、legacy adapter、`action_ctx`，不读取 raw TBGD/TextMap。

## 工程规则

- 非必要不要读取整个项目；优先读取与当前任务直接相关的文件。
- 文件查找优先限制在工作区内，不要全盘找同名文件。
- 结构性代码问题优先用 CodeGraph；文字、日志、路径搜索优先用 `rg`。
- 修改要从根源修复；如果小修补会加重结构债，应选择更干净的结构性改动。
- 信息不足且无法从仓库发现时，先提问，不要自行假设关键规则。
- 新依赖必须先征得用户明确同意。
- Python 依赖优先考虑已有 uv 环境；禁止未经允许创建新的 uv 环境。
- `npx`、`npm install`、`pip install`、`curl | sh`、`git clone` 等会下载、安装或执行外部代码的操作，必须先征得用户明确同意。
- 观测战斗伤害只能作为验证数据，不能作为模拟输入。
- 有意义的结构或机制变更要新增或更新 `live_validation_reports/`。
- 验证输出放进 `/tmp` 或版本化输出目录，不要污染仓库运行目录。
- 不要提交 `__pycache__`、`.pyc` 或临时缓存。

## 提交规则

- 每个可验证结构阶段建议提交一次检查点。
- 大变动后创建 git 提交保留检查点。
- 按当前协作约定，阶段验收成功后提交一个 git 检查点；验收未通过、仍有 source/语义/通用性问题时不要为了留档提交。
- 纯规划文档、交接文档、报告口径整理默认不作为检查点提交；除非用户明确要求提交，或该文档更新与一次阶段验收/实现检查点绑定。
- v8 代码检查点不要混入无关文件。
- `AGENTS.md` 只有在用户明确要求维护项目入口说明时才提交；本次交接文档更新属于允许范围。
- 如果工作区里存在用户未提交修改，不要回滚；与当前任务无关则忽略。
