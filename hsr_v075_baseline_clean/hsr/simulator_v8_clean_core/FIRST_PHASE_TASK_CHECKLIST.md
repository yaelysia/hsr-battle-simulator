# v8 第一阶段任务清单

本文档是 `FIRST_PHASE_MINIMUM_BATTLE_LOOP_PLAN.md` 的执行清单。后续实现线程每完成一项，就把对应 `[ ]` 改成 `[x]`，并在必要时补充验证报告或代码检查点。

第一阶段目标：让 v8 core 具备“外部推演器驱动下的最小完整战斗闭环”。

## 勾选规则

一项任务只有同时满足以下条件，才可以勾选：

- 代码实现完成。
- 正例验证完成。
- 负例验证完成。
- snapshot replay 通过。
- source audit 通过。
- blocked / audit_only / discovered_only 不产生 mutation 的约束被验证。
- 没有引入 runtime 读取 raw TBGD、TextMap、旧 v7、旧 model pack。
- 若改变接口或行为，已在任务记录中说明是否需要兼容。

只完成设计或半条纵切时，不勾选最终任务；可以勾选对应的设计子项。

## P1-0 动作权责边界

目标：明确外部推演器负责选择动作，v8 core 只负责合法性判断、规则执行、transition 输出。敌方 AI 不做。

详细计划见 `P1_0_ACTION_BOUNDARY_TASK_PLAN.md`。

- [x] P1-0.1 梳理当前 `ActionCommand`、`CombatExecutor.execute`、queue drain、enemy action candidate 的实际边界。
- [x] P1-0.2 定义 action availability 数据结构或等价查询结果。
- [x] P1-0.3 区分 `external_selectable`、`queued_mandatory`、`queued_selectable`、`blocked` 四类行动状态。
- [x] P1-0.4 明确 ally 普通行动如何暴露给外部推演器。
- [x] P1-0.5 明确 enemy 普通行动如何暴露给外部推演器，确保 core 不替敌方做策略选择。
- [x] P1-0.6 明确 summon 独立行动是否作为 external selectable，以及缺 timeline admission 时如何 blocked。
- [x] P1-0.7 明确 ultimate interrupt window 如何表达为 selectable window。
- [x] P1-0.8 明确 mandatory queue item 存在时，普通 action input 如何被拒绝。
- [x] P1-0.9 为 action availability 增加 transition/process 观测字段。
- [x] P1-0.10 增加 ally legal action 正例验证。
- [x] P1-0.11 增加 enemy legal action 正例验证。
- [x] P1-0.12 增加 enemy explicit command 执行验证。
- [x] P1-0.13 增加 enemy action 缺来源 blocked 验证。
- [x] P1-0.14 增加 mandatory queue 阻塞普通输入验证。
- [x] P1-0.15 更新阶段报告，说明敌方 AI 不在 core 中实现。

完成口径：

- [x] P1-0-DONE core 不主动决定敌人动作，外部可枚举当前可输入动作，mandatory queue 与 selectable action 不混淆。

## P1-1 UnitLifecycle 通用系统

目标：统一角色、敌人、召唤物、assistant/servant 相关实体的出生、死亡、退场、复活预留、行动资格。

详细计划见 `P1_1_UNIT_LIFECYCLE_TASK_PLAN.md`。

