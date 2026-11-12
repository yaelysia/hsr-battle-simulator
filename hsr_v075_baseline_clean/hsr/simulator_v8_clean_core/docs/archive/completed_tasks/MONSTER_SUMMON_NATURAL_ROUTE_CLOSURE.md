# 战斗中怪物自然召唤与后续行动

基线 `255f153`，包含已验收性能优化 `b1f42db`。实现：dsh / DeepSeek；约束与集中验收：Codex。
验收：2026-10-22 通过 Codex 集中验收，随本提交收口。当前状态以[交接](../../../../CODEX_HANDOFF.md)为准。

后续复查发现：子单位虽标为 Lv44，出生面板仍直接使用基础档案，未应用等级/难度缩放。
出生面板已在后续批次按当前战斗关卡等级/难度上下文修正（该批交付与验证见
[召唤出生属性任务](MONSTER_SUMMON_STAT_BINDING.md)），示例与固定命令也随之更新；本文其余
运行证据只证明控制流及当时输入下的审计/回放，数值以新批次为准。

## 本批可观察成果

从正式角色构筑与来源波次入场，经外部 `BattleSession.advance/submit` 完成：

```text
银鬃尉官正常入场 → 外部合法选择召唤技能 → 来源分支自然召唤士兵
→ 子单位完成出生和被动启动 → 进入时间线并执行一次正式动作
→ 玩家自然击败至少一个子单位 → 尉官仍存活时再次合法召唤
→ 新实例进入正常行动流程 → 继续一次公开操作
```

目标是关闭 V3 的一条自然路线与其共享依赖，不以生成 spawn mutation、直接调用 SummonSystem
或单个叶子可执行代替交付。不要求本批完成整场胜利或全怪物目录。

## 已核对的事实与固定入口

- 波次：`ExcelOutput/StageConfig.json` 的 `StageID=307311`，wave 0，Level 44，
  原始队伍为单只 `1003010`。使用 `wave_only`，不声明该 Rogue 关卡完整环境已支持。
- 父卡：`MonsterConfig[MonsterID=1003010]`；配置为
  `Config/ConfigCharacter/Monster/Monster_W1_Soldier03_00_Config.json`。
  配置与该行的 `SummonID01 / SummonID02` 一致，均为 `1002040`；
  `SummonIDList=[1002040,1002040]`。编译已自动加载父卡和子卡，不再修一遍依赖收集。
- 公开技能：`monster_skill:100301004`，`SkillTriggerKey=Skill08`，来源
  `Config/ConfigAbility/Monster/Monster_W1_Soldier03_00_Ability.json` 的
  `Monster_W1_Soldier03_00_Skill08_Phase02`。召唤经 PredicateTaskList 决定，
  读取 `MonsterIDFromCustomValue.Hash`，位置为 First/Last；不能把分支展开成无条件出生。
- 被动根：同文件 `Monster_W1_Soldier03_00_PassiveSkillInitiate`。包含 AddModifier、
  DefineDynamicValue 与 ByCompareMonsterID；其中 SummonCounter 的 Define 省略 ResetValue，
  AICounter 的 ResetValue 显式为 1。省略值的语义须沿现有正式规则或适用资料核对，不能猜 0。
- Codex 在当前基线上做了一次限定构建及入场：35.28 s 构建，43.44 s 总墙钟，
  峰值 891676 KiB。正式入场以 `monster_passive_startup_root_on_start_has_unadmitted_tasks`
  拒绝；该来源 24 条召唤候选 intent（含不同入口投影）均缺
  `custom_value_hash_to_name_binding_missing`，继而无法解析子卡及等级策略。
  这是初始化与静态绑定的证据，尚未执行父技能；不把所有 24 条候选都变成本批准入指标。
- 探针复用现有希儿/娜塔莎正式构筑，只用于定位入场；最终路线优先复用阿兰＋娜塔莎等
  已验证的普通构筑，允许正规调整等级/晋阶维持存活，重新生成并校验正式构筑身份。
  不覆盖运行中的 HP、资源、状态、时间线或队列。

