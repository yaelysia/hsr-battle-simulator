# P8-R1 召唤关系初始化与通用光环生命周期修复执行卡

## 执行配置

- 任务性质：P8-S8 验收后的跨系统修复门，不重新定义或撤销 S8 已完成的光锥机制图闭合。
- 对应问题：P8-I19。
- 硬前置：P8-S8 与 CHAR-M1 已验收，基线不得早于检查点 `137167d`。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`max`。
- 推荐模式：普通聚焦模式；若使用 Goal 模式，Goal 只能覆盖本卡，到 `ready_for_review` 必须停止。
- 并行约束：若遗器轨正在施工，必须使用独立 Git worktree。本卡可与 P8-S9 至 S14 并行，但必须在 P8-S15 开始前验收并合入其基线。

## 前因后果

P8-S8 已证明当前 162 张已发布光锥的机制图本身均可 lowering、admission 和执行。CHAR-M1 又关闭了记忆角色与忆灵构筑的外部依赖。随后按正式角色构筑重新运行光锥目录启动时，结果为：

```text
159 started
3 equipment-side startup blocked
0 external character-build dependency
```

三项阻断分别落在：

- 《将光阴织成黄金》：启动时需要解析装备者与其忆灵；当前战斗尚未建立召唤关系状态，且后续出生的忆灵也没有通用光环补投影。
- 《愿虹光永驻天空》：开局角色创建监听会比较“该角色的忆灵”和当前事件实体；当前把“暂时没有忆灵”误判为目标解析错误。
- 《致长夜的星光》：启动时会为忆灵侧安装监听；当前把合法的空忆灵集合误判为召唤运行时缺失。

这不是三张光锥各自缺少效果实现。共享根因有两类：

1. 正式战斗在注册装备 provider、执行启动效果和派发开局事件之前，没有显式建立一个 schema 合法的空召唤关系状态。
2. lowering 已保存 `IsHaloStatus`，但 runtime 没有消费这一语义。当前 AdditionConfig 子状态只对应用当刻的目标执行一次；之后出生、离场、死亡、复活或改变归属的单位不会自动加入或退出光环。

全量 TBGD 中存在大量真实 `IsHaloStatus=true` 来源，且分布于装备、角色、忆灵、怪物和关卡能力中。因此必须修复通用内核，不能增加三张光锥或装备专用分支。

## 详细阶段目标

完成本卡后，系统应同时具备以下能力。

### 1. 战斗出生即具有合法的空召唤关系

所有通过正式 scenario 构建的 `BattleState`，在任何 provider 注册、装备启动效果、BattleSetup 或角色创建事件执行前，都必须已经包含一个由召唤系统统一定义的空运行时结构。

这个结构表示“当前没有召唤单位”，不是“召唤系统不可用”。它必须：

- 使用召唤系统当前 schema 版本和同一套构造 / 校验逻辑，禁止在 scenario 或验证器中复制手写字典。
- 能被 target、condition、status、summon、snapshot 和 replay 共同读取。
- 明确区分合法空状态与字段缺失、版本错误、索引损坏等非法状态。
- 不触发任何召唤单位出生，也不为角色凭空创建忆灵。

直接手工构造且缺少或损坏召唤状态的 `BattleState` 仍必须 fail-closed；不得让 target 层在读取时偷偷把错误状态补成空状态。

### 2. 目标查询区分“空集合”和“解析失败”

召唤目标查询需要表达三种不同结果：

1. 成功解析且有目标。
2. 成功解析但当前没有匹配目标。
3. 因 schema、来源、表达式或关系损坏而无法解析。

消费方根据自身语义处理：

- 条件判断面对合法空集合时应得到可计算的 `false`，不能报“首目标无法解析”。
- 对群体施加效果面对合法空集合时应形成可审计的 no-effect，不得产生状态 mutation。
- 光环面对合法空集合时仍需保留有效光环关系，以便未来成员加入。
- 必须选择一个目标的动作在合法集合为空时仍应不可用，不能把“空集合可解析”误解释成“动作可以执行”。
- 缺失、损坏或自相矛盾的召唤运行时继续 blocked 且 state unchanged。

