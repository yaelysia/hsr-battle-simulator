# 普通怪物战斗闭环批次

基线：`b9eba45`；TBGD：`14c1d18f91a8101d610e6c523447a7517de3fae1`。
实现固定由 dsh / DeepSeek 完成，Codex 负责范围与集中验收；当前状态只在
[交接](../../../../CODEX_HANDOFF.md)维护。本文件已从单条召唤者死亡路线扩为完整能力批次，
原有文件路径保留；以下为本批完成条件，当前交付状态与证据见文末交付记录。

## 批次目标与交付粒度

交付普通怪物/普通精英的战斗闭环：正式入场 → 双方合法行动及必要被动 → 召唤、子单位
行动与死亡、再次召唤 → 召唤者死亡后的关联退场与队列清理 → 清场/换波 → 胜利或失败终局。
所有操作由外部 `BattleSession.advance/submit` 推进，不实现敌方 AI。

内部按“来源与动作准入、生命周期与队列、换波与终局、审计与恢复”拆实现项，连续完成。
两类真实召唤者、非召唤敌人的波次行为和两个胜负方向一起交付；单个任务节点变 executable、
单条退场路线成功或测试数量增加都不构成批次完成。途中发现的同类接线、被动、目标、
资源和动作缺口在本批内消化，不另开一批、不逐项等待 Codex 验收。

已接通的能力直接复用；列清本批新增行为及复用证据，不把旧路线再跑一遍计为新增成果。
整批实现后集中交付与验收，验收通过后再按用户指令统一提交。只有无法消解的规则冲突、
实际范围取舍或新增依赖/权限需求才中途请求裁决，不把普通实现阻断上交为规划问题。

## 必须覆盖的真实场景

| 验收结果 | 正式来源起点 | 必须完成的可观察行为 |
| --- | --- | --- |
| A. 银鬃尉官完整召唤生命周期与胜利 | `1003010 → 1002040`，沿用 Stage `307311` wave 0 | 保持正确出生面板、子单位行动、自然击败子单位与再召唤；在仍有活子单位时自然击败召唤者，真实监听排队退场，清理后胜利。已验收前半链复用，新增死亡后半链；队列未闭合前不得提前胜利。 |
| B. 第二种召唤者的独立战斗闭环 | 金人司阍 `2013010 → 灯昼龙鱼 2012010`，选固定来源内实际包含它的关卡 | 完成召唤所需的正常技能/被动状态、子单位行动及其正式死亡效果、主人死亡后的关联退场，最终胜利；验证不同卡片/状态/召唤参数经共享机制工作。不能改名复用 A，不能跳过本来源必要被动或在未接通技能前秒杀来冒充完成。 |
| C. 多波推进及后续敌人实际行动 | 优先复用 Stage `201010110` 与 `arlan_serval_natasha_two_waves.json`，也可与 B 的正式多波来源合并 | 第一波真实清场，必要死亡/退场/取消队列先闭合，再出生第二波；新单位被动初始化一次、至少一个敌人实际使用合法技能，之后继续公开操作直至胜利。不能仅验证波次数字变化或沿用“赶在阻断技能前全秒杀”的旧证据。 |
| D. 自然败北与终局封闭 | 复用 A/B/C 任一来源范围，选择能自然败北的正式构筑和外部命令 | 敌方实际行动击败最后一个可战斗己方单位，必要回调/队列按规则结算后败北；存活敌方召唤物不能阻止败北，不能误判胜利；两个终局都不再接受战斗行动。不得手工清空己方或写入 outcome。 |

至少两种真实召唤者；A/B 必须是两个真实战斗，C/D 可合并到上述来源的合法场景/恢复分支，
不要求人为凑四套规则构建。B 的来源一致性已做静态核对，运行准入和实际效果仍待本批实现；
选定来源后一次列全影响其合法战斗的依赖，连续补齐，不能只保留 A 后将 B/C/D 再次延期。

保留既有示例，新增固定场景/命令用于交付；A 可用
`examples/cli/silvermane_lieutenant_owner_death{,.commands}.json`，其余按场景命名。
允许调整正式成品构筑、等级、技能等级、装备与外部选择来缩短实战；禁止运行时注入 HP、
状态、AV、队列或胜负，禁止屏蔽不利监听。范围为所选普通战斗的 `wave_only`；多波不得用
截取末波替代，不宣称完整 Rogue、剧情多阶段首领、评分或掉落环境已经完成。

## 已核对的来源与缺口

