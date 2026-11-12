# 怪物召唤单位的有效等级与出生属性

起点：`7ff13e3`，TBGD 固定为 `14c1d18f91a8101d610e6c523447a7517de3fae1`。
实现：dsh / DeepSeek；范围、约束与集中验收：Codex。当前状态只在[交接](../../../../CODEX_HANDOFF.md)维护。

## 本批成果

纠正怪物召唤的出生数值，使正式来源波次内的子单位按其有效等级、难度上下文和自身卡片
生成 HP、攻击、防御、速度及韧性，初始 AV 使用最终速度和实际 DelayRatio。
同一出生事实继续被伤害、治疗、目标、时间线、原生审计与 replay 消费。

修复后重新交付上一批的公开自然链：召唤 → 子单位行动 → 自然击败一个子单位 → 召唤者
存活时再次召唤 → 新实例行动 → 后续公开提交。允许调整正式成品构筑和固定命令以适应正确数值，
不覆盖运行时 HP、面板、资源或时间线。本批不要求打完银鬃尉官，也不扩展死亡退场队列。

## 已核对事实

- Stage `307311` wave 0 的银鬃尉官 `1003010` 为 Lv44，StageConfig 的 HardLevelGroup 为 2。
  子卡 `1002040` 的 MonsterConfig 默认 HardLevelGroup 为 1；这两种声明不能混作同一个输入。
- Codex 使用已有场景和缓存规则进行了公开召唤。子单位实际 `level=44`，但 HP 为 `120.9`、
  攻击 `18`、防御 `210`、速度 `83`，逐项等于 `CombatantProfileIR.base_stats`。
- `_summon_monster_entry_from_raw` 当前将 `level_policy.kind` 标为
  `profile_base_stats_no_runtime_level_scaling` 并准入；`_summoned_monster_birth_template`
  只把 `level` 绑定到 owner，面板则固化为基础值。这是实际数值缺陷，不是新功能需求。
- HardLevelGroup 表的 Lv44 行明显不是单位倍率：组 1 的 HPRatio 为 `14.570795`、AttackRatio 为
  `10.381433`；组 2 分别为 `21.74886`、`12.875552`。这些数值说明缩放缺失，不能据此任选一组。
- 正式波次出生已经通过 `_wave_level_policy` 与 `_wave_enemy_birth_template` 处理等级/难度倍率。
  优先复用其来源解析、字段映射和绑定方式，不再造一套怪物面板引擎。
- `_summon_damage_stat_blocked_reason` 当前仅以档案 executable 为召唤怪物放行；档案存在不能
  证明本次实例已取得正确等级的面板。这里是必须同步核对的消费者。

临时事实：`/tmp/hsr_next_batch_summon_stat_facts.json`；公开出生记录见
`/tmp/hsr_next_batch_owner_death_probe.json`。后者只提供出生和行动的探查记录，未完成召唤者死亡。
以上关键事实均已写在正文，不依赖临时文件长期保存。

## 开工先确定的来源口径

先核定召唤的有效等级、HardLevelGroup 和适用的 EliteGroup 从何处继承，以及显式覆盖的优先级。
尤其核对本例 Stage 组 2 与子卡默认组 1 的差异；不能直接复制父单位最终面板，不能为了让旧
命令通过而选较弱倍率，也不能凭一个同名字段擅自裁定覆盖。

采用适用的 TBGD 或可靠机制资料，把结论、链接/来源路径及适用条件写入现有规则说明后实施；
成熟规则由工程侧直接采用。仅当存在实际未解冲突时保留具体冲突，不把猜测变成 executable。
本批的数值预期必须在该口径确定后建立，不能先锁死某个组的答案再倒推规则。

## 生产权威与完整调用链

| 边界 | 本批需要核对的生产者与消费者 |
| --- | --- |
| 来源与基础面板 | MonsterConfig / MonsterTemplateConfig / HardLevelGroup / EliteGroup；已有 CombatantProfile 与波次等级策略，确认各层已应用的倍率 |
| 编译 | `tbgd/lowering.py` 的 `_hard_level_profiles`、`_wave_level_policy`、`_summon_monster_entry_from_raw`、`_summoned_monster_birth_template`、`_birth_profile_stat_resolutions` |
| 正式输入 | 现有 IR / RuleBook 与出生请求承载有效上下文、选中来源及数值；只做必要扩展，不把 `source.evidence` 或 raw_parameter_blocks 变为运行参数 |
| 出生与校验 | `AbilityTaskSystem.execute_summon_monster_task` → `SummonSystem.plan_spawn_from_intent/apply_spawn` → `UnitSpawnSystem.plan/UnitSpawnPlan.to_unit`，实际单位和请求重验使用同一正式输入 |
| 后续消费 | 初始 AV、`core/executor.py` 的召唤伤害门禁、普通属性/伤害消费者、出生后启动及光环；不绕过已有生命周期 |
| 证明 | 原生 spawn mutation / settlement / `RuntimeSourceAuditor._audit_summon_mutation` / 保存与回放，不能只证明来源字段存在 |

