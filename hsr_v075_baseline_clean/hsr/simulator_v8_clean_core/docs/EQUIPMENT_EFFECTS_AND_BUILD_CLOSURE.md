# R06 光锥与遗器完整效果

本批由用户安排 dsh / DeepSeek 实现，Codex 集中验收。实现基线 `b35d0a7`；
当前状态只在 [CODEX_HANDOFF.md](../../CODEX_HANDOFF.md) 维护。
执行成本与来源采用遵循 [本地约定](AGENT_WORKFLOW_AND_VALIDATION.md)，不另设审批或验证套餐。

## 交付目标与范围

把固定来源内已发布光锥、遗器成品及套装效果接入同一正式构筑与战斗链：

```text
成品输入 → 装备装配与参数绑定 → 静态属性／动态启动
         → 事件触发／阈值变化／实际结算 → 到期与施加者清理 → 来源审计
```

范围包含光锥等级、晋阶、叠影和命途资格，遗器六部位、主副词条和套装阈值，
以及这些装备的战斗效果。复用既有成品输入，不模拟获取、强化过程或新增战中换装功能。
构筑表单中的替换／卸下通过重新装配生效；战斗中状态到期、施加者退场及再次施加按既有生命周期执行。

这是一个整包：目录装配、共同机制、同族接线和组合路线连续完成后交回。
不能只解开一个光锥、只修改准入标签，或仅交一张缺口报告就算本批完成。
装备实际需要的共享事件、目标、数值或快照能力随本批补齐，归回既有生产权威；
不扩做 R07/R08 的完整角色与阶段，也不将这些装备所需的局部能力简单推给后续包。

## 已核对基线

2026-10-26 在固定 TBGD `14c1d18f91a8101d610e6c523447a7517de3fae1`、
`b35d0a7` 上核对：

- `EquipmentConfig`：162 张，均 `Release=true`；`RelicSetConfig`：58 套，均已发布；
  正式 IR 有 90 个套装阈值、224 个 `mainline_equipment` 图。
- 复用 `arlan_fleet_vs_antimatter.json` 的来源范围，仅构建 RuleBook，不创建会话：
  8 个图尚未通过 `_equipment_graph_runtime_closure_reason`，其余 216 个通过该静态检查。
  **静态通过不代表运行、数值、清理或所有分支已经验证。**
- 旧 `test_equipment_battle.py` 只列出 6 个阻断能力，已不能充当当前完整名单。
  修改其预期时依据下面的行为与正式证据，不把实际结果直接抄成新的白名单。
- 基线构建 34.87 s，墙钟 35.75 s，峰值 829,276 KiB；摘要在
  `/tmp/r06_equipment_baseline.json`。这是一次现有装备场景范围构建，不是全角色／全怪物编译。

### 当前可见缺口与共同生产者

| 真实来源能力 | 当前首个可见阻断 | 本批必须追完的行为 |
| --- | --- | --- |
| `Ability20015` | `OnBeforeSkillUse` 仍归旧阶段 deferred | 普攻条件、当前技能延迟修正、实际行动间隔与作用域结束 |
| `Ability21033`、`Ability23002` | `OnTriggerDeath`；后者另有 `OnAfterBeingAttacked` | 按正式事件区分击杀者／死者／受击者；治疗、血量阈值、增益次数及到期，不重复消费同一事件 |
| `Ability23033` | `OnAfterSkillUse` deferred | 技能类型、波次条件、回能、行动延后／提前及动态计数的完整分支 |
| `Ability23051` | `OnBeforeSkillUse` deferred | 终结技前的群体增益、群疗、最低 HP 目标追加治疗，以及是否具有派生单位的条件分支 |
| `Ability23041` | `OnBeforeHitAll` deferred | 本次攻击的正式目标与伤害数据；按施加者筛选附加弱点状态、此次增伤、受击侧减防光环及退场清理 |
| `Ability23013` | `OnSnapshotCreate` 缺正式来源 | 治疗数据读取、存储／快照、后续攻击消费及重置，区分治疗者、攻击者和目标 |
| `Ability20024` | `OnElationPointChange` 范围／字段未准入 | 读取正式欢愉资源的阈值进入／退出，正确增加／移除属性，不重复堆叠 |