不得通过把所有目标错误都改成空集合来完成本目标。

### 3. 建立来源驱动的通用光环关系

只有真实 IR 中明确带有 `IsHaloStatus=true` 的 AdditionConfig 子状态才能建立光环。不能根据状态名称、目标是群体、持续时间永久或当前三张光锥反向猜测。

光环运行时必须保存或能够唯一重建：

- 父状态实例。
- AdditionConfig 子效果。
- 原始目标表达式。
- 施加者、来源实例与机制来源。
- `AliveOnly` 等已存在的成员资格约束。
- 当前已投影成员及每个子状态的稳定来源身份。

这些信息必须以通用、可序列化、可校验的状态表示存在；不能保存 raw TBGD payload、Python callable 或装备专用对象。若建立额外索引，父状态关系仍是唯一事实源，不能出现两套会漂移的权威状态。

### 4. 光环成员随战斗状态变化自动对账

通用 reconciliation 至少覆盖以下时机：

- 父状态首次添加。
- 父状态叠层、刷新或动态值变化。
- 父状态到期、驱散、主动移除或来源单位被清理。
- 单位出生、离场和替换。
- 单位死亡与复活。
- 已有通用 transition 支持的 owner、队伍或召唤关系变化。
- snapshot 恢复后的后续 transition。

每次对账必须保证：

- 新进入目标集合的单位恰好获得一次当前版本的子状态。
- 已经是成员的单位不会因重复事件叠加一份相同来源。
- 离开目标集合的单位只移除本光环投影的子状态，不删除同名但来自其他来源的状态。
- 后出生单位继承父状态当前叠层和动态值，不回到初始值。
- 父状态更新后现有成员与未来成员观察到同一版本。
- 多个装备者、多个父状态和同名子状态之间来源隔离。
- 父状态消失后不留下孤儿子状态或悬空关系。

### 5. 召唤登记、事件与光环投影顺序一致

单位出生 transition 必须保证监听器处理“单位已创建”事件时，能够同时看到：

- 新单位已经存在。
- owner / summoner 关系已经登记。
- 召唤运行时索引已经更新。
- 当前有效光环能够把该单位识别为成员。

如果关系登记、目标解析、光环投影或必需监听结算中的任一步失败，正式 transition 不能留下“单位已出生但关系或光环未完成”的半提交状态。blocked 结果必须 state unchanged，并保留具体失败来源。

### 6. 三张真实光锥与完整目录收口

修复后必须使用正式构筑和真实能力图证明：

- 《愿虹光永驻天空》在开局没有忆灵时正常注册监听，空集合条件求值为 false；以后真实忆灵出生时，监听可根据已登记关系命中。
- 《致长夜的星光》在开局没有忆灵时正常完成启动；以后真实忆灵出生时，其既有创建监听 / 状态路径可执行。
- 《将光阴织成黄金》在开局只对当前成员生效并保留光环关系；忆灵晚出生后获得当前叠层对应的子状态，父状态更新和移除也能同步。
- 当前 162 张已发布光锥均通过正式目录启动，装备侧失败与角色构筑外部依赖同时为零。

上述光锥身份只用于最终目录回归和报告定位。生产实现、主样例选择与通用验证不得按固定 ID 或名称分支。

## 本阶段只做

- 建立正式战斗的空召唤运行时初始化边界。
- 回正召唤目标查询的“有结果 / 空结果 / 错误”语义。
- 将现有 `IsHaloStatus` lowering 事实接入通用状态与单位生命周期。
- 修正出生 relation、创建事件和光环 reconciliation 的必要提交顺序。
- 修复本轮真实触发的 shared target、condition、status、summon、event、snapshot / replay 缺口。
- 更新 P8-S8 目录启动分类，使其反映修复后的当前事实。

## 本阶段不做