临时输入及完整错误：`/tmp/hsr_next_batch_summon_probe.scenario.json`、
`/tmp/hsr_next_batch_summon_probe.{py,json,log}`；以上来源与结论已保存在正文。

## 生产权威与接线范围

| 边界 | 入口与职责 |
| --- | --- |
| 卡片与来源绑定 | `tbgd/monster_cards.py` 的卡片及召唤依赖；`tbgd/lowering.py` 的 `_ability_graph_source_context`、CustomValues、`_lower_summon_monster_intents`、出生模板与准入。必要时最小扩展现有 IR/RuleBook，正式值必须独立于审计摘要 |
| 被动初始化 | `lowering._admit_passive_startup_slot` 与 `systems/startup.py`；沿真实根保留条件、动态值和状态执行，不跳过整个被动 |
| 技能执行与出生 | `AbilityTaskSystem.execute_summon_monster_task` → `SummonSystem.plan_spawn_from_intent/apply_spawn` → UnitSpawn/UnitLifecycle；保持父技能原子提交 |
| 出生后的启动 | `SummonSystem._with_halo_reconciliation` 已调用 `apply_monster_startup`、光环协调并运输事件/RNG/已派发身份；复用，不另建第二套启动流程 |
| 后续行动 | 既有 timeline、scheduler、ActionAvailability、目标与资源契约；子单位读取自己的正式怪物卡与动作集 |
| 证明 | 原生 mutation/settlement/source audit、保存与 replay；证明过程不反向提供运行参数 |

怪物入口目前保留 external_legacy 拓扑范围。不得伪造角色身份、修改 invocation_role 或把怪物
强塞进角色图来绕过准入；沿实际入口复用共享执行器。无需为此迁移全部怪物目录。

## 一次性约束

1. **CustomValues 按卡片/调用者作用域绑定。** 复用已有名称哈希算法及参数绑定机制，
   保留 name、hash、值、配置/表行字段和所属卡片。共享能力文件不能固化成第一张卡的值，
   不能只按 hash 全局查找或排序任选候选。运行时核对实际 caster 的卡片与正式上下文，
   不从 raw、`raw_parameter_blocks`、日志或 `source.evidence` 推导业务值。
2. **审计摘要不是完整输入。** 当前 `_custom_value_binding_summary` 只作摘要，条目会截断，
   且明确标记 `hash_to_name_admitted=False`；不能反向把这份摘要当成正式绑定表。
   从完整来源生成正式输入，保留哈希冲突、缺失及未决多来源的拒绝。
3. **不擅自裁定覆盖优先级。** 例如 `1003011` 的表行 SummonID02 为 `1002050`，
   其 Config_A 的默认值为 `1002040`。本批主路线选择无此分歧的 `1003010`；
   未有正式覆盖依据的其它卡继续拒绝，不能借用主卡的绑定。灰熊等冲突不并入本批。
4. **初始化保留实际语义。** 明确 Define 缺省/重置与已有动态值的关系，沿正式规则求值；
   不补伪 raw 节点。ByCompareMonsterID 使用匹配的正式单位/卡片身份，条件假与输入缺失
   必须区分。必要的静态激活筛选须有不可变正式输入和可追查选择依据，不写 ID 白名单。
   表现任务仅沿现有分类处理，状态及潜在监听依赖不因名称像 HUD/Score 就整段删除。
5. **次数、位置与时机来自实际分支。** SummonIDList 只声明依赖，不能用其长度制造单位。
   每个实际执行条目独立出生，First/Last、DelayRatio、等级和初始 AV 消费正式策略。
   不抢占存活单位位置、重置全队 AV、把 AI 偏好序列当作强制操作或额外开回合。