原始能力位于 `Config/ConfigAbility/Equip/`；`23041` 在 `Equip32.json`、`23051` 在
`Equip36.json`、`20024` 在 `Equip40.json`，其它列项在 `EquipmemtAbility.json`。
这是当前首个阻断的定位表，不是完整修改清单。先读同图全部回调、子任务和同族消费者，
把隐藏在首个阻断后的缺口一次归并；不得每放开一个事件就重跑整场来寻找下一个错误。

## 正式调用链与复用边界

| 环节 | 现有权威／入口 | 实施要求 |
| --- | --- | --- |
| 来源与目录 | `tbgd/light_cone_cards.py`、`relic_cards.py`、`equipment_ability_families.py`、`lowering.py` | 保留正式目录、参数来源、publication 与引用一致性；可靠机制资料可通过现有规则注册接入，不必复刻无战斗意义的原生组织 |
| 成品装配 | `builds/equipment_assembler.py`、`relic_set_assembler.py` → `character_assembler.py` → `scenarios/build_state.py` | 保留输入校验、资格与套装贡献边界；参数属于确切装备实例／叠影／套装阈值，不能借用另一实例的上下文 |
| 动态运行 | `systems/ability.py`、`status_callbacks.py`、`ability_property_watchers.py`、`event_dispatch.py` 及相应数值领域 | 优先扩现有消费者与 producer，整图 executable 必须对应全部战斗分支可执行；不按装备 ID 或名称写内核分支 |
| 属性与生命周期 | `systems/unit_stats.py`、`status.py`、`dynamic_values.py` | 复用有效属性、精准状态实例、同事务清理与 R05 的 HP 钳制事实；不要另造属性公式或状态仓库 |
| 公开查询／操作 | `queries/equipment.py`、`BattleSession`、CLI | 装配预览、战斗准入与实际执行口径一致；不另建装备操作服务或由 UI 补算 |
| 审计 | `core/source_audit.py`、原生 mutation／settlement | 从实际生产链确定正式预期，不能用“声明和副本相等”代替验证来源 |

只读取本表与所选行为直接相关的代码；P8 旧执行卡只用于具体规则追溯，不重新执行旧阶段套餐。

## 一次性实现约束

1. **参数和构筑隔离**：光锥叠影／等级与角色技能等级互不混用；套装不足阈值不启动、跨过阈值
   只激活一次。同装备两名佩戴者、同名状态不同施加者均按实际实例绑定。删除装备后的新构筑
   不保留旧参数、贡献、启动任务或派生状态；不要求新增战中换装协议。
2. **事件由对应领域签发**：行动／命中读取正式准入事实，治疗读取正式治疗结果，资源范围读取
   实际资源 producer。验证 actor、target、命中／行动／回调身份、事件时点与作用域。
   不从普通 payload、source_trace、evidence 或相邻日志重建权限；必要字段进入正式类型。
   相同合法事件不得重复发放，非法或缺失上下文必须在任何状态、资源、RNG 修改前阻断。
3. **临时效果只影响正式范围**：`ModifyCurrentSkillDelayCost`、伤害数据修改、回能与计数
   对准来源定义的当前行动／命中／状态，不泄漏到后续行动。保留 R05 的有效 MaxHP 与
   `action_sp_base` 单一回能生产者契约；DoT、额外伤害和插入行动是否参与按正式条件区分。
