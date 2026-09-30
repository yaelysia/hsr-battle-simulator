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

### 2026-09-30 实战对比记录与 MCP 协作入口

- 游戏实战的逐项记录方式仍在讨论，尚未授权实现记录器。前次误加的独立 HTML
  页面及检查文件已经撤回；当前没有可用的游戏观测记录器，也没有与战斗归档对照的功能。
  如果以后决定实现，应优先复用现有模拟器的场景、合法动作、提交、快照和 replay；
  游戏实测只作并列观测，不能反向覆盖内核规则。具体交互和粒度仍待用户决定。
- 用户提出可能恢复 local-workspace-mcp 做多 AI 协作。本次仅同步项目事实入口：
  根目录 CODEX_HANDOFF.md 已改为当前导航，MCP project_info 会列出 AGENTS.md 与它。
  近期战斗实现仍是本地未提交改动，**没有**补录为 MCP 任务、批准计划或审核通过记录；
  历史账本不能充当本轮交付证据。是否重新启用审批工作流由用户后续决定。

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
- 本轮修改仍在工作区，未提交、推送或更改 TBGD pin。下方各历史检查点只描述其当时边界。

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
3. P9 总计划第 0 节当前路线及涉及的机制包。
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
