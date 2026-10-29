# v8 当前交接

更新：2026-10-29。只维护当前状态、已验收基线、阻断和下一步；更新时替换对应条目。

## 当前状态

- 主线：`simulator_v8_clean_core`；用户调度 dsh / DeepSeek，Codex 负责完整任务文档与集中验收。
- 已验收实现基线：`a961e9f`（R06 装备效果、治疗/快照事实、最终公式与原生附伤结算审计）；R05 `b35d0a7`、普通怪物与工作台 `516acc8` 继续保留。
- TBGD 固定指针：`14c1d18f91a8101d610e6c523447a7517de3fae1`；本批未新增依赖或环境。
- 当前主线：R06 已验收提交；进入 R07 角色派生单位整包，执行说明已准备。未推送。

## 当前批次：R07 角色派生单位（待实现）

执行入口：[完整范围、调用链、一次性约束与验证节奏](simulator_v8_clean_core/docs/CHARACTER_DERIVED_UNITS_CLOSURE.md)。
从 `a961e9f` 连续完成六个忆灵及其主人构筑、可行动伙伴/战斗事件、联合/指令行动与完整退场再创建。
已核对固定来源六个忆灵定义、角色事件创建关系，以及现有战斗事件仅支持被动倒计时的边界；
助手 raw 协议无实际消费者时不另造实现。完整父形态和活动环境仍按原包归属，实际必需的共享缺口就地补齐。
按四组行为路线组织必要验证，复用定向规则与已有证据，整包冻结交回；本轮准备未运行真实编译或整场。

## 最近收口：R06 光锥与遗器完整效果（已验收提交）