本节代码缺口描述的是开工基线 `b9eba45`；当前实现与验收以文末交付记录为准，不作当前阻断清单。

- 银鬃尉官、子卡、来源技能与出生数值已在基线验收，入口为既有自然召唤示例及
  `MONSTER_SUMMON_STAT_BINDING.md`，不重做另一套面板或召唤实现。
- 金人司阍 `2013010` 的 `MonsterConfig.SummonIDList=[2012010]`，
  `Config/ConfigCharacter/Monster/Monster_W2_Mecha03_00_Config.json` 的
  `W2_Mecha03_00_SummonID=2012010` 与之一致；对应
  `Config/ConfigAbility/Monster/Monster_W2_Mecha03_00_Ability.json` 声明召唤任务及对子单位
  添加 `MCommon_Servant`。该实例提供第二类来源，不能据此预先宣称其整张卡已准入。
- 既有 `test_multiwave_battle.py` 已证明 Stage `201010110` 的基础换波与胜利，但其中短胜利
  路线明确赶在部分阻断动作前击败敌人；本批 C 要补实际敌方行动及死亡/队列闭合证据。
- `Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json` 的 `MCommon_Servant`：
  `OnCreate → OwnerEntityAddAbility(Common_Servant_Forcekill)`；`OnListenCharacterDie` 使用
  `ByHasSummonRelation(SummonerType=ParamEntity, ServantType=ModifierOwnerEntity)`，成功时
  `TurnInsertAbility` 指向该状态所有者，优先级 `MonsterForceKill`，Owner/TargetAliveState
  均为 `Mask_AliveOrRevivable`，`CanRunOnUnselectableTarget=true`。
- `Config/ConfigAbility/Common_Additional_Ability.json` 的 `Common_Servant_Forcekill.OnStart`：
  `ForceKill(TargetType=AbilityTargetEntity, AbortUnusedInsertAbility=true)`；未声明双 mute。
- 当前 `event_dispatch.py` 将 `unit.defeated → OnListenCharacterDie` 归为 `owner_local`，
  `_scope_matches` 在该事件上按击杀归属者匹配，会漏掉观察召唤者死亡的子单位。
  已有死亡事件边界会校验真实 `defeat_record` 与生命周期 mutation 身份，应保留并复用。
- `_queue_task_abort_states` 只准入 `Mask_Alive` / `Mask_AliveOrLimbo`；本来源的 mask 尚被拒绝。
  `ForceKill` lowering 与 runtime 目前只支持双 mute 的 battle_event/servant 退场形状。
- `PendingDefeatPlan` 目前明确要求 `damage_system` 的原生致死 HP mutation 与伤害归属；
  新的非伤害强制死亡不能伪造伤害包来满足该契约。
- 调度器已有队列优先于波次清场的顺序；波次有存活原生成员时 `no_change`，全部死亡后
  活着且计入清场的敌方召唤物会阻断。不要通过改为 `wave_clear_policy=ignore` 绕过退场。

## 先定规则，再接线

先核定本形状 `ForceKill` 的 HP/死亡事件、击杀归属与回能、`AbortUnusedInsertAbility` 的
对象和时点，以及 `Mask_AliveOrRevivable` 的生命状态含义，简记适用来源与结论后实现。
复用可靠机制资料，无需逐项请求批准；只有实际未解且影响本批行为的冲突才上报。
不能因未声明 mute 就沿用双 mute 行为，也不能凭字段名称把新 mask 等同于 limbo。
主人死亡时本批首先覆盖仍存活的子单位；未支持的 Revivable 情况继续明确阻断，
不能静默删除来源字段或全局放宽死亡单位权限。`ForceKill` 与 `removed` 是否同阶段须按来源
处理；不得为了清场直接删除单位，也不得将父单位的击杀者自动套到所有子单位。

## 生产链与一次性约束