- 不重新实现三张光锥的伤害、资源、状态或监听规则。
- 不把条件型战斗效果提前折算到静态面板。
- 不改 S5 已建立的光锥静态贡献账本；真正无条件的固定属性继续在构筑装配阶段进入面板。
- 不强制记忆角色在战斗开局生成忆灵。出生时机仍由真实召唤 / 生命周期来源决定。
- 不扩面其余五个尚未正式准入的记忆角色与忆灵内容。
- 不实现全部角色、怪物、关卡光环来源的完整内容卡；本卡完成的是通用光环 runtime，并对当前已发布光锥来源做穷尽验收。
- 不建立 equipment-specific halo handler、光锥 ID 分支或验证专用 runtime。
- 不修改 P8-S9 之后的遗器定义、实例或词条实现。

## 静态与动态边界

本卡必须保持以下分层：

```text
无条件、只依赖构筑输入的固定属性
    -> 构筑装配器
    -> 最终面板

依赖事件、状态、目标关系或战场成员变化的效果
    -> provider / listener / ability graph
    -> runtime transition

IsHaloStatus 光环
    -> 来源驱动的动态成员关系
    -> 状态生命周期与单位生命周期协同对账
```

即使一个光环从开局开始长期存在，只要它作用于会出生、离场或改变资格的战斗单位，就不能被压平成角色面板属性。

## 来源与模型约束

开始编码前，执行线程必须对当前已发布光锥图中的全部 halo 子效果建立结构化来源矩阵，至少记录：

- 父状态和子状态身份。
- 目标表达式形态。
- `AliveOnly` 的真实取值。
- 子状态是否带持续时间、叠层、动态值、chance 或嵌套 AdditionConfig。
- 当前 lowering、admission 和 runtime 消费状态。

矩阵必须从当前 source fingerprint 重新生成，不固定当前数量。若发现 chance、嵌套光环或成员关系语义无法由现有结构确定，并且会改变本卡目标或原子性设计，必须停止并交回规划线程修订，不能自行猜测。

lowering 对 `IsHaloStatus` 必须使用严格布尔语义。字段缺失表示普通 AdditionConfig；错误类型不能按 truthy 值启用光环。每条关系必须保留父状态、子效果和原始字段路径。

## 原子性、审计与回放约束

- 父状态和其必需子状态 / 光环关系的首次建立必须作为一个可信结果提交。
- 出生单位、召唤关系、光环成员变化和由创建事件触发的必需结算不得形成可被正式推演器接受的部分后继。
- reconciliation 必须幂等；相同状态重复执行不得生成重复 mutation。
- 每个新增 mutation 都要有 settlement，并能反查到父状态实例、子效果、能力图、装备实例和 raw `IsHaloStatus` 来源。
- process-only 的空集合记录必须明确 `state_unchanged=true`；存在持久光环关系时，关系建立 mutation 与目标为空的 no-effect 记录要分开表达。
- snapshot / compact state 必须保留后续对账需要的语义状态；replay 不得依赖历史 `/tmp`、重新读取 raw TBGD 或重新猜测成员。

## 目标与证据映射

| 目标 | 允许通过的结果 | 不能通过的结果 | 证据 |
|---|---|---|---|
| 空召唤状态 | 正式状态在首个启动效果前已有合法空 schema | target 读取时临时 fallback，或验证器手填假 servant | initialization-order matrix |
| 空集合语义 | condition 可计算 false，群体效果 no-effect，动作仍不可用 | 把所有错误吞成空集合 | target-consumer matrix |
| halo 来源 | 只由真实布尔字段启用，父子和路径完整 | 名称推断、装备 ID 分支、truthy 宽松转换 | halo source matrix |
| 晚出生投影 | 后出生 servant 获得父状态当前版本且只一次 | 仅启动时当前目标生效 | spawn/reconcile transitions |
| 生命周期清理 | 离场、死亡、父状态移除后关系和子状态正确更新 | 孤儿状态、误删其他来源 | lifecycle matrix |
| 原子提交 | 任一必需步骤失败均无部分状态 | 单位出生成功但 relation / halo 失败 | failure atomicity matrix |
| 三锥闭合 | 三项真实阻断均由共享路径关闭 | fixture 绿但正式目录仍 blocked | catalog startup matrix |
| 回放审计 | mutation、settlement、source walkback、replay 一致 | 只有日志或最终面板对比 | audit/replay samples |

