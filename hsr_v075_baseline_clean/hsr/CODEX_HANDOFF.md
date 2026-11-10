# v8 当前交接

更新：2026-11-10。当前实现与验收状态只在本文件维护。

## 方向矫正（2026-11-10，用户确认）

原因和决定见[项目目标](simulator_v8_clean_core/PROJECT_GOALS.md#2026-11-10-方向矫正)，路线见
[工程完结路线](simulator_v8_clean_core/P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md#0-工程完结路线)。
终点改为 v1 名单；专属行为可写内容卡的专属处理器；正确性看游戏数值对照，来源审计可开关；
性能是验收项。原 R01–R18 不再是任务清单。

本轮只修改了文档：未改代码、未跑回归、未提交。代码与新方向的差距：

- 尚无内容专属处理器的挂载接口；`systems/effect.py` 的 opcode 注册是通用机制入口，不是内容挂点。
- 尚无任何游戏数值对照。
- 性能远未达预算，见下方基线。

## 当前任务：M1 地基矫正

HEAD `8d6ddc9`；已验收实现基线 `a961e9f`（R06）。TBGD 固定
`14c1d18f91a8101d610e6c523447a7517de3fae1`；依赖和环境未变。

| 项 | 内容 | 状态 |
| --- | --- | --- |
| 用户决定 | 2026-11-10 已定：[v1 名单](simulator_v8_clean_core/P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md#v1-名单)由工程侧选定（18 角色、18 套构筑、11 种敌人、3 类环境，共 50 条）；数值容差 1%、性能预算启动 5 秒与单条命令 0.1 秒先按默认，后续再调；对照实验对象为遐蝶死龙 | 已定 |
| 1 在途改动落点 | R07 在途改动已按现状提交为检查点（见下方“R07 检查点”）；遐蝶死龙、昔涟德谬歌停止通用路径扩展 | 已提交，带 3 失败 5 错误 |
| 2 性能 | 以下方基线为起点，先处理启动指纹，再定位执行期序列化的生产者；核对推演器所需的状态分支能力 | 基线已测 |
| 3 处理器对照实验 | 限时一周，默认遐蝶死龙：用专属处理器做到可公开操作，记录代码量、共享文件改动数与耗时，对比通用路径；同时确立挂载接口 | 未开始 |
| 4 数值对照方法 | 用已打通的路线做出第一组游戏数值对照，固定记录格式 | 未开始 |

v1 进度：0/50。已有路线的条目都还缺数值对照，因此均未计为完成。M1 完成后进入 M2，各项出口见路线文档的[里程碑](simulator_v8_clean_core/P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md#里程碑)。

### 性能基线（2026-11-10）

场景 `examples/cli/arlan_vs_antimatter.json` 与同名 `.commands.json`（阿兰对两只反重子，9 条命令），
`cli run`，系统 `python3` 3.12.3（本检出没有 `.venv`）。

- 冷缓存 2 分 16 秒，热缓存 68 秒；IR 缓存目录 216 MB。
- cProfile（含剖析开销共 143 秒）：会话初始化 62.5 秒，其中 `builds/manifest.py` 的
  `canonical_ir_fingerprint` 53.4 秒（`_update_digest` 约 925 万次；现有身份缓存只在进程内有效）。
  9 次提交 48.5 秒，期间 `json.dumps` 约 202 万次（20.7 秒）、`immutable_json.thaw_json` 约 744 万次（19.9 秒）。
- 距预算：启动约差一个数量级，单条命令差一到两个数量级。后两者按剖析比例估算，未单独计时。

## R07 检查点（2026-11-10 按现状提交，未整包验收）

提交前普通回归加 `bridge_reference` 反例合跑一次：3 failed、5 errors，其余通过，日志 `/tmp/r07_checkpoint_regression_full.log`。未修复，如实保留：

- `test_arlan_action_graph_mvp.py::test_servant_camera_triggers_do_not_block_an_avatar_action_binding`：昔涟忆灵镜头能力未出现在表现集合中。
- `test_r07_shared_mechanism_contract.py` 两项：角色 ID 分组条件返回 None；能力作用域动态值报 `store_schema_invalid`。
- `test_p9_a2_direct_static_context.py` 五项 setup 错误：动作发现守卫在 198 秒耗尽（`direct_action_discovery_guard_exhausted`），未确认是回归还是耗时所致。

这些只在对应名单条目实际依赖时处理；昔涟不在 v1 名单内。

[R07 执行说明](simulator_v8_clean_core/docs/CHARACTER_DERIVED_UNITS_CLOSURE.md)保留原目标供追溯，整包验收已停止。

下表是 2026-11-07 的实现记录与路线观察，改动未提交、未经正式 integration 验收。
已有路线的部分按现状收束；“剩余缺口”一列不再沿通用路径推进，是否完成取决于是否进入 v1 名单。

| 内容 | 已有实现与观察 | 剩余缺口或未验证项 |
| --- | --- | --- |
| 丹恒 / 景元 / 托帕 / 灵砂 | 创建、护盾与换主；龙灵、神君、账账、浮元动作及相关退场已有路线记录 | 丹恒 PointB3/护盾伤害分支、景元/灵砂行迹及 E0 以外未验证；各独有行为仍需准确归属证据 |
| 记忆主（男/女） | 终结技创建忆灵并以忆灵身份出伤，弹射/全体攻击、亡语和主人倒下退场 | 充能满后的指令技能链未单独验证 |
| 长夜月 | 终结技按忆灵生命上限出伤、忆灵连续行动与伤害成长、主人倒下退场 | 第二次终结技与退场后再创建未在最近一轮观察 |
| 阿格莱雅 | 忆灵创建、联合攻击、倒计时退场和技能重召唤已有路线记录 | 核对最终共享改动的影响 |
| 风堇 | 终结技创建忆灵、技能治疗本人与忆灵、重复终结技 | SPD=0 忆灵的链式插入出伤未触发；退出和再次创建仍需核对 |
| 遐蝶 | 正式战况受伤积满新蕊（2000/2000），终结技进入死龙创建 | 创建仍阻断；不可选中、属性重置、生命消耗与循环、伤害、自爆/再创建及 Buff 复制链未完成 |
| 昔涟 | 技能、普攻与附加真伤 | 终结技、德谬歌行动与链接未完成；涉及选择/控制分支、特殊资源与表达式语义 |

已有共享修改涉及点号目标关系、创建时技能参数注入、稳定能力作用域、忆灵削韧来源、
并列时间轴和特殊资源门禁。长夜月终结技修正为读取忆灵生命上限，原先误读主人面板；
这些实现继续复用，正确性随最终差异集中复查。

## 已有修复与验证记录


- 前次审查的五项问题已有修复记录：装备上下文目标准入、敌我判定、命中回调重入事实、
  表现分类和计数许可。组件与反例 **94 passed**，装备闭包 **1 passed**。
  装备此前的 17 图阻断属于本批回归，已有闭包恢复记录，不再列为开工待修项。
- [派生单位路线检查](simulator_v8_clean_core/tests/test_r07_derived_unit_routes.py) 已有 9 项；
  记录为本地替身逐条执行通过，未经正式 pytest integration，不计作正式集成验收通过。
- 先前 **892 项普通回归**记录保留，默认未选 integration，不能代替整包行为与审计验收。
- 死龙、德谬歌与链接不再沿通用路径推进，去向见上方 M1 第 1、3 项。

## 已验收基线


| 范围 | 可用行为与边界 |
| --- | --- |
| R06 光锥与遗器效果（`a961e9f`） | 224 图静态闭包与 162 光锥／58 套遗器／90 阈值证据保留；正式 emission 统一决定最终公式与 indirect 身份。剩余边界：23033 雷遁两次普攻分支、20015 自然行动提前、23041 弱点 +60% 分支为组件证据，路线 B 为定向自然段。见[说明](simulator_v8_clean_core/docs/EQUIPMENT_EFFECTS_AND_BUILD_CLOSURE.md)。 |
| R05 四卡构筑与普通队伍（`b35d0a7`） | 四卡行迹/星魂构筑与普通队伍实战；阿兰 E4 的救援入队/排空、SetHP 救回与 HP 钳制已接通。共享缺口只按四卡实际依赖补齐，未纳入其它普通角色、增强版、装备目录和特殊关卡。见[说明](simulator_v8_clean_core/docs/CHARACTER_BUILD_AND_ORDINARY_PARTY_CLOSURE.md)。 |
| 普通怪物战斗闭环（`516acc8`） | 两类召唤者的关联退场、队列清理、多波与胜负；B 路线 41 条公开命令完成自然死亡、爆炸、主人后死、关系 ForceKill 与胜利，耗时 11 分 15 秒。R16 稳定接口范围的工作台随同验收。见[说明](simulator_v8_clean_core/docs/MONSTER_SUMMON_OWNER_DEATH_CLOSURE.md)。 |
| V3 自然召唤与出生数值 | Stage 307311 的召唤、子行动、子死亡后再召唤与后续提交已接通；卡片作用域及位置不变量已修。出生面板按战斗等级上下文缩放，数值、来源副本及原生结算审计已验收，见[路线说明](simulator_v8_clean_core/docs/MONSTER_SUMMON_NATURAL_ROUTE_CLOSURE.md)与[出生属性任务](simulator_v8_clean_core/docs/MONSTER_SUMMON_STAT_BINDING.md)。 |
| 第二轮性能优化 | 冻结子树共享、内部只读摘要、来源证据容量与目录哈希编码已验收；九步约 27 s，四项集成 48.88 s、88 项快测及 1205 组旧新对照通过。证据与范围见[优化说明](simulator_v8_clean_core/docs/COMPILE_AND_RUNTIME_PROFILE_OPTIMIZATION.md)。 |
| 自动插入行动 | 真实监听阈值→入队→自动战技→清理→后续公开操作已验收；开始/终结 tag 事实、实际等级、BP 免扣与 SPBase 单一回能生产者、取消和晚期回滚受原子边界保护。九步归档独立 replay 19 步 0 错误；限定构筑、命令和剩余边界见[路线说明](simulator_v8_clean_core/docs/SEELE_AUTOMATIC_INSERT_ACTION_ROUTE.md)。 |
| 后置监听行动事实 | 派生通知绑定自身作用域，希儿增强版条件为假的真实监听与四次公开提交可用；89 项定向及 1 项自然路线通过，独立 replay 9 步 0 错误。来源与边界见 [路线说明](simulator_v8_clean_core/docs/SEELE_POST_ATTACK_LISTENER_ROUTE.md)，插入行动真分支见上行。 |
| V2 五元素普通击破 | 火/雷/冰/量子/虚数的首次击破、元素后续效果、自然恢复、同目标二次击破及后续合法行动通过；限定正式构筑、来源波次、普通单韧性和存活施加者，见 [V2 说明](simulator_v8_clean_core/docs/V2_ORDINARY_ELEMENT_BREAK_ROUTES.md)。共享动态值清理、多目标原子合并与差分审计已验收。 |
| I12 逐任务绑定 | 倍率、基准、等级及削韧来源逐任务绑定；继承传播与物化分开，冲突拒绝，常数时间查找。29 项验收通过；继承链包含明确标注的组件输入，不代表完整角色整图。边界见 [I12 契约](simulator_v8_clean_core/docs/archive/completed_tasks/I12_STANDALONE_DAMAGE_BINDING.md)。 |
| I11 真实来源子图 | Phainon 当前回合所有者 Buff 寿命延长、爻光新增状态实例寿命修改、遐蝶限定 InfectModifier 状态复制；生命周期事实与属性审计通过。 |
| I11 完整内容限制 | 爻光 A6 正式构筑启动尚未验证；遐蝶完整忆灵/死龙与整场未验；Phainon 完整 Ultra 仍有其它未准入任务。 |
| V2 风属性普通击破 | 丹恒＋娜塔莎自然完成首次击破、风化、恢复、二次击破和后续行动，并完成回放；仅普通单韧性，配置与固定命令为 `examples/cli/danheng_wind_break_natural{,.commands}.json`。 |
| 已有共享链与路线 | 普通伤害/治疗/护盾、双方外控、任务图与 RNG、限定两波及归档恢复、普通公共环境 full_stage、普通多层韧性，以及阿兰/娜塔莎/希露瓦、三月七、佩拉、阿格莱雅等已记录的限定路线继续复用。 |

以上均按已验证的来源、构筑和行为范围使用。这些验收是执行自洽与来源审计证据，**都还没有做游戏数值对照**；
进入 v1 名单的条目需补对照后才计为完成。逐项验收记录见
[矫正前交接快照](simulator_v8_clean_core/docs/archive/CODEX_HANDOFF_PRE_CORRECTION_2026-11-10.md)。
其它插入类型迁移、注册事件根 TriggerAbility 的行动事实作用域及瓦尔特其它缺口仍待具体内容接线。
详细历史证据按关键词查[归档快照](simulator_v8_clean_core/docs/archive/CODEX_HANDOFF_PRE_SLIM_2026-10-19.md)，
实际命令和检查入口以 CLI 与测试文档为准。

## 已知限制（矫正前的待办清单，不是 v1 任务）


以下是矫正前记录的缺口。只有 v1 名单条目实际依赖的才成为任务，并按成本选择通用机制或专属处理器；
其余只是已知限制。启动时核对当前源码和正式调用者。

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
不因来源齐全就标为“仅待验收”。进度只按 v1 名单条目计量。

## 工作入口

- [CLI 操作与场景](simulator_v8_clean_core/CLI_MVP.md)、[测试入口](simulator_v8_clean_core/tests/README.md)。
- [实施与验证约定](simulator_v8_clean_core/docs/AGENT_WORKFLOW_AND_VALIDATION.md)、[文档索引](simulator_v8_clean_core/DOCUMENTATION_INDEX.md)。
- 矫正前的路线与交接见
  [R01–R18 路线快照](simulator_v8_clean_core/docs/archive/p9/ENGINEERING_ROUTE_R01_R18_PRE_CORRECTION_2026-11-10.md)、
  [交接快照](simulator_v8_clean_core/docs/archive/CODEX_HANDOFF_PRE_CORRECTION_2026-11-10.md)；更早记录见
  [2026-10-19 快照](simulator_v8_clean_core/docs/archive/CODEX_HANDOFF_PRE_SLIM_2026-10-19.md)。