执行入口与交付表：[最终复审修复与复验](simulator_v8_clean_core/docs/EQUIPMENT_EFFECTS_AND_BUILD_CLOSURE.md#最终复审修复与复验2026-10-28通过)。
224 图静态闭包、162 光锥／58 套遗器／90 阈值证据保留。正式 emission 统一决定最终公式与
indirect 身份；普通间接附伤正例通过，缺失或损坏的原生结算被拒绝。
Codex 源码复查及四个复验入口、永久回归合跑 **78 passed，27.74 s**（墙钟 30.72 s，
峰值 891,928 KiB），日志 `/tmp/r06_final_acceptance.log`；本轮未发现新的可操作问题。
实现方常规、elation／remodifier／装备闭包及 A／B／C、R05 公开路线证据按影响范围复用，未重复整场或全量回归。
剩余边界：23033 雷遁两次普攻分支、20015 自然行动提前、23041 弱点 +60% 分支（组件证据）、
路线 B 为定向自然段。已随 `a961e9f` 提交，未推送；未新增依赖／环境，未改 submodule。

## 最近收口：R05 四卡构筑与普通队伍战斗（已验收提交）

执行入口：[完整范围与结果](simulator_v8_clean_core/docs/CHARACTER_BUILD_AND_ORDINARY_PARTY_CLOSURE.md#结果2026-10-24)；
本轮结论见同文件[集中修复与验收](simulator_v8_clean_core/docs/CHARACTER_BUILD_AND_ORDINARY_PARTY_CLOSURE.md#集中修复与验收2026-10-26通过)。
救援准入改为核对实际源状态、typed pending plan 与 RuleBook 归属，不再读取 source_trace。
HP 钳制由执行路径生成 `StatusHPClampFact`，审计复用 `current_max_hp` 重算完整前后上限，
绑定实际状态实例与属性写；实际 HP 写及原生结算触发专用审计，删标签不能绕过。
事实不进入 mutation JSON，保留既有归档协议。新增 12 项纯组件检查，并扩展正式 E4 检查，
覆盖空 trace、联合伪造及 JSON 往返。最终四轮反例、入库检查与正式 E4 合跑
**47 passed，132.39 s，峰值 967,824 KiB**，日志 `/tmp/r05_codex_fix_final.log`。
其余关联检查及玲可／三月七路线 B 的逐事务审计、归档与 replay 已通过，按未受最后修正
影响的范围复用证据；最后集中修复未跑全量。已随 `b35d0a7` 提交，未推送。
共享缺口只按四卡实际依赖补齐，未纳入其它普通角色/增强版/装备目录/特殊关卡。
P9 总路线中的其它机制仍保留原归属。

## 最近收口：普通怪物战斗闭环（已验收并提交）

实现提交 `516acc8`；范围、原生路线与保留边界见
[普通怪物执行说明](simulator_v8_clean_core/docs/MONSTER_SUMMON_OWNER_DEATH_CLOSURE.md)。

### 集中验收状态

- Codex 已完成相关源码、正式调用者、取消/原子边界及原生审计复查；入库 16 项、全部历史反例与相关检查合跑 124 项通过、4 项集成未选，`git diff --check` 通过；本轮未发现新的可操作问题。
- 验收确认：失败身份的 Revivable/limbo 隔离、完整队列差分与原位过渡、正式 dequeue 准入及移除身份、ForceKill 清理因果均通过；原生结算中的完整 resolution 与 RuleBook `to_json()` 严格相等，缺失/替换/篡改均拒绝。实现方 169 项定向及 A/C 各 1 项集成证据保留，本轮复用既有整场/replay，未修改生产代码。详见[集中验收结论](simulator_v8_clean_core/docs/MONSTER_SUMMON_OWNER_DEATH_CLOSURE.md#集中验收状态2026-10-24已通过)。
- 新 B：41 条公开命令完成首鱼自然死亡→同死亡实例许可/清理→自身 MaxHP × 正式 0.4 参数爆炸→实际减防→主人在余鱼存活时后死→关系 ForceKill→余鱼自身死亡插入→胜利。每笔事务过 RuntimeSourceAuditor；集成与独立 replay 通过，含终局拒绝检查的归档为 84 步、0 错误，耗时 11:15.31。
- A/C/D 复用原生实战/回放证据；旧 77 项受影响检查及 669 项普通回归仅作历史底座，本轮未重新跑全量。旧目标 HP 基准的 B 归档已作废，不能替代当前证据。
- R16 稳定接口范围及六文件已独立验收，随 `516acc8` 提交；UI 普通检查 14 项、客户端与错误交互检查通过，两场真实浏览器/下载恢复证据已收取。旧缺参 fixture 一行修复的相关 29 项通过；其余内容接入后的完整工作台仍按 R16 范围推进。

## 最近收口：召唤出生数值（已验收并提交）

范围、来源口径、实现与验证见
[召唤出生属性任务](simulator_v8_clean_core/docs/MONSTER_SUMMON_STAT_BINDING.md#本批交付)。
要点：召唤任务未声明独立难度，卡片 `MonsterConfig.HardLevelGroup` 全表默认为 1；
有效等级、HardLevelGroup 与 EliteGroup 改为从当前战斗的关卡波次策略解析，卡片默认值只留证据。
Lv44 子单位出生面板由 120.9/18/210/83/60 修正为 2629.437174/231.759936/639.99999/83/60，
AV 仍为 10000/83；缺上下文或召唤者等级不一致时整笔召唤 fail-closed。
出生记录含有效等级/难度、选中行、倍率、profile base 与结果；Codex 两轮复查共 6 处 P2 已加固：
出生审计由实际 spawn 与正式 `intent → entry → 模板` 驱动（标签缺失/不一致拒绝，servant 必须解析到
可执行的 ServantDefinitionIR），按元数据、单位 flags 与原生结算计划逐项核对，来源行与上下文副本
按嵌套路径比较，结算计划必须来自 `summon_transition`/`summon_system` 生产者。伤害门禁要求可执行
等级缩放。10 个篡改反例已迁入仓库测试。
示例与 16 步公开自然链已更新，独立 replay 0 错误。
Codex 本轮完成审计差异与生产者/消费者复查，出生属性模块 14 项（含 10 个入库反例）、
合法结算重关联与 servant 出生 2 项通过；自然链与独立 replay 复用本批已有证据。
交付的基线对照记录保留：非集成回归 637 通过、28 项 `_build_graph()` 缺参失败；另有 4 项
字符/编译集成失败，均已在 `7ff13e3` 复现，本轮未重复全量检查。
剩余：非中性卡片 EliteGroup 的叠加口径与无 stage/wave 身份战场的 fail-closed。
召唤者死亡后的 `MCommon_Servant → Common_Servant_Forcekill` 与清场已由当前 R01 完成。

## 已验收基线

| 范围 | 可用行为与边界 |
| --- | --- |
| V3 自然召唤与出生数值 | Stage 307311 的召唤、子行动、子死亡后再召唤与后续提交已接通；卡片作用域及位置不变量已修。出生面板按战斗等级上下文缩放，数值、来源副本及原生结算审计已验收，见[路线说明](simulator_v8_clean_core/docs/MONSTER_SUMMON_NATURAL_ROUTE_CLOSURE.md)与[出生属性任务](simulator_v8_clean_core/docs/MONSTER_SUMMON_STAT_BINDING.md)。 |
| 第二轮性能优化 | 冻结子树共享、内部只读摘要、来源证据容量与目录哈希编码已验收；九步约 27 s，Codex 四项集成 48.88 s、88 项快测及 1205 组旧新对照通过。证据与范围见[优化说明](simulator_v8_clean_core/docs/COMPILE_AND_RUNTIME_PROFILE_OPTIMIZATION.md)。 |
| 自动插入行动 | 真实监听阈值→入队→自动战技→清理→后续公开操作已验收；开始/终结 tag 事实、实际等级、BP 免扣与 SPBase 单一回能生产者、取消和晚期回滚受原子边界保护。九步归档独立 replay 19 步 0 错误；限定构筑、命令和剩余边界见[路线说明](simulator_v8_clean_core/docs/SEELE_AUTOMATIC_INSERT_ACTION_ROUTE.md)。 |
| 后置监听行动事实 | 派生通知绑定自身作用域，希儿增强版条件为假的真实监听与四次公开提交可用；Codex 89 项定向及 1 项自然路线通过，独立 replay 9 步 0 错误。来源与边界见 [路线说明](simulator_v8_clean_core/docs/SEELE_POST_ATTACK_LISTENER_ROUTE.md)，插入行动真分支见上行。 |
| V2 五元素普通击破 | 火/雷/冰/量子/虚数的首次击破、元素后续效果、自然恢复、同目标二次击破及后续合法行动通过；限定正式构筑、来源波次、普通单韧性和存活施加者，见 [V2 说明](simulator_v8_clean_core/docs/V2_ORDINARY_ELEMENT_BREAK_ROUTES.md)。共享动态值清理、多目标原子合并与差分审计已验收。 |
| I12 逐任务绑定 | 倍率、基准、等级及削韧来源逐任务绑定；继承传播与物化分开，冲突拒绝，常数时间查找。29 项验收通过；继承链包含明确标注的组件输入，不代表完整角色整图。边界见 [I12 契约](simulator_v8_clean_core/docs/archive/completed_tasks/I12_STANDALONE_DAMAGE_BINDING.md)。 |
| I11 真实来源子图 | Phainon 当前回合所有者 Buff 寿命延长、爻光新增状态实例寿命修改、遐蝶限定 InfectModifier 状态复制；生命周期事实与属性审计通过。 |
| I11 完整内容限制 | 爻光 A6 正式构筑启动尚未验证；遐蝶完整忆灵/死龙与整场未验；Phainon 完整 Ultra 仍有其它未准入任务。 |
| V2 风属性普通击破 | 丹恒＋娜塔莎自然完成首次击破、风化、恢复、二次击破和后续行动，并完成回放；仅普通单韧性，配置与固定命令为 `examples/cli/danheng_wind_break_natural{,.commands}.json`。 |
| 已有共享链与路线 | 普通伤害/治疗/护盾、双方外控、任务图与 RNG、限定两波及归档恢复、普通公共环境 full_stage、普通多层韧性，以及阿兰/娜塔莎/希露瓦、三月七、佩拉、阿格莱雅等已记录的限定路线继续复用。 |

以上均按已验证的来源、构筑和行为范围使用，不代表全角色、全装备或全部整场已通过。
其它插入类型迁移、注册事件根 TriggerAbility 的行动事实作用域及瓦尔特其它缺口仍待具体内容接线。
详细历史证据按关键词查[归档快照](simulator_v8_clean_core/docs/archive/CODEX_HANDOFF_PRE_SLIM_2026-10-19.md)，
实际命令和检查入口以 CLI 与测试文档为准。

## 后续待办

启动相应任务时核对当前源码和正式调用者；以下条目不代替具体内容的准入与执行检查。

| 编号 | 剩余范围 |
| --- | --- |
| I1 | R05 已接通阿兰 E4 的 pending 身份、正式救援入队/排空、SetHP 救回与来源审计；白露/杰帕德等其它救援内容及其消费时点仍须按实际来源核定，见下表。 |
| I2 | 欢愉攻击者与属性源分离、其它特殊开关/倍率及完整阶段编排；已有基础链和限定爻光附伤继续复用。 |
| I3 | 特殊关卡模板、评分、副关卡及额外胜负条件；普通公共环境 full_stage 已有证据。 |
| I5 | 其它免疫通知、多个保护竞争、零基础概率及强制控制覆盖顺序；单保护的限定回调已通。 |
| I7 | 共享同步 TriggerBreak、RedStance 虚韧性及其它非普通强制形态；普通多层不重复实现。 |
| I8 | 确实影响战斗顺序的动态/嵌套并行屏障、超出父动作目标范围等；当前固定根并行范围继续复用。 |
| I9 | R06 已接通真实治疗 mutation 的 OnSnapshotCreate 事实与正式传输；其它快照只按实际内容依赖补生产者，出生事件与普通导出不能代替。 |
| I10 | 既有双 mute 及本批非 mute + AbortUnusedInsertAbility 之外的退场形态；半 mute 与未准入组合继续阻断。 |
| I11 余项 | 其它/组合 StatusTypeMask、寿命 Set/减少、其它 InfectModifier 变体及尚未接通的精准实例操作。 |
| V1 | R16 稳定接口范围的浏览器点击、导入/下载恢复已验收；后续内容接入后的完整工作台验证仍待完成。 |
| V3 | 两类普通召唤者的关联退场、多波与胜负闭环已验收；剩余为非中性 EliteGroup、未采用动作（如 201301002/FatigueRatio）、评分成就、未采纳位置类型、配置分歧及完整 Rogue 环境。 |

## 规则待定与待归因

| 项目 | 当前处理 |
| --- | --- |
| I1 救援消费时点 | 白露/杰帕德来源确认经插入队列救回，但相对致命单击、整段攻击或完整技能的消费时点未确认；先补可区分依据，再实施该路径。 |
| I6 同类控制抵抗叠加 | 同 STAT_CTRL 多来源仍拒绝；已有资料不能区分其加算/乘算，无新直接证据不重复搜索。 |
| 施加者死亡/移除后的 DOT 属性 | 活体施加者实时属性已通；死亡后的属性保留规则待补，不擅自改成施加时锁面板。 |
| 护盾上限 | 护盾加成是否影响叠盾上限、上限降低后如何处理，仍待适用规则。 |
| 其它来源缺省及条件循环 | R06 已接通缺省 HealByHealerAttack 与行动延迟 Add；其它缺省和依赖运行状态的条件循环按实际未覆盖内容归因，不重复立项已完成形状。 |

未正式编译或执行的角色、构筑、怪物阶段、特殊死亡/分摊/转换等按实际依赖归因，
不因来源齐全就标为“仅待验收”，不以目录覆盖数量估算成品完成率。

## 工作入口

- [CLI 操作与场景](simulator_v8_clean_core/CLI_MVP.md)、
  [测试入口](simulator_v8_clean_core/tests/README.md)。
- [实施与验证约定](simulator_v8_clean_core/docs/AGENT_WORKFLOW_AND_VALIDATION.md)、
  [文档索引](simulator_v8_clean_core/DOCUMENTATION_INDEX.md)。
- 长期目标见[工程完结路线](simulator_v8_clean_core/P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md#0-工程完结路线)；
  旧检查点、规则依据和逐轮记录见[历史快照](simulator_v8_clean_core/docs/archive/CODEX_HANDOFF_PRE_SLIM_2026-10-19.md)。
