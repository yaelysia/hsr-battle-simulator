# 正式角色构筑与普通队伍战斗批次（R05）

启用日期：2026-10-24。实现由用户安排 dsh / DeepSeek，Codex 负责集中验收。
实现基线：`516acc8`（普通怪物战斗闭环、死亡与队列原生审计及已验收工作台改进）。
上一批已通过集中验收并提交，当前 HEAD 可包含其后的文档交接提交；不能从仍缺上一批
成果的 `b9eba45` 另起实现。TBGD 保持 `14c1d18f91a8101d610e6c523447a7517de3fae1`，
复用根 `.venv`，不更新来源、不新增依赖或环境。本批已成为当前实施入口，不沿用旧 R04 说明。

## 交付目标

将阿兰 1008、娜塔莎 1105、玲可 1110、三月七 1001 从现有的限定构筑路线，扩成可使用完整
合法构筑的普通战斗角色：等级/晋阶、有效技能等级、属性与额外能力行迹、零至六魂的前缀
选择均经正式装配，并真正进入技能、天赋、回调和队列。四人已用于普通怪物 B 路线，
复用现有伤害、治疗、护盾、反击和普通战斗底座，不重做另一套角色执行器。

“完整”覆盖这四张普通角色卡的战斗构筑和动作分支；增强版、其它命途、记忆/欢愉、
自由挂载召唤物、全装备目录及特殊关卡不并入。必要共享缺口随本批消费者一次解决，
不能只将槽位改为 executable，或删除不利行迹/监听后就宣称角色完整可用。

## 已核对的起点

- `tbgd/character_cards.py::_trace_nodes_and_slots` 对带 AbilityName 的行迹建立了
  `trace_ability_hook`，保留节点、能力、参数与动态值声明，但仍以
  `trace_ability_effect_not_admitted_v0_265` 初始化为阻断；lowering 的
  `_admit_trace_startup_ability_slot` 在无 EnhancedID 时直接返回原槽位，普通卡不能借用
  已有增强版启动准入。复用既有动态图装配，不把这个分支简单删除后全局放行。
- 四卡的额外能力不都通过独立 AbilityName 声明：基础表中阿兰的三个额外能力有该字段，
  娜塔莎只有 SkillTree02 声明独立能力，玲可/三月七没有这种声明。
  `_trace_nodes_and_slots` 与绑定层还处理 `trace_extra_effect`，其中仅有 ExtraEffect 引用的
  部分会以 `trace_extra_effect_has_no_structured_effect_source` 阻断。必须继续查实际能力图、
  选择条件或已采纳规则来建立正式绑定，不能为凑三个 hook 伪造能力，也不能将纯显示引用
  当效果执行；本批就是要将这些不同声明路径接成同一正式构筑链。
- `builds/character_assembler.py::assemble_character_build` 已负责行迹/星魂选择、有效等级、
  贡献与动态根装配，并调用现有装备装配。`scenarios/build_state.py` 将正式结果用于出生与启动。
  `AbilityTaskSystem.execute_character_build_startup` 是已有的构筑能力入口，继续复用。
- `test_character_build_startup.py` 已证明娜塔莎 E0/E1/E4 的限定启动差异、受击回能和一次性
  自疗；`test_eidolon_source_branches.py`、`test_p9_a2_formal_build_param_projection.py` 已有
  选择及参数隔离检查。这些证据不代表四张卡的全部行迹/星魂和技能分支已完成。
- 普通怪物 B 的四人构筑与命令可用于复用输入和来源定位。其死亡爆炸/召唤路线属于上一批，
  本批新增成果必须是构筑能力的实际消费，不能只重复旧胜利路线。

## 开工时一次核对的内容

按四张卡分别列一张简表，列出动作/被动、三个额外能力行迹、属性/技能行迹、六个星魂及
来源参数。每项标明已接通、实际接线缺口或规则问题，沿现有槽位、绑定、启动和消费函数核对，
不将旧报告或测试数量当当前状态。不同卡的同根问题合并修复，避免四次重复实施。
该表是同一实现会话的起点，核对后继续完成 A–D，不单独交回调查结果。