## 拟改文件与关键边界

执行线程必须先用 CodeGraph 核对当前调用链。预计触达范围如下，允许按当前代码结构做最小调整，但不得扩大到相邻内容轨：

- `scenarios/build_state.py`
  - 在 provider 注册和启动效果前创建合法空召唤运行时。
- `systems/summon.py`
  - 公开统一的空 runtime 构造 / 校验边界。
  - 保证 spawn / remove 与 relation 更新可供事件和 halo 对账消费。
- `systems/target.py`
  - 区分 resolved-empty 与 resolution failure。
- `rules/evaluator.py`
  - 条件对合法空目标集合执行正常真假判断。
- `tbgd/lowering.py`
  - 收紧 `IsHaloStatus` 类型与父子来源契约；不重复 lower 效果图。
- `systems/status.py`
  - 建立、更新、移除 halo 关系并复用现有状态生命周期。
- `systems/event_dispatch.py`、`core/executor.py` 或统一 transition 入口
  - 仅在现有顺序无法保证关系可见和原子提交时修改。
- core state codec、compact state、snapshot / replay
  - 仅迁移新增的权威 halo 状态，不保存派生缓存副本。
- `tools/validate_p8_r1_summon_runtime_halo_lifecycle.py`
  - 新增本卡唯一主验证。
- `tools/validate_p8_s8_light_cone_remaining_gameplay_closure.py`
  - 只修正目录启动证据和必要的聚焦模式，不放宽原有 S8 谓词。
- 新增 `v8_p8_r1_summon_runtime_halo_lifecycle_ready_for_review.md`。

## 结构化验收谓词

```text
formal_state_has_canonical_empty_summon_runtime=true
summon_runtime_initialized_before_provider_and_setup_events=true
missing_or_malformed_summon_runtime_blocked=true
valid_empty_servant_group_resolved=true
resolved_empty_condition_evaluates_false=true
resolved_empty_group_effect_is_audited_no_effect=true
required_action_with_empty_target_group_unavailable=true
published_light_cone_halo_sources_non_empty=true
published_light_cone_halo_projection_gap_count=0
halo_source_flag_strictly_typed=true
halo_relation_persists_without_current_member=true
spawn_event_observes_registered_owner_relation=true
late_spawn_receives_active_halo=true
late_spawn_uses_current_parent_stack_and_values=true
halo_reconciliation_idempotent=true
ineligible_member_does_not_retain_halo_child=true
reeligible_member_is_reconciled=true
parent_removal_cleans_halo_children=true
same_named_independent_status_preserved=true
multiple_halo_sources_isolated=true
failed_reconciliation_state_unchanged=true
snapshot_round_trip_preserves_halo_semantics=true
sampled_halo_mutations_source_audited=true
sampled_halo_transitions_replay_equal=true
equipment_specific_halo_handlers=0
catalog_started_count=162
catalog_equipment_failure_count=0
catalog_external_character_build_dependency_count=0
formal_catalog_startup_complete=true
```

目录总数作为当前事实输出，不允许写进生产分支。若当前发布目录随 source fingerprint 改变，验收应比较“已发布集合全部 started”，而不是继续固定 162。

## 必须覆盖的负例

