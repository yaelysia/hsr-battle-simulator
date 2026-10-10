# v8 当前交接

本文只维护当前已验收边界、正在推进的阶段和下一入口。历史过程、阶段数字和修复流水账不在这里
重复；需要时从文档索引和 Git 历史按关键词追溯。

## 当前主线

```text
simulator_v8_clean_core
TurnBasedGameData -> compiler/lowering -> Canonical IR / 数据卡 IR -> Combat Core
```

项目不实现敌方 AI。外部推演器像玩家一样控制敌我双方，内核只负责给出合法动作、目标、时机和
确定性结算。

## 已验收边界

- P1-P7 已建立最小战斗循环、状态、召唤、波次、队列、目标、RNG、内容卡、动态参数、架构边界和
  可信状态提交等通用底座。
- P8 已完成当前来源下的光锥、普通玩家遗器、词条、套装、装备装配、构筑汇合、来源审计与 replay
  收口；`CUSTOM` 遗器模板保留来源但明确排除正式玩家构筑。
- CHAR-M1 已建立记忆角色与忆灵 owned-combatant 构筑边界。
- P9-S0 至 P9-S8B6 已验收。角色能力来源、构筑绑定、动态值、目标、条件、任务图 IR、共享原子执行、
  普通动作、独立能力、状态 callback 和跨入口 continuation 已进入统一生产链。
- P9-S8C1A 已验收：任务图具备加权 choice/selection 的严格 IR、稳定身份、父子 `.OddsList[i]`
  来源关系、数值定义配对、不可变容器和严格 JSON codec。
- P9-S8C1B 已验收：现有正式 `ability_phase_callback` action entry 的 `RandomConfig` 现在由共享 task-graph materializer 从同一 signed `CharacterAbilityRawSnapshot` 读取 `OddsList[i]`，复用既有 numeric lowering，并把 definition/choice 与既有 S8A branch 一一绑定到 `TaskGraphIR.weighted_selections`。真实 Direct 已动态证明单 entry 与 ability catalog 共享同一物化结果。
- P9-S8C1C 已验收：现有 `ability_phase_callback` 与 `status_callback` 对 `RandomConfig` 共用同一 weighted-selection materializer；完整 raw/S8A/source-ledger 来源分母与 level-specific formal-position multiplicity 已通过 STRICT 双向闭合，status 单 entry 与联合目录一致，S8C1B action 回归保持。
- P9-S8C1 聚合已验收：独立 STRICT 审计从实时来源重新得到 direct `RandomConfig` 分母 `24`，raw/S8A/source-ledger exact-equal，`formal_bound/no_formal_producer=14/10`；全部正式 producer/definition-level/task multiplicity 的 expected/actual formal positions 为 `117/117`，公开联合 catalog 的 weighted-selection ordinal/branch/`OddsList[i]`/numeric/source identity 一一闭合。最终执行 head `7a75e80a02f886ab1036cbe041b3b031d7057e82` 的 PR CI run `33857786539` 通过；`full_canonical_ir_build_count=0`，未执行 runtime RNG、mutation/event/settlement/replay。该检查点只完成静态任务图契约，不代表 S8C runtime/RNG 或 S5D2 transaction/replay 已闭合。
- P9-S8C2 已验收：共享 `TaskGraphExecutor` 现在具备 `RandomConfig` / `weighted_single` 专用的类型化 weighted-selection hook/result contract，由 executor 反查 accepted IR 校验 selection/choice/ordinal/branch identity，只执行被选 branch，并将恰一个合法 `RNGEvent` 纳入既有 task-graph result、duplicate identity 与原子 rollback 空间。执行 head `5e14526f4046626528aee4a594a8e7eb8a9ef14a` 的 PR #5 CI run `34080289369` 已通过独立核验。该检查点不计算动态权重、不接真实 ability/status RNG ledger caller，也不代表 projectile、barrier、parallel、sequence-select 或整个 S8C 已闭合。
- Route A 前置 A1 `P9_FORMAL_ACTION_GRAPH_ADMISSION_AUTHORITY` 已通过独立 REVIEW：正式 action admission 现在从与 `AbilityTaskSystem` 一致的 `action_root` 图闭包做静态支持投影，只通过真实 `TriggerAbility` 链接纳入 `nested_only`，排除闭包外 bound phase/task，同时保留 reachable blocker、process-only 区分、external-legacy 与上游准入门。REVIEW 返修补齐了跨图路径敏感 active-cycle fail-closed；实现 head `84ee94b4d1bf25221d783f8a84d7b79f8e46f896` 的 hosted CI run `34122026242` 已通过。该检查点不包含 A2，也不代表 PR #9 caller/RNG-ledger 已完成。
- Route A 的 A2 独立 L0 前置 `P9-A2-P0_ACTION_WINDOW_STATUS_CALLBACK_ADMISSION_FINALIZATION` 已通过独立 REVIEW：`tbgd/lowering.py` 在既有 status event producer 与 typed `TriggerAbility` link 事实形成后增加单一 post-link admission finalization，只移除来源可证明为过早冻结的精确 `status_callback_event_not_admitted:<event>` blocker。STRICT Direct 在 lowering 之前从 formal raw/source graph 动态枚举 action-window `TriggerAbility` occurrence，并与 pre-finalizer IR、typed target/final graph、production audit 双向 exact 对账；当前来源只有 1 条真实正例发生 blocked→executable transition，其余同 action-window event 独立 blocker 均保持。真实 queue resolution 驱动 invocation role，A1 admission regression 保持；生产实现 commit `a73576c6d5d751f6c5d14713e5ed49883fc82b2f`，PR #12 最终执行证据 run `34193467352` 全绿且 workflow 权限为只读。该检查点只闭合 A2 的 merged-master L0 admission prerequisite，不代表 PR #11 的 action-window status→nested formal ability runtime transport/routing 已完成，也不替代其真实 `CombatExecutor.execute(ActionCommand)` Direct。
- Route A 的 A2-P1 前置 `P9-A2-P1_FORMAL_PROCESS_ONLY_SOURCE_IDENTITY` 已通过独立 REVIEW：formal lowering 现在只在同一 `process_only` task 的 own `EffectIR` 唯一且旧 source 与 canonicalization 前 task source exact-equal 时同步 canonical `IRSource`；既有 client-only `TriggerAbility` post-conversion 路径也只在唯一 exact pair 下同步，ambiguity/source disagreement 均保持 no-rewrite/fail-closed。STRICT Direct 从 pinned TBGD/current formal lowering 动态重建完整分母，`5073` 条 baseline mismatch 全部由 topology-evidence normalization 唯一解释并在当前生产 lowering 中降为 `0`，`8120` 条 non-process-only pair 与独立来源保持不变；same-owner 正式 action 只移除 `process_only_task_effect_source_mismatch`，`ability_task_graph_nested_identity_mismatch`、S8C/S11 等后续 blocker 继续 fail-closed。生产修复 commit `d163e0d3225a8e31bfd4af602541049332614e59`；REVIEW 返修后 final EXEC head `4cca72510761331c9fb721999d436bf6f0861e66` 的 P1 run `34330329036` 与 P0 regression `34330328967` 全绿，workflow 权限保持只读。该检查点只闭合 formal process-only task/effect source identity，不代表后续 same-owner formal blocker、PR #11 A2 runtime transport 或 PR #9 caller/RNG-ledger 已完成。
- Route A 的 A2-P2 前置 `P9-A2-P2_PROCESS_ONLY_TRIGGER_ABILITY_ADMISSION_IDENTITY` 已通过独立 REVIEW：A1 formal action admission 现在只让 canonical `ability_call` 或 non-process-only gameplay `TriggerAbility` 进入 nested-edge identity 路径，合法 process-only `TriggerAbility` materialized `leaf` 在既有 process-only source/effect contract 通过后不再被 opcode-only 误判为 nested gameplay edge；process-only `ability_call`、non-process-only `TriggerAbility` leaf、普通 task `ability_call` 以及 reference/link/nested graph mismatch 仍 fail-closed。STRICT Direct 从 pinned TBGD 与 merged production 动态选择 same-owner ordinary action，只移除该 process-only leaf 的 `ability_task_graph_nested_identity_mismatch` provenance，root/reachable/excluded identity 与 hit-random/audit/unsupported/damage-heal-shield 等其它 blocker 保持，ActionContract 仍按后续域 fail-closed，runtime graph/mutation/RNG 均为 `0`。final EXEC head `a5ad6031bbe02f0e7e90d7c227124814d4e662d1` 的 P2 run `34569640362` 全绿，workflow 权限保持只读；PR #14 已以 squash merge `d1c28c0c0e10ed8b268739b71bab1784574a8d93` 合入。该检查点只闭合 A1 对 process-only TriggerAbility leaf 的 admission identity，不代表后续 same-owner formal blocker、PR #11 A2 runtime transport 或 PR #9 caller/RNG-ledger 已完成。
- Route A 的 A2-P3 前置 `P9-A2-P3_S8C_WAIT_ANIM_STATE_PROCESS_ONLY_BARRIER_RETIREMENT` 已通过独立 REVIEW：task-graph materializer 只对 source-proven、lowering 已证明为 `process_only` 且字段责任全部为 `presentation_excluded/excluded` 的 `WaitAnimState` presentation barrier 退休错误的 `hit_random_sequence` obligation；节点保持 materialized process-only leaf 与 exactly-one same-source `audit_only` EffectIR reference，不把 audit identity 升级为 gameplay effect。STRICT Direct 的 formal WaitAnimState 分母为 `22330/22166/164`（total/admitted/blocked），PR14 同一代表 action provenance 精确由 `WaitAnimState×2 + FireProjectile×1` 降为 `FireProjectile×1`，mutation/event/RNG/settlement/replay 均为 `0`。final EXEC head `1ccedb3630b81dc190e52b3f0c2160f3e344775e` 的 final-head runs `34700147202` / `34700147243` 全绿；PR #16 已以 squash merge `dae1441e3227b3c0ab86cb4ca847368594832c1b` 合入。该检查点只闭合 WaitAnimState process-only presentation barrier，不实现 FireProjectile、S11 或 PR #11 A2 runtime transport。
- P9-S5D2 的随机目标基础和弹射目标消费已完成，但其完整动作 transaction/replay 正例明确等待 S8
  随机控制流闭合后回验，因此该聚合项仍未勾选。

