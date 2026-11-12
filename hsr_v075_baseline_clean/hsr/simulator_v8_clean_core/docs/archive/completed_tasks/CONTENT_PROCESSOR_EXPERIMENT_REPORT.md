# M1-3 内容专属处理器对照实验报告

> **已归档（2026-11-12）**：实验已结束，结论与接口已写入[架构契约](../../../ARCHITECTURE_BOUNDARY_CONTRACT.md#内容专属处理器)，遐蝶的现状在[交接](../../../../CODEX_HANDOFF.md)。
> 注意第 3、5 节中“吐息执行 6 次”等探针 v5 的证据已被第 9 节撤销（把回退普攻误记为吐息），以第 9 节为准。

日期：2026-11-11。实验对象：遐蝶死龙（用户指定默认对象）。限时一周。
执行：processor-experiment（侦察/接口/处理器 v0.1.0–v0.2.0）+ lead（评审、contract 层旁路修复、复查后 v0.3.0 修复与验证）。

**复查纠正（2026-11-11 晚）**：初版报告的"吐息端到端验证"是误判——探针 v5 归档中 6 次
1140711 请求全部失败（辅助动作 ParamList 只有 1 个元素，处理器却要求 2 个），探针回退到
1140701 普攻；报告把 emission ID 含 "11407" 的伤害（实为普攻）误计为吐息。验证方法错误：
未核实提交动作本身成功。Codex 复查提出 5 项问题（P1×2、P2×3），已全部修复，见 §9。

## 1. 实验问题

名单内只有一个内容使用的专属行为，写内容卡专属处理器是否比扩展通用编译器/内核更省？
同时确立处理器挂载接口与书写约定（架构契约第 5 节留白）。

## 2. 结论

**处理器路径显著更省，建议作为名单内单内容专属行为的默认接入方式。**
多个名单内容共用的行为仍扩展通用机制一次；现有通用机制能表达的继续声明式装配。

## 3. 投入对比

| 路径 | 投入 | 结果 |
| --- | --- | --- |
| 通用路径（R07 检查点 e034cd0） | 90 文件 +15753/-1505，数周，覆盖 10 个派生单位角色 | 死龙创建/行动/退场已通；吐息（UseSkillOneMore）与主动自爆（bounce）仍被编译图覆盖阻断，继续扩展需为单角色新增 opcode 与领域支持 |
| 处理器路径（本实验） | 新文件约 1600 行（content_hooks + 目录 + castorice + 测试）；共享文件 6 个（rulebook/executor/event_dispatch/action_availability/battle_catalog/session）；约一天 + 复查修复半天 | 挂载接口确立；v0.3.0 吐息经正式参数绑定 + L1 伤害/削韧结算（复查修复后，严格验证见 §9）；再创建清理安全网装配 |

## 4. 挂载接口（已落地，契约第 5 节同步更新）

- 装配：`content_processors/` 目录（L2 数据，键=entity_ref）→ `mount_catalog` 只挂载 IR 中实际存在的内容；
  `build_battle_rulebook` 末尾统一装配；RuleBook 携带排序后的 MountedProcessor（content_id + version）。
- 挂点：H1 动作执行（通用 preflight 后；takeover=False 前置清理 / True 整段替换效果段，通用 trigger window 仍触发）；
  H2 事件监听（监听器分派后，同一 dispatch 通道与去重，深度上限 8）；H4 可用性过滤。
- 分派：按单位自身 template_id 字典查找，content_id 排序，在场门禁；内核无名称/固定 ID 分支。
- 图覆盖旁路：处理器 claims_action 命中的动作，仅跳过枚举的编译图覆盖类阻断
  （`GRAPH_COVERAGE_BLOCK_PREFIXES`：task_graph_* / effect_coverage_* / bounce_not_executable /
  condition_not_executable / damage_emission_scaling_ratio_not_runtime_bound / process_only_task_coverage_mismatch），
  availability 与 executor 的 contract 层与 event/binding 层共用同一枚举；目标/资源/生命周期/控制门禁一律照常。
- 输出：HookResult 只含类型化 mutations/events/rng_events/records；ProcessorServices 门面包装 L1 系统
  （SummonSystem/StatusSystem/RNG/MutationReducer），候选 state 推进，失败零 mutation 零 RNG，经既有原子边界整事务拒绝。
- 版本身份：setup_records 记录 content_processor_mount（content_id + version，排序确定性）；
  语义变更必须升版本；replay 经 setup_audit 比对拒绝版本漂移；不进 rules_fingerprint。

## 5. 验证证据（复查后 corrected）

- 组件测试 `tests/test_content_processor_interface.py` 19/19（含按复查更新的两项：takeover 效果阶段顺序、
  remove_summon 准入由领域条件而非 source_trace 决定）。
- Codex 复查复现 `/tmp/test_m1_codex_review.py` 5/5 通过（takeover 前窗口顺序、辅助动作参数×2、
  正式削韧、takeover 后攻击通知）。披露：削韧复现夹具原缺形式字段，已补
  `show_stance_list=tuple(row['ShowStanceList'])`（同一真实技能行，非生产代码改动）。
- 真实 IR 组件验证：1140702 经正式 show_stance_list[1]=30 走 L1 ToughnessSystem，
  目标韧性 100→70、伤害经 L1 direct 结算（/tmp/m1_3_prod_stance.py）。
- fork 集成 2/2 + 归档回归 12/12（executor 重构后）。
- 严格战斗探针 v3（/tmp/m1_3_strict_v2.py，吐息禁止回退、逐次记录处理器证据/伤害/削韧/HP 消耗）：
  1140711 实战 4 次提交全部 ok=true、无回退；每次含 content_processor 结算证据、
  L1 伤害（34.9/32.8）、HP 消耗 500（=2000×0.25）、雷弱敌韧性 60→30/300→270（stance 30），
  已破韧目标正确跳过。日志 /tmp/m1_3_strict_v3.log。
- 全量普通回归（executor 重构后）：仅 R07 检查点 3 项已知失败，无新增。
- **初版误判存档**：探针 v5 的"6 次吐息伤害"实为 1140701 普攻（吐息请求失败后回退），
  归档 `/tmp/m1_3_dragon_archive_1794387028.json.gz` 中 6 次 1140711 请求均 blocked。
- 通用路径已覆盖（探针 v1–v3 实证，处理器不接管）：敌方不可选中（StackCustomUnselectable TeamDark）、
  友方可选中（4399 V3.2 攻略【后援】语义，维持 targetable=true）、属性重置（ReinitProperty）、
  终结技禁用与 Skill02→21 映射（AttachSkillTypeDisable/SetControlSkillMapping）、弹射排除死龙、
  天赋增伤扩散、出生数值（HP=新蕊上限、速度=Skill03 参数#0）。

2026-11-12 文档复核纠正：原“3 回合寿命与到期自爆已覆盖”结论撤销。
最新 97 步归档中，同一死龙经历 4 次自然回合后仍 active，未挂寿命状态；出生生命周期为
`permanent_until_removed_or_owner_removed`。来源中的 LifeTime→TiggerKiller→InsideExplode
子图存在不代表自然入场链已接通。敌方不可选中则有 `TeamDark` 旗标和共享目标过滤器的组件证据。

## 6. 剩余缺口（归 M2 遐蝶条目，不是实验遗留）

| 缺口 | 说明 |
| --- | --- |
| 3 回合到期自爆 | 当前自然入场链未贯通；与主动 Skill23 按钮分别核对 |
| UseSkillOneMore 多次吐息循环 | v0.4.0 仍为单次吐息；多次循环未实现 |
| BP 层数倍率（Skill02 参数#2/#3） | 随循环一并实现 |
| 主动自爆 Skill23 按钮 | bounce_not_executable 属图覆盖旁路范围，但自爆伤害/治疗/退场整段需 H1 接管与数值对照 |
| 再创建自然验证 | 清理安全网已装配；探针未自然驱动到再创建（队列 staleness 死锁干扰），需生存策略重跑 |
| 吐息/自爆数值对照 | 按 M1-4 格式（numeric_validation/）做第一组处理器数值对照 |

## 7. 已知限制

- 队列 staleness：nat 阵亡后敌方队列 `queue_actor_unit_defeated` 全候选阻断死锁（通用问题，非遐蝶专属）。
  只记录不修；M2 锚点场景（敌方队列+死亡）实际依赖时归因修复。
- H1 接管边界：只接管通用 preflight 已通过的动作；binding 被阻断又必须处理器执行时需前置挂点提案，不擅自扩。
- 处理器不持有跨调用可变状态；持久信息进类型化 state 字段（replay 保证）。

## 8. 书写约定

见架构契约第 5 节（本实验确立）：一个内容一个文件；数值读数据卡参数、禁止写死；
只经 services 产生 mutation；不读 raw/TextMap/它卡私有状态；定义处注明依据与版本；
失败 fail-closed；第二个使用者出现时提升为通用机制。

## 9. 复查问题与修复（2026-11-12，死龙处理器 v0.4.0）

| # | 问题 | 修复 |
| --- | --- | --- |
| P1-1 | 辅助动作 1140710/1140711 的 ParamList 只有 1 个元素，处理器统一要求 2 个 → 提交必失败回退普攻 | 倍率改经正式技能参数绑定解析：动作伤害效果 DamagePercentage 主哈希 → `servant_skill_param_binding_source`（L1，servant 配置 ReadInfo 链；辅助哈希 -2087063973 正式绑定 Skill02 ParamList[2]，主动作 1476844314 绑定 [1]）；主动作保留自身 param_list[1] 形式回退；无绑定 fail-closed |
| P1-2 | 接管先执行全部效果再遍历触发窗口 → 前窗口晚于正文；takeover 跳过普通分支 → 无 action.after_attack | H1 移入执行计划效果阶段（首个 damage 步或首个 post-before 窗口）：前窗口回调先跑→处理器钩子→takeover 替换根效果图（OnStart）与 damage_plan；前后窗口与共享通知链照常；处理器伤害命中接回 action_hit_targets 与 post-action notice |
| P2-1 | 单次吐息遗漏削韧；首次修复只削韧，没有进入击破生命周期 | `services.apply_toughness` 派发削韧前/后事件，经 ToughnessSystem → BreakSystem 处理击破、状态、延后与多层溢出；复用原数值权威，失败整笔回滚。HookResult 传递已派发身份和归一化结果，H1/H2 不重派内部事件 |
| P2-2 | remove_summon 以 source_trace.rule 非空为运行门禁（违反 source_trace 审计边界） | 门禁移除；准入由已装配处理器行为 + SummonSystem.plan_remove 领域条件决定；source_trace 仅记录 |
| P2-3 | 公式复算被标记为已完成游戏对照（PROJECT_GOALS 要求实测或成熟计算器） | numeric_validation README/记录/交接纠正：复算=公式一致性中间证据，游戏对照待外部输出，M1-4 未收口 |
| P2-4 | 攻击前窗口已按时执行，但其临时增伤没有传入接管伤害 | 执行器把类型化贡献交给 ProcessorServices，由服务合并当前行动者的伤害包；保留自身贡献、相同贡献去重，HP 消耗不受增伤影响 |

定向检查：`test_content_processor_combat.py` 普通组件覆盖贡献合并与失败回滚，integration 覆盖
正式入场后的 H1/H2 击破、伤害/状态/延后与每类通知一次；`test_multilayer_toughness.py` 对比
处理器与原路径的多层溢出、完整状态及 RNG。组件输入不作为游戏数值对照。

本轮验证：相关定向 62 项、H1/H2 集成 2 项通过；真实辅助吐息 4 次提交成功，无普攻回退，
新归档独立进程回放 `ok=true, step_count=97, errors=[]`。固定阿兰基准单次提交均值
0.317 秒（前次复核 0.264 秒），初末快照与全部操作同基线；本次未作性能优化。
重任务串行：四人严格探针 471.25 秒 / 峰值 2,388,392 KiB，独立回放 453.24 秒 /
峰值 975,008 KiB。证据：`/tmp/m1_shared_fix_{regression,integration,breath,benchmark,replay}.log`；
归档 `/tmp/m1_3_dragon_archive_1794444904.json.gz`。本轮未跑全量回归。

教训：验证必须核实提交动作本身成功与结算来源身份，不能用 ID 前缀模糊匹配统计；
接管必须嵌入既有执行计划的效果阶段，不能在窗口循环外整段前置。