4. **快照语义与序列化快照分开**：先沿 `23013` 的治疗数据生产、存储、攻击消费、重置追完。
   若实现原生 snapshot 回调，只能由真实战斗快照 producer 提供带身份与寿命的事实；
   单位出生、`BattleState.snapshot()` 或导出 JSON 都不能冒充该事件。若采用可靠资料定义的
   等价战斗规则，通过正式 IR／规则注册表达并记录依据，不强行制造原生事件。
   两种实现都必须证明存储值、取值时点、受益者及消费次数，不以循环重复累加代替存储规则。
5. **阈值和清理是同一生命周期**：覆盖低于／等于／高于阈值、进入、重复通知、退出、再次进入；
   施加者／目标变化后只移除该来源的条目，保留兄弟实例。到期、移除和再施加不能串用旧动态值。
   HP 上限收缩继续走共享原生钳制链，不手写 HP 或绕开 `StatusHPClampFact`。
6. **失败与审计不靠自报标签**：同组后续叶子失败应回滚本组状态、资源、队列与 RNG。
   原生 settlement 必须关联实际 mutation 和正式规则；审计由真实写边界／生产者选择，
   从正式 IR 与原生事实确定数值、目标、实例及完整允许差分。删标签、改记录名、联合修改
   metadata 与 settlement 都不能授予权限；合法完整 transition 必须先通过，不能只测试拒绝。

这些约束只针对本批改变的边界选择必要检查，不为每件装备复制一套负例矩阵。
如出现未知规则，先核对既有来源与适用资料；已确认规则直接实现。只有会改变范围或确有冲突
且无法消解的规则才提交具体问题，不把“尚未读源码／未运行”包装成待用户裁决。

## 执行顺序与验证安排

### 内部步骤一：一次完成行为归并

复用基线结果，沿装配、触发、结算、到期／退场与再次施加读完相关链。
在本文交付表中将全部 162 张光锥、58 套／90 阈值归到实际行为族，列出共用根因与消费者；
既有支持条目、实际缺口和未验证分别标明，不另建目录平台或为每张卡生成报告。
不重复全目录构建；本次已经构建的相同代码／范围可直接命中缓存。

### 内部步骤二：集中实现并用小检查排错

按参数／装配、行动与伤害事件、治疗与存储、资源范围、清理的共同生产者依次完成。
先用真实叶子与正式类型化组件输入查清各族行为、来源及原子性；修改共享函数前核对全部调用者。
普通组件检查不得隐式重编译完整来源；真实规则和会话前置使用明确标注的 integration 模块。
阶段性检查发现问题就保存正式输入与失败前状态，回到该组件定位；同根修复完成前不反复从入场重跑。

### 内部步骤三：合并代表性公开路线

- 路线 A 优先复用 R05 阿兰／娜塔莎与来源关卡：正式装备构筑，包含受击／击杀相关恢复、
  治疗数据存储、后续攻击消费、到期／再次触发及后续公开提交。先核对每张光锥的实际命途资格。
- 路线 B 优先复用三月七／娜塔莎及现有可执行普通角色：覆盖终结技前群体效果、普攻行动
  间隔修正和至少一种套装阈值的实际结算；多名佩戴者与团队增益不得串源。
- 命中前附加弱点筛选、欢愉范围等未自然覆盖的边界，以真实装备 IR 和正式领域 producer
  的定向检查补足并明确标注组件输入。若改动只有公开路线才能证明，再补一条直接消费它的
  路线；不为每件装备各跑一场，也不由装备组件证据宣称整个欢愉／派生角色已经完成。

路线从 `assembled_character_build` 与来源波次入场，外部 `advance/submit` 驱动，
不在运行中注入状态、改 HP／计数或手工派发事件冒充自然过程。支持为组件边界显式构造输入。
用实际 mutation／settlement 与独立来源预期判断效果，不能只断言战斗继续或某错误码消失。
首次有效运行保存归档与中间观察，后续只查字段就读取该归档。