- [x] P1-1.1 审查 `UnitState`、damage kill attribution、target alive/dead filter、timeline eligibility 当前实现。
- [x] P1-1.2 定义 UnitSpawn mutation 语义。
- [x] P1-1.3 定义 UnitDefeat mutation 语义。
- [x] P1-1.4 定义 UnitRemove mutation 语义。
- [x] P1-1.5 定义 UnitRevive 的 blocked 或预留策略。
- [x] P1-1.6 明确 defeated 与 removed 的区别。
- [x] P1-1.7 明确 removed unit 是否保留 tombstone 以支持 replay 和 audit。
- [x] P1-1.8 将 damage 导致 HP 到 0 的路径接入 UnitDefeat。
- [x] P1-1.9 统一死亡单位在 target resolver 中的过滤行为。
- [x] P1-1.10 统一死亡 actor 的 action availability 行为。
- [x] P1-1.11 统一死亡或 removed actor 对 pending queue item 的取消、跳过或 blocked 行为。
- [x] P1-1.12 统一死亡或 removed unit 对 timeline plan 的影响。
- [x] P1-1.13 为 spawn unit 建立初始 profile/card/source trace 要求。
- [x] P1-1.14 增加 damage defeat 正例验证。
- [x] P1-1.15 增加 dead target skipped 验证。
- [x] P1-1.16 增加 dead actor action blocked 验证。
- [x] P1-1.17 增加 UnitSpawn replay 验证。
- [x] P1-1.18 增加 UnitRemove replay 验证。
- [x] P1-1.19 增加 queue item actor removed 后处理验证。
- [x] P1-1.20 更新阶段报告，说明 lifecycle 对 target、timeline、queue、damage 的统一影响。

完成口径：

- [x] P1-1-DONE 单位生灭全部通过 mutation，target/timeline/queue/damage 对死亡和退场语义一致。

## P1-2 WaveSystem 最小骨架

目标：让多波战斗成为真实状态系统，而不是只有 `wave_index` 字段。

详细计划见 `P1_2_WAVE_SYSTEM_TASK_PLAN.md`。

- [x] P1-2.1 审查当前 `wave_index`、scenario enemy 构建、`OnWaveMonster`、event dispatch 的实际落点。
- [x] P1-2.2 定义 WaveDefinition IR 或等价 runtime setup 结构。
- [x] P1-2.3 定义 BattleWaveRuntimeState 或等价状态结构。
- [x] P1-2.4 定义 WaveTransitionPlan 或等价处理流程。
- [x] P1-2.5 定义 wave enemy entries 到 UnitSpawn 的来源链路。
- [x] P1-2.6 实现 current wave active enemy 集合跟踪。
- [x] P1-2.7 实现 wave clear 判定。
- [x] P1-2.8 实现 wave_index mutation。
- [x] P1-2.9 实现 wave despawn/remove 处理。
- [x] P1-2.10 实现 next wave spawn 处理。
- [x] P1-2.11 明确 enemy summon 是否计入 wave clear 的策略。
- [x] P1-2.12 明确跨波保留 HP、SP、energy 的策略。
- [x] P1-2.13 明确跨波状态保留或清理策略。
- [x] P1-2.14 明确跨波 queue 清理策略。
- [x] P1-2.15 明确跨波 summon 保留策略，缺来源时 blocked。
- [x] P1-2.16 接通真实 wave event source。
- [x] P1-2.17 接通 `OnWaveMonster` 可执行触发路径或明确 blocked 原因。
- [x] P1-2.18 增加 current wave clear 正例验证。
- [x] P1-2.19 增加 next wave spawn 正例验证。
- [x] P1-2.20 增加 wave_index replay 验证。
- [x] P1-2.21 增加 missing wave definition blocked 验证。
- [x] P1-2.22 增加 summon enemy 是否阻塞 wave clear 的验证。
- [x] P1-2.23 更新阶段报告，说明 wave source、mutation、event、replay 链路。

完成口径：

- [x] P1-2-DONE 击杀当前波最后敌人后，可通过 mutation 进入下一波，新波敌人由规则生成并可 replay/source audit。

## P1-3 Summon / Assistant / Servant 最小闭环

目标：把 summon/assistant/servant 从预留字段推进为可执行实体或可执行队列语义。

详细计划见 `P1_3_SUMMON_ASSISTANT_SERVANT_TASK_PLAN.md`。