逐项确认来源身份及参数的正式入口：角色卡 → 选中节点/星魂 → 构筑绑定/动态根 → 启动能力
或动作分支 → 数值/状态/队列结算。保留源行与正式引用，不从显示说明、普通事件 payload 或
source_trace 推断构筑选择。依据不足的效果查适用的可靠机制资料，简记条件与链接即可。

## 整批完成条件

| 结果 | 必须交付的可观察行为 |
| --- | --- |
| A. 四卡构筑准入与差异 | 四卡的 E0、各实际产生不同效果的星魂前缀、合法行迹组合和有效技能等级可以正式装配。参数按各自技能/行迹等级读取；验证选中与未选中、同卡不同实例与跨卡隔离。未解锁、不满足晋阶/前置、重复或异卡节点继续拒绝。 |
| B. 四卡构筑能力消费 | 阿兰的 HP 消耗及其实际构筑分支，娜塔莎的治疗/清除及行迹星魂，玲可的生存反应/持续治疗与防护分支，三月七的护盾/受击反击及其构筑分支，均按固定来源核对并执行。列举这些行为用于定位，不以举例代替卡上其它战斗效果；不用组件注入替代正式构筑挂载。 |
| C. 合法普通队伍实战 | 用至少两个有区分度的正式构筑场景覆盖四卡新增能力与双方实际行动，经公开 advance/submit 完成战斗。让新增能力的条件真正成立，检查其实际值、目标和后续影响；同一场可覆盖多个能力，其余参数/选择边界用组件检查，不为每个星魂各跑一场。 |
| D. 构筑稳定性与失败边界 | 已提交构筑、参数和启动身份不受兄弟实例或调用者修改污染；未选择的能力不能被普通动作入口冒用。启动晚失败、回调晚失败或参数缺失时，按本次改动涉及的事务边界验证零状态/RNG 泄漏。保存/恢复后有效构筑与行为一致，审计能反查实际已选来源。 |

四卡覆盖齐备后集中交付，不每接一个行迹或星魂就交回。规则争议只阻断实际依赖；如确有
无法消解的规则冲突，汇总具体卡/效果、缺少条件和影响交用户判断，继续完成其余已明确工作。
不擅自缩成两张卡或只验 E0；也不展开全部角色/全部环境的目录任务。

## 生产边界与实施约束

1. **选择权威**：复用 CharacterBuildInput、角色卡、节点/星魂绑定和正式启动。把普通行迹
   能力映射到唯一合法的正式图/效果并验证完整依赖；没有依据的能力继续阻断，禁止全局改绿。
2. **参数与时机**：静态面板、有效技能等级、动态效果分别消费正式输入。技能倍率与行迹参数
   不混用等级；选中星魂的提升不能污染未选实例。入场触发一次，后续触发由实际事件生产者
   提供事实；不把被动挂载、主动施放和每回合触发互相代替。
3. **实例与身份**：同名状态、治疗者/施加者、效果所有者、实际目标及回调触发实例独立绑定。
   原生参数来源可反查；不按角色名、固定 ID、文件名、hash 或观测数值在 runtime 特判。
4. **持续治疗及防护**：对四卡实际需要的采样时点、持续时间、刷新、解除/到期与再施加先定
   适用规则。已有存活施加者 DOT 语义不能外推所有 HoT/护盾；有实际快照需求就补足对应
   生产→消费→清理，不能忽略 UseSnapshotEntity，也不为名称相同搭建无消费者的平台。
5. **资源与原子性**：沿用既有 HP 成本、BP 与 SPBase 单一回能生产者、插入行动和状态生命周期。
   不复制计划/正文两套资源口径。实现阻断保留待处理条目，已确认的正常取消沿正式取消契约；
   同一事务回滚完整，独立已提交的上一事务保留。
6. **审计与序列化**：新增行为影响 IR 身份、编码、缓存、归档时同步相应边界。审计核对实际
   写入、完整列表差分、来源身份、原生 settlement 及关联 ID；按正式定义与实际写入确定边界，
   不能靠剥离标签或改结算类型降级检查。结算携带的规则定义副本与本次正式对象整体严格
   比较，不能只查 ID、键存在或两份可改写副本相等。runtime 不消费审计 evidence；
   恢复兼容若确有新影响，先说明具体接口及方向。