组件完成后合并运行必要 integration；一次构建每个必要规则范围，复用不可变规则和只读前置，
成功路线的可变会话独占。重任务串行持有 `/tmp/hsr-v8-validation.lock`，记录耗时／峰值。
不默认跑全量普通回归、全目录编译或所有历史验证器；规则／来源发生变化时的缓存重建另列。
只有修改归档／身份／确定性路径，或现有证据不能覆盖时才独立 replay；普通装备数值接线不自动触发。

## 整包完成与交回

- 全部固定已发布装备均有正式归属；列出的 8 个缺口及其同根消费者闭合，不靠删分支或降为
  non_gameplay 通过。新发现的战斗分支保留到本包一并处理，不能静默缩小目录。
- 分开报告来源／静态准入、构筑、运行、生命周期与公开路线证据；每族共享能力与实际装备
  挂载都有证据，未完整接入的角色仍保留其角色包归属，不外推全角色可用。
- 保留能发现实际错误的最小回归，集中复查生产者、传播、消费者与审计分派后再冻结；
  不仅逐条补最后一轮反例。提交说明给出新增可用行为、共同修复、实际验证与具体剩余依赖。
- 结果直接替换本文末尾的交付表，交接只更新状态和入口，不追加逐轮流水账。
  实现方未获另行授权不提交、不推送、不改 submodule、依赖或环境；整包交回 Codex。

## 交付表（2026-10-28，已验收）

实施起点 `70b9e07`，整包验收后于 2026-10-29 提交为 `a961e9f`，未推送。全部 224 个 `mainline_equipment` 图通过运行时静态闭包；
162 张已发布光锥、58 套遗器、90 个阈值均进入正式 IR。8 个原始缺口全部闭合，无删除分支或
降级为 non_gameplay。

