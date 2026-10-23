# v8 当前交接

更新：2026-10-23。只维护当前状态、已验收基线、阻断和下一步；更新时替换对应条目。

## 当前状态

- 主线：`simulator_v8_clean_core`；实现固定交给 dsh / DeepSeek，Codex 负责范围、约束与验收。
- 最近已提交基线：本次召唤出生数值提交；父提交 `7ff13e3`，含已验收性能优化 `b1f42db`。
- TBGD 固定指针：`14c1d18f91a8101d610e6c523447a7517de3fae1`；本批未新增依赖或环境。
- 当前主线：召唤单位有效等级/难度属性已通过 Codex 集中验收，随本提交收口；下一批待准备。

## 本批交付（已验收，随本提交收口）

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
剩余：非中性卡片 EliteGroup 的叠加口径、无 stage/wave 身份战场的 fail-closed、
召唤者死亡后的 `MCommon_Servant → Common_Servant_Forcekill` 与清场仍待后续批次。

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
| I1 | 排队救援的 pending 身份、limbo 队列权限、HealHP/SetHP 与跨交易审计未接通；普通致死已闭环。当前救援队列路径以 `limbo_queue_rescue_not_connected` 拒绝，消费时点见下表。 |
| I2 | 欢愉攻击者与属性源分离、其它特殊开关/倍率及完整阶段编排；已有基础链和限定爻光附伤继续复用。 |
| I3 | 特殊关卡模板、评分、副关卡及额外胜负条件；普通公共环境 full_stage 已有证据。 |
| I5 | 其它免疫通知、多个保护竞争、零基础概率及强制控制覆盖顺序；单保护的限定回调已通。 |
| I7 | 共享同步 TriggerBreak、RedStance 虚韧性及其它非普通强制形态；普通多层不重复实现。 |
| I8 | 确实影响战斗顺序的动态/嵌套并行屏障、超出父动作目标范围等；当前固定根并行范围继续复用。 |
| I9 | OnSnapshotCreate 正式事件生产者；出生事件与普通 snapshot 导出不能代替。 |
| I10 | battle_event/servant 双 mute 退场之外的 ForceKill 形态。 |
| I11 余项 | 其它/组合 StatusTypeMask、寿命 Set/减少、其它 InfectModifier 变体及尚未接通的精准实例操作。 |
| V1 | 工作台真实浏览器点击、布局、导入/下载；已有 HTTP/客户端检查不代替浏览器验收。 |
| V3 | 出生数值批次已验收并随本提交收口；后续为召唤者死亡监听/强制退场队列/清场、非中性卡片 EliteGroup 口径、评分与成就、未采纳位置类型、灰熊等配置分歧及完整 Rogue 环境。 |

## 规则待定与待归因

| 项目 | 当前处理 |
| --- | --- |
| I1 救援消费时点 | 白露/杰帕德来源确认经插入队列救回，但相对致命单击、整段攻击或完整技能的消费时点未确认；先补可区分依据，再实施该路径。 |
| I6 同类控制抵抗叠加 | 同 STAT_CTRL 多来源仍拒绝；已有资料不能区分其加算/乘算，无新直接证据不重复搜索。 |
| 施加者死亡/移除后的 DOT 属性 | 活体施加者实时属性已通；死亡后的属性保留规则待补，不擅自改成施加时锁面板。 |
| 护盾上限 | 护盾加成是否影响叠盾上限、上限降低后如何处理，仍待适用规则。 |
| 其它来源缺省及条件循环 | 部分百分比治疗公式、行动延迟操作缺省仍待依据；依赖运行状态推进的条件循环需按实际内容归因。 |

未正式编译或执行的角色、构筑、怪物阶段、特殊死亡/分摊/转换等按实际依赖归因，
不因来源齐全就标为“仅待验收”，不以目录覆盖数量估算成品完成率。

## 工作入口

- [CLI 操作与场景](simulator_v8_clean_core/CLI_MVP.md)、
  [测试入口](simulator_v8_clean_core/tests/README.md)。
- [实施与验证约定](simulator_v8_clean_core/docs/AGENT_WORKFLOW_AND_VALIDATION.md)、
  [文档索引](simulator_v8_clean_core/DOCUMENTATION_INDEX.md)。
- 长期目标见[工程完结路线](simulator_v8_clean_core/P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md#0-工程完结路线)；
  旧检查点、规则依据和逐轮记录见[历史快照](simulator_v8_clean_core/docs/archive/CODEX_HANDOFF_PRE_SLIM_2026-10-19.md)。