## 一次性实现与审查约束

1. **等级和数值同源。** 展示等级、倍率选择、实际面板与证据必须一致。按当前有效上下文解析，
   不将编译时一个默认等级固化到全部实例；跨等级、跨卡、跨难度不能共享错误缓存结果。
2. **倍率只应用一次。** 确认档案中已经包含的模板/卡片修正，再应用实际等级/难度修正。
   HP、攻击、防御、速度、韧性分别映射对应字段，不能一律乘 HP 比例；无缩放的字段保留其正式固定值。
   抗性、弱点等不借本批擅自新增经验公式。
3. **权威输入独立于审计。** runtime 不读 raw、网页、文件名或审计 evidence 取业务值。
   不按角色/怪物 ID 分支。优先复用已编译的上下文；不能每次召唤扫描来源全表。
4. **出生之后不回退。** 数值缺失、冲突、非法或等级不受支持必须在正式边界阻断，不能回退
   基础档案、等级 1、父面板或默认倍率。消费门禁必须识别缺少有效缩放的实例。
5. **派生值一致。** 满血出生应 `hp == max_hp`，满韧出生同理。AV 用最终速度计算，并只应用一次
   实际分支 DelayRatio；不改变其它单位的 HP/AV。First/Last 端点顺序与位置唯一性保持。
6. **请求与序列化完整。** 必要新增字段纳入请求身份、重验、IR 指纹和缓存往返，合法输入编码前后
   一致，非法输入不能经默认值或过滤静默变成有效输入。参数保持卡片/实例/当前战斗作用域。
7. **父技能仍原子。** 第二个出生条目缺少等级/难度输入时，父动作资源、计数、所有新单位、
   事件、RNG、出生后启动和派发身份一起回滚；失败不能保留第一只的候选状态。
8. **数值审计实际写入。** 原生记录保留基础值、有效等级/难度、选中行、倍率与结果，实际 spawn
   数值必须与其一致。只改实际出生属性或错配倍率行并重新关联 settlement，审计仍须拒绝。
9. **共享修复的边界。** 覆盖正式召唤入口的同类消费者；已有波次入场和 servant 构筑路径不退化。
   子怪先自然死亡、再召唤新实例时重新取得正确输入，不继承旧 HP、状态、动态值或旧解析结果。

Codex 验收先读完整生产差异和直接调用者，再检查测试是否独立证明上述不变量；不会以
“测试很多”“档案 executable”或 replay 自洽代替等级面板正确性的核对。

## 最小合并验证

- 先做一个组件模块：同一真实子卡的至少两个来源等级/难度上下文，以及一次异卡隔离。
  期望值独立读取所选正式行并计算，不调用被测的缩放 helper 生成预期。至少一组倍率不为 1。
  这些是明确标注的组件输入，不宣称两条完整战斗已通过。
- 一个必要失败检查覆盖第二个出生失败整笔回滚；一个数值篡改检查覆盖实际写入与原生审计。
  复用已有测试和只读前置，不另建庞大负例矩阵。
- 新旧字段经过 IR/请求编码和编译缓存恢复；按实际改动选取
  `test_wave_birth_source_proof.py`、`test_monster_summon_atomicity.py`、
  `test_monster_spawn_position_endpoints.py`、`test_servant_create_continuation.py` 等相关小检查，
  不运行其名称对应的历史阶段套餐。
- 组件通过后，将现有 `test_monster_summon_natural_route.py` 和对应示例/命令更新到正确数值，
  一次构建、一次入场完成公开链；对召唤与子行动做原生审计，用同一会话保存归档并独立 replay
  一次。不再另跑 CLI 生成重复战斗；原有低血量下的一击击败子单位不能继续当验收前提。
- 使用已有 `.venv`，重任务串行持有 `/tmp/hsr-v8-validation.lock`。本批不做全目录编译或
  全量回归，不新增依赖、环境，不更新 submodule。冷构建/命中/自然链/回放成本分开记录。

交付：正式来源口径、修复后的实际出生值与独立预期、公开自然链、审计/回放及剩余限制。
替换当前短交接和相关文档中的过期结论，未提交、未推送，整批交回 Codex 集中验收。

## 已定位的后续入口（本批不实现）

`Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json` 的 `MCommon_Servant`：
OnCreate 注册 `Common_Servant_Forcekill`；OnListenCharacterDie 经 ByHasSummonRelation
确认关联后，使用 MonsterForceKill 优先级排队执行。目标能力位于
`Config/ConfigAbility/Common_Additional_Ability.json`，ForceKill 带
`AbortUnusedInsertAbility=true`。现有准入只支持另一种双 mute 退场形状。