- [x] P1-3.1 审查 `UnitSide=summon`、snapshot teams、target resolver、timeline summon admission、monster `summon_refs`、assistant queue 当前实现。
- [x] P1-3.2 定义 `battle_unit_summon`、`assistant_ability`、`servant`、`summoned_monster` 的分类。
- [x] P1-3.3 明确 summon 是否使用 `summon` side，敌方召唤怪是否使用 `enemy` side 加 summon metadata。
- [x] P1-3.4 定义 summon owner/summoner/source/lifetime/timeline/targetability/wave persistence 字段。
- [x] P1-3.5 定义 assistant queue item 的 owner/source/ability/target 字段。
- [x] P1-3.6 定义 servant 是独立 unit 还是 owner-bound runtime component。
- [x] P1-3.7 接入 `SummonMonster` admission 的第一条真实来源路径。
- [x] P1-3.8 将 summon spawn 接入 UnitSpawn。
- [x] P1-3.9 将 summon death/expire 接入 UnitDefeat/UnitRemove 或在缺真实来源时 detailed blocked。
- [x] P1-3.10 接入 summon target resolver。
- [x] P1-3.11 接入 owner 的 summon target。
- [x] P1-3.12 接入 enemy summon target。
- [x] P1-3.13 接入 summon timeline eligibility。
- [x] P1-3.14 缺 summon speed/AV 来源时保持 blocked 或不可行动，不使用默认值。
- [x] P1-3.15 接入 assistant queue ability 的最小执行路径或详细 blocked。
- [x] P1-3.16 明确 assistant damage/status/resource 归因或 blocked 边界。
- [x] P1-3.17 增加 summon monster spawn 验证。
- [x] P1-3.18 增加 summon targetable 验证。
- [x] P1-3.19 增加 summon death/expire executable 或缺真实来源 blocked 验证。
- [x] P1-3.20 增加 owner death interaction 验证。
- [x] P1-3.21 增加 assistant queue ability execution 或详细 blocked 验证。
- [x] P1-3.22 增加 unsupported summon blocked 验证。
- [x] P1-3.23 更新阶段报告，说明 summon/assistant/servant 的分类和已支持范围。

完成口径：

- [x] P1-3-DONE 至少一种真实 summon 或 assistant 机制可从 IR admission 到 runtime mutation，并通过 replay/source audit。

## P1-4 状态系统主体

目标：把 buff/debuff/control/DoT 的通用状态底座补齐，避免后续角色、怪物、光锥、遗器扩面时出现 runtime 特判。

详细计划：`P1_4_STATUS_SYSTEM_TASK_PLAN.md`。P1-4 是状态系统主体阶段，每个小项必须按“目标 / 要做什么 / 验收结果 / 禁止事项”执行，不能只以验证脚本通过作为完成标准。

来源缺口口径：当前若结构化扫描证明某机制没有真实 TBGD / IR 正例，只能记录为 `source_gap_blocked` 并验证 state unchanged，不能合成 executable mutation 来勾选。已知缺口包括 `P1-4.11 stack + duration refresh` 和 `P1-4.29 / P1-4.42 random dispel`。

