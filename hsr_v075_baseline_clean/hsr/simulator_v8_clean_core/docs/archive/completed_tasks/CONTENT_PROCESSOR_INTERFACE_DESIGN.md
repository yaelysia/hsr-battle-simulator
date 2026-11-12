# 内容专属处理器挂载接口设计（M1-3 对照实验，评审稿 v1）

> **已归档（2026-11-12）**：这是接口落地前的评审稿，原位于 `content_processors/DESIGN.md`。其中的写入边界、实施顺序和待裁决问题只对当时有效；
> 现行接口与书写约定以[架构契约](../../../ARCHITECTURE_BOUNDARY_CONTRACT.md#内容专属处理器)和 `core/content_hooks.py` 为准。

日期：2026-11-11。作者：processor-experiment。状态：lead 已评审通过（2026-11-11），按提案实施。
落地后由 lead 确认后补充 ARCHITECTURE_BOUNDARY_CONTRACT.md 第 5 节留白。

## 评审补充要求（lead，2026-11-11，具有约束力）

1. **分派顺序显式确定**：多处理器按 content_id 排序分派；挂载记录同样按 content_id 排序。
   处理器产生的事件走同一类型化 dispatch 通道与既有去重规则，不得开私有通道。
   （本条与下文第 6 节书写约定一并写入将来的契约第 5 节文本。）
2. **热路径纪律**：services 与 HookResult 路径禁止无谓 thaw/to_json——冻结容器是 dict/list 子类，
   json.dumps 可直接序列化；仅哈希消费时用 detach=False。新类型不得加"构造时重算身份哈希"的
   防伪检查；身份校验按需做。
3. **性能基准义务**：挂载前后跑固定基准 examples/cli/arlan_vs_antimatter.json + 同名 commands
   （.venv/bin/python，分阶段计时），随报告提交。
4. **写入边界**：授权实施清单＝rules/rulebook.py、core/executor.py、systems/event_dispatch.py、
   systems/action_availability.py、tbgd/battle_catalog.py、新文件 core/content_hooks.py、
   content_processors/ 包。严禁触碰 lead 在途性能文件：systems/dynamic_values.py、core/reducer.py、
   systems/task_graph.py、archive_json.py、builds/manifest.py、tbgd/compile_cache.py、
   battle_archive.py、core/audit_policy.py；超出清单先提案等确认。
5. **版本身份**：进 setup_records、不进 rules_fingerprint；语义变更必须升 version 常量。
6. **H1 接管**：仅实测语义缺口才接管，接管清单与理由逐项进报告；R07 遐蝶用例必须保持通过。
7. **队列边界**：自爆插入遇准入缺口提最小通用提案，不私改队列。

## 0. 侦察结论（已验证的事实基础）

**任务前提需要修正**：在 R07 检查点 e034cd0（当前 HEAD 代码）上，遐蝶死龙"创建"已经可用：

- `tests/test_r07_derived_unit_routes.py::test_castorice_newbud_netherwing_hp_lock_overflow_and_departure`
  两次独立运行均通过（2026-11-11，各约 8 分钟，持 /tmp/hsr-v8-validation.lock，真实 TBGD 编译）。
  覆盖：新蕊积满→终结技消耗新蕊→死龙创建→死龙行动出伤→濒死队友锁 1 HP 溢出由死龙承担→死龙退场。
- IR 静态探针（热缓存）：avatar_skill:140703 及其 binding executable；servant:11407 executable
  （representation=unit，birth template 齐全）；死龙五动作 servant_skill:1140701/1140702/1140710/1140711/1140712
  （Skill01/02/21/22/23）全部 executable。
- CODEX_HANDOFF 的"创建仍阻断"是 2026-11-07 观察记录，晚于它的检查点提交已把创建打通。

**真实剩余缺口**（IR 探针 + 原始来源核对）：

| 缺口 | 证据 | 来源依据 |
| --- | --- | --- |
| 死龙可被选中（应不可选中） | lifecycle_source.targetable=true（lowering.py:17482 通用默认）；**但** Servant_CastoriceServant_PassiveSkill01 的 MServant_CastoriceServant_Passive OnStack 含 StackCustomUnselectable(TeamDark)，通用路径已编译实现（effect.py:4505，custom_unselectable_teams 标志）→ 运行时可能已生效，待探针验证 | TBGD 能力节点（固定提交）；TargetSelectGroup=1 仅死龙独有（语义无定义表，弱证据） |
| 寿命=永久（应 3 回合） | lifetime_policy=permanent_until_removed_or_owner_removed（lowering.py:17486） | MServant_CastoriceServant_LifeTime：OnPhase1 自身层数 -1，销毁→TiggerKiller→Disable；层数初值来自 Skill03 参数 #1=3（AvatarSkillConfig 140703 ParamList [165,3,1,0.25,0]） |
| 退场后再创建被阻断 | replacement_policy blocked: create_servant_alive_only_guard_missing；plan_spawn_servant 对 defeated 实例要求已准入替换策略（summon.py:366-379） | 遐蝶 Skill03 的 CreateServant 无 alive-only 守卫包裹，通用发现器（_discover_servant_replacement_policies）找不到策略；游戏内终结技可再次创建 |
| 生命消耗/强制自爆/BP 强化映射语义未验证 | 图已编译，但 LoseHP 循环、HP 不足强制 Skill23、BPSkill_Level→Skill21/22 映射未逐项验证 | Servant_CastoriceServant_Skill02/21/22 Phase02 的 LoseHP 与 BPCost_3 判定；BP_Explode OnDestroy 的 SetControlSkillMapping |
| Buff 复制链整链未验证 | I11 有 InfectModifier 组件证据；创建时 Remodifier+InfectModifier 全链未验 | Avatar_Castorice_00_Skill03_Phase02 |
| 出生属性 | HPBase=0/HPInherit=0，MaxHP/CurrentHP 由 CreateServant DynamicValues 注入（hash 778854283，绑定遐蝶 MaxHP 比例）；速度=Skill03 参数 #0=165，不继承；同被动 OnStack 含 ReinitProperty BaseHP（属性重置来源） | AvatarServantConfig 11407 + Skill03 CreateServant 节点；测试已观察到死龙 HP>0，说明注入已生效，需核对数值 |
| 终结技禁用与 Skill21 映射（可能已通用） | MAvatar_Castorice_00_Skill03_Field OnStack：AttachSkillTypeDisable(Ultra) + SetControlSkillMapping(ControlSkill02→Skill21)；OnDestroy 恢复；lowering 已有两 opcode 处理 → 待探针验证 | TBGD GlobalModifiers（固定提交） |

**通用路径已有投入**（对比基线）：R07 检查点 e034cd0 单提交 90 文件 +15753/-1505，
其中 tbgd/lowering.py +4915；覆盖 10 个派生单位角色，8 个有可用路线，遐蝶创建已通但上表缺口仍在。
此前 I11（InfectModifier 等）另有投入。这些实现按方向矫正继续复用，不重写。

## 1. 设计原则

1. 处理器是 L2 内容卡的代码，随卡装配；内核只消费"已装配处理器"，按单位自身身份做通用字典分派，
   不按名称/固定 ID 分支（与 combatant_action_set 按 template_id 查找同构）。
2. 三个公共挂点：动作执行（H1）、事件监听（H2）、可用性过滤（H4）。生命周期节点由 H2 的
   unit.created/summon.spawned/unit.defeated/summon.removed/回合事件覆盖，不另设挂点。
3. 处理器只产生类型化 mutation/event/rng_event，经既有原子提交边界落地；失败零 mutation 零 RNG。
4. 数值结算一律调用 L1 通用系统（DamageSystem/StatusSystem/SummonSystem/ResourceSystem/QueueSystem/
   TargetSystem/RNG），不复制公式；倍率等参数取自数据卡（ActionDefinitionIR.param_list、
   ServantDefinitionIR.stat_source、dynamic_value_bindings），定义处注明来源。
5. 最小介入：已可用且语义正确的声明式行为不接管；处理器只补缺口。接管某动作时整段替换其效果执行
   （override），不做半接管，避免两套语义叠加。是否接管按实测语义缺口决定并记录。

## 2. 装配入口

- 新包 `simulator_v8_clean_core/content_processors/`（L2，本实验自由写入区）：
  - `__init__.py`：`PROCESSOR_CATALOG: dict[str, Callable[[], ContentProcessor]]`，键为内容身份
    entity_ref（"avatar:1407"、"servant:11407"）。目录内容是 L2 数据，不是内核分支。
  - `castorice.py`：遐蝶角色卡处理器（含死龙子卡行为）。
- 内核新文件 `core/content_hooks.py`（L1 协议，随本设计交 lead 集成）：
  协议、HookResult、上下文、MountedProcessor 注册类型、通用分派辅助。
- `RuleBook` 增加可选字段 `content_processors: tuple[MountedProcessor, ...] = ()`（默认空，
  现有构造零影响）+ 两个通用查找：`processor_for_unit(state, unit_id)`（按 unit.template_id）、
  `processors_for_event(event)`（按订阅声明）。
- 装配调用点：`tbgd/battle_catalog.py::build_battle_rulebook` 末尾 +1 行
  `rules = mount_content_processors(rules)`（函数在 content_processors/__init__.py，
  遍历目录、只挂载 IR 中实际存在的内容身份）。CLI、测试、replay/resume 都经此入口，一处挂载全覆盖。
  不动 builds/manifest.py 与 tbgd/compile_cache.py（lead 在途）。
- 挂载身份记录：MountedProcessor 携带 content_id + processor version 常量，进入 setup_records，
  供归档/replay 识别处理器版本（不进 rules_fingerprint，避免与 lead 的性能改动冲突；如需进指纹另议）。

## 3. 处理器签名与 mutation 上下文

```python
@dataclass(frozen=True)
class HookResult:
    ok: bool
    blocked_reason: str = ""
    mutations: tuple[Mutation, ...] = ()
    events: tuple[GameEvent, ...] = ()
    rng_events: tuple[RNGEvent, ...] = ()
    records: tuple[dict[str, JSONValue], ...] = ()

class ContentProcessor(Protocol):
    content_id: str          # 所属卡身份
    version: str             # 书写约定：语义变更必须升版本
    def claims_action(self, action_id: str, level: int) -> bool: ...
    def execute_action(self, ctx: ActionHookContext) -> HookResult: ...
    def subscriptions(self) -> tuple[EventSubscription, ...]: ...
    def on_event(self, ctx: EventHookContext) -> HookResult: ...
    def filter_choices(self, ctx: AvailabilityContext) -> AvailabilityResult: ...
```

- ActionHookContext：只读候选 state、command、已通过通用 preflight 的 TargetResolution、
  ActionDefinitionIR、资源计划结果、services 门面。
- EventHookContext：只读候选 state、当前 GameEvent（类型化 payload）、services。
- services 门面（ProcessorServices）包装 L1 系统：apply_damage(DamagePacket)、
  spawn_servant / remove_summon（SummonSystem plan+apply）、add/remove_modifier（StatusSystem）、
  resolve_target_expression（TargetSystem，同一套合法性）、resolve_rng（RNGRequest→RNGResolution，
  事件入账）、queue_insert、typed HP/resource mutation 构造器。每次调用返回类型化结果并把 mutation
  应用到内部候选 state（MutationReducer），后续步骤可见前序效果；与 ability task 系统同模式。
- 处理器不持有跨调用可变状态；一切持久信息进 unit flags/resources（类型化 mutation），保证 replay。
- 失败语义：任一服务调用失败 → 处理器返回 ok=False + blocked_reason；挂点把失败并入既有
  finalize_selected_execution_graph 原子边界，整事务零 mutation、零 RNG、零队列变化。

## 4. 分派点（共享文件最小 diff 提案，全部由 lead 集成或批准后动手）

| 文件 | 挂点 | 提案规模 |
| --- | --- | --- |
| rules/rulebook.py | content_processors 字段 + processor_for_unit / processors_for_event | ~25 行 |
| core/content_hooks.py（新） | 协议 + HookResult + 上下文 + services 门面 + mount 辅助 | ~300-400 行 |
| core/executor.py | H1：execute() 中 action_enabled 后、编译图分支前；claims_action 命中则走处理器效果执行，替换 ability-graph/damage 段；preflight（目标/资源/生命周期）与 postflight（时间线/队列/行动结束事件）保持通用 | ~40-60 行 |
| systems/event_dispatch.py | H2：_dispatch_event 监听器分派后，按订阅调用处理器，结果并入同一 dispatch/原子边界；事件身份与去重规则不变 | ~30-40 行 |
| systems/action_availability.py | H4：_summon_choices 与角色动作选择末尾，处理器过滤/替换候选；blocked 原因并入既有结构；决策指纹自然覆盖 | ~15 行 |
| tbgd/battle_catalog.py | 装配调用 +1 行 | 1 行 |

合计共享文件 5 改 1 新（core/content_hooks.py 属内核新文件，一并交 lead）。
不动：tbgd/lowering.py、rules/ir.py、systems/ 其余热点、builds/manifest.py、tbgd/compile_cache.py。

H1 边界说明：v1 只接管"通用 preflight 已通过"的动作；若未来某动作 binding 被阻断又必须处理器执行，
再向 lead 提案前置挂点，不在本实验擅自扩。

**H1 实施细化（2026-11-11 落地，已报 lead）**：HookResult 增加 takeover 标志。
takeover=False（默认）＝前置清理钩子：处理器 mutation 先落地，编译图随后照常执行；
takeover=True＝整段替换编译效果段（通用触发窗口仍派发）。再创建守卫用前者：
defeated 死龙先经 SummonSystem.plan_remove/apply_remove 清理（_defeated_servant_instances
只计 defeated，清理后编译 CreateServant 不再被 replacement_policy 阻断），无需接管终结技。

## 5. 遐蝶处理器的行为分工（最小介入）

保持声明式（已验证可用）：新蕊积累与终结技门禁、终结技消耗新蕊、CreateServant 创建、
死龙 Skill01/02/21/22/23 的编译伤害图、HP 锁与溢出事件生产。

处理器负责（缺口）：
1. H2 summon.spawned（死龙）：targetable=false 标志 mutation（依据：游戏规则+ServantConfig，定义处注明）；
   寿命层数初始化核对（若编译注入缺失则补 mutation，参数取 Skill03 param #1）。
2. H2 回合事件（死龙 OnPhase1 对应事件）：寿命 -1；归零 → 触发强制自爆流程（插入 Skill23 队列动作，
   经 QueueSystem；若队列准入不足则提案最小通用缺口，不私改队列）。
3. H2 unit.defeated/summon.removed + H1 终结技前置：再创建守卫——存在 defeated 死龙时先
   SummonSystem.plan_remove/apply_remove 清理，再放行编译 CreateServant（_defeated_servant_instances
   只计 defeated，清理后通用 spawn 不再被 replacement_policy 阻断）；存在 active 死龙时终结技
   在 H4 隐藏（游戏内按钮不可用），提交则原子拒绝。
4. H2 hp 变化事件：死龙 HP 低于下次行动消耗 → 强制自爆（若编译图未表达）。
5. H4：BPSkill_Level → Skill02/21/22 按钮映射（来源：BP_Explode OnDestroy 的 SetControlSkillMapping、
   OnPhase1Change）；Disable 修饰器存在时隐藏死龙动作。
6. H1 接管（仅当实测语义缺口）：Skill23 自爆伤害+治疗+退场整段、Skill02/21/22 的 LoseHP 循环，
   用 DamagePacket + param_list 倍率调 L1 伤害；接管清单在报告中逐项记录。
7. Buff 复制链：先验证编译 InfectModifier 全链；缺口才由处理器在创建事件补（调 StatusSystem）。

## 5.1 图覆盖旁路枚举（H1/H4，lead 2026-11-11 批准，条件 1）

处理器 claims_action 命中的动作，可用性与执行 preflight 仅绕过以下编译图覆盖类阻断理由
（core/content_hooks.GRAPH_COVERAGE_BLOCK_PREFIXES，单一枚举源）：
- task_graph_*（task_graph_definition_not_admitted / task_graph_control_requires_domains 等）
- effect_coverage_*（effect_coverage_status:unsupported:UseSkillOneMore 等）
- bounce_not_executable
- condition_not_executable
- damage_emission_scaling_ratio_not_runtime_bound
- process_only_task_coverage_mismatch

目标合法性、资源、生命周期、控制门禁、身份校验一律照常，不得绕过。
组件测试三条（test_content_processor_interface.py）：claimed+图阻断→可用；
未 claimed+同阻断→仍阻；claimed+资源门禁失败→仍阻。

## 5.2 接管清单（逐项，lead 条件 3）

| 动作 | 接管模式 | 理由（实测） | 版本 |
| --- | --- | --- | --- |
| avatar_skill:140703（终结技） | H1 前置清理 takeover=False | defeated 死龙残留时再创建被 replacement_policy 阻断；清理后编译图照常（退场=removed 时本就不阻断，此为安全网） | 0.1.0 |
| servant_skill:1140702/1140710/1140711（吐息 Skill02/21/22） | H1 整段接管 takeover=True | 编译图不可准入：UseSkillOneMore 不支持+ByAnd 条件阻断+scaling 未绑定（探针 v3 dump）；名单内无第二使用者 | 0.2.0 |

未接管（通用已正确，探针实证）：创建、Skill01、寿命倒计时、到期自爆序列、
敌方不可选中、弹射排除、终结技门禁、Skill21 映射、天赋增伤扩散、BattleCry、HP 锁溢出。

## 6. 书写约定（草案，落地后写入契约第 5 节）

- 一个内容一个文件（content_processors/<content>.py），处理器类注明 content_id、version、
  逐行为依据（TBGD 能力名 + 固定提交 14c1d18f…，或资料链接 + 适用版本/条件）。
- 多处理器按 content_id 排序分派；处理器事件走同一类型化 dispatch 通道与既有去重规则，不开私有通道。
- services 与 HookResult 路径不做无谓 thaw/to_json；新类型不做构造时身份哈希重算。
- 数值一律读数据卡参数；禁止写死倍率/层数/速度；参数缺失 → fail-closed 拒绝，不猜。
- 只经 services 产生 mutation；禁止直接改 state、禁止私写公式、禁止绕过目标/资源/概率/抵抗/免疫/RNG。
- 不读 raw TBGD/TextMap；不读其它内容卡私有状态；跨卡影响只能经公共事件与通用系统。
- 无跨调用可变状态；持久信息进类型化 state 字段。
- 失败返回 ok=False + 机器可读 blocked_reason；不产生部分 mutation/RNG。
- 第二个内容需要同样行为时提升为通用机制，两处改复用（契约第 5 节原文）。
- RNG 一律经 services.resolve_rng(RNGRequest)：请求自带 before_state 身份与完整
  decision identity；解析事件入 HookResult.rng_events，随原子提交入账或整体丢弃。

### 处理器移除准入的依据与记录约定（lead 复核注记，2026-11-11）

services.remove_summon 使用 SummonSystem.plan_remove 的准入形状
（coverage_status=executable + remove_source_admitted=True）。这不是绕过准入：
处理器移除属于已挂载内容卡已准入行为的一部分（如遐蝶再创建前清理退场死龙，
依据 Skill03_Phase02 无条件 CreateServant 源节点）。约定：
- 调用方必须传 source_trace.rule（TBGD 源节点身份或已采纳资料依据），缺失即
  ProcessorBlocked(content_processor_remove_rule_source_missing)，失败关闭。
- admission 载荷记录 admission_basis=content_processor_mounted_behavior 与
  rule_source（含处理器 content_id:version），随 mutation/settlement 入账，
  供审计与 replay 识别移除依据。
- 禁止用该入口移除与处理器内容无关的单位；移除对象必须属于本卡生命周期
  （由处理器行为定义保证，复核时检查）。

## 7. 测试方式

- 组件测试（快，不编译 TBGD）：挂载/分派通用性（无名称分支）、失败零 mutation 零 RNG、
  订阅过滤、候选 state 推进、版本身份入 setup_records。
- 集成测试 tests/test_content_processor_castorice.py（-m integration，公开 advance/submit）：
  创建→不可选中（敌方目标候选不含死龙）→行动与 HP 消耗→寿命到期强制自爆→自爆伤害/治疗/退场→
  再创建→Buff 复制链。复用 R07 场景助手（stage 307214，低等级快速积满新蕊）。
- 回归守卫：R07 遐蝶用例保持通过（里程碑节点持锁运行）。
- 性能：挂载前后同路线启动/单命令耗时对比，随报告提交（执行热点改动后基准义务）。
- 数值对照：自爆/行动伤害做第一组游戏数值对照（M1-4 格式），对照值只检验不写回规则。

## 8. 实施顺序与里程碑

1. lead 评审通过 → 集成挂点 diff（lead 动手或授权我动手）+ 挂载骨架 + 组件测试。
2. 缺口 1/2/3（不可选中、寿命、再创建）→ 定向集成检查。
3. 缺口 4/5/6/7 按实测逐项 → 定向检查；需要接管动作时先报 lead。
4. 全路线集成 + R07 回归守卫 + 性能对比 + 实验报告（代码量、共享改动数、耗时、与通用路径对比、
   接口约定草案）。一周时限 2026-11-11 起；到时未完成则如实报告进度与剩余。

## 9. 风险与开放问题（请 lead 裁决）

- H1 接管会替换已编译伤害图：若接管，R07 用例的行为断言必须保持；若某动作编译语义已正确，不接管。
- 寿命到期强制自爆需要队列插入准入（DeathrattleQueueAdmission 已存在）；若死龙自爆插入形状不被
  现有准入覆盖，最小通用缺口提案交 lead，不在处理器私改队列。
- 处理器版本是否进 rules_fingerprint：默认不进（setup_records 记录），避免与 lead 性能改动冲突。
- 任务前提修正（创建已通）是否影响实验对象选择：默认继续遐蝶死龙（缺口仍真实存在），请 lead 确认。