因此后续应沿正式死亡监听和队列接通强制退场，不能按“召唤者死亡就全删”绕过来源。
`WaveSystem` 对计入清场的存活召唤物目前会返回实现阻断；该终局行为须与退场队列一起核对。

## 本批交付

### 已核定的来源口径

- 召唤任务只声明 `MonsterID` / `LocationType` 与任务级 `DelayRatio`；
  `Config/ConfigAbility/Monster/Monster_W1_Soldier03_00_Ability.json` 的 `SummonMonster`
  节点没有等级、难度或倍率字段，因此召唤单位不可能携带自己的难度覆盖。
- 固定来源中 `MonsterConfig.HardLevelGroup` 的 2509 行全部为 1，
  `MonsterUniqueConfig` 的 35 行也全部为 1：卡片字段不含逐卡信息，不能当战斗难度。
- `StageConfig.HardLevelGroup` 按 `StageType` 区分（Mainline 1 / VerseSimulation 2 /
  Challenge 3），`EliteGroup` 同样是关卡字段；难度是战斗输入而不是卡片输入。
- 493 个可被召唤的怪物卡 `EliteGroup` 全部为中性 1，数据里没有逐卡精英倍率可叠加。
- 结论：召唤单位的有效等级 = 当前战斗关卡等级（本例 44，与召唤者等级一致）；
  HardLevelGroup / EliteGroup 取当前战斗的关卡上下文，倍率取 `HardLevelGroup` 的选中行
  （若关卡声明 EliteGroup 则先并入该倍率）。卡片 HardLevelGroup/EliteGroup 只作为审计证据
  记录，不参与运行，也不存在同名字段覆盖优先级。
- 选中行：`ExcelOutput/StageConfig.json` 的 `307311`（Level 44、HardLevelGroup 2、
  无 EliteGroup）、`ExcelOutput/HardLevelGroup.json` 的 `(2, 44)`、
  `ExcelOutput/MonsterTemplateConfig.json` / `MonsterConfig.json` 的 `1002040`。

### 实现

- 编译：`SummonMonsterEntryIR.level_policy` 改为
  `battle_stage_level_hard_level_group_inherited_from_summoner`，卡片默认值只进证据；
  出生模板的等级与五项面板改为 `level_context_field` / `level_context_scaled_stat`
  绑定（base 值为已含 MonsterConfig 修正的 profile base），AV 仍由最终 speed 与
  DelayRatio 计算一次。
- 运行：`SummonSystem` 从 `global_flags.wave_runtime` 找到当前关卡波次定义，取
  `level_policy` 的等级、经验难度组、精英组与倍率，写成 `request.level_context`；
  缺关卡身份、缺策略、倍率非法或召唤者等级与策略不一致都会在规划阶段阻断整笔召唤，
  不回退基础档案、等级 1、父面板或默认倍率。
- 消费：`_summon_damage_stat_blocked_reason` 对召唤怪物额外要求可执行的
  `summon_level_context` 与五项倍率，否则 `summon_damage_stat_level_scaling_not_admitted`。
- 审计：spawn mutation 记录有效等级/难度、选中行来源、倍率、profile base 与结果；
  `RuntimeSourceAuditor` 从 RuleBook 的波次等级策略与 `CombatantProfileIR` 重新计算
  五项面板、满血/满韧与初始 AV，实际写出值或倍率行被改动都会被拒绝。
- 请求：`level_context` 进入 `UnitSpawnRequest` 的序列化、行为身份、模板重验与
  `plan.to_unit` 重算；非法输入不会被默认值或过滤静默转成有效输入。

### 审查加固（P2）

Codex 两轮复查共指出 6 处审计缺口与 10 个放行反例（原 5 例 + 复查新增 5 例），全部已修复；
10 例已从 /tmp 迁入仓库测试 `test_monster_summon_birth_stats.py` 的参数化用例
`test_birth_audit_rejects_mismatched_formal_identity`。

第一轮的 3 处缺口：

- 出生审计入口由实际 spawn 与正式召唤定义驱动，不再由 `summon_operation` 标签决定是否检查数值：
  标签缺失/不一致本身也记违规，但仍执行数值审计。
- 数字档案从 `intent → entry → birth_template` 解析：profile 身份、base 值、DelayRatio 与等级上下文
  取正式 IR（模板 bindings 与 `intent.delay_policy`），metadata 只是被核对的记录；实际单位 flags、
  metadata 与原生 settlement 计划里的 `unit_spawn_plans` / `unit_spawn_requests` 逐项一致。
- 来源行比较改为按嵌套路径：stage / hard_level_profile / elite_group 每个节点保留自身身份与 evidence
  树，避免两侧都被归一为空、选错难度行仍被放过。

复查新增的 3 处缺口：