- [x] P1-4.1 审查 `systems/status.py`、`status_callbacks.py`、`AddModifier`、`RemoveModifier`、DoT/status damage 当前实现。
- [x] P1-4.2 定义 status instance identity 和 source stack 规则。
- [x] P1-4.3 实现 max stack admission。
- [x] P1-4.4 实现 add stack mutation。
- [x] P1-4.5 实现 stack cap。
- [x] P1-4.6 实现 stack reduce 和 stack 到 0 移除。
- [x] P1-4.7 实现 stack 影响 dynamic value/formula 的读取路径。
- [x] P1-4.8 定义 refresh policy admission。
- [x] P1-4.9 实现 duration refresh。
- [x] P1-4.10 实现 stack-only refresh。
- [ ] P1-4.11 实现 stack + duration refresh。
- [x] P1-4.12 实现 replace/coexist 的最小可执行策略。
- [x] P1-4.13 定义 duration tick owner：holder turn、caster turn、action、wave、permanent。
- [x] P1-4.14 实现 turn start duration tick。
- [x] P1-4.15 实现 turn end duration tick。
- [x] P1-4.16 实现 action after duration tick。
- [x] P1-4.17 实现 wave end status cleanup。
- [x] P1-4.18 实现 status expire mutation。
- [x] P1-4.19 将 DoT tick 接入状态生命周期。
- [x] P1-4.20 实现 tick 后 callback 触发。
- [x] P1-4.21 定义 chance admission：base chance、effect hit、effect resist、immunity。
- [x] P1-4.22 接入状态命中的 RNG event。
- [x] P1-4.23 实现 status apply success settlement。
- [x] P1-4.24 实现 status apply failure settlement。
- [x] P1-4.25 实现 resisted settlement。
- [x] P1-4.26 实现 immunity settlement。
- [x] P1-4.27 定义 dispellable、positive、negative、control 分类。
- [x] P1-4.28 实现确定性 dispel。
- [ ] P1-4.29 实现随机 dispel 的 RNG 接入。
- [x] P1-4.30 实现 dispel skipped/failed settlement。
- [x] P1-4.31 定义 control 对 action availability 的 gating。
- [x] P1-4.32 定义 control 对 timeline/queue 的最小影响。
- [x] P1-4.33 增加 status apply success 验证。
- [x] P1-4.34 增加 chance failure 验证。
- [x] P1-4.35 增加 resisted 验证。
- [x] P1-4.36 增加 immunity 验证。
- [x] P1-4.37 增加 stack cap 验证。
- [x] P1-4.38 增加 duration refresh 验证。
- [x] P1-4.39 增加 DoT tick 验证。
- [x] P1-4.40 增加 expire remove 验证。
- [x] P1-4.41 增加 deterministic dispel 验证。
- [ ] P1-4.42 增加 random dispel replay 验证。
- [x] P1-4.43 增加 control blocks action 验证。
- [x] P1-4.44 增加缺 chance/formula/source blocked 验证。
- [x] P1-4.45 更新阶段报告，说明状态通用语义和剩余 blocked 范围。

完成口径：

- [x] P1-4-SUBSTRATE-ACCEPTED 状态系统底座已通过有来源正例和 source-gap/blocked 验证；剩余无真实来源项不产生 synthetic mutation。
- [ ] P1-4-DONE 状态 stack、refresh、duration、tick、chance/resist/immunity、dispel、control gating 形成通用底座并通过验证。

## P1-5 行动队列与窗口语义

目标：统一追击、反击、终结技插队、额外回合、assistant、insert action/ability 的窗口和优先级。

详细计划：`P1_5_QUEUE_WINDOW_TASK_PLAN.md`。

验收口径：每个 queue family / window / drain 机制先按 `executable / source_gap_blocked / implementation_missing` 三态判断。有真实 TBGD/IR 来源的机制必须完成 positive executable validation；当前没有真实来源的机制只能做 coverage gap、blocked、state unchanged 和 no synthetic mutation 验证，不能为了勾选 checklist 合成正例。

- [x] P1-5.1 审查 `systems/queue.py`、`QueueIntentIR`、status callback queue intent、executor queue drain 当前实现。
- [x] P1-5.2 定义 battle start、wave start、turn start、before action、after damage、after kill、after action、turn end、wave end、ultimate interrupt、queue drain 等窗口。
- [x] P1-5.3 定义 queue family 优先级，并区分 TBGD source 与 engine scheduling convention。
- [x] P1-5.4 定义 mandatory queue。
- [x] P1-5.5 定义 selectable queue。
- [x] P1-5.6 定义 conditional queue。
- [x] P1-5.7 补齐 queue item 字段：id、family、priority、actor、owner/source、action/ability、target expression、source trace、expiration、cancel。
- [x] P1-5.8 实现 queue drain process event。
- [x] P1-5.9 实现 follow-up 最小顺序。
- [x] P1-5.10 实现 counter 最小顺序。
- [x] P1-5.11 实现 extra turn 与 timeline 的关系。
- [x] P1-5.12 实现 insert action 最小语义或 blocked 策略。
- [x] P1-5.13 实现 insert ability 最小语义或 blocked 策略。
- [x] P1-5.14 实现 assistant family 最小顺序。
- [x] P1-5.15 实现 ultimate selectable window 暴露。
- [x] P1-5.16 实现 actor death/remove 时 pending queue 处理。
- [x] P1-5.17 实现 unknown queue family blocked。
- [x] P1-5.18 增加 follow-up order 验证。
- [x] P1-5.19 增加 counter order 验证。
- [x] P1-5.20 增加 after kill callback 验证。
- [x] P1-5.21 增加 extra turn order 验证。
- [x] P1-5.22 增加 ultimate selectable window 验证。
- [x] P1-5.23 增加 assistant family order 验证。
- [x] P1-5.24 增加 actor removed queue cancel/blocked 验证。
- [x] P1-5.25 增加 unknown family blocked 验证。
- [x] P1-5.26 更新阶段报告，说明 queue/window 顺序和推演器可见边界。

