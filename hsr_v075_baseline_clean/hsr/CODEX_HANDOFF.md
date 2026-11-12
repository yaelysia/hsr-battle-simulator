# v8 当前交接

更新：2026-11-12。当前实现与验收状态只在本文件维护；过程细节不在此累积，按 Git 或归档追溯。

方向（2026-11-10 用户确认）：终点是 [v1 名单](simulator_v8_clean_core/V1_ROUTE.md#v1-名单)；专属行为可写内容专属处理器；正确性看
游戏数值对照；来源审计可开关；性能是验收项。定义见[项目目标](simulator_v8_clean_core/PROJECT_GOALS.md)，里程碑见[路线](simulator_v8_clean_core/V1_ROUTE.md#里程碑)。

## 当前状态

- 本检查点基于 `c26b5d6`；装备范围编译、依赖缓存与可复现身份修正已复核，随本检查点提交。本轮不代表 M1-4 或遐蝶完整机制验收。
- TBGD 固定 `14c1d18f91a8101d610e6c523447a7517de3fae1`。环境：仓库根 uv `.venv`（Python 3.10.12、pytest 9.1.1）。
- **v1 进度 0/50**：没有任何条目取得游戏实测或成熟计算器的对照值。
- 用户已定：名单由工程侧选定；数值容差 1%；性能预算启动 5 秒；单条命令 0.1 秒为目标，
  2026-11-11 接受当前 0.33 秒先收口，推演器实测不足再投入。

| M1 项 | 状态 |
| --- | --- |
| 1 在途改动落点 | 完成。R07 按现状提交为检查点 `e034cd0`，带已知失败（见下） |
| 2 性能 | 基准规则暖加载 1.71 秒、会话初始化 0.44–0.47 秒；单条命令约 0.311 秒，未达 0.1 秒目标。当前及历史操作边界均可免重放分支；磁盘恢复仍先校验重放 |
| 3 处理器对照实验 | 结论已出：单内容专属行为默认走处理器。接口见[架构契约](simulator_v8_clean_core/ARCHITECTURE_BOUNDARY_CONTRACT.md#内容专属处理器)；遐蝶处理器 v0.4.0，剩余分支见下 |
| 4 数值对照方法 | **未收口**。记录格式已固定（[说明](simulator_v8_clean_core/docs/numeric_validation/README.md)）；阿兰两组只做了公式一致性复算，游戏对照待外部输出 |

## 下一步

1. 取得第一组外部对照值（游戏实测或成熟计算器），补进阿兰两份记录，收口 M1-4。
2. 修复两项待修问题（见下），复跑 V2 五元素击破集成和阿兰击破路线。
3. 继续 M2：先基础队 9 人与已有 6 种敌人，再锚点场景敌人，最后召唤与记忆两组。

## 工程收束（2026-11-12）

- 状态长短摘要共用一次序列化和 SHA；动态值默认不重复规划，`HSR_EAGER_IDENTITY_AUDIT=1` 可恢复诊断复核。过期计划检查、不可变状态、原子提交与 RNG 保留。
- 正式规则身份已纠正为内容哈希：冷编译一次计算 Canonical IR 与来源内容指纹，随 IR 在同一受摘要校验的载荷中保存；暖加载/首次会话不重算。绝对路径、时间戳、inode、Python 版本只属于本地失效键，不进入构筑清单的身份字段。此前以缓存键作为规则身份的设计会污染快照/状态摘要，已撤回；归档仍为 v4，旧本地身份归档不保证回放兼容。实际依赖与目录元数据的定向失效机制保留。
- 装备默认按实际构筑与共享池的并集编译，保留所需套装完整成员、词条组、阈值和跨文件能力引用。显式 `include_equipment=True` 仍提供完整目录。固定阿兰装备场景从 162 张光锥/726 个模板/58 套遗器缩至 1/25/2，七步公开选择与 HP/能量/韧性/AV/状态/RNG 均与改动前相等。
- 装备来源查询默认读取原生结算，`audit=True` 才运行整笔审计；会话仍默认精简诊断，审计需 `diagnostics="full"`。遗器完整目录检查与所选范围依赖检查已分开，仅外圈、仅内圈和无光锥构筑不会再被六槽位全目录约束误拒。
- 包入口改为 CLI；运行协议与执行分派中的阶段值改为语义名称，本轮补齐原子提交、行动可用性、波次、召唤、出生及装备目录 schema，并统一目标依赖归属名称。已清理反馈列出的无用导入和多余空行；旧报告中的阶段归属保留。
- 核对生产、测试、UI 与 CI 后移除 221 个历史工具模块、v7 的 92 个文件、model-pack 的 35 个文件、309 份无现行引用的报告及旧 HTML；保留依赖闭包内的 23 个工具。历史从 `c3b3483` 读取。
- 三条遗留测试已修正：角色分组用正式目标别名，动态仓库使用合法空入口。昔涟 `Ready_Camera` 名称仍在固定来源中；其父 `Skill01_VisualPrepare` 被整体识别为表现能力，依赖遍历停止展开，所以不单独生成子镜头 effect。此前“名称随版本变化”的解释错误，测试现核对真实父节点为 audit_only、原始父节点仍引用该镜头，并保留行动准入断言。
- 身份修正后的普通回归 943 passed、165 deselected、19 subtests passed（129.24 秒）；公开精简/完整模式、历史分支/恢复与装备八步操作（含独立 CLI replay）2 passed（110.78 秒）。31 项身份/缓存/归档定向检查验证冷编译只算一次、暖加载不重算、不同目录/时间戳下身份及构筑清单所在快照/摘要一致、规则内容变化则身份改变。上轮装备目录对照与共享池 6 项证据继续保留。
- 缓存验证覆盖未读取文件改动继续命中、读取文件改动（含恢复 mtime）失效、增删/改名失效、冷编译中途变化不发布、缓存不可写回退、解析后的符号链接依赖，以及缓存放在来源子目录时不被自身写入反复失效。证据：`/tmp/hsr_scope_fast.log`、`/tmp/hsr_equipment_scope_tests.log`、`/tmp/hsr_scoped_integration.log`。
- 本轮日志：`/tmp/hsr_portable_identity_tests.log`、`/tmp/hsr_identity_normal.log`、`/tmp/hsr_identity_routes.log`。数值记录新增 Git 提交以区分代码实现；内容指纹不代替代码版本，旧记录不回填新指纹。
- 提交前补齐构造阶段的来源读取：冷编译器在依赖跟踪内创建，避免仅构造器读取的配置漏出清单。组件复现由失败转为通过，缓存/身份/归档合并复验 32 passed（2.81 秒），见 `/tmp/hsr_scope_commit_review.log`；本项未改变战斗执行，复用上述整场证据。

保留边界：冷编译的能力名称索引仍需发现装备能力文件，以定位跨文件引用和歧义；光锥/遗器共享一次发现。目录变化保守失效，尚未精确到每条目录查询。未按行数拆分 lowering，未将不同语义的校验机械合并。`support` 的全目录统计仍是显式诊断功能。

## 待修问题

| 问题 | 现象与影响 |
| --- | --- |
| XP_Minion 被动准入回归 | 8001040/8001050 的 PassiveSkillInitiate OnStart 效果未准入，已验收的 V2 雷击破路线（`arlan_thunder_break_natural`，stage 202110311）入场阻断；疑为 R07 共享改动引入，普通回归不含 integration 所以未被发现。阻塞阿兰击破分支的对照 |
| 队列 staleness | 单位阵亡后其队列条目导致 `queue_actor_unit_defeated` 全候选阻断死锁（通用问题）。已阻断遐蝶再创建集成测试，锚点场景也会依赖 |

## M2 进行中

### 阿兰（avatar:1008），条目未完成

构筑：80 级、P6、E0、满行迹；光锥 23002（80/P6/S1）；外圈 102 四件（15 级）；内圈 302 两件（15 级）；无副词条。
场景：`examples/cli/arlan_lv80_full_traces_two_waves.json`、`arlan_lv80_full_traces_break.json`（stage 1022514）。

| 分支 | 可战斗 | 数值 |
| --- | --- | --- |
| 普攻、战技、终结技 | 是 | 公式复算 8 个事件误差 0%；游戏对照未做 |
| 天赋、行迹、能量与战技点 | 是（归档实证） | 未对照 |
| 装备：23002、102 四件套、302 速度阈值 | 是（入场激活与事件实证） | 未对照 |
| 雷属性击破 | 未验证 | 未对照 |

击破说明：stage 1022514 的敌人没有雷弱点，削韧被跳过是正确的游戏行为，不存在削韧绑定缺口
（2026-11-11 的初判是误诊）。击破验证需要雷弱点关卡，而现成的 V2 雷击破路线被上面的 XP_Minion 回归阻断。
记录：[m2-arlan-…-001](simulator_v8_clean_core/docs/numeric_validation/records/m2-arlan-e0-lv80-p6-full-traces-102-302-23002-001.yaml)。

### 遐蝶（avatar:1407）死龙，处理器 v0.4.0

已通：新蕊积满、终结技创建死龙、死龙行动出伤、辅助吐息（倍率取正式参数绑定，含削韧、击破、多层溢出和攻击前增伤）、
濒死锁血与退场。最近一轮辅助吐息 4 次提交成功，独立回放 97 步无错误。
敌方不可选中已装配：归档中的 `custom_unselectable_teams=[TeamDark]`，共享目标过滤器按敌方队伍拒绝选择，
友方选择不受此标记限制。3 回合到期自爆**未贯通**：最近归档同一死龙经历 4 次自然 turn.begin/end 后仍 active，
未安装寿命状态，出生生命周期为 permanent_until_removed_or_owner_removed；不能沿用旧报告“已覆盖”的结论。
未完成：3 回合寿命与到期自爆、UseSkillOneMore 多次吐息循环、BP 层数倍率、主动自爆按钮、
退场后再创建的自然验证、全部数值对照。
检查入口：`tests/test_content_processor_combat.py`（普通与 integration）、`tests/test_multilayer_toughness.py`、
`tests/test_content_processor_interface.py`。实验报告与接口设计稿已归档：
[报告](simulator_v8_clean_core/docs/archive/completed_tasks/CONTENT_PROCESSOR_EXPERIMENT_REPORT.md)、[设计稿](simulator_v8_clean_core/docs/archive/completed_tasks/CONTENT_PROCESSOR_INTERFACE_DESIGN.md)。

## 性能现状（2026-11-12 复测）

基准：`examples/cli/arlan_vs_antimatter.json` 与同名 `.commands.json`（9 条命令），`.venv/bin/python`，暖缓存、进程内分阶段计时。

- 上一检查点的空装备精简模式基准：规则暖加载 1.71 秒；规则身份解析 0.057 毫秒；会话初始化 0.44–0.47 秒；九条命令 2.72–2.88 秒（中位数 0.311 秒/条）。CLI 模块导入另计。同进程交替恢复旧动态值重规划时为 0.384 秒/条，新路径约少 19%，最终 HP/能量/韧性/RNG 相等；这不是把 cProfile 各项累计时间相加所得的估算。
- 带装备场景首次会话初始化实测 0.96 秒，不再支付首次整树身份计算。上一检查点的历史分支约 1.3 毫秒，本轮未改该路径。
- 本轮装备范围基准：缓存键中位数 0.645→0.091 秒（同进程各三次，约 7 倍）；记录 3,668 个读取文件与 12,675 个目录，替代暖命中逐个枚举约 123,396 个 JSON。目录只 stat，不读取其所有子文件。完整规则加载还包含反序列化、RuleBook 与场景来源处理，不能将缓存键倍数宣称为整场倍数。
- 装备范围优化当时的 `arlan_lv80_full_traces_two_waves`：冷构建 31.09 秒、暖加载 2.55 秒、首次会话 1.37 秒；七条命令逐步结果与 `c26b5d6` 相等，见 `/tmp/hsr_equipment_scope_before.json`、`/tmp/hsr_equipment_scope_final.json`。这些冷构建数字未包含本轮恢复的内容哈希；当前实测冷构建（含内容身份计算）38.79 秒、首次会话 1.03 秒，暖加载无需重算内容哈希，不与空装备基准混比。
- 装备阿兰首条伤害 HP metadata：327,097 → 64,687 字节（约 −80%），输入 9,591 → 5,393 字节；短输入与完整输入结果一致。归档已有对象共享编码，压缩体积未降低：九步约 221/222 KB（完整/精简）；不能将展开的 JSON 体积当成落盘大小。
- 显式 `compile_scope` 池仍支持阿兰单人/阿兰＋娜塔莎切队，合法选择与结算不变；尚未编译全 v1 名单池。装备查询检查本轮包含一次冷编译 35.96 秒，与暖加载分开记录。
- 本轮未达 0.1 秒目标。当前测量为 `/tmp/hsr_cleanup2_performance.json`；旧 `/tmp/hsr_cleanup_performance.json` 属于上一检查点。移出五项真实目录检查后普通回归从约 211 秒降至约 130 秒，这是测试分层收益，不冒充内核运算加速。

## R07 检查点里各角色的状态

`e034cd0` 提交时未经整包验收。“剩余”一列不再沿通用路径推进，进入名单的角色按处理器路径完成；昔涟不在名单内。

| 内容 | 已有实现与观察 | 剩余缺口或未验证项 |
| --- | --- | --- |
| 丹恒 / 景元 / 托帕 / 灵砂 | 创建、护盾与换主；龙灵、神君、账账、浮元动作及相关退场已有路线记录 | 丹恒 PointB3/护盾伤害分支、景元/灵砂行迹及 E0 以外未验证；各独有行为仍需准确归属证据 |
| 记忆主（男/女） | 终结技创建忆灵并以忆灵身份出伤，弹射/全体攻击、亡语和主人倒下退场 | 充能满后的指令技能链未单独验证 |
| 长夜月 | 终结技按忆灵生命上限出伤、忆灵连续行动与伤害成长、主人倒下退场 | 第二次终结技与退场后再创建未在最近一轮观察 |
| 阿格莱雅 | 忆灵创建、联合攻击、倒计时退场和技能重召唤已有路线记录 | 核对最终共享改动的影响 |
| 风堇 | 终结技创建忆灵、技能治疗本人与忆灵、重复终结技 | SPD=0 忆灵的链式插入出伤未触发；退出和再次创建仍需核对 |
| 遐蝶 | 创建、出伤、敌方不可选中和单次辅助吐息已有实现与证据，详见上方当前状态 | 3 回合到期自爆、多次吐息/BP、主动自爆、再创建自然验证与数值对照仍未完成；不按旧报告推断已覆盖 |
| 昔涟 | 技能、普攻与附加真伤 | 终结技、德谬歌行动与链接未完成；涉及选择/控制分支、特殊资源与表达式语义 |

## 已验收基线

以下都是矫正前验收的行为范围，证据是执行自洽与来源审计，**都没有做游戏数值对照**；对应的任务说明已归档。

| 范围 | 可用行为与边界 |
| --- | --- |
| R06 光锥与遗器效果（`a961e9f`） | 224 图静态闭包与 162 光锥／58 套遗器／90 阈值证据保留；正式 emission 统一决定最终公式与 indirect 身份。剩余边界：23033 雷遁两次普攻分支、20015 自然行动提前、23041 弱点 +60% 分支为组件证据，路线 B 为定向自然段。见[说明](simulator_v8_clean_core/docs/archive/completed_tasks/EQUIPMENT_EFFECTS_AND_BUILD_CLOSURE.md)。 |
| R05 四卡构筑与普通队伍（`b35d0a7`） | 四卡行迹/星魂构筑与普通队伍实战；阿兰 E4 的救援入队/排空、SetHP 救回与 HP 钳制已接通。共享缺口只按四卡实际依赖补齐，未纳入其它普通角色、增强版、装备目录和特殊关卡。见[说明](simulator_v8_clean_core/docs/archive/completed_tasks/CHARACTER_BUILD_AND_ORDINARY_PARTY_CLOSURE.md)。 |
| 普通怪物战斗闭环（`516acc8`） | 两类召唤者的关联退场、队列清理、多波与胜负；B 路线 41 条公开命令完成自然死亡、爆炸、主人后死、关系 ForceKill 与胜利，耗时 11 分 15 秒。R16 稳定接口范围的工作台随同验收。见[说明](simulator_v8_clean_core/docs/archive/completed_tasks/MONSTER_SUMMON_OWNER_DEATH_CLOSURE.md)。 |
| V3 自然召唤与出生数值 | Stage 307311 的召唤、子行动、子死亡后再召唤与后续提交已接通；卡片作用域及位置不变量已修。出生面板按战斗等级上下文缩放，数值、来源副本及原生结算审计已验收，见[路线说明](simulator_v8_clean_core/docs/archive/completed_tasks/MONSTER_SUMMON_NATURAL_ROUTE_CLOSURE.md)与[出生属性任务](simulator_v8_clean_core/docs/archive/completed_tasks/MONSTER_SUMMON_STAT_BINDING.md)。 |
| 第二轮性能优化 | 冻结子树共享、内部只读摘要、来源证据容量与目录哈希编码已验收；九步约 27 s，四项集成 48.88 s、88 项快测及 1205 组旧新对照通过。证据与范围见[优化说明](simulator_v8_clean_core/docs/archive/completed_tasks/COMPILE_AND_RUNTIME_PROFILE_OPTIMIZATION.md)。 |
| 自动插入行动 | 真实监听阈值→入队→自动战技→清理→后续公开操作已验收；开始/终结 tag 事实、实际等级、BP 免扣与 SPBase 单一回能生产者、取消和晚期回滚受原子边界保护。九步归档独立 replay 19 步 0 错误；限定构筑、命令和剩余边界见[路线说明](simulator_v8_clean_core/docs/archive/completed_tasks/SEELE_AUTOMATIC_INSERT_ACTION_ROUTE.md)。 |
| 后置监听行动事实 | 派生通知绑定自身作用域，希儿增强版条件为假的真实监听与四次公开提交可用；89 项定向及 1 项自然路线通过，独立 replay 9 步 0 错误。来源与边界见 [路线说明](simulator_v8_clean_core/docs/archive/completed_tasks/SEELE_POST_ATTACK_LISTENER_ROUTE.md)，插入行动真分支见上行。 |
| V2 五元素普通击破 | 火/雷/冰/量子/虚数的首次击破、元素后续效果、自然恢复、同目标二次击破及后续合法行动通过；限定正式构筑、来源波次、普通单韧性和存活施加者，见 [V2 说明](simulator_v8_clean_core/docs/archive/completed_tasks/V2_ORDINARY_ELEMENT_BREAK_ROUTES.md)。共享动态值清理、多目标原子合并与差分审计已验收。 |
| I12 逐任务绑定 | 倍率、基准、等级及削韧来源逐任务绑定；继承传播与物化分开，冲突拒绝，常数时间查找。29 项验收通过；继承链包含明确标注的组件输入，不代表完整角色整图。边界见 [I12 契约](simulator_v8_clean_core/docs/archive/completed_tasks/I12_STANDALONE_DAMAGE_BINDING.md)。 |
| I11 真实来源子图 | Phainon 当前回合所有者 Buff 寿命延长、爻光新增状态实例寿命修改、遐蝶限定 InfectModifier 状态复制；生命周期事实与属性审计通过。 |
| I11 完整内容限制 | 爻光 A6 正式构筑启动尚未验证；遐蝶完整忆灵/死龙与整场未验；Phainon 完整 Ultra 仍有其它未准入任务。 |
| V2 风属性普通击破 | 丹恒＋娜塔莎自然完成首次击破、风化、恢复、二次击破和后续行动，并完成回放；仅普通单韧性，配置与固定命令为 `examples/cli/danheng_wind_break_natural{,.commands}.json`。 |
| 已有共享链与路线 | 普通伤害/治疗/护盾、双方外控、任务图与 RNG、限定两波及归档恢复、普通公共环境 full_stage、普通多层韧性，以及阿兰/娜塔莎/希露瓦、三月七、佩拉、阿格莱雅等已记录的限定路线继续复用。 |

## 已知限制（不是 v1 任务，名单条目依赖时才处理）

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

## 规则待定

| 项目 | 当前处理 |
| --- | --- |
| I1 救援消费时点 | 白露/杰帕德来源确认经插入队列救回，但相对致命单击、整段攻击或完整技能的消费时点未确认；先补可区分依据，再实施该路径。 |
| I6 同类控制抵抗叠加 | 同 STAT_CTRL 多来源仍拒绝；已有资料不能区分其加算/乘算，无新直接证据不重复搜索。 |
| 施加者死亡/移除后的 DOT 属性 | 活体施加者实时属性已通；死亡后的属性保留规则待补，不擅自改成施加时锁面板。 |
| 护盾上限 | 护盾加成是否影响叠盾上限、上限降低后如何处理，仍待适用规则。 |
| 其它来源缺省及条件循环 | R06 已接通缺省 HealByHealerAttack 与行动延迟 Add；其它缺省和依赖运行状态的条件循环按实际未覆盖内容归因，不重复立项已完成形状。 |

## 入口

- [CLI 操作与场景](simulator_v8_clean_core/CLI_MVP.md)、[测试入口](simulator_v8_clean_core/tests/README.md)、[实施与验证约定](simulator_v8_clean_core/docs/AGENT_WORKFLOW_AND_VALIDATION.md)、[文档索引](simulator_v8_clean_core/DOCUMENTATION_INDEX.md)。
- 历史交接快照：[2026-11-12 整理前](simulator_v8_clean_core/docs/archive/CODEX_HANDOFF_PRE_TIDY_2026-11-12.md)、[2026-11-10 矫正前](simulator_v8_clean_core/docs/archive/CODEX_HANDOFF_PRE_CORRECTION_2026-11-10.md)、[2026-10-19](simulator_v8_clean_core/docs/archive/CODEX_HANDOFF_PRE_SLIM_2026-10-19.md)。