- 出生种类不能信任被审标签：统一从实际 spawn payload 判定，`summoned_monster` 走数值审计，
  `servant` 必须解析到可执行的 `ServantDefinitionIR` 并核对定义身份与原生计划；
  非对象/缺 flags/未知种类 payload 一律拒绝。仅把 `summon_kind` 改成 `servant`、把操作标签改成
  `servant_spawn` 再调 `max_hp` 会被定义缺失与计划不一致双重拒绝。
- 上下文副本与缩放摘要要完整核对：除了行为身份，还比较每个上下文副本（record / 单位 flags /
  settlement plan / plan flags / plan request / scaling）的嵌套来源树；单位实际
  `summon_stat_scaling` 也按完整摘要身份（等级、难度组、精英组、倍率、来源行）核对。
- 结算生产者要校验：`summon_transition` + `summon_system` + 当前 mutation/计划身份一致，
  任意记录里携带的 `plan` 不再被当作原生结算证明。

回归：仓库内 10 个反例全部被拒绝（`-k birth_audit`：10 passed，4 deselected）；组件其余 4 项与
自然链 1 项（含独立 replay，253.82 s）通过；非集成回归仍为 637 passed / 28 项基线既有失败，
无新增失败。

### 独立预期（本例，全部由 TBGD 选中行直接计算）

- 卡片基础（已含 MonsterConfig 修正）：HP 120.9、攻击 18、防御 210、速度 83、韧性 60。
- Lv44 HardLevelGroup 2：HP 21.74886、攻击 12.875552、防御 3.047619、速度 1、韧性 1。
- 出生面板：HP 2629.437174、攻击 231.759936、防御 639.99999、速度 83、韧性 60；
  `hp == max_hp`、`toughness == max_toughness`；AV = 10000 / 83 = 120.48192771084338。
- 对照：尉官波次面板为 20226.4398 / 231.759936 / 639.99999 / 120 / 240，未被本批改变。

### 公开自然链（已更新）

- 队伍：希儿 Lv80 E0 空装备（新增正式构筑）、阿兰、娜塔莎。
- 16 步公开提交：step 0 召唤；step 1–4 破韧并由希儿战技直伤自然击败一个子单位；
  step 5 尉官存活时再次召唤；step 12/13 两个新实例各行动一次；step 14/15 继续公开提交。
- 示例 `examples/cli/silvermane_lieutenant_summon_natural{,.commands}.json` 已更新到正确数值；
  `test_monster_summon_natural_route.py` 对召唤与子单位行动做原生审计，同会话归档后由
  独立进程 `cli replay` 复跑 0 错误。

### 验证与成本

- 新增 `test_monster_summon_birth_stats.py`：同一真实子卡两个来源等级/难度上下文、
  异卡隔离、缺上下文阻断、出生数值篡改与错配倍率行拒绝；4 项通过，18.62 s。
- `test_monster_summon_natural_route.py` 通过，1 passed 268.29 s（含独立 replay 子进程）；
  交付前两项合跑 5 passed，258.18 s。
- 相关组件回归：`test_monster_custom_value_binding` / `test_monster_summon_atomicity` /
  `test_monster_spawn_position_endpoints` 30 passed（1.68 s）；
  `test_wave_birth_source_proof` 13 passed（29.01 s）。
- 非集成回归：637 passed / 28 failed，28 项全部落在
  `test_p9_a2_s8c1b_materialization_regression.py` 与
  `test_p9_a2_weighted_materialization_dispatch.py`；原因是基线 `_build_graph()` 缺
  `admitted_insert_action_task_ids` 参数，在 `7ff13e3` 的同一 in-memory fixture 上
  复现同样的 TypeError，与本批改动无关。
- 另有 4 项字符/编译集成检查（`test_compiler_consistency`、`test_character_build_startup`、
  `test_character_passive_startup`、`test_eidolon_source_branches`）当前为 4 failed / 6 passed；
  在 `7ff13e3` 基线上复跑，失败集合完全一致（同一 `_build_graph()`/内容期望漂移），与本批无关。
- 编译成本：同一示例场景冷构建 34.03 s，命中缓存 3.4 s；未做全目录编译，未新增依赖、
  环境或 submodule 更新。

### 剩余限制

- MonsterConfig 的 EliteGroup 在个别特化卡上非中性（140/705 等），当前可召唤集合全部为 1；
  若将来出现非中性精英倍率，需另行核定是否叠加。
- 只有正式关卡波次承载 battle level context；没有 stage/wave 身份的战场会 fail-closed。
- 本批之前生成的召唤归档不保证 replay：旧实例没有等级上下文，按 fail-closed 阻断。
- 仍只覆盖「怪物 → 子怪」召唤路径；召唤者死亡后的
  `MCommon_Servant → Common_Servant_Forcekill`、清场与终局行为仍留后续批次。