6. **子单位可实际使用。** 身份、卡片、等级、owner/summoner、来源与动作集完整；
   启动/出生监听一次，不能内层派发后外层重放。新单位参与正常目标、行动与胜负查询，
   死亡的旧实例不再可行动，后续召唤是独立新实例，不能携带旧状态或动态值。
7. **父技能全事务。** 规划、任一子单位出生、被动、光环、回调或最终提交失败，
   父技能资源、计数、所有新单位、时间线、事件和 RNG 一起回滚。尤其检查“第一只已出生、
   第二只启动失败”；不能只清空返回的 mutation 而遗留候选状态或派发去重信息。
8. **范围固定。** 本批在召唤者存活期间验证子单位死亡与再召唤；不扩展主人死亡清理、
   忆灵/助手、注册事件根行动事实、特殊首领阶段、灰熊配置争议或完整 Rogue 环境。
   自然路线直接依赖的共享缺口归本批集中处理，不能换成组件假输入来回避。
9. **保持对外操作与证明。** 不新建特例 CLI、生产 clone/restore 或第二套调度器。
   这是内容接线，新增正式输入可正常改变 IR 指纹；仍保持确定性、来源可追查与归档/replay
   契约。必要 IR 扩展检查编码往返及缓存恢复，不携带旧指纹绕过规则身份校验。

## 合并验证与交付

先核对上述完整链并处理同根问题，再运行自然路线；不按每个 blocker 重新从入场试跑。

- 组件侧复用 `test_monster_startup_initializers.py`、`test_wave_birth_source_proof.py`、
  `test_servant_create_continuation.py` 和实际受影响的目标/调度小检查，不运行这些名称对应的
  历史全量阶段套餐。补最小的卡片上下文隔离/冲突、重复派发与第二只启动失败回滚检查。
  多卡冲突可用真实来源组件输入证明，不必再生成第二条整场路线。
- 一个新的 `integration` 模块承担完整自然路线。一次规则构建、一次正式入场，保存关键
  只读前置供失败分支复用；成功分支通过公开操作完成召唤、子单位行动、死亡、再次召唤及
  后续公开提交。失败分支若直接调用共享生产执行器，明确标注组件边界。
- 断言实际执行的分支与出生数量、单位身份、位置/AV、被动/出生次数、公开选择/资源、
  旧实例死亡后的不可操作性与新实例隔离。召唤及子单位行动的 transition 必须通过
  `RuntimeSourceAuditor.validate_transition`，不能只校验来源字段存在或最终 HP。
- 保存该次正式会话归档，独立进程 replay 一次；不再额外运行 CLI 生成同一条战斗。
  场景与固定外部 commands 放 `examples/cli/silvermane_lieutenant_summon_natural{,.commands}.json`，
  CLI 退出 3 只表示战斗未结束，不能代替 replay 和事务成功断言。
- 使用已有 `.venv`，重任务串行持有 `/tmp/hsr-v8-validation.lock`；记录限定 cold/hit、
  自然路线与回放耗时/峰值，复用已通过且未受影响的证据。不默认全目录编译或全量回归。

整批交付写明新增可用行为、实际来源、公开操作、审计/回放结果与剩余依赖；更新短交接及
现有操作/测试导航，不重复抄实现经过。未提交、未推送，不动 submodule、依赖或环境。

## 本批交付（已验收）

### 新增可用行为

- StageConfig `307311` wave 0 的银鬃尉官 `1003010` 正常入场；被动初始化沿来源根执行：
  `AddModifier`（BattleScore1/HideMonsterHUD/MuteHitFly）、省略 ResetValue 的
  `SummonCounter=0`、显式 `AICounter=1`，以及 `ByCompareMonsterID` 根条件按该卡实际身份取假，
  其 Success 分支（OneMorePerTurn/ShieldControl）不执行。
- 外部选择 `monster_skill:100301004` 后实际执行来源分支：`ByCompareMonsterID` 假 →
  FailedTaskList；`AllTeammate <= 3` 真；`SummonCounter == 0` 真；
  `ByIsTeamLocationIndexType(Left)` 真。两条 SummonMonster 各出生一个 `monster:1002040`，
  位置 First/Last，初始行动值取该分支实际参数（Failed 分支未声明 DelayRatio，即完整行动值）。