| 边界 | 约束及完成判据 |
| --- | --- |
| 编译与正式输入 | 沿真实 callback/引用编译到 QueueIntent/Window/Priority/Resolution、能力注册与任务图、ForceKill effect；生命周期 mask、AbortUnusedInsertAbility 等行为进入正式字段及身份/序列化/缓存，不读取 raw 或审计 evidence 驱动执行。 |
| 动作与被动覆盖 | 对 A/B 的普通技能、召唤及其前置状态、反击/死亡效果列出正式动作集和实际覆盖；C 的后续敌人必须真正行动。所选实战依赖的普通共享缺口在本批补齐，不靠屏蔽被动、改目标规则、跳过必要技能或秒杀掩盖；外部负责选择，不写敌方策略。 |
| 出生、行动与再召唤 | 保持战斗等级/难度缩放、卡片参数隔离、位置唯一与 First/Last 端点、真实初始 AV 和出生后启动；死亡旧实例不再行动，重新出生使用新身份，不继承旧 HP/状态/动态值/待执行条目。不同来源不能串参数或跨实例借身份。 |
| 死亡生产与派发 | 从正式最终死亡生产者取得本次死亡单位和因果；与当前状态的生命周期记录绑定，不能信任可篡改的 param_entity_id、日志或旧事件。区分观察者死亡监听与击杀者本地回调，不全局改写其它事件族的作用域；未最终死亡/被救回不触发本链。 |
| 关系与实例作用域 | ParamEntity 是本次死亡单位，ModifierOwnerEntity 是当前监听状态的子单位；用正式 owner/summoner 关系判定。两个子单位分别产生自己的条目，互不借身份；无关死亡/无关子单位零副作用，重复派发不重复入队。 |
| 能力与队列 | OnCreate 注册和队列解析均来自正式能力引用；实际执行者及目标均绑定对应子实例，消费时核对其实际能力注册，不能仅凭全库同名定义放行。保留 MonsterForceKill 的正式顺序、生命范围和不可选中目标权限，不给普通队列开放这些权限。入队与消费各自重验，目标已死亡/移除须按正式取消契约处理，不换成同卡新实例。 |
| ForceKill 与清理 | 在通用生命周期边界产生正式非伤害死亡/退场事实，复用适用的状态、光环、动态值、目标资格与召唤仓库清理；不伪造命中、伤害或击杀回能。不得继承双 mute 路径或按怪物 ID 特判。清理 AbortUnusedInsertAbility 时保留无关单位条目、顺序和当前消费者的正确终结，不清空整个队列。 |
| 事务 | 父单位被击败及其死亡监听产生的入队同属原行动事务：第二个监听/入队失败时，父 HP/死亡记录、资源、首条入队、事件、RNG 与派发身份一起回滚。后续每次队列消费是另一笔事务：实现失败回滚本次 dequeue/正文/清理/RNG，保留待消费条目，不撤销已提交的父死亡或前一条成功消费。合法取消与实现阻断须明确区分。 |
| 调度与终局 | 退场队列不额外推进 AV、开启普通回合或扣取行动资源；队列未闭合前不能提前胜利/换波。全部实际阻挡者消失后进入已有胜利或后续波次规则；无退场声明的其它存活敌人仍须保留和计数。最后一个己方单位自然死亡时正确败北，不能被敌方存活召唤物卡住或误判胜利；胜负优先级沿用正式规则。 |
| 波次与会话恢复 | 新波次只出生/启动一次，旧波次实例不再得到行动或泄漏临时状态、光环、动态值和无效队列。区分应保留的跨波次玩家状态/资源与临时字段，不能整仓重置；合法归档恢复后结果与连续执行一致，终局查询和重复提交不再修改状态。 |
| 原生审计 | enqueue/dequeue、HP/生命状态、清理与终局 mutation 均反查本次正式定义、实际目标和原生结算。识别种类/操作时必须与正式定义互校，缺字段不能跳过审计；上下文、实际写入及所有被声明的证据副本一致；校验结算生产者、类型及 mutation/计划身份。审计不替代 runtime 边界校验。 |
| 同族影响与范围 | 检查上述共享函数的所有正式调用者；保留既有双 mute servant/battle_event 退场、普通死亡与击杀回能、普通插入行动和已验收召唤面板。本批扩充两类普通召唤者的合法战斗闭环，不追求全怪物目录；剧情首领、Rogue 全环境、角色排队救援和评分不并入。 |

## 内部推进与集中验证

先以 A/B/C/D 的准入与行为差分列出内部工作清单，共享生产者/消费者的同根问题一起修。
可以逐项做局部检查并汇报进度，但不要每修一个叶子、每过一条路线就交回验收。各项使用同一
基线持续集成，四类验收结果及共享失败边界齐备后整批交回，避免拆成连续微批。

测试复用同一来源切片、RuleBook 和只读前置，完整来源或完整场景显式标记 `integration`；
不同来源范围按需编译并复用缓存，不能为了“一次构建”扩成全目录，也不为每个负例新建会话。