7. **共享缺口**：新增目标、嵌套、事件或快照能力只实现四卡真实依赖的部分，检查所有正式
   调用者并集中接线。R04 的其它并行/复杂目标、R02 救援复活、R06 全装备目录及 R07 完整
   角色派生单位仍有原范围，不以修改本批名称消失，也不强制本批先完成它们的全部机制。

## 验证与成本

- 同一四卡来源范围复用 RuleBook 和只读前置。选择、参数、身份和失败边界先做最小检查，
  根因修复稳定后合并跑 C 的实战。只新增能发现实际错误的检查，不为每个字段建负例矩阵。
- 复用现有构筑启动、星魂来源分支、参数投影、免疫/反击/治疗和队列资源检查；新选择要与
  实际运行结果对上，不能只检查 IR 的 coverage_status 或本次新增字段等于自己写入的值。
- 来源和预期从实际选中行及已采纳规则独立核对。正式入场、启动和新增能力相关 transition
  过 RuntimeSourceAuditor；组件输入如实标注，不冒充整卡实战。
- 完整编译/正式场景显式标记 integration，重任务串行持有 `/tmp/hsr-v8-validation.lock`。
  先保存首次有效路线和原生归档，之后查字段直接读该产物，不重复从入场运行作观察。
- 本批若改变构筑启动、序列化或恢复链，选组合最完整的一份现成归档独立 replay；无不同
  风险的其它路线不追加相同回放。普通回归按实际影响选取，不默认全目录或全量回归。
- 普通怪物及已验收工作台成果已在基线提交，不得回滚或混入无关改动。跨领域发现先归因；
  不创建新的付费调查/修复会话，不自行启动代理，保持用户安排的一次实现会话。

## 交付与验收

交付四卡能力覆盖表、关键修改及原因、固定正式输入/命令、必要测试与归档和具体剩余依赖；
注明复用的证据。本文件只替换结果节，短交接只写状态和入口，不追加逐轮流水账。
完成后冻结实现，整批交回；Codex 先审完整相关源码差异、调用者、权威与失败路径，再合并
必要验证，集中反馈。同一实现会话一次处理同根问题；验收通过后按用户指令提交再进入后续批。


## 结果（2026-10-24）

### 1. 四卡能力覆盖表

下表按正式来源列出本批接通的行为。参数值取自角色配置 `DynamicValues.Floats`
（`SkillTreeParam` / `SkillRank` / `SkillParam`），行迹节点 ID 即 trace PointID。
“实测”一栏只写本批真实跑出的事务级证据，不以 IR 字段替代。