- 子单位出生后复用既有出生后启动（被动/光环一次、事件与 RNG 一并运输），进入时间线并各执行一次
  正式动作；玩家自然击败其中一个后，尉官存活时再次使用同一技能，新实例（新身份、新 AV、新阵型
  位置）出生并进入正常行动流程，随后继续一次公开操作；旧实例与新实例不共用位置，相邻目标解析
  保持可执行。
- 死亡的旧实例保留在状态与审计中，但不再获得任何决策，也不把状态或动态值带给新实例。

### 实际来源与正式输入

- **CustomValues 卡片作用域绑定**：MonsterConfig 表行 `CustomValues`
  （`BFLIFKBEOPJ`/`MNDFOPKBHKP`）与怪物 Config 的 `CustomValues` 必须一致；名称哈希复用
  `dynamic_key_hash.tbgd_dynamic_key_hash`（`SummonID01 → -289960725`、
  `SummonID02 → -1856044666`）。每张卡独立生成 `by_hash`/`by_name` 正式绑定；
  冲突（`1003011` 表行 `SummonID02=1002050` vs Config_A `1002040`）或单侧缺失按名拒绝，
  不跨卡借值、不按 hash 全局排序。审计摘要仅作摘要；运行时数值来自正式绑定。
  caster 卡片作用域写入正式 IR 字段 `SummonMonsterIntentIR.caster_card_scope`，运行时只消费该
  字段并核对实际怪物卡身份；`source.evidence` 仅用于审计，裁剪证据不改变准入结果。
- **省略 ResetValue**：仅按“目标动态值不存在时初始化为 0”准入（沿用 lowering 既有
  `tbgd_define_dynamic_value_missing_reset_defaults_to_zero` 投影）；目标值已存在时 fail-closed，
  不推断重置语义、不补伪 raw 节点。
- **ByCompareMonsterID**：被动根与技能根都按单位正式怪物身份求值；条件假与身份/输入缺失区分。
- **ByIsTeamLocationIndexType**：只准入 `Left/Right/Medium/Max`（缺省 Type 视为 `Left`）；
  以目标同 side 存活单位的实际战斗位置序分类（最小=Left、最大=Right/Max、其余=Medium），
  `TeamLight/TeamDark` 与目标 side 不符为假。依据是来源配对语义（Left 分支出生在 First，
  Right/Max 出生在 Last/AfterCaster）与引擎既有 formation position 事实；
  `Pos2/Pos3` 没有单一正式索引依据，继续拒绝。
- **ByCheckCustomValueBool**：`Key.Hash=381879059` 经全库名称反查等于 `W1_Soldier`
  （MonsterConfig `CustomValueTags`）。怪物出生模板携带卡片的 `CustomValueTags` 与来源，
  角色/随从按对应来源无该字段登记为空列表；条件按单位正式声明判定，缺来源仍 fail-closed。
  该条件使 BattleScore1 的 `OnListenCharacterDie` 回调可正常求值（标签不匹配时无事发生），
  不再阻断死亡事件；评分/成就回调（`SetBattleAchievement`、`OnBeforeDying` 事件族）继续按既有
  准入拒绝，不影响战斗结果。
- **出生位置唯一分配**：`First/Last/BeforeCaster/AfterCaster` 的相对位置绑定在共享出生规划中读取
  当前队伍阵型的已有槽位（`UnitSpawnRequest.formation_positions`），同一意图内按规划顺序逐个占用
  下一个空槽；再召唤不会与存活单位（也不会与仍在场的旧实例）共用位置，出生后
  `EntityRelationResolver` 的 `formation.adjacent` 可正常解析。
  `First/KeepOnFirst` 取 `min(-1000, min(occupied) - 1) - offset`，`Last/KeepOnLast` 取
  `max(1000, max(occupied) + 1) + offset`：正常阵型仍落在内部锚点 `±1000`；当阵型已越过锚点
  （多只召唤的 `spawn_index` 递增，或兄弟单位离场留下空档）时，结果保证在整个占用范围之外，
  不会再插进阵型中间，也无需再扫描空槽。`BeforeCaster/AfterCaster` 本批不改：当前正式契约
  没有证明它们要求“紧邻”，不能只凭名称冻结相邻语义。