1. **真实来源局部链**：真实 MCommon_Servant 回调→关系条件→正式入队→实际 ForceKill。
   同时检查两个关联子实例、一个无关对象；验证生命 mask/不可选中权限、重复事件与失效目标，
   并覆盖 AbortUnusedInsertAbility 的相关/无关条目差分。合并必要分支，不建庞大负例矩阵。
2. **两笔事务边界**：分别在第二个死亡监听入队、一次队列消费的晚期步骤制造实现失败，
   检查上表要求的状态、队列、资源、事件、RNG 与身份不泄漏；合法取消另用现有检查复用。
3. **审计正反例**：合法原生结果及合法重关联必须通过；改目标/实际生命周期写入、伪装
   操作或种类、错配来源或结算生产者仍须拒绝。篡改时同步相关 mutation_id 引用，避免只因
   ID 未更新而假通过。新增回归直接纳入仓库测试，不只留在 `/tmp`。
4. **成组公开实战**：按 A/B/C/D 矩阵交付固定场景与命令，整批实现稳定后合并运行一次，
   分别断言实际动作、关键死亡效果、队列顺序、换波及胜负；两种召唤者不能只做组件输入。
   在同一来源范围内可复用正常归档恢复来分支，不能手改快照伪装自然胜负。对新增执行、清理、
   换波与终局 transition 做原生审计，保存各场景可重放归档；选变更组合最完整的一份独立进程
   replay 一次，其余仅在有不同恢复风险时追加，并如实区分已保存与已独立回放。
   不按内部任务重复跑整套路线，也不另跑 CLI 生成同一场战斗。
5. **按影响复用**：`test_pending_defeat_lifecycle.py`、`test_queue_terminal_callbacks.py`、
   `test_queue_battle_state_transition.py`、普通击杀回能及波次边界检查；只选择实际受影响用例。
   换波/终局补队列未排空、最后一个敌人/己方死亡、另有无关存活敌人、下一波初始化失败的
   最小组件检查，覆盖胜负与原子性；不为这些失败分支分别重跑完整战斗。

已有环境 `.venv`；重任务串行持有 `/tmp/hsr-v8-validation.lock`，记录实际耗时/峰值。
默认不跑全目录编译、全部旧自然路线或历史阶段验证器；整批末尾按影响边界判断是否需要
一次完整普通回归，内部实现项不各自触发全量。新增重任务前说明它要回答哪个尚未解决的
问题。既有 `_build_graph()` fixture 缺参等基线失败保留原归因，不重复全量确认。
旧规则指纹归档不作兼容目标；未授权不提交、不推送、不改 submodule、依赖或环境。

交付一张 A/B/C/D 结果表：正式怪物/关卡、实际新接通行为、固定输入/命令、最终结果、
原生审计/恢复证据与保留限制；已有证据注明复用，不能用总测试数代替成果。
更新本文件的交付节及短交接，整批交回 Codex；验收先复查完整生产差异、直接调用者和
审计/序列化边界，再合并必要检查。全部完成后集中验收、按用户指令提交一次。

## 本批交付记录（2026-10-24；A/B/C/D 已验收并提交）

以下为当前源码与运行证据；A/B/C/D 及验收修复已通过 Codex 集中验收，当前状态见
[交接](../../../../CODEX_HANDOFF.md)。实现固定由 dsh / DeepSeek 完成，Codex 集中验收。
实现提交：`516acc8`；TBGD 指针未变，未推送。