| 卡 | 行为 | 来源与参数 | 正式接入路径 | 实测 |
| --- | --- | --- | --- | --- |
| 阿兰 1008 | 天赋「至痛至怒」 | 被动能力，无行迹参数 | 既有天赋启动 | 既有，本批回归 |
| 阿兰 | A2「复活」PointB1 1008101，[0.3, 0.2] | `trace_ability_hook` → `Avatar_Arlan_SkillTree01` → `M_Arlan_Tree01` `OnTriggerDeath`/`HealHP` | 事件+治疗回调准入扩展 | 45% 生命击杀后治疗记录（路线 A） |
| 阿兰 | A4「坚韧」PointB2 1008102，[0.5] | 启动效果 `StackStatusResistance`，BehaviorFlag `STAT_DOT` | effect.py 新 opcode；status.py 施加概率扣减 | DoT 概率记录 `behavior_flag_resistance: 0.5`（路线 A） |
| 阿兰 | A6「不屈」PointB3 1008103，[0.5] | 启动分支 HP≤50% → `AddModifier` `BlockDamage_Count` | damage.py 新增非 DoT 伤害格挡（直接/欢愉/击破/超击破/追加） | 低生命入场安装 `BlockDamageExcludeDot` 并被真实攻击消费（路线 A） |
| 阿兰 | E1/E2/E3/E4/E5/E6 | SkillRank/SkillAddLevelList：0.1 增伤、1 层驱散、技能/普攻+2、0.25/2 回合复活、终结技/天赋+2、0.2 终结技增幅 | 既有星魂选择器 + 启动/动作分支；E4 常驻 `PassiveSkill_UnDead` 并接未决死亡救援链 | 选中与隔离；E4 正式构筑原生致死→`OnLimboWaitHeal`→插入能力 25% 复活→继续（星魂测试） |
| 娜塔莎 1105 | 天赋「生命虹吸」 | 被动治疗，无行迹参数 | 既有 | 既有，本批回归 |
| 娜塔莎 | A2「舒缓」PointB1 1105101，[1] | `BySkillPointActivated` → 技能 `DispelStatus` 1 层 | `trace_skill_point_param` 槽 → 动态参数源 | 技能清除记录（路线 A） |
| 娜塔莎 | A4「医者」PointB2 1105102，[0.1] | `trace_ability_hook` → `Avatar_Natasha_SkillTree02` → `M_SkillTree_HealRatioUp` | 普通卡行迹 hook 启动准入 + 动态参数 | 入场状态与治疗增幅（组件检查） |
| 娜塔莎 | A6「复苏」PointB3 1105103，[1] | `BySkillPointActivated` 选择器写入 `SkillTree_LifeTime` | 行迹参数槽 + 既有技能持续回合分支 | 技能 HoT 持续 3 回合（路线 A 归档） |
| 娜塔莎 | E1/E2/E3/E4/E5/E6 | Rank 能力：0.15/400 受击治疗、终结技 HealHP/HoT、技能/终结技+2、命中回能 5、终结技/天赋+2、普攻 0.4 附加 | 既有星魂启动/动作分支；选择器隔离 | 既有 E0/E1/E4 测试 + 本批星魂测试 |
| 玲可 1110 | 天赋「户外生存经验」/秘技 | 既有 | 既有 | 既有，本批回归 |
| 玲可 | A2「探险」PointB1 1110101，[2] | `BySkillPointActivated` → `M_..._Tree01_Listen` 子修饰器；受击前给玲可能量 | 行迹参数槽 + 星魂/行迹选择器 | 能量增加记录（路线 B） |
| 玲可 | A4「探险技巧」PointB2 1110102，[0.35] | `M_..._Tree02_Resistance` 的 `StackStatusResistance`（STAT_CTRL） | 同上，控制抵抗概率 | 入场控制抵抗 0.35（组件检查） |
| 玲可 | A6「极限生存」PointB3 1110103，[1] | 选择器 `SkillTree_LifeTime` → 天赋 HoT +1 回合 | 行迹参数槽 | 技能 HoT 持续 3 回合（路线 B） |
| 玲可 | 战技「生存反应」 | 技能参数 [0.05, 50]；公式 `(MaxHP−HPConvert)×(param0+Rank06)` + HPDelta | 新增 `HPConvert` 属性桶、max_hp 合成与 `HPDelta` 平铺 | 目标获得 5% MaxHP 转换与 50 治疗；E6 后为 11%+Effect RES 0.3（路线 B/星魂测试） |
| 玲可 | E1/E2/E3/E4/E5/E6 | 治疗增幅、1 层抵抗、技能等级、目标 3% 玲可 MaxHP 攻击、终结技/天赋等级、6% MaxHP+30% Effect RES | 既有星魂选择器与技能分支 | E4 攻击值、E6 hp_convert/Effect RES（星魂测试） |
| 三月七 1001 | 天赋「少女的特权」/秘技 | 既有护盾/反击底座 | 既有 | 既有，本批回归 |
| 三月七 | A2「纯洁」PointB1 1001101（前置 1001201） | `DispelStatus` 1 层（技能） | 既有选择器 + 参数槽 | 减益 2→1（组件检查） |
| 三月七 | A4「加护」PointB2 1001102，[1] | 选择器 `_Tree02_LifeTimeAdd` → 护盾持续 +1 | 行迹参数槽 | 技能护盾持续 4 回合（组件检查）；路线 B 用入场护盾消费反击 |
| 三月七 | A6「冰咒」PointB3 1001103，[0.15] | 选择器 `_Tree03_ChanceAdd` → 终结技冻结概率 | 行迹参数槽 + 概率结算 | 终结技冻结概率提升（组件检查） |
| 三月七 | E1/E2/E3/E4/E5/E6 | 冻结回能 6、入场护盾（0.24/3/320）、技能/终结技+2、反击追加 0.3 防御倍率且次数+1、终结技/天赋+2、护盾治疗参数 | 既有星魂选择器、入场护盾能力、反击插入能力 | E2 入场护盾；E4 反击插入能力在自身能力作用域写入防御倍率并完成伤害（路线 B） |