完成口径：

- [x] P1-5-SUBSTRATE-ACCEPTED 队列/窗口底座已通过有来源正例和 source-gap/blocked 验证；mandatory/selectable/conditional 可区分，queue drain 可 replay，推演器能知道当前是否必须先结算队列或等待 selectable window。
- [ ] P1-5-DONE 所有列出的 queue family 和窗口都有真实来源正例，队列顺序确定，mandatory/selectable 可区分，queue drain 可 replay，推演器能知道当前是否必须先结算队列。

## P1-6 目标系统关键缺口

目标：补齐第一阶段最影响通用战斗的目标表达式，并保持失败时 blocked/state unchanged。

详细计划：`P1_6_TARGET_SYSTEM_TASK_PLAN.md`。

验收口径：每个 target expression / sort / fetch / random / adjacent / unique / summon / servant 子机制先按 `executable / source_gap_blocked / implementation_missing` 三态判断。有真实 TBGD/IR 来源的目标机制必须完成 positive executable validation；当前没有真实来源或缺 runtime context 的机制只能做 coverage gap、blocked、state unchanged 和 no synthetic mutation 验证，不能为了提高 coverage 默认选第一个目标、默认排序或偷偷随机。

- [x] P1-6.1 审查 `systems/target.py` 和 TBGD lowering 中 TargetSort、TargetFetch、Retarget、TargetSequence、TargetFilter admission。
- [x] P1-6.2 定义 target resolution record 的完整字段。
- [x] P1-6.3 实现 TargetSort admission。
- [x] P1-6.4 实现按 HP/HP ratio 排序。
- [x] P1-6.5 实现按 toughness 排序或明确 blocked。
- [x] P1-6.6 实现按 position 排序或明确 blocked。
- [x] P1-6.7 实现 TargetFetch caster。
- [x] P1-6.8 实现 TargetFetch owner。
- [x] P1-6.9 实现 TargetFetch partner 或明确 blocked。
- [x] P1-6.10 实现 TargetFetch unique entity。
- [x] P1-6.11 实现 adjacent target。
- [x] P1-6.12 实现 random target 的 deterministic choice 接入。
- [x] P1-6.13 实现 random target 的 RNG event 记录。
- [x] P1-6.14 实现 summon target。
- [x] P1-6.15 实现 servant target 或明确 blocked。
- [x] P1-6.16 实现 dynamic max number admission。
- [x] P1-6.17 明确缺排序规则 blocked。
- [x] P1-6.18 明确缺 payload blocked。
- [x] P1-6.19 明确 unique entity 找不到 blocked。
- [x] P1-6.20 明确 random 缺 RNG choice blocked 或返回需要 choice。
- [x] P1-6.21 增加 HP ratio sort 验证。
- [x] P1-6.22 增加 adjacent target 验证。
- [x] P1-6.23 增加 random target replay 验证。
- [x] P1-6.24 增加 unique summon target 验证。
- [x] P1-6.25 增加 dead/alive filter 验证。
- [x] P1-6.26 增加 missing sort blocked 验证。
- [x] P1-6.27 增加 missing payload blocked 验证。
- [x] P1-6.28 更新阶段报告，说明新增 target expression coverage。