1. 正式状态构建后，删除召唤 runtime 再执行相关目标查询：blocked，state unchanged。
2. schema 版本错误、`by_owner` 类型错误、active entity 与索引矛盾：blocked，不能降级为空集合。
3. 合法空 runtime 下查询 `CasterServant`：resolved-empty；对应交集条件为 false。
4. 合法空目标下尝试需要 servant 作为必选目标的动作：动作不可用。
5. `IsHaloStatus` 为字符串、数字或对象：不能启用 halo，lowering / admission fail-closed。
6. 父状态存在、当前无成员：关系保留但无伪造子状态；之后出生可补投影。
7. 同一出生 / 创建事件重复处理：不重复添加子状态。
8. 父状态叠层后再出生：新成员获得当前叠层；旧成员不保留旧版本。
9. servant 离场、死亡或失去资格：只清理对应 halo 子状态。
10. servant 复活或重新满足资格：恰好恢复一次。
11. 两个 wearer 提供同名 halo 子状态：移除一个来源不影响另一个。
12. 目标表达式、子效果或父状态来源损坏：整个必需 transition blocked，无部分 mutation。
13. snapshot 后恢复并继续 spawn / remove：成员和结果与原连续执行一致。
14. 删除 halo 关系或篡改其来源身份后 replay：必须检测不一致。
15. 尝试在 light-cone ID 分支或 equipment-only handler 中修复：静态审计失败。

## 验证与资源限制

新增主验证必须提供轻重分离的模式，便于施工时只跑必要范围：

```bash
cd hsr_v075_baseline_clean

PYTHONDONTWRITEBYTECODE=1 python3 -B \
  -m hsr.simulator_v8_clean_core.tools.validate_p8_r1_summon_runtime_halo_lifecycle \
  --tbgd-root ../turnbasedgamedata-main \
  --output-dir /tmp/hsr_v8_p8_r1_halo_runtime \
  --runtime-only

PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B \
  -m hsr.simulator_v8_clean_core.tools.validate_p8_r1_summon_runtime_halo_lifecycle \
  --tbgd-root ../turnbasedgamedata-main \
  --output-dir /tmp/hsr_v8_p8_r1_halo_source_catalog \
  --source-catalog-only
```

两种模式都通过后，验收前只运行一次合并主验证：

```bash
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B \
  -m hsr.simulator_v8_clean_core.tools.validate_p8_r1_summon_runtime_halo_lifecycle \
  --tbgd-root ../turnbasedgamedata-main \
  --output-dir /tmp/hsr_v8_p8_r1_summon_runtime_halo_lifecycle
```

必跑直接回归，全部串行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B \
  -m hsr.simulator_v8_clean_core.tools.validate_p3_s2_summon_runtime_schema \
  --tbgd-root ../turnbasedgamedata-main \
  --output-dir /tmp/hsr_v8_p8_r1_p3_s2

PYTHONDONTWRITEBYTECODE=1 python3 -B \
  -m hsr.simulator_v8_clean_core.tools.validate_p3_s8_summon_target_relations \
  --tbgd-root ../turnbasedgamedata-main \
  --output-dir /tmp/hsr_v8_p8_r1_p3_s8

PYTHONDONTWRITEBYTECODE=1 python3 -B \
  -m hsr.simulator_v8_clean_core.tools.validate_p3_s9_summon_lifecycle_cleanup \
  --tbgd-root ../turnbasedgamedata-main \
  --output-dir /tmp/hsr_v8_p8_r1_p3_s9

PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B \
  -m hsr.simulator_v8_clean_core.tools.validate_p8_s8_light_cone_remaining_gameplay_closure \
  --tbgd-root ../turnbasedgamedata-main \
  --output-dir /tmp/hsr_v8_p8_r1_catalog_startup \
  --catalog-startup-only

PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_r1_pycache \
  python3 -m compileall -q hsr/simulator_v8_clean_core