“底座已验收”不等于全内容完成。P1-P8 的完成结论只适用于各阶段声明的来源与功能范围。

## 2026-09-23 已验收检查点补记

- Route A 的 A2 / PR #11 已完成独立 FULL_AUDIT 及 CLOSURE_AUDIT，原三个 blocking finding 全部关闭。最终审核 HEAD 为 `69b333406959695c2d37b720e89cca895baf5c65`，合并提交为 `2d60a4305206bc11b67edf445a55478d90c96257`；本地协调器任务 `PR11-A2-RUNTIME-RESUME` 为 `completed`，Revision 56，`local_finalized=true`。
- 已验收边界为真实 `CombatExecutor.execute(ActionCommand)` → 正式 action-window → 生产附着 status → typed nested ability → `AbilityTaskSystem` 的 weighted deferred，以及整动作零提交回滚。静态技能参数、caster 归属、impact fact 封签/窗口运输和最终精确 HEAD 验证均属于该检查点；不是完整角色出生或 RandomConfig gameplay 已完成。
- 关闭审核：PR #11 评论 `5789905304`；同一审核 HEAD 的 A2 / 四项固定门 / S8C1B / S8C1C CI 已在审核中核实。前述各 Route-A predecessor 的记录描述当时边界，其中“PR #11 尚未验收”等文字只作历史解释，不能覆盖本补记。

## 当前工作

<a id="reverse-driven-20261008"></a>
### 2026-10-10 归档证据去重与批末验证成本

- 已定位旧记录3.27GB的根因：数值来源、DoT账本、整包 damage metadata、致死派生 mutation
  与审计导出在多个路径重复展开；不是状态历史均匀增长。用户已确认不需要旧归档/审计接口兼容。
- 新格式为 `hsr_battle_archive_v2` 引用表，会话为 `hsr_battle_session_v2`。相同容器只保存一次，
  恢复共享内容后核对全部正式事实；引用不进入规则执行。旧格式明确拒绝，场景/操作仍用普通JSON。
- 伤害五类路径共用无整包别名的 metadata 生成；DoT账本用求值键与条目索引，击败/击杀回能用
  同次执行的 HP mutation ID 关联完整伤害证据。审计验证致死血量、路径与来源，缺证据仍阻断。
  内部会话/原子提交证据/来源审计复用不可变数据，默认导出独立；删除旧逐转换分帧和暂存读取器。
- 同一21次提交路线生成成功，胜利终态保持不变，归档43条操作。压缩363808字节、引用表
  3204883字节、12225个不同对象；旧压缩记录约86MB。生成2:27.96、峰值926924KiB；
  独立CLI文件回放 `ok=true / step_count=43 / errors=[]`，2:36.48、峰值895936KiB。
  两次进程均无换页；旧生成/回放为9:23/13:14，峰值约3.6/3.9GiB。
  产物 `/tmp/hsr-serval-audit-v2-20261010.json.gz`，同名前缀的 run/replay 日志与 time 文件保留证据。