完成口径：

- [x] P1-6-SUBSTRATE-ACCEPTED 目标系统底座已通过有来源正例和 source-gap/blocked 验证；target resolution record 完整，缺排序、缺 payload、缺 RNG choice、unique not found、target removed/defeated 均 blocked/state unchanged。
- [x] P1-6-DONE sort/fetch/adjacent/random/unique/summon target 的第一阶段关键子集均有真实来源正例可用，目标失败不产生 mutation。剩余 source gap：toughness/formation sort 当前无安全正例，owner fetch 无当前数据库正例，servant target 无 executable runtime registry。

## P1-7 RNG 与分支基础

目标：所有概率和随机目标都可记录、可 replay，并为后续推演器分支枚举预留接口。

- [ ] P1-7.1 审查当前 `rng_state`、transition rng events、target random、status chance 相关实现。
- [ ] P1-7.2 定义统一 RNG event 格式。
- [ ] P1-7.3 定义 deterministic choice 输入格式。
- [ ] P1-7.4 明确 seed/draw 模型与 explicit choice ledger 的取舍。
- [ ] P1-7.5 实现状态命中 RNG event。
- [ ] P1-7.6 实现 effect resist RNG event。
- [ ] P1-7.7 实现 control resist RNG event。
- [ ] P1-7.8 实现 random target RNG event。
- [ ] P1-7.9 实现 random bounce RNG event 或明确 blocked。
- [ ] P1-7.10 实现 random dispel RNG event。
- [ ] P1-7.11 增加 `requires_rng_choice` 或等价状态。
- [ ] P1-7.12 增加 `available_rng_outcomes` 或等价预留。
- [ ] P1-7.13 增加 probability weight 记录或预留。
- [ ] P1-7.14 禁止无记录进程随机数进入 runtime。
- [ ] P1-7.15 增加同一 RNG event replay 验证。
- [ ] P1-7.16 增加不同 RNG event 不同合法结果验证。
- [ ] P1-7.17 增加 missing RNG choice blocked 验证。
- [ ] P1-7.18 增加 probability settlement success/failure 验证。
- [ ] P1-7.19 更新阶段报告，说明 RNG ledger 和后续 branch enumeration 预留。

完成口径：

- [ ] P1-7-DONE 第一阶段所有随机和概率路径都进入 RNG event，replay 不依赖进程随机状态。

## P1-8 最小战斗配置入口

目标：提供能表达第一阶段验证战斗的配置入口，避免只能手写 `BattleState`。

- [ ] P1-8.1 审查 `scenarios/schema.py`、`scenarios/build_state.py`、UI scenario 编排当前能力。
- [ ] P1-8.2 定义最小 BattleSetup schema 或扩展 ScenarioSpec。
- [ ] P1-8.3 增加 ally roster 配置。
- [ ] P1-8.4 增加 enemy waves 配置。
- [ ] P1-8.5 增加 initial SP 配置。
- [ ] P1-8.6 增加 initial energy 配置。
- [ ] P1-8.7 增加 initial HP ratio 配置。
- [ ] P1-8.8 增加 initial statuses 配置。
- [ ] P1-8.9 增加 initial summon/servant 配置。
- [ ] P1-8.10 增加 initial timeline 配置或明确由 runtime 初始化。
- [ ] P1-8.11 增加 deterministic RNG choices 配置。
- [ ] P1-8.12 增加 objective metadata 预留。
- [ ] P1-8.13 确保配置入口不成为规则来源。
- [ ] P1-8.14 增加 two-wave setup 验证。
- [ ] P1-8.15 增加 initial statuses setup 验证。
- [ ] P1-8.16 增加 initial summon setup 验证。
- [ ] P1-8.17 增加 deterministic rng setup 验证。
- [ ] P1-8.18 增加不存在 card/profile 构建失败或 blocked 验证。
- [ ] P1-8.19 更新 scenario README 或阶段报告，说明第一阶段配置入口边界。