git diff --check
```

条件触发回归：

- 修改 status 通用叠层、刷新、移除或 callback 路由时，补跑 P2 对应 focused 状态生命周期验证。
- 修改 condition / listener 分发时，补跑 P8-S7 监听聚焦回归，不运行完整 S7 全源聚合。
- 修改 executor、reducer 或事件原子提交时，补跑 P7-S3 原子提交与 P7-S15 replay 聚焦回归。
- 修改 compact state 时，补跑 P7-S18。

明确不运行：

- P1-P7 阶段聚合。
- 完整 P8-S8 gameplay aggregate；本卡只需要目录启动定向入口与新主验证。
- `validate_v0_209`。
- P8-S9 之后的遗器验证。
- 默认完整 Canonical IR、RuleBook、全 transition 或全 raw halo dump。

资源要求：

- 当前 source fingerprint 下只构建一次完整光锥 RuleBook，并在主验证各矩阵间复用。
- source-only 与 runtime-only 施工模式不得各自重复全量 lowering。
- 默认只输出 summary、source-shape matrix、target-consumer matrix、lifecycle matrix、negative matrix 和少量 audit / replay 样本。
- 重验证严格串行，前一进程退出并释放资源后才能开始下一项。

## Gap 与停止条件

- 如果当前代码事实已不是 159/162，先分类变化原因；若三项阻断已被其他提交改变，停止并由规划线程修订本卡。
- 如果真实 `IsHaloStatus` 来源要求一种当前卡未描述的成员资格、chance 或嵌套生命周期，且会改变权威状态或原子提交设计，停止询问，不得猜测。
- 如果只有通过强制开局生成 servant 才能让目录启动变绿，本卡失败。
- 如果通过把所有 target error 降级为空集合才变绿，本卡失败。
- 如果晚出生、父状态更新、来源隔离和清理没有真实 transition 证据，即使 162/162 启动也不能通过。
- 如果三张光锥之一仍为 equipment gap，或出现新的 equipment gap，本卡不能通过。
- 非当前已发布光锥内容卡未全量接入可以记录为内容扩面，但通用 halo runtime 本身不能保留已知实现缺口。

## Ready-for-review 产物

- `tools/validate_p8_r1_summon_runtime_halo_lifecycle.py`。
- 当前已发布光锥 halo 来源形态矩阵。
- 空 runtime 初始化顺序与三态目标查询矩阵。
- spawn、更新、死亡 / 复活、移除、多来源、失败原子性 transition 样本。
- 三张已知阻断项与完整目录启动结果。
- settlement、source walkback、snapshot / replay 证据。
- `live_validation_reports/v8_p8_r1_summon_runtime_halo_lifecycle_ready_for_review.md`。
- 实际修改文件、未运行验证、资源使用和剩余内容 gap 说明。

执行线程最终状态只能是 `ready_for_review`。不得修改本卡或 P8 总 checklist，不得提交 Git，不得开始 P8-S15、P8-S18 或其他阶段。

## 2026-07-24 验收裁决

运行时修复已经通过代码审查、R1 runtime 聚焦验证、P7-S3 和 P7-S15 直接回归。原目录启动验证在 1.5 GiB 限制下触发 `MemoryError`；用户决定本轮不继续运行该重验证，等待验证体系治理后以低内存目录入口补证。

因此必须区分：

- R1 生产修复：已验收。
- 当前已发布光锥完整正式目录启动：`deferred / not_proven`。

后者不是已确认的生产失败，但在完整目录证据生成前不得标记通过，也不得宣称 `formal_catalog_startup_complete=true`。

## 唯一执行清单（仅验收线程可勾）

- [x] 正式战斗在任何 provider、启动效果和开局事件前具有统一、合法且为空的召唤运行时。
- [x] 召唤目标查询严格区分非空、合法空集合和解析失败，各消费方按自身语义处理。
- [x] 当前已发布光锥中的全部真实 halo 来源均完成严格类型化投影和通用 runtime 准入。
- [x] 光环关系可在无当前成员时持久存在，并对出生、更新、死亡 / 复活、离场和父状态移除正确对账。
- [x] spawn relation、创建事件和 halo 投影顺序一致，失败路径原子 blocked 且 state unchanged。
- [x] 多 wearer、多来源、同名状态和重复事件均不串线、不重复、不误删。
- [ ] 三张已知光锥通过真实构筑与真实事件链闭合，当前已发布光锥目录全部正式启动。
- [x] 代表 mutation 具备 settlement、raw source 反查、snapshot 和 replay 证据。
- [x] 没有固定 ID、装备专用 runtime、假 servant、静态面板规则迁移或 target error fallback。
- [ ] 主验证、直接回归、资源审计和 `ready_for_review` 报告完整；当前只缺完整目录启动的低内存补证。