- 73项不同的归档、不可变导出、伤害/DoT、资源、真实阿兰致死与来源审计检查通过，重复运行不累加。
  当前两个DoT验证器导入通过；历史P8 S8验证器仍引用已退休接口，未把它作为本批验收入口。
  不宣称全量验证。定位先分析已有产物；批末只生成一次、独立文件回放一次，不额外叠加同场内存回放。
- 来源编译和战斗执行成本仍在，未引入缓存或把审计引用作为runtime输入。未新增依赖/环境，
  TBGD pin未改；按用户要求将近期成果纳入本地检查点提交，未推送。实际提交身份以 Git 历史为准。
  命令、格式与边界见 `simulator_v8_clean_core/CLI_MVP.md`。

### 2026-10-09 希露瓦技能组

- 用户要求按可用成果批量推进，集中修复共享根因并在批末验证；不再以单个 blocker 修复作为交付。
- 新增 `examples/cli/serval_natasha_vs_antimatter.json` 及同名操作脚本：E0/Lv1 空装备、零初始能量，
  来源关卡 `200021050` 的两只8级重子。21次提交覆盖普攻、战技、感电 DOT、天赋追加伤害、
  终结技申请/队列执行与胜利。终态希露瓦 HP124.8/E25、娜塔莎 HP158.4/E90、SP2，两怪 HP0。
- 通用修复：严格排除来源证明的表现挂点、空动画范围、秒数等待与场景显隐；技能动作和状态
  回调均保留完整 Retarget 条件。`AbilityTaskIR.target_expression_id` 与正式图引用一致，仍由
  CanonicalIR 校验。按一个来源行为标记执行 `LifeTime + Add`，逐实例原生记录持续时间变化，
  多标记及未知修改形态保持阻断。终结技对存活目标将感电2→4；随机目标结果连同 RNG 交给
  已有任务图原子执行器，避免多目标仍存活时被旧的通道阻断。
- 本地 `OnAfterAttack` 只消费动作结束窗口，逐目标 `OnListenAfterAttack` 仍独立派发，修复天赋
  重复触发；DOT 参数只从当前状态实例及未被遮蔽的正式构筑绑定读取，不能由兄弟状态补缺。
- 插入行动击败等待中的回合所有者后，合法查询转交调度器；只在死亡已结算时关闭该回合，
  不执行死者 TurnEnd 状态扣时/回调，不允许存活者跳过行动。行动前 DOT 致死链保持原有生产权威。
- 内部 snapshot 共享已冻结子树，原子提交直接比较不可变快照并复用差异判断；公开导出仍独立，
  candidate/reducer 一致性与零提交保护保留。同一实际状态10次构造微测3.3427s→0.0029s；
  这是内部快照微测，不能当整场加速倍数。首次编译70–94s、审计导出成本仍在。
- 旧结构的历史成本基线：展开约3.27GB、压缩约86MB，生成9分23秒、文件回放13分14秒，
  峰值约3.6/3.9GiB；全文读取曾因超过14GiB被终止。旧记录在
  `/tmp/hsr-serval-final-20261009.json.gz`，不再由新读取器兼容；当前结果以上方2026-10-10检查点为准。
- 丹恒本批仅完成缺口定位：E0 仍有真实 `source_graph` 构筑回调未通过正式准入，不能删除它来
  绕过出生检查；后续从该来源图回调、暴击减速和天赋事件链继续纵向贯通，未计入可用角色。
- 2026-10-09 状态/资源/归档55项定向检查通过；新增完整场景1项通过（626.73秒、峰值约5.6GiB），
  包括21次提交、双存活目标延长探查及内存中的完整回放。独立 CLI 运行、写入与文件回放均通过。
  来源、随机、冻结、快照与不可变状态的定向回归也已通过，不宣称全量测试。入口及命令见 `CLI_MVP.md`。
  额外构筑、DOT 采样刷新/重施、完整击破通知等保留缺口。本批未提交/推送，未新增依赖/环境，TBGD pin 未变。

### 2026-10-09 娜塔莎 E0 普攻与终结技

- 正式动作准入复用构筑条件 producer，仅排除能明确求值的未激活星魂/行迹分支；
  条件事实不足继续保守检查。修复 E0 普攻/终结技被未激活 E6/E2 分支误挡的问题。
- 正式来源中的单目标、忽略碰撞且等待完成的 `FireProjectile` 已进入原任务图执行器，
  命中子任务与真实来源保留；渲染、光照和 UI 通知按严格来源形态排除。
  不模拟动画飞行时间，异步在途与碰撞结果仍需对应内容的正式 producer。
- 群体治疗由正式目标系统解析存活队友，逐目标复用既有治疗、低 HP 加成与结算；
  任一目标失败时丢弃本次全部 mutation。没有第二套群疗公式或按角色名分支。
- 复用 `examples/cli/arlan_natasha_vs_antimatter.json`，新增
  `arlan_natasha_ultimate_vs_antimatter.commands.json`：十四次提交，含娜塔莎普攻、
  两次战技、一次终结技申请及队列执行。自然积能到90，在阿兰回合插入群疗后继续并获胜。
  终态阿兰 HP163.2/能量110、娜塔莎 HP158.4/能量5、SP4，两怪 HP0。