| 验收结果 | 正式来源与固定输入 | 已接通行为 | 证据 |
| --- | --- | --- | --- |
| A. 银鬃尉官召唤者死亡→胜利（已通过） | Stage 307311 wave 0；examples/cli/silvermane_lieutenant_owner_death{,.commands}.json | 公开召唤两名 1002040；Seele 击破量子弱点后原生 break DOT 在召唤者回合开始击败主人，两名子单位仍存活；MCommon_Servant 以 summoner_relation_local 作用域接收死亡事件，按 ByHasSummonRelation 各自入队 Common_Servant_Forcekill（MonsterForceKill 优先级、alive_or_revivable、不可选中目标权限）；插入能力执行正式非伤害强制死亡（HP/生命状态/defeat_record、无命中/伤害/击杀回能）并清理该单位未用插入条目；两名子单位退场后波次清场并胜利 | tests/test_monster_summon_owner_death_route.py：公开 advance/submit、每条 advance/submit 事务过 RuntimeSourceAuditor、断言死亡时子单位存活与入队/清理/换波/终局顺序、终局后拒绝操作、保存归档并由独立进程 cli replay 0 错误；另 tests/test_monster_forced_death_boundaries.py 5 项（AbortUnusedInsertAbility 相关/无关条目差分、掩码 revivable 分支显式阻断、非活跃目标拒绝、第二个关系监听入队失败整笔回滚、伪造来源/击杀回能/缺 effect 身份的审计拒绝） |
| B. 金人司阍→灯昼龙鱼第二召唤者闭环（已验收） | Stage 307214 wave 0；examples/cli/b_mecha03_blue_dragon_fish_owner_death{,.commands}.json（Lv80 E0 Arlan/Natasha/Lynx/March7th，各六件成品遗器） | 三次战技触发 Overdrive 累积至 3，正式插入召唤两鱼；两鱼实际行动。首鱼自然死亡后，同一死亡实例触发状态清理、确认死亡与动画插入；爆炸以该鱼自身 MaxHP × 卡片参数 0.4 为基准，对其它存活同队单位造成火伤，主人实际落减防，余鱼的合法概率未命中保留原生证据。后续单体行动击败主人时余鱼仍有 HP；关系监听对余鱼正式 ForceKill，无伤害/击杀归属；余鱼再执行自己的空目标死亡插入，之后清场胜利 | tests/test_b_mecha03_owner_death_route.py：41 条公开命令，每笔事务过 RuntimeSourceAuditor；正式 IR、formula/ledger 的施法者基准、两受者不同 MaxHP、实际减防、具体死亡身份及退场/终局顺序全部核对；集成及含终局拒绝检查的 84 步独立 replay 通过、0 错误 |
| C. 多波推进及后续敌人实际行动（已通过） | Stage 201010110；examples/cli/c_multiwave_real_action{,.commands}.json（复用已验收 melee 两波输入并固定为 C 场景身份） | 第一波真实动作清场后出生第二波并各初始化一次；敌方实际执行 monster_skill:100204001（命中、血量下降、防御降低 debuff）；继续公开操作至胜利 | tests/test_c_multiwave_real_action_route.py：wave 0/1 各 started/cleared 一次且 clears[0] < starts[1]、每单位 passive 启动不重复、敌方技能与减益、wave/终局 transition 过 RuntimeSourceAuditor、归档独立 replay 0 错误；终局后拒绝操作 |
| D. 自然败北与终局封闭（已通过） | Stage 307311 wave 0；examples/cli/d_natural_defeat_terminal{,.commands}.json（Lv1 Seele，沿用已验收构筑输入） | 召唤者公开召唤两名子单位后以自身技能自然击败最后一个可战斗己方；败北时敌方召唤物仍存活但不阻止败北；未误判胜利；两种终局均拒绝后续 advance/submit | tests/test_d_natural_defeat_terminal_route.py：致命伤害 mutation 来自 damage_system、击杀归属为召唤者、存活敌方召唤物断言、battle.defeat 与终局拒绝、时间线/终局 transition 审计、归档独立 replay 0 错误 |

### 共享生产链改动