完成口径：

- [ ] P1-8-DONE 可以用配置文件构建两波、有状态、有召唤、有 deterministic RNG 的第一阶段验证战斗。

## P1-9 聚合验证与阶段验收

目标：把第一阶段拆散的能力合并成可重复的验收命令和报告。

- [ ] P1-9.1 新增第一阶段聚合 validation 命令。
- [ ] P1-9.2 聚合 action boundary 验证。
- [ ] P1-9.3 聚合 UnitLifecycle 验证。
- [ ] P1-9.4 聚合 WaveSystem 验证。
- [ ] P1-9.5 聚合 Summon/Assistant/Servant 验证。
- [ ] P1-9.6 聚合状态系统验证。
- [ ] P1-9.7 聚合 queue/window 验证。
- [ ] P1-9.8 聚合 target 验证。
- [ ] P1-9.9 聚合 RNG 验证。
- [ ] P1-9.10 聚合 BattleSetup 验证。
- [ ] P1-9.11 聚合 snapshot replay 验证。
- [ ] P1-9.12 聚合 source audit 验证。
- [ ] P1-9.13 增加 static checks，确认 runtime 不引用旧 simulator、旧 model pack、TextMap、raw TBGD。
- [ ] P1-9.14 生成第一阶段 source audit 抽样报告。
- [ ] P1-9.15 生成第一阶段 blocked/audit_only/discovered_only 不产生 mutation 报告。
- [ ] P1-9.16 新增 live validation report。
- [ ] P1-9.17 更新 `CODEX_HANDOFF.md` 或主线交接摘要。
- [ ] P1-9.18 跑 `compileall`。
- [ ] P1-9.19 跑第一阶段聚合 validation。
- [ ] P1-9.20 跑 `git diff --check`。

完成口径：

- [ ] P1-9-DONE 第一阶段所有聚合验证通过，报告说明当前做到哪里、剩余 blocked 范围、距离完整复刻还缺什么。

## 全阶段验收

以下全部勾选后，第一阶段才算完成：

- [ ] PHASE1-ACCEPT-1 外部可以显式驱动 ally/enemy/summon 合法动作。
- [ ] PHASE1-ACCEPT-2 core 不做敌方 AI。
- [ ] PHASE1-ACCEPT-3 多波战斗可通过 WaveSystem 推进。
- [ ] PHASE1-ACCEPT-4 单位 spawn、defeat、remove 可 replay。
- [ ] PHASE1-ACCEPT-5 至少一种 summon 或 assistant 机制能真实执行。
- [ ] PHASE1-ACCEPT-6 状态 stack、refresh、duration、tick、chance/resist/immunity、dispel 有通用底座。
- [ ] PHASE1-ACCEPT-7 follow-up、counter、extra turn、assistant、ultimate window 有清晰队列/window 语义。
- [ ] PHASE1-ACCEPT-8 sort/fetch/adjacent/random/unique/summon target 的关键子集可用。
- [ ] PHASE1-ACCEPT-9 RNG 事件进入 transition，不存在不可追踪随机。
- [ ] PHASE1-ACCEPT-10 最小 BattleSetup 能构建两波、有状态、有召唤、有 deterministic RNG 的验证场景。
- [ ] PHASE1-ACCEPT-11 聚合 validation 通过。
- [ ] PHASE1-ACCEPT-12 snapshot replay 通过。
- [ ] PHASE1-ACCEPT-13 source audit 通过。
- [ ] PHASE1-ACCEPT-14 blocked/audit_only/discovered_only 不产生 mutation。
- [ ] PHASE1-ACCEPT-15 runtime 不引用旧 simulator、旧 model pack、TextMap、raw TBGD。

## 当前状态

- [ ] 第一阶段未开始实现。
- [x] 第一阶段实现中。
- [ ] 第一阶段已完成。

当前建议从 `P1-4 状态系统主体` 开始。P1-0 至 P1-3 已形成第一阶段前置底座；不要先做内容扩面。