技能等级：四卡等级 80 晋阶 6，E3/E5 的 `SkillAddLevelList` 计入有效等级（技能/终结技/天赋
按来源分别投影）；行迹 10 个属性/技能节点与 3 个额外能力节点均按合法前置装配。

### 2. 关键修改及原因

| 文件 | 修改 | 原因 |
| --- | --- | --- |
| `tbgd/character_cards.py` | 无 AbilityName 的行迹参数节点生成 `trace_skill_point_param` 槽（每级参数+动态绑定）；参数槽不参与动态图绑定，但仍须可执行；全为参数时允许选择分类 | 娜塔莎/玲可/三月七的额外能力参数没有独立能力声明，原实现没有可消费槽位 |
| `tbgd/lowering.py` | 行迹启动 ability 准入不再限定 EnhancedID，按 OnStart 可执行效果 opcode 逐个准入；新增 `StackStatusResistance` 载荷与覆盖；扩展 `OnTriggerDeath`+`HealHP` 回调准入；控制状态 `Pursued` 追加伤害按运行期表达式准入；能力任务无 `ContextScope` 时默认写入自身能力作用域 | 普通卡行迹启动被错误拒绝；阿兰 A2/A4、控制状态追加伤害缺少正式入口；反击插入能力把动态值误写进状态作用域 |
| `builds/character_assembler.py` | 动态根绑定要求选中项与机制槽绑定一致且机制槽可执行 | 防止未选中或阻断槽位被启动能力借用（fail-closed） |
| `systems/dynamic_values.py` | `character_trace_param_binding_source` 消费 `trace_skill_point_param` 槽，要求可执行且无 blocked_reason | 行迹参数进入正式数值求值 |
| `rules/ability_properties.py`、`systems/unit_stats.py` | `HPConvert` → `hp_convert` 属性桶；max_hp 合成加入该桶；开放消费者校验 | 玲可「生存反应」的 MaxHP 转换公式需要正式属性桶 |
| `systems/status.py` | `_map_stack_property` 映射 `HPConvert`；减益概率按 BehaviorFlag 计算 `behavior_flag_resistance`；状态生命周期事件 ID 增加写入身份后缀 | 阿兰 A4 的 DoT 抵抗进入概率结算；同一事务内多次替换不再撞事件身份 |
| `systems/effect.py` | 实现 `StackStatusResistance` | 行迹/状态启动的正式抵抗来源 |
| `systems/damage.py` | 所有伤害族的前置准入先于格挡副作用：直接伤害走正式 `resolve_scaling_basis`（含额外基准），欢愉复用 `_elation_admission` 的 context 权限/公式/倍率/术语检查，其它族补齐 amount stage、发射与模板条件；`BlockDamageExcludeDot` 格挡复用 `StatusSystem` 生命周期消费，`damage_blocked` 记录携带状态实例与实际伤害请求 | 阿兰 A6 格挡需要正式伤害链实现，且任何不合法请求都不得消耗保护状态或绕过正式 applier 的拒绝语义 |
| `systems/ability.py` | 每次能力调用固定一个 `stable_ability_instance_id`；standalone 伤害的额外倍率求值使用该实例 | 反击插入能力内动态值与伤害读取须落在同一能力作用域；原实现按 `state.event_index` 重算会漂移 |
| `core/model.py`、`systems/unit_stats.py` | `current_max_hp` 直接从 `systems.unit_stats` 解析（出生 `UnitState.max_hp` 保留），不再依赖注册副作用或导入顺序；条件、`hp_ratio`、治疗基准/封顶、比例成本、完整性上限统一消费有效上限 | HPConvert 已进入有效 MaxHP，但原有多处消费者仍读出生面板，且注册式解析会在不同进程给出不同上限 |
| `core/model.py`、`systems/status.py`、`systems/status_callbacks.py`、`core/source_audit.py` | 移除/驱散、自然到期、替换/刷新、减层和 StackProperty 首次追加/原位更新共用 HP 钳制；执行路径生成 `StatusHPClampFact`，审计从事实中的不可变单位复用 `current_max_hp` 重算完整上限，绑定实际生产实例、属性写与唯一原生结算；实际 HP 写触发专用审计；`DispelStatus` 缺省目标按减益处理 | 上限下降不能留下非法 HP；不信任自报上限、不只统计 HPConvert，删标签和联合改写审计副本均不能绕过 |
| `tbgd/lowering.py`、`systems/effect.py`、`systems/ability.py`、`systems/queue.py`、`core/executor.py` | 准入 `OnLimboWaitHeal` 回调任务（能力任务中仅含 ModifierName 与 Add 的 `SetModifierValue` 采纳为一层）；实现 `SetHP`（含 limbo 救援）；新增 `LimboRescueQueueAdmission` 并在规划时复核 typed pending plan/pending_id、原生 limbo-wait 事件、RuleBook 回调/任务/intent 归属、条目字段与源状态实例绑定；排空复用 `plan_entry` + `drain_admitted` 的正式 drain/window/resolution；执行器在同一事务内执行插入能力并校验复活 | 阿兰 E4 需要未决死亡→救援消费→恢复生命→继续行动链；凭据字段存在不等于身份绑定，手工出队不能满足既有队列审计契约 |
| 测试 | `test_character_build_selector_branches.py`、`test_character_eidolon_build_branches.py`、`test_r05_ordinary_party_routes.py`、`test_damage_formula_reconciled_rules.py`、`test_hp_clamp_source_contract.py` | 组件差异、星魂前缀、两条正式路线，以及格挡/击破/完整当前上限/原生 HP 事实/E4 救援身份检查 |