- 已用现有 Windows FFmpeg 查看公开终结技片段
  [BV1aL411z7cn](https://www.bilibili.com/video/BV1aL411z7cn/)（2023-05-25 发布）的每秒抽帧概览。
  约8秒处可见四名友方的绿色回血提示；版本与构筑未确认，只记录群体回血的可见行为，
  不以跳字反推精确公式、内部事件数或伤害请求。原始片段与抽帧仅写 `/tmp`。
- 本日只读核对 PR #8 仍为 `9a7ab71b00a0027e994ad33d06a918a998602a24`。
  验证：23 项来源/动作图检查、60 项治疗/能量/队列/随机定向检查通过；新进程完整场景
  1 项通过（345.44 秒）。其中状态副本探查确认群疗对30% HP目标提供25%天赋加成，
  对31% HP目标不加成；激活 E6 后其真实缺口仍阻断普攻。合计84项，不计重复运行。
  独立 CLI replay 为 `ok=true / step_count=29 / errors=[]`，归档仅在
  `/tmp/hsr-natasha-ultimate-probe-20261009.json.gz`。
  保留边界：额外行迹/星魂、属性改变时的快照采样、同目标覆盖重施及特殊时序仍未整链验收。
  本轮尚未提交/推送，未新增依赖或 uv 环境，TBGD pin 未变。

### 2026-10-08 逆向驱动：先修真实战斗结果，再扩充治疗场景

- 用户收窄目标为尽量还原实际战斗的模拟器，不完整复刻原生引擎。按选定行为核对来源、
  已确认研究与必要的视频观察，复用通用机制并检查结果；不以所有 raw 任务或内部协议
  清零为前置。四层分工及来源/原子提交不变量保留，目标与执行约定已同步。
- 阿兰战技的 `LoseHPByRatio.Floor` 已从错误的取整标志修为剩余 HP 下限，保留数值表达式。
  正常损血不舍入，濒死及 1 HP 成本保留 1 HP，缺少下限绑定时零提交。采用 PR #8
  `9a7ab71b00a0027e994ad33d06a918a998602a24` 的已确认 HP-loss 规则，不声称视频新实测。
- 娜塔莎编译失败的根因是独立能力漏用已有镜头调用分类；现复用来源解析，不放宽 IR
  完整性检查。另修共享出生事件：普通入场、单位出生、召唤出生不再误发 `OnSnapshotCreate`。
  真实阿兰+娜塔莎 E0/Lv1 无装备场景能编译和入场。
- 娜塔莎战技已接通：目标关系采用角色配置的正式选择契约；纯镜头分支、特效与语音子树
  依据结构排除，真实治疗保留。`AddRatio=1` 在真实请求位置增加动作 `SPBase`，资源计划
  不提前双发；瞬时治疗加成由类型化回调结果供给，审计记录不驱动结算。
- 持续治疗复用现有状态回调与治疗执行器。重复施放时，动态读取按 actor/当前能力实例
  复用已有可见性规则，避免历史实例同键歧义；动态索引的排序不一致也已在共享 producer 修复。
  新样例为 `examples/cli/arlan_natasha_vs_antimatter.json` 及配套 `.commands.json`。
  十二次手动提交获得胜利：阿兰 HP138.72/能量110，娜塔莎 HP158.4/能量90，SP0、两怪 HP0。
  第二次治疗选择自身，阿兰原 HoT 在其回合开始触发两次并到期。
- 已读取公开视频 [BV19nYMz2EGj](https://www.bilibili.com/video/BV19nYMz2EGj/) 的公开画面流
  （852×480、30 fps、120.065 秒），用现有 FFmpeg 抽取概览与选定动作片段。
  18 秒画面中阿兰 HP3367/SP3，20 秒「禁锢解除」期间 SP 仍为3；22 秒画面中
  阿兰 HP2862、SP2，24 秒「如雷疾行」期间 SP3。54 秒可见多个伤害跳字及右上总伤害899118。
  这些是选定画面的显示事实；构筑与增益未确定，不能据此确定精确伤害公式、独立伤害请求数、
  逐请求回能或原生事件时机，不声称已经逐帧核对整场。另找到
  [速度/行动值解释视频](https://www.bilibili.com/video/BV1qw4m1f7ry/) 与
  [娜塔莎指南](https://www.youtube.com/watch?v=L4mWo12QIqY)，尚未看完整视频或核对其演示。
  用户此前已说明 Windows 侧有 FFmpeg，不能再以下载授权阻断。已定位并验证
  `C:\haoyue\ffmpeg\bin\ffmpeg.exe` 与同目录 `ffprobe.exe`，从 WSL 调用现有工具；
  路径通过 `wslpath -w` 转换，抽帧产物仅写 `/tmp`。未安装新依赖，也未改 uv 环境。
- 验证：当前五个定向测试文件 104 项通过（14.11 秒），覆盖治疗/回能、作用域读取、
  真实来源分类及相关随机/终结技/表现 barrier 回归；`test_cli_content_scope.py` 两项完整
  场景检查通过（1027.73 秒），包含原九次阿兰胜利、新双人十二次胜利及各自 `verify_archive`
  replay。合计 106 项，不计重复运行，不宣称全量测试。
  新场景另有真实条件/参数的低 HP 组件探查：30% HP 边界请求治疗101.36，阿兰48.96→150.32；
  该探查使用状态副本，不改胜利脚本历史，不冒充完整游戏操作或视频实测。
  本轮早期另有出生/快照分离与真实被动启动的检查；mixed 场景旧数值不冒充本轮新结果。
- 当日保留边界：普攻与终结技尚未验收；其后续进展见上方 2026-10-09 节。静态面板路线
  不证明治疗者属性改变时的快照采样、同目标覆盖重施、额外行动和特殊死亡语义。
  相关研究已给基础公式与普通持续治疗行为，不能因 native 快照协议未恢复而拒绝这些已确认行为，
  也不能把本次结果扩大为快照机制已经完整实现。
- `git diff --check` 通过。本轮源码和文档修改尚未提交/推送，TBGD pin 未变，未新增依赖。

<a id="mcp-status-20260930"></a>
### 2026-09-30 提交后状态校准与 MCP 信息同步

- 已核实业务基线为 `master@6733fd350ddbbf72b30d808153e8abc2a538c48c`，父提交是
  `2d60a4305206bc11b67edf445a55478d90c96257`。CLI、内核、相应测试和交接已进入新提交；
  不再将这批成果描述为未提交。两提交之间 TBGD submodule 指针没有变化。
- 本轮开始时已跟踪文件干净，只有 `hsr_battle_sim_ui_v10_toughness_fixed.html` 与
  `hsr_v075_baseline_clean/hsr/simulator_v8_ui/UI_V2_WORKBENCH_TASK_PLAN.md` 两个未跟踪项，
  均不在本次提交和信息同步写入范围。本节及关联入口校准是随后新增的文档修改，尚未提交。
- 本次核对了精确提交中的 CLI 入口、规则注册变更、关键正式消费者和保留的阻断，以及现有
  交接、缺口与任务记录。没有重新执行 pytest、CLI、replay 或独立审核；下列运行结果沿用
  2026-09-28～29 的既有记录，不冒充新提交上的本轮运行。远端推送状态未核实。
- 采用的研究版本仍为此前已核对的 PR #8 `4d524d6c1e4875d748b5adb568e478a554b34d3b`；
  本轮没有重新检查 PR #8 的远端增量。

| 工作项 | 当前状态与边界 |
| --- | --- |
| CLI 单场景 MVP、会话与归档 | 已提交；既有记录为阿兰 E0/Lv1 对两只 Lv2 重子，九次操作胜利、独立 replay 十九步成功。该场景不发生击破，不证明任意配置或败北路线。入口：`simulator_v8_clean_core/CLI_MVP.md`。 |
| PR8 已确认数值与资源规则 | 已提交；包括治疗/护盾操作数、终结技 SPNeed 扣费与回能、非致死逐请求受击回能、普通多盾并行吸收等。规则注册版本现为 `hsr_v8_engine_rules_v8`；各项仍受缺口表所列范围约束。 |
| 正式随机与事件调用链 | 已提交；ability/status 加权选择、条件/随机目标/调度的 RNG 事务，以及嵌套生命周期事件去重已有实现和既有定向记录。不能扩大为完整弹射/投射物内容已完成。 |
| 普通击破、恢复与冻结 | 组件已提交；初始公式、部分周期参数/层数、单韧性恢复及冻结最后一次行动跳过有既有记录。完整公共击破通知链仍未闭合。 |
| 行动前 DOT 致死调度 | 已提交；既有记录覆盖伤害/击败提交、关闭死者回合及下一行动者推进，不等于所有死亡/复活机制完成。 |
| 通用底层后续 | 阶段仍在推进，不重做已接通能力。致死受击回能待实测；TriggerBreak 通知映射待确认；首次计时研究有争议并暂停；护盾 cap/加成、免控消费等按受影响分支保留限制。详细状态沿用 G01～G12。 |
| 内容接入与延期范围 | RetargetPerSequence/FireProjectile、CreateServant、秘技/场地、复活、特殊韧性、多波等按对应内容需求处理；不是当前 MVP 的新增前置，也没有由本轮自动派发执行。 |
| 实战对比记录器 | 仍在讨论，未实现；本次信息同步不授权其施工。 |

#### MCP 正式任务与本次同步结果

| 任务 | 保留的正式状态 | 信息解释 |
| --- | --- | --- |
| PR11-A2-RUNTIME-RESUME | completed | 原审核 HEAD `69b333406959695c2d37b720e89cca895baf5c65`，合并提交 `2d60a4305206bc11b67edf445a55478d90c96257`。历史审核不覆盖此次后续提交。 |
| P9-A2-P6-DAMAGE-AUDIT-REFERENCE | completed | 原 P6 audit-reference 交付已结束，不作为当前待执行任务。 |
| P9-A2-P5-SETTLEMENT-BARRIER | completed | 原 P5 交付已结束，不作为当前待执行任务。 |
| PR17-P4-CLOSEOUT-R2 | completed | 原 PR17 收尾已结束，不恢复旧会话。 |
| P9-A2-P6-VALIDATION-CLOSEOUT | cancelled | 保留原取消记录；原说明指向的 `P9-A2-P6-VALIDATION-CLOSEOUT-R2` 不在当前七条账本中，不虚构该记录或等同于其它任务。 |
| PR17-P4-CLOSEOUT | cancelled | 历史取消项；可核实后续 `PR17-P4-CLOSEOUT-R2` 已 completed。 |
| P9-S8C1A | cancelled | 本条取消不表示加权选择能力未实现；能力现状以上表与源码为准。 |

当前账本没有执行中、待审核、返修或待决策任务；这只描述 MCP 管理的任务，不能据此断言
其它本地代理进程是否运行。新提交中的工作流外成果没有对应的新任务卡，也没有新增审批或审核。

本次已实际尝试仅更新 `next_action`、不传 `state`：`P9-S8C1A` Revision 2 被拒绝为
`INVALID_TASK_TRANSITION: 不允许从 cancelled 转为 cancelled`；`PR11-A2-RUNTIME-RESUME`
Revision 56 被拒绝为 `INVALID_TASK_TRANSITION: 不允许从 completed 转为 completed`。
两次均未写入成功。当前公开工具也没有项目状态/工作流外成果导入入口；因此本次完成交接信息
校准，看板写入仍受接口限制。解除该限制需要明确的元数据更新或事实补录入口，不能通过
重开旧任务、改写历史 HEAD/审核、直接编辑账本或伪造执行来替代。本轮未修改 MCP 服务代码。

以下日期小节保留当时实施过程；其中“未提交”“未走 MCP”等历史描述不覆盖本节的新提交事实。

### 2026-09-30 实战对比记录与 MCP 协作入口

- 游戏实战的逐项记录方式仍在讨论，尚未授权实现记录器。前次误加的独立 HTML
  页面及检查文件已经撤回；当前没有可用的游戏观测记录器，也没有与战斗归档对照的功能。
  如果以后决定实现，应优先复用现有模拟器的场景、合法动作、提交、快照和 replay；
  游戏实测只作并列观测，不能反向覆盖内核规则。具体交互和粒度仍待用户决定。
- 根目录 CODEX_HANDOFF.md 是当前导航，MCP project_info 会列出 AGENTS.md 与它。
  用户随后提交了近期成果并要求校准 MCP 信息层；新提交、现有任务与实际写入限制以上方
  “提交后状态校准与 MCP 信息同步”为准。本次没有启动新开发或重建历史审批/审核。

### 2026-09-28 最新本地实施：PR8 已确认规则与通用调用链

- 本轮研究已核对至 PR #8 `4d524d6c1e4875d748b5adb568e478a554b34d3b`。用户确认事实直接
  编译或注册为规则；研究自身有争议、暂停或待实测的项目不升级为确认事实。
- 非致死受击回能按实际请求的 `SPHitBase × SPHitRatio × (1 + ERR)` 结算并截顶，删除旧的
  单请求限制；真实双请求各 7.5 的执行、截顶、来源审计与 mutation replay 已通过。
  致死回能按用户安排等游戏实测，仍阻断；完整弹射内容的投射物链并未因此自动接通。
- 普通多盾改为各池并行扣伤害，HP 只承担超出最大适用盾的部分；耗尽事实精确清除所属
  状态及其 OnDestroy 效果，保留别的存续盾。多池全局回调次序未确认。最新研究撤回了
  “统一将护盾加成乘入叠盾 cap”的依据，相关组合明确阻断；无加成的固定上限仍可用。
- 正式 ability/status 已消费 weighted selection 的真实权重与 RNG；条件、随机目标及
  回合调度的 RNG 纳入原子事务。真实来源 consumer 探针通过，不等于相关角色整套内容可玩。
  状态回调递归分派保留每个事件一次，修正了嵌套生命周期事件重复收集导致正式动作回滚的问题。
- 冻结最后一次计时会保留本次行动跳过，不再先过期后漏跳。普通击破初始公式已修复等级
  基数、最大韧性参数角色；状态保留原始百分比，物理裂伤只乘一次击破特攻并应用 DEF/RES。
  风化实际层数已验证普通分支 1 层、高 rank 分支首次 3 层、同源再次施加封顶 5 层；复用
  共享状态叠层，保留定义的 MaxLayer/LayerAddWhenStack 且具体施加字段优先。
  跨文件 AddModifier 命名参数通过编译时已声明的动态变量槽建立对应，避免感电倍率为 2、
  周期公式读取的同一参数却被默认为 0；运行时消费该对应，不按元素名或固定 hash 分支。
  对应真实表达式、伤害管线和冻结行为检查已通过。
- 普通恢复的来源范围通过真实模板 StanceCount 贯通到单位事实，单韧性才准入；不实现特殊
  计数。从已安装的击破状态验证 OnEndBreak/OnDestroy，韧性回满、公共减伤从 0 还原到 0.1，
  感电保留且周期实际扣血；同一来源的 +0.25 行动延后、来源审计和 mutation replay 通过。
  完整击破链尚不能声明贯通：用户确认公共状态
  中 TriggerBreak 只是独立序列化任务，原生映射、归属、次数及跨回调顺序仍未闭合，不能
  据此额外派发；保留 `break_trigger_notification_mapping_unconfirmed` 阻断。
  PR #8 新增的数据库充分性判定进一步确认固定导出不足以唯一重建原生通知协议；
  `ForbidRecallModifierEventList` 不能直接当成通知去重规则。
  此前临时 probe 漏掉公共状态子 lifecycle 回调，
  其“恢复返回成功”不能作整链证据；此问题已明确留在当前缺口表，不能跳过任务做假成功。
- 2026-09-29 补上行动前 DOT 致死后的通用调度：正式提交伤害和击败，同一步关闭死者回合，
  不对死者恢复韧性、开放决策或执行 TurnEnd 状态扣时；下一 step 由波次或时间线继续。
  真实感电 HP 1→0、来源审计、mutation replay、下一行动者检查通过；相邻冻结检查保持通过。
  `OnImmune` 消费仍缺免疫判定到回调及保护实例的映射；800304005 弹射仍缺
  RetargetPerSequence/FireProjectile 正式 consumer 和目标重选规则，未写猜测性的结果。
- 首次计时的统一语义仍有争议且研究已暂停；特殊韧性、多波、复活、具体技能投射物等随
  内容接入处理。详细当前边界见 `simulator_v8_clean_core/docs/MVP_KNOWN_GAPS_2026-09-28.md`。
- 最终源码重新执行原 CLI 九步脚本得到 victory，阿兰 HP `5.25078`、能量 `15`；独立进程
  replay 返回 `ok=true, step_count=19, errors=[]`。归档为
  `/tmp/hsr-mvp-pr8-shared-final-20260928.json.gz`；同前缀 `-run.log`、`-replay.log` 保存结果。
  该场景不发生击破，不将它当作尚未贯通的完整公共击破链证据。
- 上述成果已纳入 2026-09-30 提交 `6733fd350ddbbf72b30d808153e8abc2a538c48c`，
  TBGD pin 未改；本轮信息核对没有验证远端推送。下方历史检查点只描述其当时边界。

### 2026-09-28 当前路线：先通用底层，特殊机制随内容实现

- 用户已确认：先完成角色、敌人和场地共同依赖的基本战斗规则与执行能力，再逐步接入具体
  内容，并在接入时实现所需特殊机制。底层目标比单场景 MVP 更完整，但不要求先实现最终
  产品的全部机制；“未来可能复用”不是将特殊机制提前施工的理由。
- 四层保持 L0 来源编译、L1 通用机制执行、L2 内容装配、L3 外部操作，审计/replay 横切。
  后续特殊机制需要扩展 L0/L1 时，在对应内容任务中完成，再由 L2 装配，不把结算写进内容卡。
- 复用已有常规数值/资源、基础状态、行动/队列、弱点/削韧与普通击破、单位/场景生命周期。
  第一阶段只补这些基础执行链的实际缺口，不重做已完成领域；阶段范围和结束条件见
  [P9 当前路线](simulator_v8_clean_core/P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md#0-当前路线机制优先内容逐步扩充)。
- weighted-selection 正式 caller/RNG 已补，普通状态/击破调度按上方最新实施记录推进。
  首次计时研究现有争议，不能写成已确认算法；不读取或移植失败测试 PR #9，旧 P9 未勾选项
  不能自动加入本阶段。
- 超击破结算器已有，触发入口随相关内容接入；复活、特殊资源/韧性、形态变化、召唤物特殊
  行动、敌人阶段和场地专属规则也由对应内容需求推动。具体技能的削韧量绑定属于内容接入，
  普通击破自然恢复属于本轮底层连接缺口，二者不能混在同一前置清单中。
- 多盾消耗、致死/多请求受击回能等基本规则边界保留真实阻断记录；已确认结论直接实现，
  未知只阻断依赖分支。不把它们改名为特殊机制，也不以全部边界清零阻止无关内容接入。
- 已有 CLI MVP 作为持续运行与游戏实测对照载体。完全本地实施，PR #8 用户确认事实直接
  作为规则依据并保留研究来源；不恢复 MCP 审批链、全目录验收或覆盖率目标。
- 此前延期内容仍保留在最终范围，UI、养成、敌方 AI 继续排除；历史记录不覆盖上述最新
  阶段边界和本地实施结果。

### 2026-09-28 MVP 检查点：一个完整场景已交付

- 用户进一步收敛：MVP 只需一个最简单的战斗场景和操作路径完整完成，不以更多角色、
  任意胜负路线或通用机制全部闭合作为前置。以下较早“少量完整角色”等表述以此为准。
- 沿用阿兰 E0/Lv1 对两只 Lv2 重子的单波 CLI 示例及九次操作脚本；UI、养成、敌方 AI、
  特殊韧性和多波仍不做。已确认的 PR #8 事实直接落地，不要求补找 native 实现。
- 正式能力图已移除普通削韧的主动硬门，沿用共享 ToughnessSystem / BreakSystem。
  已确认的普通单体普攻基数 30 由编译层提供，保留来源逐段比例；真实阿兰普攻正例通过，
  两段合计削韧 30，伤害先于本段削韧。其他技能量、完整击破模板及自然恢复仍未宣称完成。
- `ModifyHealData.Target_HealTakenRatio` 已经编译并由受治疗者 `OnBeforeBeingHeal` 消费，
  保留真实条件和 `ParamEntityActualOwner` 目标解析；与治疗者加成在同一乘区计算。
  原始 Sam 条件/任务正例验证基础 1000、加成 +0.5、惩罚 -0.9 实际治疗 600。
  现有 sustain 文件定向回归通过；不据此宣称完整 Sam 内容可玩。
- 测试只围绕实际行为和变更风险：必要的新规则正例、真实 CLI 战斗与独立 replay。
  已精简整场测试中的无关数值检查及重复非法输入检查，不追覆盖率、不堆形式验收。
- 本轮 CLI 实跑完成九次操作并获胜，阿兰 HP `5.25078`、能量 `15`；独立进程 replay 返回
  `ok=true, step_count=19, errors=[]`。归档 `/tmp/hsr-mvp-20260928.json.gz`，日志
  `/tmp/hsr_mvp_cli_run_20260928.log` 与 `/tmp/hsr_mvp_cli_replay_20260928.log`。
  该限定场景的 MVP 闭环已完成；所有修改仍在本地，未提交或修改 TBGD pin。
- 接下来的产品入口是 `simulator_v8_clean_core/CLI_MVP.md`；扩展内容时再处理对应机制，
  不把 `docs/MVP_KNOWN_GAPS_2026-09-28.md` 的全部条目重新变成 MVP 必做清单。

### 2026-09-26：PR #8 已确认事实的本地落实

- 用户本轮明确授权：绕过 MCP 协调工作流，直接本地实现；PR #8 中已确认的事实可直接作为
  规则依据，公式或数值不必在 TBGD 中另行找到。保留实际来源，不伪称为数据库或 native 实现。
  这覆盖本轮与旧“只认结构化 TBGD”限制冲突的部分；研究记录自身仍未知的语义不补造。
- 固定研究基线为 `a987d2607f135799a9427c9341ebdf002a1b2c90`；TBGD pin 未改。
- 本地已接入治疗/护盾完整操作数、带上限叠盾、固定能量恢复的 ERR 豁免、独立减伤乘积、
  动态防御属性池与单来源控制抵抗、11条共享类别免疫；普通多盾的未知消耗路径拒绝执行，
  不再按总和给出错误结算。终结技使用独立 SPNeed 成本，按扣费后最新状态结算回能，
  不再要求满容量或在队尾清空多余能量；规则注册版本升为 v7。
  同时修复关联的移除/驱散上下文、事务事件身份与资源监听后过期计划问题。
- 这些是本地未提交改动，不代表 P9 后续阶段、完整角色或全项目验收。
  具体覆盖、命令和残留边界见
  `live_validation_reports/pr8_confirmed_rules_local_execution_2026-09-26.md`。

### 2026-09-26：本地命令行战斗雏形（首场真实胜利已跑通）

- 用户已确定交付为命令行闭环、少量完整角色与敌人；暂不做 UI，不走 MCP 工作流。
- 新入口是 `simulator_v8_clean_core.cli`，使用现有 `.venv`；命令、输入和当前限制见
  `simulator_v8_clean_core/CLI_MVP.md`。CLI 经 `BattleSession` 复用正式 DecisionSystem，
  提供 query/play/run/replay；归档保留入场审计及全部正式 transition，不覆盖已有文件。
- 阿兰 E0/Lv1/无额外行迹与装备的正式出生、普攻、战技损血后当次天赋增伤、终结技插入与
  击杀回能已贯通。修复了状态参数作用域、动态值 name/hash、事件即时投递和去重、同速模板、
  插入行动的原回合归属及清场阶段转换。冻结的 Set(0.5) 行动成本也不再误算为 Add(0.5)。
- 怪物三来源发现保留两个被动；四个公共韧性状态真实安装，减伤由来源属性承担一次。
  纯表现控制器经结构与所选来源的私有身份逃逸检查后排除，缺失被动定义仍阻断。
- 内置双方脚本通过真实 CLI 跑出胜利，阿兰剩余 HP 约 5.25078、能量 15。范围是单波未击破
  战斗；致死受击回能和普通击破恢复仍有执行边界，不代表任意路线/全内容已支持。
  复现入口与具体限制见 `simulator_v8_clean_core/CLI_MVP.md`。
- 后续优先补上述真实玩法缺口；旧阶段顺序只作依赖参考，不能代替用户本轮范围。
  所有修改仍在本地，未提交或更新数据 submodule。

### 2026-09-28：MVP 范围与回能进度纠正

- 用户明确将虚韧性等特殊韧性机制、特殊韧性计数、多波出生移出 MVP 必做范围。
  继续完成少量角色与敌人的单波命令行战斗，不再以这些延期项阻塞验收。
- 此前“红韧性”是对 `RedStance` 的不严谨直译；PR #8 的现有来源记录仅区分其事件路由，
  没有确认它与虚韧性的对应关系。保留原始标识，不冒充已确认的游戏术语。
- PR #8 当前 head 已核对为 `6bec249c231645112b4fa07201b7322d00c9af4e`。此前实现使用
  `a987d2607f135799a9427c9341ebdf002a1b2c90`；其后的六个提交更新击破跨零段及状态首次计时
  研究，并未新增回能专题。本次核对不等于这些新研究已全部落实，TBGD pin 仍未改变。
- 普通回能、ERR、固定回能、终结技扣能与返能、击杀回能已有研究并已部分贯通。
  代码当前对致死受击及多请求受击回能主动阻断。核对最新相关正文、85 条 PR issue 评论与
  0 条行级 review 评论后，未找到这两个边界的明确结论；F07 §4.2 的攻击者回能例子不能
  直接确定受击方分配，§11 仍列逐段分配残留。已询问用户具体结论或记录位置，不能断言
  用户未在其他地方研究过。当前阻断是实现限制，不是已确认的游戏规则；缺少 native
  位置也不是拒绝已确认行为的理由。
- 本次进一步核对发现：正式能力图在产生削韧 mutation 时就主动阻断，不能只报告“击破恢复
  未完成”。当前无弱点匹配示例绕过了此路径。状态首次扣时、随机分支正式调用、多盾/复活等
  已知边界及其 MVP 适用范围集中记录于
  `simulator_v8_clean_core/docs/MVP_KNOWN_GAPS_2026-09-28.md`；本次仅盘点，未修改战斗逻辑或重跑测试。

长期总计划：

```text
simulator_v8_clean_core/P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md
```

已合并主线的历史检查点（其后本地成果见上文）：

```text
P9-A2 / PR #11 — accepted and merged
master checkpoint: 2d60a4305206bc11b67edf445a55478d90c96257
```

当前施工以最新“通用机制优先、内容逐步扩充”路线为准；已完成 MVP 的交付条件不变。
不重做 A2，不把旧阶段串行依赖或阶段聚合当成继续本地实现的前置。

用户于 2026-09-23 明确：PR #9 是失败测试片，不是本轮任务，也不是下一阶段的代码来源或前置。旧文档中“恢复 PR #9”的路线已被该决定取代；不读取、恢复、合并、移植或改动该 PR。后续以已合并主线加当前本地成果为基线，按 P9 新路线核对生产调用链并本地实现；不自动创建分支、提交或 PR。

## 仍未完成

- P9-S8C 剩余真实 RandomConfig caller/RNG-ledger integration、projectile、多 hit identity、barrier、parallel、sequence-select/timeline-wait，以及后续角色共享控制流、事件、状态、伤害、资源、队列、死亡、击破、形态和独立行动实体。
- P9-S5D2 的完整动作 transaction/replay 回验，仍等待 S8 随机控制流闭合。
- P9 完成后的全角色目录回验，以及记忆、欢愉专属内容增量。
- 全怪物、全召唤内容、全关卡环境和特殊玩法的数据卡扩面。
- 当前阶段已经明确归属的 P3/P4/P5 内容来源缺口。
- 外部推演器接入与更广的操作/对照流程可后续扩展；当前 CLI 已构成限定场景完整流程，UI 继续延期，推演策略不是内核任务。

这些缺口不能因为通用底座存在而标记为完成，也不能用 fixture 冒充真实内容可执行。

## 开工入口

新线程只读取与任务直接相关的最小集合：

1. 工作区永久约束：`AGENTS.md`。
2. 当前状态：本文。
3. 下一行为先按本文 2026-10-09 节定位；P9 总计划第 0 节及机制包按需要读取。
4. 相关生产符号、正式调用者和来源；需要追溯时才读对应旧执行卡。
5. `docs/AGENT_WORKFLOW_AND_VALIDATION.md` 第 0 节本地约定；不默认恢复旧审批工作流。

架构修改再读 `ARCHITECTURE_BOUNDARY_CONTRACT.md`、`FORBIDDEN.md`；规划或验收再读
`docs/AGENT_WORKFLOW_AND_VALIDATION.md`。禁止新线程默认通读全部计划、报告和历史验证器。

## 证据与历史

- P8 最终结论：`live_validation_reports/v8_p8_equipment_build_light_cone_relic_final_checkpoint.md`。
- P9-S8C1A ready-for-review 证据：`live_validation_reports/P9-S8C1A_WEIGHTED_SELECTION_IR_ready_for_review.md`；最终通过结论只认总计划 checklist、accepted 执行卡状态和合并后的 Git 检查点。
- P9-S8C1B 执行证据：`live_validation_reports/P9-S8C1B_ACTION_ENTRY_WEIGHTED_SELECTION_execution_report.md`；其真实 Direct 证明 action-entry 纵切并作为 S8C1C action 回归上游。
- P9-S8C1C 执行证据：`live_validation_reports/P9-S8C1C_REMAINING_ENTRY_RANDOM_CONFIG_SOURCE_CLOSURE_execution_report.md`；其 STRICT Direct/Catalog 证明当前完整 RandomConfig 来源与 formal-position 闭合，不代表 runtime RNG、S8C1/S8C 聚合或 S5D2 已完成。
- P9-S8C1 聚合执行证据：`live_validation_reports/P9-S8C1_RANDOM_CONFIG_GRAPH_AGGREGATE_execution_report.md`；其 STRICT Fast/Direct/Catalog 与 PR #4 最终 CI 证明当前静态 RandomConfig task-graph aggregate contract，不代表 S8C runtime/RNG 或 S5D2 已完成。
- P9-S8C2 执行证据：PR #5 正式 `[HANDOFF:REVIEW]` 评论 `5564689207`、执行 head `5e14526f4046626528aee4a594a8e7eb8a9ef14a` 与 CI run `34080289369`；独立 REVIEW 已核对生产 diff、聚焦测试和 Actions 日志。该证据只接受共享 weighted-selection executor contract，不接受真实 caller 或 S8C 聚合。
- Route A A1 执行与 REVIEW 证据：`live_validation_reports/P9_FORMAL_ACTION_GRAPH_ADMISSION_AUTHORITY_execution_report.md`、PR #10 `[RETURN_FOR_FIX]` 评论 `5570308533`、修复后实现 head `84ee94b4d1bf25221d783f8a84d7b79f8e46f896` 与 CI run `34122026242`。该证据只接受 formal action graph admission authority；A2 与 PR #9 caller/RNG-ledger 仍未验收。
- Route A A2-P0 执行与 REVIEW 证据：`live_validation_reports/P9-A2-P0_ACTION_WINDOW_STATUS_CALLBACK_ADMISSION_FINALIZATION_execution_report.md`、PR #12 REVIEW 返修评论 `5578826676` / `5579864543`、生产实现 commit `a73576c6d5d751f6c5d14713e5ed49883fc82b2f` 与最终执行 CI run `34193467352`。该证据只接受 merged-master L0 action-window status callback/task admission finalization prerequisite；PR #11 的 A2 runtime transport/routing 与真实 `CombatExecutor.execute(ActionCommand)` Direct 仍未验收，PR #9 caller/RNG-ledger 继续暂停。
- Route A A2-P1 执行与 REVIEW 证据：`live_validation_reports/P9-A2-P1_FORMAL_PROCESS_ONLY_SOURCE_IDENTITY_execution_report.md`、PR #13 REVIEW 返修评论 `5597805187`、生产修复 commit `d163e0d3225a8e31bfd4af602541049332614e59`、final EXEC head `4cca72510761331c9fb721999d436bf6f0861e66` 与 P1 CI run `34330329036`。该证据只接受 formal process-only task/own-effect canonical source identity closure；后续 same-owner formal blockers、PR #11 runtime transport 与 PR #9 caller/RNG-ledger 仍未验收。
- Route A A2-P2 执行与 REVIEW 证据：`live_validation_reports/P9-A2-P2_PROCESS_ONLY_TRIGGER_ABILITY_ADMISSION_IDENTITY_execution_report.md`、PR #14 final EXEC head `a5ad6031bbe02f0e7e90d7c227124814d4e662d1`、P2 CI run `34569640362` 与 squash merge `d1c28c0c0e10ed8b268739b71bab1784574a8d93`。该证据只接受 process-only `TriggerAbility` canonical leaf 的 A1 admission identity closure；后续 same-owner formal blockers、PR #11 runtime transport 与 PR #9 caller/RNG-ledger 仍未验收。
- Route A A2-P3 执行与 REVIEW 证据：`live_validation_reports/P9-A2-P3_S8C_WAIT_ANIM_STATE_PROCESS_ONLY_BARRIER_RETIREMENT_execution_report.md`、business/evidence head `62bf4b15561e48c80fb308d13951c226bac34be5`、final EXEC head `1ccedb3630b81dc190e52b3f0c2160f3e344775e`、final-head CI runs `34700147202` / `34700147243` 与 squash merge `dae1441e3227b3c0ab86cb4ca847368594832c1b`。该证据只接受 WaitAnimState process-only presentation barrier retirement；FireProjectile、S11、PR #11 runtime transport 与 PR #9 caller/RNG-ledger 仍未验收。
- 历史 P9 验收只代表对应 checklist/Git 检查点的声明范围；新路线的本地进度以上文为准，不能靠旧报告标题推断当前能力。
- 文档归属与归档：`simulator_v8_clean_core/DOCUMENTATION_INDEX.md`。
- 瘦身前交接全文：`simulator_v8_clean_core/docs/archive/CODEX_HANDOFF_PRE_SLIM_2026-07-24.md`。

## 工作边界

- runtime 不读 raw TBGD、TextMap、旧 v7 或旧 model pack。
- 内容差异进入数据卡与机制图，不进入核心特判。
- 缺来源、缺语义或身份冲突必须 blocked 且 state unchanged。
- UI 和推演器不复制规则。
- 检查真实行为与正式调用链；仅在具体风险需要时增加反例，不为覆盖率或形式验收堆测试。
- 根据实际改动选择必要检查；不默认附加全量、目录检查或历史验证套餐。
- 本地实现、自查和交接由主线程负责；旧独立执行/验收角色不是当前任务前置。