- 编译与装配：ForceKill 准入本批非 mute + AbortUnusedInsertAbility 形状；关系死亡回调按正式 summoner 关系作用域编译，队列保存生命掩码与不可选中权限。角色/怪物卡仍提供参数与能力，runtime 不按固定单位 ID 分支。
- 动画与执行：含玩法叶的 wrapper 按完整父准入及 child ledger 源顺序执行；纯表现仅在来源形状得到证明时跳过，未知字段/时间/缺依赖阻断。叶任务及监听失败回滚整笔，不泄漏 mutation、事件或 RNG；AllTeammate 为施法者队其它存活单位。
- 死亡与队列：正式最终死亡、源状态、callback/task/intent/resolution/body 一致后才能产生和消费具体 Deathrattle 许可。该死亡身份沿 scheduler → standalone invocation → effect 传递；错误许可阻断并保留条目，不伪装成正常取消。ForceKill 由共享生命周期生产 HP/defeat_record 与原生死亡事件，不伪造伤害或击杀归属。
- 清理：silent 是 StatusLifecyclePlan 正式字段；ExitBreak 仅清理对应已最终死亡实例的破韧现场，limbo/待决死亡继续阻断；审计 trace 不控制运行。状态、动态值、halo 与队列依赖仍由各正式领域清理。
- 审计：强制死亡与队列清理、独立计数、Protected、死亡 ExitBreak、已采纳削韧参数均核对正式定义、实际完整差分与原生结算；不能通过剥离标签、改 sibling 或自填来源摘要绕过。
- ByMaxHP 的施法者基准与 [Candle Flame 机制资料](https://honkai-star-rail.fandom.com/wiki/Entranced_Ingenium:_Illumination_Dragonfish) 一致：灯昼龙鱼自身最大生命值的 40%。页面未注明机制适用版本；本批仅据此核对基准主体，倍率仍来自固定 TBGD SkillP01 ParamList[0]，削韧沿固定来源的数值单位，runtime 不读网页。
- 未改 TBGD 指针、未新增依赖/环境；已提交为 `516acc8`，未推送。

### 验证与限制

- Codex 已复查生产差异、实际调用者、权限/传播/原子边界及篡改反例；三方集成后，主区生产 Python 与实测隔离树逐文件相同。
- 新 B 一次集成通过，41 条固定公开命令、每笔 RuntimeSourceAuditor、终局拒绝检查及 84 步独立进程 replay 全部完成，0 错误。墙钟 11:15.31，峰值 RSS 1,861,232 KiB（约 1.78 GiB），IR 指纹 `1e5ddb9fe87cb22ae721988df7f5b8b9f3baf95e148451f849c98a5b09032a27`。
- 合入主区后 93 项定向检查通过，4 项既有集成按标记未运行；覆盖队伍计数、ForceKill 准入、回调失败传播、动画准入/顺序、死亡许可/正文接线及来源差分审计。旧许可 fixture 已同步正式接口，不增加生产兼容。
- A/C/D 复用原生实战和回放证据。旧 77 项受影响检查与 669 项普通回归仅为历史底座；本轮未重跑全量/全目录，旧错误 HP 基准的 B 结果不作为正确证据。
- 固定命令根严格为 `{"commands": [...]}`，来自成功公开 submit 的 operation.command，包含终结技请求与其队列执行；不使用私有派生命令或失败探索命令。
- 本批覆盖选定两类召唤者的完整操作链；金人司阍未采用动作 `monster_skill:201301002` 仍因 `FatigueRatio` 未支持而原子阻断，不能据此宣称整张卡所有动作可用。Revivable 等未准入分支保持阻断；旧规则指纹归档不作兼容目标。
- 工作区已合入，2026-10-24 全部已报问题及原反例均通过集中复验，整批已验收并提交为 `516acc8`，未推送。已有 A/B/C/D 原生实战和回放证据继续有效。

### 集中验收状态（2026-10-24，已通过）

Codex 已复查本批相关生产差异、正式调用者、死亡许可与传播、取消/原子边界、实际队列
差分和原生结算。最后一次合并复验 124 项通过、4 项集成未选，包含仓库
`tests/test_queue_terminal_remove_boundaries.py` 全部 16 项及原始临时反例；
`git diff --check` 通过。本轮未发现新的可操作问题。

已确认的共享契约：

1. 未准入 Revivable 按实际失败身份判断；仍 limbo 时阻断并保留、零副作用，已确认
   死亡/移除正常取消，其它合法 limbo 身份不干扰判断，Deathrattle 许可边界继续有效。
2. terminal_remove 精确移除一条，保留兄弟条目与顺序；waiting/retarget 由旧条目加正式
   允许字段构造完整预期，新条目不得夹带 actor、tag、策略或其它字段改写。
3. 队列减长写核对实际移除身份及正式生产者；ForceKill 清理因果不由可删标签选择。
   合法动作起手 dequeue 仅在正式操作、计划已准入、条目/窗口/RuleBook 身份及原生
   结算全部一致后豁免清理因果。缺失、空、阻断、借用计划与改名结算均拒绝。
4. 原生 dequeue 结算中的完整 queue_resolution 与本次 RuleBook 定义 `to_json()`
   严格相等，覆盖身份、resolved_kind/resolved_ids、coverage 和 source；缺失定义或
   不可执行定义不得豁免。计划/窗口副本、payload 形状、trace 与 mutation_id 继续核对。

原始复现 `/tmp/test_r01_codex_acceptance.py`、`/tmp/test_r01_terminal_followup.py`、
`/tmp/test_r01_dequeue_producer_review.py`、`/tmp/test_r01_dequeue_resolution_review.py`
均通过，对应反例已迁入上述仓库模块。实现方最后的 169 项定向回归与 A/C 各 1 项
集成结果保留；本轮只补审计比较，复用已有 A/B/C/D 与 B 的 84 步独立 replay，
未重跑全量、整场或回放。Codex 未修改生产代码；整批已验收并提交为 `516acc8`，未推送。