### 3. 固定正式输入与命令

- 路线 A：`examples/cli/r05_arlan_natasha_trace_curriculum.json`（`201010110`，阿兰 80/6/E6
  行迹全选、45% 入场生命；娜塔莎 80/6/E6 行迹全选）及对应
  `.commands.json`（8 条，含双方行动）。
- 路线 B：`examples/cli/r05_lynx_march_survival_counter.json`（`400020800`，玲可 80/6/E6、
  三月七 80/6/E4，行迹全选，初始能量为显式输入）及对应 `.commands.json`（12 条，玲可
  战技→三月七、敌人攻击带护盾的三月七、三月七反击与普攻）。
- 驱动方式：`BattleSession.advance_with_transitions()` + `submit(command_from_json(...))`；
  `RuntimeSourceAuditor.validate_transition` 覆盖入场/启动/技能/反击/波次 transition。
  归档由 `write_archive` 写入临时目录，`replay_archive` 用同一 RuleBook 独立重放。

### 4. 测试与证据

- 命令：`cd /home/zhangjinhao/code/hsr && .venv/bin/python -m pytest
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_character_build_selector_branches.py
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_character_eidolon_build_branches.py
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_r05_ordinary_party_routes.py -m integration`
- 结果：26 项集成检查通过（选择/参数、格挡审计、当前上限与生命周期 16 项；星魂前缀与 E4 救援 8 项；正式路线 2 项）。
- 覆盖：阿兰 A2/A4/A6 与 DoT 概率；娜塔莎 A2/A4/A6 与 HoT 持续；玲可 A2/A4/A6、战技
  转换与星魂 E4/E6；三月七 A2/A4/A6、E2 入场护盾与 E4 反击；星魂选中/未选中、同卡实例
  隔离与跨卡隔离；两条路线逐命令审计、归档与独立 replay。
