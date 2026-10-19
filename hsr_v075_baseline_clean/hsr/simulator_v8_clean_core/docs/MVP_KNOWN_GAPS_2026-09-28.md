# 命令行 MVP 已知缺口清单

机制盘点日期：2026-09-29；提交信息于 2026-09-30 校准。上述本地成果现已进入业务提交
`6733fd350ddbbf72b30d808153e8abc2a538c48c`，父提交为 `2d60a4305206bc11b67edf445a55478d90c96257`。
2026-09-30 校准时研究版本为 PR #8 `4d524d6c1e4875d748b5adb568e478a554b34d3b`，当时没有重跑。
2026-10-08 按逆向驱动路线新增 G13/G14，已只读核对 PR #8
`9a7ab71b00a0027e994ad33d06a918a998602a24` 的治疗/HP 与能量记录，并修复相关来源接线。
本表保留各自日期的行为证据与缺口边界，不是全角色普查或新提交的独立审核。
历史提交与 MCP 信息同步结果见[历史交接快照](archive/CODEX_HANDOFF_PRE_SLIM_2026-10-19.md#mcp-status-20260930)。

此表最初记录的是 2026-09-28 单波命令行 MVP，不能作为当前工程的范围裁决。
当前按[工程完结路线](../P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md#0-工程完结路线)
连续推进，包含构筑、多波、复杂机制和操作产品；敌方 AI 策略仍不纳入。旧 MVP 的暂缓项
并未从最终成品范围排除。PR #8 已确认规则直接使用，无须重新寻找 native 实现或 TBGD 同值。
以下“待补依据”不表示用户从未在其他记录中研究过。

## 已证明的交付范围

阿兰 E0 / Lv1 / 无额外行迹与装备，对两只 Lv2 重子，九次提交获胜；另进程 replay 的十九次
操作校验成功，已于 2026-09-28 重新通过真实 CLI 运行和独立回放。
其雷属性不命中敌人的冰/风弱点，故这条路径没有验证削韧、击破、控制或败北。
普攻、战技损血后的当次天赋增伤、终结技插入、击杀回能、被动出生及一次普通减伤已贯通。
基础公式、治疗、单盾、同源叠盾等另有定向检查，不能据此宣称所有相关角色可玩。

2026-10-08 新增阿兰+娜塔莎 E0/Lv1 空装备场景，十二次手动提交胜利；包括单体治疗、
自我治疗、两次目标回合开始的持续治疗及到期移除，每次治疗只扣一次战技点、只回一次能量。
操作与边界见 [CLI_MVP.md](../CLI_MVP.md#双人治疗胜利路线2026-10-08)。

2026-10-09 复用双人场景新增十四次提交的普攻与终结技路线：自然回能到 90、插入群疗、
继续阿兰回合并获胜。普攻投射物只接等待单目标命中的来源形态；完整投射物系统不在此结论内。
操作见 [CLI_MVP.md](../CLI_MVP.md#双人普攻与终结技胜利路线2026-10-09)。

## 当前已知机制边界

| ID | 玩家会遇到的情况 | 当前证据与缺口性质 | MVP 关系 |
| --- | --- | --- | --- |
| G01 | 敌人一击打死角色 | 2026-10-10 用户确认致死命中仍给受击者回能；已删除 `_with_hit_energy` 的致死工程阻断。真实单次命中保留伤害、死亡、`SPHitBase × SPHitRatio` 回能、受击者 ERR、容量上限、审计与 mutation 回放。 | 该共享阻断已关闭；真实致死和截顶通过，不代表全部败北或特殊死亡内容完成。 |
| G02 | 同一技能有多个伤害请求 | 已按 PR8 接入非致死实际请求的 `SPHitBase × SPHitRatio`，由共享资源系统应用受击方 ERR 和容量上限；真实双请求源各 7.5 的执行、截顶、审计与 replay 已通过。不按整动作或每人去重。 | 此通用回能规则已补；完整敌人动作仍需其目标/条件/投射物等内容装配，不能据此宣称弹射整链已完成。 |
| G03 | 命中弱点、削韧、击破、元素效果及自然恢复 | 普通单体、扩散及群攻削韧已绑定正式技能数据与逐段比例。公共击破状态、25% 延后、韧性减伤解除、初始击破伤害及每目标一次通知已贯通；`TriggerBreak(Caster)` 消费同一次领域事实。2026-10-16 普通多层已接剩余层数、单段跨层、中间伤害/通知、末层完整击破及同卡自然恢复；强制、共享、虚韧性及特殊采样继续保留缺口。 | 真实三层卡的来源组件、公共模板防双算、恢复、审计、replay 与晚期失败回滚通过，不冒充完整首领战。旧雷击破/恢复及希露瓦＋娜塔莎普通场景证据继续保留，具体范围以当前交接为准。 |
| G04 | 限时状态首次扣回合、冻结跳过行动、续上同一状态 | 2026-10-10 用户确认普通 buff 按计时单位回合开始扣时；回合开始后施加不追扣，下次正常扣，不额外跳过首次计时。正式 scheduler 已排除开始回调中新加的状态；光环父状态到期清理投影和来源校验已检查，受益者回合不单独消耗投影。原冻结最后一次行动跳过检查保留。 | 普通首次计时已关闭；同一状态重施、额外行动及具体来源的特殊 moment 仍按内容验收，不统一覆盖其来源规则。 |
| G05 | 不同角色的护盾同时存在、盾属性变化或容量下降 | 普通多盾已按每个适用池各自扣本次伤害、HP 只承受一次超出最大盾的余量结算。类型化耗尽事实将该盾所属状态及 OnDestroy 效果精确清理，保留其它存续盾。全局多池通知顺序、盾加成与 cap 的矛盾说法、降低 cap 后补盾仍未定；带护盾加成且依赖叠盾上限的请求明确阻断，撤回旧代码统一放大 cap 的假设。 | 无盾示例不触发；盾角色组合按其实际需要补。 |
| G06 | 一次免控被消耗、多个控制抵抗类别重叠、强制控制 | 静态共享免疫十一条及单一 STAT_CTRL 已接；有 OnImmune 消费的路径仍拒绝，重叠类别及保护消费顺序未闭合。普通效果命中公式不是整体未实现。 | 当前无相关申请；含免控/控制的内容才需要。 |
| G07 | 技能随机选分支、弹射/投射物、并行或特殊序列 | 普通 weighted selection 已由正式 ability/status consumer 求权重并生成 RNG，状态条件/随机目标及回合链的 RNG 也纳入原子事务。2026-10-09 新接单目标、忽略碰撞且等待命中的正式投射物序列，真实娜塔莎普攻可执行；异步在途、碰撞、并行与特殊序列仍按具体内容处理，不能据此宣称完整弹射技能已可玩。 | 普通随机与选定投射物路径已补；剩余技能任务形态随实际内容接入，不要求用户重建随机算法。 |
| G08 | 复活、分摊伤害、特殊死亡触发及行动前死亡 | `UnitLifecycleSystem.revive_blocked` 仍拒绝复活；普通回血不能替代复活。行动前周期伤害击败行动者已接正式死亡与回合关闭：保留伤害和击败 mutation，死者不恢复韧性、不开决策、不再执行 TurnEnd 状态扣时；下一步由现有波次或时间线继续。真实感电 HP 1→0 的来源审计、replay 与下一行动者检查通过。分摊/转换及同时致死、竞争复活、抑制死亡触发的完整内容链未验收；具名行为有研究，通用边界不能靠名称推断。 | 普通行动前死亡调度已补；特殊死亡和复活随内容接入。 |
| G09 | 特殊治疗惩罚 | 已接入 `Target_HealTakenRatio` lowering 与受治疗者 `OnBeforeBeingHeal`；通过原始 Sam 条件和目标所有者解析，将 -0.9 与治疗者 +0.5 相加一次，基础 1000 实际恢复 600。瞬时加成改由类型化回调结果供给，不从审计记录重建。 | 本条共享规则已接；新增双人样例含普通治疗，无 Sam，不代表整个 Sam 或所有治疗角色内容已完成。 |
| G10 | 伤害过程中属性变化、复杂减防组合、极值或逐段舍入 | 普通 DEF/RES 公式、独立减伤等已有研究与实现；复合静态 DEF/减防/无视防御仍有 engine convention，快照/实时采样、极值 clamp、逐段舍入仍有未统一边界。跨零普通击 0.9 已确认，不再列未知。 | 区分普通内部范围和相关极值/特殊效果；不能要求用户重做普通公式。 |
| G11 | 技能创建忆灵/召唤物及其独立行动 | 定义、owner、状态与时间线底座不等于真实 CreateServant 完整调用链；此前审计标未接通，本次无新增整场证据。 | 当前阿兰无召唤物；选入相关角色时须单独贯通。 |
| G12 | 秘技入场、完整关卡环境、特殊伤害体系 | CLI 强制 `stage_scope=wave_only`，只装配怪物波次，不装完整关卡全局能力；MazeBuff 秘技到规范输入适配尚未完整接通；Elation 伤害仍明确 blocked。 | 当前限定场景不包含；这些并非已完整支持，也不自动追加到 MVP 必做项。 |
| G13 | 阿兰低 HP 使用战技 | 2026-10-08 已修复 `LoseHPByRatio.Floor` 被误当取整标志的问题；来源数值表达式成为剩余 HP 下限，损失为 `min(请求量, max(0, HP−下限))`。正常损血保留小数，濒死与 1 HP 路径保留 1 HP，缺少下限绑定不提交。 | 本条真实数值问题已修；不等于致死受击回能或特殊 HP 转换已完成。 |
| G14 | 娜塔莎进入双人场景，使用普攻、治疗战技与终结技 | 镜头、出生事件、治疗目标、纯表现、单次回能、持续治疗和重复动作动态值已接。2026-10-09 正式构筑条件排除未激活星魂分支，普攻命中、自然积能、插入终结技及逐目标群疗已贯通，十四次提交获胜；额外构筑未整链验收。 | E0/Lv1 选定行为已实现。属性改变时的快照采样、同目标覆盖重施及额外行迹/星魂仍留缺口，不能扩大为完整角色或通用快照支持。 |
| G15 | 希露瓦普攻、战技感电、天赋与终结技 | 2026-10-09 已接完整目标筛选、逐感电目标追加伤害、当前 DOT 实例参数和来源持续时间延长；21次提交自然积能并获胜，插入终结技击败当前行动者后可继续调度。 | `serval_natasha_vs_antimatter` 的 E0/Lv1 路线已贯通；额外构筑、DOT 采样刷新/重施及其它时序仍需独立验收。丹恒来源图回调准入尚未闭合，不能计入可用内容。 |

## 验证缺口与内容范围，不是新规则问题

2026-10-12 丹恒 E0/Lv1 与娜塔莎的正式双人入场定向复现失败，未计入可用内容。
`MAvatar_DanHeng_CheckSelfBeingTarget` 依赖 `OnListenInsertAbilityAbort`，当前调度没有对应的
类型化生产者；不能用 `queue.action.after` 的 Finish 通知替代。击败/死亡回调中的行动提前
仍未准入。`OnAfterHit` 的 AddModifier 与已有生产者上的 `OnListenAfterSkillUse` 状态效果、
`OnListenTurnEnd` 的 `SetDynamicValueByModifierValue` 已接既有消费者。
瞬时 `Attacker_WindPenetrate` 及固定来源另四种穿透字段已进入直接伤害抗性乘区，来源回调产出
类型化贡献，只影响当前伤害包；非直接伤害暂无消费者，明确拒绝而非静默丢失。
机制条的 Active/CD/数量属于正式资源状态，不能整体标成表现；本轮补齐 CD/ActiveCount、
数值求解失败零提交及明确目标校验，省略 BarType 的更新仍缺选择既有条目的来源契约。
仅空字段 `TriggerEnergyBarEffect` 按现有表现分类排除，新增字段仍拒绝。
上述均有来源片段与边界状态检查，不能扩大为丹恒完整可用。
这些依赖归路线第 4 项，不阻止独立的构筑与多波工作；本轮没有要求用户猜测 Abort 语义。
探针为 `/tmp/hsr-danheng-startup-20261012.py`，最新结果在
`/tmp/hsr-danheng-callbacks-final-20261012.log`，仍拒绝 E0 入场。

2026-10-12 银鬃兵多波探查另定位两项实际依赖：

- 枪兵 `monster_skill:100205001` 的四个技能参数已进入通用消费者，直接伤害只使用来源中的
  伤害参数，不把概率、裂伤比例和持续时间各算一次伤害。裂伤 `MCommon_DOT_Tear` 的
  `UseSnapshotEntity=true`、`OnCreate`/`OnPhase1` 明确读取 `SnapshotPropertyEntity.Attack`；
  现按明确的存活来源关系和公开动态采样实测接通当前施加者属性，定向检查覆盖攻击力与击破
  特攻随后续 buff 更新；来源死亡、移除或缺失仍阻断，重施/叠层另按实际规则处理。来源为
  `Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json`。
- 近战兵 `monster_skill:100204001` 的表现距离分支已接通：严格校验距离表达式与两个分支，
  仅在所有子任务均满足既有表现契约且同步标记序列一致时归为 process-only，完整保留两分支
  payload，不虚构距离条件结果。移动任务新增的归一化动画时点字段也经过来源形状校验。
  真实两波自然交战已执行 4 次近战攻击，伤害、回能、两回合减防和胜利通过。存在战斗效果、
  未知字段或不同同步标记的分支仍 blocked；角色正式任务图的距离分支不借用外部拓扑归约。

以上缺口归路线第 4、5 项。限定清怪路线的多波验证不证明这些敌人的全部动作已支持。

- 早期 MVP 限定一条胜利路线；现已增加普通败北、敌方回合终结技、三人组合、部分星魂/装备
  及两波清怪路线。当前证据以交接为准，不能用这些样例或目录条目数冒充完整角色数量。
- 构筑/装备装配底座存在，不应列成整块未实现；不同实装内容的被动与来源链仍需逐个验收。
- 本轮只做新增规则的必要正例及真实 CLI 战斗、独立 replay；不为覆盖率追加异常矩阵，
  不重复运行与改动无关的全量集合，也不宣称全量全绿。
- 新内容可能暴露新缺口，不能将此表解释为对整个游戏的完整性保证。

## 需要补充行为结论的范围

### 2026-10-13 普通角色附加伤害

采用 [Star Rail Wiki 附加伤害机制](https://honkai-star-rail.fandom.com/wiki/Additional_DMG)：
普通角色附加伤害可暴击，接受元素/全伤增益，不自动接受普攻、战技、终结技、追击或持续伤害
专属增益。页面未标版本；本批适用固定来源中的普通 `Pursued` 攻击力伤害，击破附加伤害仍走
独立击破公式。共享消费者复用普通暴击与 RNG，取消 `Pursued` 自动读取欢愉增伤的错误映射。
固定暴击、特殊倍率覆盖及瞬时伤害修改仍需其对应正式消费者，不据此宣称所有附加伤害完整。

2026-10-15 补充采用 [HoYoWiki 追击与附加伤害区分](https://wiki.hoyolab.com/m/hsr/entry/1244?lang=en-us)：
普通附加伤害不削韧，也不自然回能；角色明确提供的额外回能另按其规则执行。页面未标版本。
本批仅将来源明确 `AttackType=Pursued`、普通直伤且 `StanceValue` 确实缺省的请求编译为不要求
削韧 emission，并保留独立的已采纳资料 `IRSource`；显式削韧值仍走原链，其它攻击类型缺值仍阻断。

### 2026-10-12 按新来源约定采用普通击破行为

以下结论用于普通击破实现，替代下文历史记录中“必须还原原生通知协议才可开工”的要求。
它们不证明原生内部回调总序，也不扩大到强制击破、共享韧性、虚韧性或特殊星魂。

- [KQM 怪盗资料](https://srl.keqingmains.com/equipment/relics#thief-of-shooting-meteor)给出装备者
  造成弱点击破时恢复基础 3 点能量。[HoYoLAB 希露瓦 1.2 指南评论的原始自测](https://www.hoyolab.com/article/21074498)
  记录终结技击破四目标、怪盗贡献 12 点；据此采用普通每被击破目标一次。该证据读取自搜索
  索引中的测试评论，不是本项目亲测或已观看录像。17173 灵砂 2.5 稿有“每攻击一次”的相反
  说法但未列测试条件，暂采用前述可核对构筑与能量分项的记录，不外推灵砂特殊行为。
- [KQM 姬子资料](https://srl.keqingmains.com/characters/fire/himeko)支持队友与自身击破均可充能，
  普通敌人与精英/Boss 分别贡献 1/3 点。这约束的是监听范围，不要求所有状态接收相同通知。
- [KQM 阮梅 1.6 指南](https://hsr.keqingmains.com/ruan-mei/)明确天赋附加伤害发生在击破者攻击
  结束之后，击杀与击杀回能归阮梅，且该附加伤害不再次触发她的怪盗回能。
  四魂首次增益采样仍不由此推断，相关路径需单独处理，不能阻断普通无该星魂的战斗。
- [KQM 伤害公式](https://srl.keqingmains.com/combat-mechanics/damage/damage-formula#toughness-multiplier)
  给出有韧性时乘 0.9、击破后乘 1。实现保留削尽韧性的原攻击使用击破前状态，先解除韧性
  减伤再结算初始击破伤害；后续命中读取当前状态。
- 普通单体、扩散及群攻技能采用正式技能数据 `ShowStanceList` 的主目标、群攻每目标、邻位
  三个数值槽；保留原任务的逐段比例。阿兰与希露瓦源任务核对了槽位及对应操作数，KQM 姬子
  页面提供普通 30/60/30 旧制数据例。弹射、条件动态量或无法对应的表达式继续保留缺口。

普通击破事件接线采用模拟器明确约定：先目标进入击破状态，再初始击破伤害，随后通知击破者
及符合条件的全局监听。公共状态中的通知任务消费同一次领域事实，不重复派发；未知强制任务
不能凭同名自动跳过。具体通过范围以当前交接中的实际验证为准。

G01 与 G04 的普通边界已由 2026-10-10 用户确认并落实，以上新增结论覆盖此前等待实测或暂停
研究的状态；不能据此推断特殊死亡、重施或额外行动。G02 的逐请求权重继续采用 PR8 结论。
G03 的普通已知数值/延迟/恢复规则、G07 的执行链、G09 的已知治疗输入由实现方落实，不要求
用户重新研究。G03 普通通知按上述行为契约实现；下文原生协议研究保留为历史证据，
不再阻断已经明确的普通行为。

2026-10-16 用户确认多层韧性允许单段削韧溢出到下一条，甚至一次消耗多条。本批采用该规则：
一次命中的有效削韧量只求值一次，剩余量逐条消费；非末层仅执行对应的
`StanceCountDown` 伤害和通知，最后一条才进入完整击破。该用户确认未附游戏版本，当前装配以
固定 4.3 TBGD 的单条上限及层数为准；不能据此推导虚韧性或共享韧性数值池。

2026-10-16 多层自然恢复采用公共状态的真实任务顺序：
`GlobalModifier_Common_Specific.json` 的
`$.ModifierMap.StanceBreakState._CallbackList[1].CallbackConfig[1:3]` 为
`ResetStance(ModifierOwnerEntity) → SetStanceCount(ModifierOwnerEntity)`，后者没有显式计数字段。
结合[公共战斗教程](https://honkai-star-rail.fandom.com/wiki/Tutorial/Battle)的回合开始恢复韧性及移除
击破状态规则，本批将这条无显式计数的自然恢复链规范为：仅完全击破、剩余层数为零时，先补满
当前条，再将层数恢复到同一正式怪物卡的 `template_config.stance_count`。适用于当前固定 TBGD
公共状态；教程页面未标适用版本。这是采用的该来源形态语义，不扩展为任意 `SetStanceCount`
或显式计数形态，也不推断强制恢复、共享韧性及虚韧性。

PR #8 最新[数据库充分性判定](https://github.com/yaelysia/hsr-battle-simulator/blob/4d524d6c1e4875d748b5adb568e478a554b34d3b/docs/tbgd_evidence/shared/break_notification_database_sufficiency_verdict_v1.md)
确认固定导出不足以唯一重建该原生通知协议；`ForbidRecallModifierEventList` 中出现
`OnTriggerBreak`，但其含义不能推成去重规则。该研究增量没有闭合护盾加成上限、免控消费或
特殊计时；致死回能和普通首次扣时采用上述后续用户确认，不改写 PR8 当时的证据。
G06 的真实保护状态可见 `OnImmuneDebuff → RemoveModifier`，但静态免疫判定缺少到哪个回调、
哪个保护实例以及多源次数/顺序的关系，故不能仅按回调名字消费保护。G07 的真实怪物动作
`800304005` 包含 `RetargetPerSequence` 和 `FireProjectile`；当前仅接来源已闭合的单目标等待命中投射物，
该怪物的逐序列重选与完整弹射组合仍未接通，
`TauntOrRandomEnemy` 的抽样、重复与失效回退规则亦未确认，已完成的逐请求回能不能代替完整弹射。

### 2026-10-10 击破通知续查

按用户要求继续研究 G03，实际核对 PR8 当前 HEAD `9a7ab71b00a0027e994ad33d06a918a998602a24`。
固定 TBGD 的 Config JSON 检索定位到 12 个文件内 21 个 `RPG.GameCore.TriggerBreak` 对象；
所检查对象均只有 `$type` 和 `TargetType`，未包含通知序列或次数规则。
`FightFest_Level_Ability.json` 的 `AbilityList[50].OnStart[3].TaskList` 连续写出两组
`ResetStance(0) → TriggerBreak(ParamEntity)`，随后显式包含元素击破模板；可可利亚共享韧性状态
还在 `OnBeingBreak` 请求 `TriggerBreak(AllTeamMember)`。这些是任务请求的结构事实，不能据此
判定实际通知次数、嵌套调度或普通击破的接收者，也不能按整次动作统一去重。

重新取得了[4.3.0 标记的任务执行器声明](https://github.com/Z4ee/AnimeSDK/blob/75b0b4b1eff6c4a2a48e15b4358b0e40b0e2045b/unitysdk/Class_3_C9CFBB2710ACF1F9.h)：
`OnTaskBegin` 仍仅转调原生地址，没有目标解析或通知分发函数体。新增核对的公开
[modifier 原生拓扑记录](https://github.com/eryou1202/hsr-battle-agent/blob/ce62dc0028d15cbdc7a332c3db860ed7fffb9c58/data/raw/4.4.54/modifier_effect_topology_09.json)
将两处 `ExecuteAllModifierEvent` 调用归到 `TurnBasedModifierInstance.OnActivate`，没有连接到
`TriggerBreak` 或给出该处事件参数；其 4.4.54 目录与 4.4.53 客户端路径也未完成版本对账。
另一个旧版 C# 命中只有配置类声明。上述材料均不能替代匹配版本的函数体或原始事件轨迹，
公开检索结果不构成全网不存在这些证据的证明；本次未获取或执行原始客户端。

本地调用链检查另外复现并修复了范围编译丢失零监听者事件声明的问题：普通普攻削韧到零时，
原先在 `OnBeforeBeingBreak` 就被误判为 `status_event_family_missing`；现在保留已知生产者协议，
未知事件及错误事件来源仍拒绝，不增加回调实现或新的击破通知。普通定向 56 项通过；
已确认普攻可到达 `break_trigger_notification_mapping_unconfirmed`，整次动作 mutation/RNG 为零且
完整快照不变；普通恢复组件也通过。该检查使用明确标注的边界 fixture，不是原生游戏观察，
不能证明通知协议。阿兰战技的匹配弱点路径还缺 `1659254037` 输入，不用普攻的 30 点基数代填。

完整通知链仍未闭合。继续恢复它需要来源及版本可核对的客户端 `GameAssembly.dll` 和 metadata、
相关函数的反汇编/调用轨迹，或能区分重复派发与嵌套阶段的原始行为证据；已向用户询问资料路径。

### 2026-10-11 公开实测线索与待复刻实验

用户允许暂放无法查明的局部阻断，并继续其它路线。公开检索找到
[Jenova 工坊的阮梅实测合集](https://www.bilibili.com/video/BV1XK411x7gk/)，页面索引包含
怪盗套回能、抢击杀等独立测试；另有[作者明确写出纠错的视频页](https://www.bilibili.com/video/BV1At4y1Z7Mm/)。
本次取得的是页面文字和索引，未取得完整逐帧画面、构筑及能量变化；不能据标题或“滞后计算”一句话
确定原生通知顺序。数据网站的阿兰削韧数值与本地 `ShowStanceList` 相符，但展示值仍不能证明
`1659254037` / `-1315627076` 的通用生产者和绑定规则，保留输入缺口。

后续游戏实验优先记录可观察行为，不要求用户识别内部回调名：

| 实验 | 固定条件与对照 | 可以约束的事实 |
| --- | --- | --- |
| 怪盗套的接收者 | 两名角色都装备四件套且能量未满，由其中一人单体击破不致死；交换击破者，再加入阮梅重复。逐人记录动作前后精确能量，排除击杀、受击及其它回能。 | 固定来源 `MRelic_111_Main.OnTriggerBreak` 给状态所有者回能；对照能约束谁收到有效通知。不能从能量总差直接猜内部回调次数。 |
| 同动作击破多个目标 | 同一群攻分别击破一个、两个不致死目标，其余构筑和初始能量相同；保留每个目标的击破前后韧性及全部回能来源。 | 区分按被击破目标和按整动作结算的可见差异；不能外推到强制重复 TriggerBreak、虚韧性或已击破目标。 |
| 阮梅四魂首次生效时点 | 新战斗、四魂增益尚未出现，记录阮梅击破特攻面板、单目标首次击破的全部伤害与增益变化；队友击破和阮梅本人击破分别记录。 | 结合既有结构化公式核对增益是否影响当次击破及天赋伤害；需足够精确的数值区分候选顺序，单看跳字先后不够。 |

每段记录客户端版本、关卡/敌人等级、角色等级/行迹/星魂、装备、初始状态、操作和时间戳。
这些实验是待取证方案，尚无新增游戏观察结论；完整击破通知仍阻断实际依赖。

若入选内容确实触发，再核对 G05 的全局多盾通知顺序及降 cap/加成 cap 争议、G06 的保护消费、
G04 的特殊续时、G08 的特殊
死亡/分摊以及 G10 的具体采样/极值。入场 HP/能量可由场景显式提供，不要求先恢复所有模式的
跨战斗继承策略。源码中的 blocked 标记只证明当前实现拒绝，不证明游戏里没有该行为。

### 2026-10-11 装备能力查询与保留阻断

限定角色/关卡但包含装备目录的正式编译共有 224 个装备能力图。本批修复复合目标来源先后顺序、
`OnlyRemoveCasterAdded` 丢失和纯表现回调分类，解除 7 个编译/查询阻断：
`Ability20005/21002/21032/21036/21056/53021/23006`。再修复启动任务丢失真实 AbilityList 索引、
出生事件来源被误当单位的接线错误；仙舟两件套的真实出生和完整战斗已通过。
该统计只表示图的查询准入，不能当成 218 件装备都已实战验收。

以下 6 个图继续拒绝实际依赖，未用说明文本或旧默认值补规则：

| 来源能力 | 尚缺事实 |
| --- | --- |
| `Ability23051/21033/23002` | 百分比 `HealHP` 未显式给出 `FormulaType`；无法唯一确定基数。 |
| `Ability20015/23033` | `ModifyCurrentSkillDelayCost` 未显式给出 `ModifyFunction`；不猜加法或乘法。 |
| `Ability23013` | `OnSnapshotCreate` 缺对应正式事件生产者；出生通知不代替快照创建通知。 |

公开检索命中[第三方配置编译器](https://gist.github.com/12345-mcpython/7a4032165da00a74dbc7bccdbe3d9500)，
它读取显式字段，并有依赖文本推断的分支；没有提供原生缺省枚举的依据，本次未采用。
后续需版本匹配的缺省值来源，或能区分候选运算的游戏数值实验；当前不以猜测继续扩准入。

### 2026-10-12 三月七护盾纵切与保留边界

真实双人场景范围编译、三月七 E0/Lv1 成品装配均通过，但正式入场被
`MAvatar_March7th_00_ListenEnergyBar.OnListenModifierAdd` 挡住；装配结果不等于完整入场可用。
初次探针 `/tmp/hsr-march-shield-probe-20261012.log`（53.31s，峰值 824948 KiB），
补充诊断 `/tmp/hsr-march-shield-probe-detail-20261012.log`（19.74s，峰值 524188 KiB）。

已补已有生产者上的 `OnPhase2`、状态增删监听、出生监听、受击前及死亡前通用效果准入，
并将 `OnStack.InitShield`、`OnDestroy.RemoveShield` 接到原有护盾执行器。
真实来源公式与 mutation/replay 检查继续复用，新增来源文件级检查覆盖普通 callback 接线；
58 项相关检查通过。随后修复普通 callback 准入丢失已编译目标，以及未接来源目标语言闭合的
共用问题；死亡前 `TargetConcat(AllTeamMember, AllUnselectable)` 与 `OnlyRemoveCasterAdded`
可沿已有 StatusSystem 执行，63 项相关检查通过。未为三月七另写护盾公式或绕过被动。
真实复查 `/tmp/hsr-march-shield-target-final-20261012.log`（54.92s，峰值 825132 KiB）当前首先
报 `dynamic_hash_unbound:Mar7th_00_Passive_CounterView`：被动 OnStart 先添加监听状态，再添加
CanAttack，之后才 SetDynamicValue；原生缺省值与通知调度不能从这段顺序自行补成零。

保留以下具体边界，不能把它们合称为“护盾公式未实现”：

- 四个 `OnListenModifierAdd/Remove` 下的 `SetEnergyBarState` 只有 `CurrentState`，
  没有 `BarType`。同文件其它任务显式给出 3，不能据此推断所有缺省任务也写 3。
  本次公开检索未找到原生缺省值或选取已有机制条的实现依据，继续拒绝。
- `SetResilience` 尚未准入普通护盾回调。现有 consumer 在非 reset 时要求同状态的护盾实例
  已存在，而现有状态生命周期先发 `OnCreate`、再发 `OnStack`，此来源在后者才 `InitShield`。
  需进一步闭合该同步任务的生命周期契约，不能仅开放白名单。
- `SetModifierValue` 的 Phase2 计数更新、`ModifierOverrideOnHitEffect` 的严格表现形状仍需逐条闭合。
  E2 等未选构筑的来源诊断不能当成
  E0 独有阻断。

## 2026-10-12 佩拉攻击后回调

固定 `Avatar_Pela_00_Ability.json` 的普通攻击后状态计数、回能和死亡通知清理已接既有消费者；
状态计数继续只读取正式状态实例，未知字段、未知读取对象和非法状态明细拒绝。动态写入同时更新
状态实例及全局存储，后续读数现在排除该实例的存储镜像，避免把同一次写入误判成多来源；
其它实例的同键冲突仍拒绝。局部来源及写入→读取→mutation 回放检查通过，不代表完整角色验收。

正式双人场景装配、E0 入场及真实战技现已通过。固定技能削韧绑定提供 `1659254037`；
`DebuffNumber`（`2612209`）采用项目已有的明确声明局部浮点槽初始零规则，补齐角色配置
到状态安装权威的接线。只初始化当前回调实际引用的 `Type=None` 声明，显式值和后续写入优先，
未声明 hash、外部参数与不相关槽不补零。
[KQM 佩拉指南（2.0）](https://hsr.keqingmains.com/pela/)说明每攻击最多一次、攻击后目标有
负面状态才回能、击杀不触发；真实任务先累计目标负面状态数，成功回能后显式清零，无负面
状态时加数均为零。初始零符合该行为，且复用现有通用规则；不声称从 raw 声明唯一还原原生
缺省协议，也不在每次攻击前强制重置。定向检查覆盖初始化与覆盖优先级，公开入口战技验证
伤害、回能和战技点消耗通过。

额外行迹的 `DamageDefenderEntity` 状态计数仍缺正式动态读取上下文，E6 直接追加伤害形状和
普攻的多投射时序也未闭合；没有静默跳过被动或宣布完整角色验收。

## 2026-10-12 虎克强化战技动作槽

固定 `Avatar_Hook_00_Ability.json` 的 `MAvatar_Hook_00_BPSkillAlter_Enable` 在 `OnStack`
把 `ControlSkill02` 映射到 `Skill21`，`OnDestroy` 映射回 `Skill02`；这证明两次切换请求，
不能反推首次入场默认槽位。真实 `ConfigCharacter/Avatar/Avatar_Hook_00_Config.json` 提供
`Skill02` 与 `Skill21` 的技能类别/目标及 ability 关联，未提供初始控制槽映射；核对过的
`GameCoreConstValue`、`GlobalConfig` 和通用/客户端常量也未给出该契约。

强化战技末尾的 `SetModifierValue` 指向上述状态，`ModifyFunction=Add`，但没有 `Value`
和 `ValueType`。这类缺省读写及计数耗尽与状态销毁的关系仍需原生契约，不能凭效果说明补成
减一次、默认为某种计数。`ShowBattleSkillEnhanced` 的局部表现分类可独立处理，但不构成
强化技能可用性闭合；目前没有按角色名、技能编号或回调出现顺序制造默认映射。

## 2026-10-12 怪物线性被动初始化与出生入口

怪物被动启动此前只接受顶层 `AddModifier`，会拒绝真实 `OnStart` 中显式常数的
`DefineDynamicValue(Caster, TargetEntity)`。这条线性形状现已接既有动态值执行器，保留真实
任务顺序、写入来源和 mutation 回放；新准入要求完整的显式 ResetValue，未知字段、非 Caster
目标、其它作用域和缺省初值仍拒绝。杰帕德源文件中的两个显式 1 值初始化经片段检查通过。

真实 `401310070` 波次入场探针（50.55s，峰值 807892 KiB）确认两个值出现在启动候选状态，
但整次入场仍失败，不能视为正式提交或可用 Boss：同关卡戍卫官有其它启动任务；杰帕德的
特殊死亡效果及 `MMonster_W1_Gepard_00_Command.OnCreate.TeamAction` 仍阻断。
`TeamAction` 带 ActorPredicate/TargetPredicate，尚不能仅凭名称认定为可删除的 AI 策略。

Boss 信息条已按任务拆开处理：只将字段完整的 `ShowBossInfoBar(TargetAlias, IsShow=bool)`
分类为表现叶子，保留原始任务、字段形状契约和被动准入中的来源记录；缺省值、未知字段及嵌套
任务仍拒绝。后续 `AddModifier(MCommon_BOSSInfoBar_Active)` 正常执行，不能把整个被动删除：
`Config/ConfigAbility/BattleEventAbility_2.json` 的
`BattleEventAbility_Challenge_Month_42_Level.OnListenModifierAdd` 会读取该状态名。
21 项定向检查覆盖保留状态、非法形状、零表现 mutation 和 mutation 回放。真实同关卡探针
不再出现信息条启动错误（46.31s，峰值 812848 KiB；`/tmp/hsr-info-bar-gepard-20261012.log`），
其余阻断仍使整次入场失败，不是 Boss 整场验收。

灰熊 `2013110` 的来源探针（46.71s，峰值 721880 KiB）更早被条件式启动和自定义召唤 ID 绑定
拒绝，尚未到达正式出生。后续已修复范围编译漏掉 `MonsterConfig.SummonIDList` 的工程问题：
按声明递归纳入子怪物卡、动作、被动和来源文件，重复/循环引用只加载一次，不改原始声明中的
次数，也不提前生成单位。缺失 ID 保留未解，未知字段形状拒绝，不能据此补出动态召唤结果。
灰熊表行明确列出 `1012021`；该依赖应由来源编译自动加载，无需用户手动扩大 monster scope。
另核对其 `Monster_RO_015_SummonID` 名称哈希为 `-1402539578`，与任务读取吻合；但角色配置
给出 `1012020`，怪物表给出 `1012021`。优先级尚未闭合，未按“看起来应覆盖”选值。
静态调用链另确认：`SummonMonster` 在
`AbilityTaskSystem.execute_summon_monster_task` 调用出生执行器；后续波次才接了
`apply_monster_startup`，战斗内召唤与预置召唤尚需闭合同一启动权威及事件去重，未宣称已修复。

怪物 ability phase 当前仍为 `external_legacy`，不在角色正式任务图目录内；直接套用角色正式
执行入口的组件探针被 `task_graph_missing:entry` 拒绝。条件式被动需要正规的怪物来源图接入，
不能伪造角色身份、队列调用或只改 invocation_role。忆灵 CreateServant 的普通调用缺口另由
PR8 `shared/owned_servant_runtime_admission_v1.md` 说明；其动态参数、被动自动启动、属性同步
和初始时间线须分别保留，不能借怪物出生协议推出忆灵规则。

## 2026-10-12 属性快照补查

固定来源的 `TargetAliasConfig.AliasDict.SnapshotPropertyEntity` 实际展开为
`Caster -> TargetFetchAliveSourceEntity`。这只证明显式选择链，不能仅按 Snapshot 名称解释为
“施加时冻结全部属性”，也不能省掉第二步直接读取当前 caster。
PR8 固定 evidence `8daa6a8abb9a15e423ecf987356dcc0a936565ba` 的
`healing_modifier_lifecycle_core_v1.md` 第 10 节仍未闭合 capture、refresh、继承和死亡后路由。

新增公开的一手实测线索：[Some DoT tests](https://www.reddit.com/r/HonkaiStarRail/comments/148tfhn/some_dot_tests/)
第 2 项记录艾丝妲攻击力 1350→1274、同一目标灼烧 229→216；第 3 项记录施加后获得停云增伤，
后续灼烧随之变化。这支持该样本并非施加时全量锁定属性；原帖把结论外推到全部 DoT 的部分不采纳。
现已读取文字、构筑说明和数值表，未独立复核图片/视频，也没有怪物、施加者死亡、复活和重施对照。
另找到 [EODGamer 的 DoT snapshot 视频](https://www.youtube.com/watch?v=1uHLSq9CvHI)
（发布于 2023-08-05），只取得标题/作者/描述，未取得可验证逐帧内容。
同帖第 4 项记录击破后获得塔利亚 20% 击破特攻：88.4%→108.4%，灼烧 1671→1849，
支持击破持续伤害也读取后续属性变化。结合正式 alias 的存活施加者关系，现已接通当前
可读数值属性；状态实例与施加者身份必须匹配，不以状态目标代替来源。死亡、移除或缺失
来源仍局部阻断，不把存活路径外推为完整快照生命周期。

待游戏复刻应区分：施加者被击败后继续结算、复活后再次结算，以及重施
是否更换属性来源。记录施加和每次结算前面板、完整构筑、版本及未混入击破的动作顺序；仅用一条
“DoT 不锁面板”结论不足以关闭这些边界。

## 直接核对入口

- `../systems/ability.py`：共享削韧接入、正式加权分支。
- `../systems/break_system.py`、`../systems/scheduler.py`、`../systems/status.py`：恢复与时钟。
- `../systems/damage.py`、`../tbgd/lowering.py`：受击回能；`../systems/shield.py`：多盾。
- `../systems/status_callbacks.py`、`../systems/unit_lifecycle.py`：回调与复活边界。
- `../tbgd/battle_catalog.py`：所选波次范围与环境准入。
- `../tests/test_cli_content_scope.py`、`../tests/test_current_skill_delay_cost.py`、
  `../tests/test_manual_ultimate_decision.py`、`../tests/test_monster_hit_energy.py`、
  `../tests/test_capped_shield.py`、`../tests/test_parallel_shield_absorption.py`、
  `../tests/test_initial_break_base.py`、`../tests/test_ordinary_frozen_turn.py`、
  `../tests/test_ordinary_break_wind_predicate.py`、`../tests/test_break_bleed_value_routing.py`、
  `../tests/test_ordinary_break_recovery.py`、`../tests/test_monster_stance_count_source.py`、
  `../tests/test_nested_status_lifecycle_event_identity.py`、
  `../tests/test_pre_action_dot_defeat.py`：对应实际行为检查。
- `../../live_validation_reports/pr8_confirmed_rules_local_execution_2026-09-26.md`：已有实施结果；
  其中早期“完整终结技尚未贯通”等表述已由随后 CLI 实测更新，以当前交接为准。