| 行为族 | 对应来源／同族装备 | 本次改动与原生执行证据 | 公开路线或组件边界 | 剩余依赖 |
| --- | --- | --- | --- | --- |
| 成品装配与静态贡献 | `light_cone_cards.py`、`relic_cards.py`、`equipment_assembler.py`、`relic_set_assembler.py`；224 图 | 162 光锥（等级／晋阶／叠影）、58 套遗器（六部位、主副词条）、90 阈值保持正式目录与参数来源；光锥参数按技能叠影索引绑定。`Ability20024` 的区间 Min 纳入 modifier 参数继承（`_modifier_range_dynamic_hashes`），避免 watcher 读不到叠影值。 | 路线 A/B/C 均从 `assembled_character_build` 与来源波次入场；路线 A 同时验证 `MRelic_302_Sub` 速度阈值实际激活（attack +8%）。 | 无（目录/装配范围内）；合法自定义成品按正式输入校验，获取和养成过程不在战斗范围。 |
| 行动、伤害与资源事件 | `Ability20015`（OnBeforeSkillUse）、`Ability23033`（OnAfterSkillUse/OnEnterBattle）、`Ability23041`（OnPhase1/OnBeforeHitAll）、`Ability23013`（OnListenAfterAttack） | `ModifyCurrentSkillDelayCost` 缺省 `ModifyFunction` 定为 Add（真实 raw 任务 → TimelineSystem，−12% 延迟登记为 88）；`Pursued + FinalFormulaType=ByPureDamage` 在格挡副作用之前由正式 executable emission 决定最终公式与 indirect 身份，进入 additional 纯伤害契约（不参与暴击／普通增伤、无暴击 RNG，仅保留目标侧倍率；普通 additional 行为不变）；审计在实际 additional 分派路径统一按正式 emission 的 final_formula_type／is_indirect 校验 metadata 与 settlement（含 20018/21029 的空公式+indirect 正例），并要求存在匹配该 mutation 的原生 `additional_damage`／`damage_system` 结算；`OnSnapshotCreate` 经正式事件传输并在公开路线实际执行；元素源 `ReadTargetType` 允许 raw 占位 `DamageType`；`OnSnapshotCreate` 由真实治疗 mutation 投影 `heal.snapshot.created`；`ByCurrentSkillType` 省略字段沿用既有 TBGD 缺省枚举 Normal。 | 组件：`test_equipment_heal_formula_delay_cost.py`（真实 20015 raw 任务 → 88 行动值）、`test_equipment_heal_record_snapshot.py`（快照身份/寿命、纯伤害对比、双佩戴者）。路线 A 胜利并出现 `status_damage_identity` 与真实 `OnSnapshotCreate` 记录，`_TotalAmount` 由正归零；路线 C 胜利并挂载 `MEquip_21033_Main`/`MEquip_23033_Sub`。 | 23033 雷遁“两次普攻后行动提前”尚未在自然路线完整跑出（仅状态挂载与真实条件树）；20015 行动提前由真实任务组件证明。 |
| 死亡相关恢复、治疗与存储 | `Ability21033`、`Ability23002`（OnTriggerDeath/OnAfterBeingAttacked）、`Ability23013`（OnAfterDealHeal/OnSnapshotCreate）、`Ability23051`（OnBeforeSkillUse） | 缺 FormulaType 的 HealHP 采用 `HealByHealerAttack`（caster.attack 基数），三张光锥真实 raw 形状校验；跨 modifier 内部动态值（治疗记录 `_TotalAmount`）下沉为 owner-unit scope 并带 owner 过滤，避免他人治疗串源；`SetDynamicValueByHealDataProperty` 的 event_value operand 只由 `HealEventFact` 读取并校验，缺失／错配在写入前阻断（不再以 0 掩盖错配）；heal mutation 由类型化 `HealEventFact` 绑定真实治疗者/目标/数值/事件 ID/source/顶层目标/window/scope/快照身份，并以 `_claims` 封存全部业务字段（`replace` 复制或改写 mutation/金额即拒绝）；派发入口在两个事件写入前校验事实、事件身份与作用域；快照归属治疗者（`actor_local`），双佩戴者各记各自治疗、无来源冲突。 | 组件：`test_equipment_heal_record_snapshot.py`（金额篡改、事件／目标／作用域错配、重放换 event_id、复制事实改值、无生产者快照、双佩戴者独立累计、快照幂等）。路线 A：23002 OnTriggerDeath 与 OnAfterBeingAttacked 治疗、0.24 伤害加成、23013 记录→攻击消费→清零与真实快照派发。路线 B：23051 终结技前群疗 + 全体 `MEquip_23051_Sub` 0.24 增伤。 | 路线 B 为定向自然段（观察到两类效果后停止，未宣称整场胜负）。 |
| 属性／资源阈值与团队效果 | `Ability20024`（OnElationPointChange）、`Ability23051`（OnStack 增伤） | `OnElationPointChange` 的 `{Min,OnEnterRange,OnExitRange}` 原生形状下沉为既有 AbilityPropertyWatcher/Range（新增 `property_source=elation_base_points`），由 `elation.points.changed` 正式事件触发重查；重复区间不重复通知、退出移除、再进入重加。`ByTargetCount` 召唤物分支沿用现有 producer（路线 B 无召唤物时 0.24，有召唤物时参数 0.12 额外项保持来源定义）。非装备来源的同形 `OnElationPointChange` 不删除：Monster_W5_JK_00 的 [0]/[1] 保留真实回调和明确 blocked 原因（`test_non_equipment_native_range_callbacks_remain_visible_and_blocked`）。 | 组件：`test_equipment_elation_point_range.py`（真实 20024 IR，阈值恰好 10 进入、重复变化不重复、跌回移除、再次进入重加、CriticalDamageBase +0.2）。路线 B：23051 Redoubt 0.24 逐单位绑定，`MEquip_23041_SubOnEmemy` 光环与被打目标 DEF −0.12 实际落地。 | 23041 “敌方拥有装备者添加的弱点” 的 +60% 伤害分支仅有 Remodifier 真实 payload 选择组件（`test_equipment_remodifier_include_limbo.py`），当前已装配角色无弱点施加者，未自然跑出。 |
| 到期、退场、清理与再次施加 | `Ability23002`（Effect OnPhase2）、`Ability20024`（range exit）、`Ability23013`（RemoveWhenCasterDead/Reset）、`Ability23033`（RemoveSelfModifier） | 23002 Effect 用 OnPhase1/OnPhase2 门控并在 Phase2 移除；20024 区间退出只移除该来源 Sub；23013 每次消费后 `_TotalAmount` 与 Flag 归零、再治疗可重新累计；23033 Raiton 状态 RemoveSelfModifier 保留在真实回调树中。 | 路线 A：23002 增益跨回合仍按来源声明保留/清理，23013 总记录多次由正归零并再次累计；组件：elation 退出/再进入、23013 双佩戴者独立累计与快照幂等、重放/复制事实拒绝。 | 23033 两次普攻后的 RemoveSelfModifier 仅在静态/条件树与专门组件覆盖范围内，未在整场自然链观察。 |