- 普通回归：`cd /home/zhangjinhao/code/hsr && .venv/bin/python -m pytest -q` 全绿（未选集成）。

### 5. 剩余依赖

- 控制状态的 `Pursued` 追加伤害按通用 additional 族准入；其快照实体（`UseSnapshotEntity`）
  在施放者死亡后的语义未单独建契约，超出本批四卡依赖。
- 路线 A 以 45% 入场生命触发阿兰 A6/A2；阿兰 E1/E2/E3/E5/E6 与三月七 E1/E6 的具体数值分支
  由星魂组件检查与既有启动来源分支覆盖；阿兰 E4 已由正式构筑的原生致死救援检查覆盖。
- 未纳入本批的其它普通角色、增强版、记忆/欢愉、自由召唤物、完整装备目录与特殊关卡维持
  各自批次范围。

## 集中修复与验收（2026-10-26，通过）

用户授权 Codex 直接修复第四轮验收的四处问题；已复查相关生产者、正式调用者和审计分派，
完成修复并集中复验；提交状态见交接。未新增依赖、环境或更新 submodule。

### 修复结果

1. **救援身份不再读取审计 trace**。`LimboRescueQueueAdmission` 从实际 pending 单位的
   状态列表绑定唯一源实例，核对 modifier/owner/active 状态，并保留 typed pending plan、
   原生事件及 RuleBook 的 callback/task/intent 归属检查。清空 trace 后正常准入，联合改写
   凭据与 trace 的不存在实例仍拒绝；JSON 往返后结论一致。任务归属按 `task.callback_id`
   核对，不能要求嵌套救援任务直接列在回调根任务列表中。
2. **专用审计由实际写边界触发**。原生 `StatusHPClampFact`、`status_system` 的实际 HP 写
   或原生钳制结算均进入 HP 专用审计；缺事实、剥离标签或改名结算不能退回通用放行路径。
3. **完整上限复用属性权威重算**。执行路径用不可变的前后 `UnitState` 生成类型化事实，
   审计调用同一 `current_max_hp` 独立重算上限，不再使用自报旧上限加 HPConvert 差值。
   HPConvert、HPDelta、HPAddedRatio 及静态属性池均覆盖；联合改写 metadata、HP 契约、
   mutation 和 settlement 不能改变预期。事实不进入 `Mutation.to_json()`，不改变归档协议。
4. **钳制绑定实际生产实例**。生命周期计划或属性写确定 owner/status/instance/operation；
   配对状态列表须与事实前后列表一致，正式 callback/task/property 归属与唯一原生结算
   完整匹配。错实例、夹带兄弟状态变化及多余结算均拒绝。

### 验证与复用范围

- 入库 `tests/test_hp_clamp_source_contract.py`：**12 项纯组件检查**，覆盖三类上限属性、
  静态属性池、首次追加/原位更新、联合篡改、标签剥离、错实例、兄弟状态、结算唯一性及
  JSON 形状。正式 E4 既有检查补充空 trace、联合伪造与 JSON 往返，不另建正式构筑前置。
- 最终集中命令合跑四轮反例、新组件模块、正式 E4 身份与原生审计检查：
  **47 passed，132.39 s**；墙钟 135.69 s，峰值 **967,824 KiB**，日志
  `/tmp/r05_codex_fix_final.log`。
- 前一批定向验证有 **101 项通过**，包括关联状态/格挡/快照/队列审计检查及玲可／三月七
  正式路线 B 的逐事务审计、归档与 replay；当次另有 5 failed/7 errors，同根为新增的
  “必须直接属于回调根列表”检查误拒嵌套 E4，已删除该过严限制，对应节点在最终命令复验
  通过。该批耗时 359.24 s、峰值 6,794,584 KiB，日志 `/tmp/r05_codex_fix_validation.log`；
  最终复验改为集中必要节点，未再次把多个规则范围与整场路线放入同一进程。
- 路线 B 的通过证据未受最后移除两处根列表限制影响，直接复用；既有路线 A 与其它
  构筑/参数证据按原覆盖范围保留。本轮未重跑全量普通回归或全目录编译。