- **阵亡不等于移除**：本路线被击败的旧实例仍为 `lifecycle_status=defeated` 且 `is_present=True`
  （只有 `removed`/离场才为假），因此继续占用原 formation position，再召唤不会复用该位置；
  不能把“阵亡”当作位置释放来处理。
- **波次清场判定**：当前波次仍有存活成员时先返回 no_change；敌方召唤（counts 策略）只在当前波次
  结束后才阻断清场，避免自然召唤冻结整个决策循环。
- **召唤归属目标**：`CasterSummonedMinions`（`summon.owned`）把已击败实例排除出当前目标，
  但保留运行时审计记录；因此死亡旧实例不阻断再次召唤，也不会被再次施加状态。

### 公开操作与验证入口

- 场景 `examples/cli/silvermane_lieutenant_summon_natural.json`，固定操作同名
  `.commands.json`，共 18 次公开 advance/submit（含一次同速 `timeline:select_tied_actor`）。
- 自然路线 integration 模块 `tests/test_monster_summon_natural_route.py`：一次规则构建、一次
  正式入场，断言实际分支/出生数量、身份、位置与 AV、被动启动次数、公开选择与资源、旧实例死亡后
  不可操作、新实例隔离，并对召唤与子单位行动的 transition 执行
  `RuntimeSourceAuditor.validate_transition`；同时保存正式归档并另起进程 `cli replay` 复跑。
- 最小组件检查：`tests/test_monster_custom_value_binding.py`（卡片上下文隔离/冲突）、
  `tests/test_monster_passive_conditional_startup.py`（条件根、省略 ResetValue 重定义拒绝）、
  `tests/test_team_location_index_condition.py`（位置分类与缺失/未知拒绝）、
  `tests/test_monster_spawn_position_endpoints.py`（正常/空/含空档阵型与连续分配下 First/Last 端点顺序）、
  `tests/test_monster_summon_atomicity.py`（第二只启动失败整段回滚、出生事件只派发一次）。

### 审计、回放与实测

- Codex 集中验收：本轮 52 项端点、卡片上下文、条件启动与原子性快测通过（2.20 s，含两个
  原始端点复现）；自然路线、原生来源审计和独立进程 replay 复用上一轮通过的证据，本轮未重复整场。
- 召唤与子单位行动的 transition 均通过 `RuntimeSourceAuditor`；每个新实例出生事件只派发一次，
  被击败实例之后不再出现在任何决策中。再召唤后旧实例（`-1000`）与新实例（`-1001`）及最后位置
  （`1001`）互不重复，`formation.adjacent` 返回 `resolved` 且能给出尉官两侧邻居。
- 独立进程 replay：36 步、0 错误、退出码 0；`cli run` 返回 3（战斗未结束）并保存可继续归档。
- 本机限定实测（串行持有 `/tmp/hsr-v8-validation.lock`）：冷构建 31.84 s / 峰值 890644 KiB；
  缓存命中构建 3.76 s；入场 7.93 s；自然路线 21.88 s；独立回放 39.00 s。

### 剩余依赖

本批仍不覆盖：主人死亡后的召唤清理、忆灵/助手、注册事件根 TriggerAbility 的行动事实、特殊首领
阶段、`1003011`/灰熊等配置分歧、完整 Rogue 环境；`ByIsTeamLocationIndexType` 的
`Pos2/Pos3` 与其他未采纳位置类型继续拒绝；评分与成就事件族仍未准入。