### 实现方验证记录（2026-10-28，最终）

- Codex 四个复验入口合并：**29 passed**（`test_r06_codex_acceptance.py` 11 + `test_r06_contract_followup.py` 9 + `test_r06_final_formula_audit_review.py` 3 + `test_r06_additional_settlement_boundary_review.py` 6）。
- 合并边界：
  - 常规：**79 passed**（出生／快照分离、治疗公式／延迟组件 7 项、可持续资源、当前技能延迟）。
  - R06 integration：治疗记录 **22 passed**、elation **2 passed**、remodifier **1 passed**、`test_equipment_battle.py` **2 passed**；damage／break 审计与格挡回归 **30 passed**。
- 代表性公开路线：
  - 路线 A（两波公共路线；阿兰 23002+遗器、希露瓦 23033、娜塔莎 23013）：**victory**（约 2:11），严格审计下通过，实际执行 `OnSnapshotCreate`，覆盖 23002 OnTriggerDeath/OnAfterBeingAttacked、0.24 增伤、23013 记录→消费→清零、遗器阈值与 23033 入场回能。
  - 路线 B（Stage 307311）：定向自然段；路线 C（Stage 200021050）：**victory**。两者沿用前轮证据，本项审计修复不改变路线行为，按约束未重跑整场。
  - R05 普通队伍路线在严格审计下复跑 **2 passed**（约 5:58），确认未回归既有角色路线。
- 纯伤害／普通间接附伤、原生结算存在性、快照事实与双佩戴者、非装备范围保留、正式传输均有真实装备 IR 的组件／反例检查；未删反例。
- 实现方验证时未提交、未推送；未更新 submodule、依赖或环境。

## 最终复审修复与复验（2026-10-28，通过）

Codex 已复查本批源码、正式调用链及审计分派，集中验收通过，未发现新的可操作问题。

- additional 的最终公式与 indirect 身份统一取自正式 executable emission；真实 20018／21029 的普通间接附伤原生结算通过。metadata 与正确重关联后的 settlement 降级均被拒绝。
- 每笔应有附伤结算必须匹配实际 mutation ID、`additional_damage` 类型及 `damage_system` 生产者；缺失、改名、错 source、非法 payload 均拒绝，再核对来源身份、HP 路由形状与最终公式。
- 四个历史复验入口与永久治疗／快照、治疗公式／延迟、伤害／格挡及出生／快照分离回归合跑：**78 passed，27.74 s**；墙钟 **30.72 s**，峰值 **891,928 KiB**，日志 `/tmp/r06_final_acceptance.log`。
- 实现方的装备闭包、elation／remodifier 及公开路线证据保留；本轮按影响范围复用 A／B／C 和 R05 整场／自然段证据，未重复全量或整场验证。交付表列出的三个组件分支与路线 B 边界继续保留。
- 验收仅更新本文和交接，未修改生产代码；整包随后提交为 `a961e9f`，未推送，未改 submodule／依赖／环境。
