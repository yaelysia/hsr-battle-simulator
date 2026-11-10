# v8 禁止事项

## 总红线

当前版本的目标是 v1 可用版：名单内的内容能打、数值与游戏对得上、速度够推演器使用。
2026-11-10 的[方向矫正](PROJECT_GOALS.md#2026-11-10-方向矫正)修订了本文件中与内容专属行为、
来源审计和验证有关的条目，并新增“方向红线”一节；其余红线不变。

v8 不为旧版兼容牺牲成品。旧版本没有稳定用户，不能把兼容旧半成品当成工程目标；
禁止为“复用旧接口”破坏原子提交、确定性和内核不按内容分支这三条底线。

## 方向红线

禁止：

- 把 v1 名单外的内容、目录覆盖或任务类型闭合列为当前任务、缺口或封版阻断。
- 为只有一个内容使用的行为扩展 lowering、IR 或内核通用机制；先写该内容卡的专属处理器。
- 同一机制在通用路径上两轮未打通后继续沿通用路径加码。
- 以验证器、契约、反例矩阵、报告或文档的数量作为交付；交付只按完成的名单条目计量。
- 为审计证据的缺失、替换或篡改新增防伪检查；在 `tools/` 新增阶段验证器。
- 未与游戏数值对照就宣称某个内容正确；用 replay 自洽或审计通过代替对照。
- 改动执行热点后不跑性能基准，或合入使基准明显变慢而未说明原因的改动。
- 未经用户决定自行增减 v1 名单，或把“先做完全部机制再接内容”恢复成工作顺序。

## 旧兼容红线

禁止：

- 为保持 v7 内部 Python API 兼容而污染 v8。
- 为保持旧 CLI、旧 JSON 内部结构、旧 compiled case 结构而改变 v8 内核设计。
- 把 `BattleSimulator` 当作 v8 核心对象。
- 引入或复活 `SimulatorRuntimeAdapter`。
- 引入或复活 `_legacy_effects`。
- 使用 `action_ctx` 作为 v8 主上下文。
- 用 wrapper 把旧运行时包成新内核。
- 把旧 model pack 当作 v8 规则事实来源。

允许旧 v7 仅作为参考和数值对照，不允许作为 v8 runtime 依赖。

## 数据来源红线

禁止：

- runtime 直接读取 TBGD raw schema。
- runtime 直接按 TBGD 原始字段名判断机制。
- runtime 读取 TextMap、技能文本或角色文本。
- 核心系统根据角色名、技能名、文件名、固定 action id、固定 hash 判断机制。内容专属行为经
  内容卡装配的处理器接入，不在核心系统里判断身份。
- runtime 根据怪物名、展示名、中文名、英文名、TextMap 名称判断机制。
- 使用 `model_pack_v3_0` 补齐 v8 规则。
- 用孤立观测伤害、旧模拟器输出或固定结算答案代替规则。
- 在 scenario 里写规则结果。
- 在测试里写死战斗结算作为模拟逻辑的一部分。数值对照中的期望值只用于检验，不属于此列。
- 把 `engine_convention` 写成 TBGD 来源。
- 用数据库中已存在的来源可以证明的规则，却继续保留自造默认值或硬映射。

规则以三种形式进入正式链路：编译为 IR、经 RuleBook 注册，或写成内容卡的专属处理器。
2026-10-12 用户已允许直接采用可靠攻略、数据网站及测试条件明确的机制研究；人工整理这些资料中的
公式、参数和触发条件属于正式规则实现，不属于“手工答案”。注明实际来源，不要求重新证明原生
内部协议或伪造 TBGD 来源。

技能文本与参数解释只允许出现在角色数据卡构建层。角色数据卡输出结构化槽位后，runtime 才能消费。

怪物、技能、状态的中文名/英文名可以进入 UI 和审计展示字段，但这些字段必须标记为 display-only，禁止驱动目标选择、伤害、AI、状态、事件或任何 mutation。

## 状态与快照红线

禁止：

- 在 system handler 中原地修改 `BattleState`。
- 绕过 `Mutation` 改 HP、能量、战技点、护盾、状态、AV、队列、flags。
- 只写 settlement 不写 mutation。
- 只写日志不写 mutation。
- after snapshot 缺字段但仍标记 transition 完整。
- before/after snapshot 无法 replay 却继续通过验证。
- 把 process-only event 伪装成状态变化。
- 把状态变化藏在临时对象、缓存或 helper 副作用里。

所有状态变化必须能从 `before + mutations` 重放到 `after`。

## 机制实现红线

禁止：

- 在核心系统里为某个角色、敌人、遗器、关卡、路线写硬编码特判，或判断具体角色名、技能名、case id。
  专属行为写进该内容卡的处理器。
- 处理器直接修改状态、另写伤害/治疗/护盾公式，或在代码里写死应来自数据卡的数值。
- 跳过未知 opcode 后仍把机制标记为 supported。
- 把 `audit_only` 当成 executable。
- 伤害族各自输出不同 settlement 结构。
- trigger window 顺序不明确时继续扩展机制。
- 队列行为不进入 snapshot。
- RNG 调用不记录事件。
- 把本该统一的机制拆成特殊路径，例如普通 buff/debuff 生命周期、普通状态 tick/expire、伤害 source frame、资源 mutation、队列 window、事件 listener。
- 把文本命中、名称相似、文件路径相似当成机制事实。
- 把角色专属机制写进核心系统；角色专属内容进入角色卡槽位或角色卡的专属处理器。
- 把怪物专属机制写进核心系统；怪物专属内容进入怪物卡机制/数据槽位或怪物卡的专属处理器。
- 把终结技连续段、真额外回合、追击/反击混成同一种“额外行动”。
- 只按 actor 归因击杀收益；击杀收益必须按具体伤害来源归因。

## 目标表达式红线

禁止：

- runtime 绕过 `TargetExpressionIR`，直接按 raw TBGD 字段名、文件名、技能名或展示名解析目标。
- 缺目标、缺事件 payload、缺当前动作 target resolution、缺参数实体列表时 fallback 到 actor、主目标、全体或空列表后继续执行。
- 任意目标 family 在来源、身份、关系、筛选、排序或随机语义未 admission 前产生 mutation。
- `Retarget`、效果目标或 callback 目标越权改写整次 action 已接受的主目标选择。
- alias 与 `target_expression_id` 同时存在但解析结果冲突时继续执行。
- 目标表达式 resolver 失败后仍让 `AddModifier`、callback task、effect 产生部分 mutation。

声明式动作的目标表达式从 Canonical IR 中的 `TargetExpressionIR` 读取；处理器选择目标时调用同一套
目标解析与合法性判定。解析结果必须可 replay，不要求另行写入审计路径。

## 怪物与敌方行动红线

禁止：

- 执行游戏客户端的敌方 AI、目标偏好、评分策略或自动战斗逻辑。
- 把 `AIPath`、`AISkillSequence` 或其他决策策略当作动作合法性和选择权威。
- 把复杂 AIPath 简化成固定序列，或因复杂 AI 未实现阻断本来规则完整的怪物动作。
- 按固定 MonsterID、怪物名、技能 ID、AIPath 白名单驱动 runtime。
- 把 `MonsterSkill.ModifierList` 当成怪物被动来源。
- 把 `MonsterConfig.AbilityNameList` 当成完整被动系统；它只是怪物机制入口之一。
- 怪物行动窗口没有外部合法选择时自动选择动作、猜测目标或造成伤害。
- 未证明 AI 字段表达强制战斗规则，就把它投影为阶段、可用性或事件约束。
- 普通怪物技能与 `ILBattleMonsterSkill` 共用 action namespace；必须分别使用 `monster_skill:<SkillID>` 与 `ilbattle_monster_skill:<ID>`。

敌我双方都由用户、UI 或外部推演器从内核公布的合法动作和目标中选择。AI 来源可以保留用于审计；
只有被独立证明为强制战斗约束的部分才能进入通用规则 IR。

## 状态监听红线

禁止：

- 带 listener/callback 的状态在 listener admission 不完整时挂成可触发状态。
- 没有真实 runtime event source 的 callback event 自动触发。
- 缺事件 payload 字段、缺条件、缺目标、缺队列优先级、缺动态值绑定时执行 callback mutation。
- before 类监听在无法保证 pending mutation 重算正确时改写同一路径。
- 将表现、镜头、音效、UI task 当成战斗 mutation。

状态监听可以完整进入事件族矩阵和覆盖报告，但只有事件源、条件、目标、task、来源全部 admission 时才能产生 mutation。

## 结算红线

禁止：

- 从日志事后反推 settlement。
- 只记录最终数值，不记录用户能看懂的计算明细。
- settlement record 无法对应 mutation，也没有 process-only 标记。
- 为拟合单个观测数值添加无依据的修正项；有条件明确的研究依据时允许修正公式。
- 用常数补洞掩盖未知公式或未知状态。
- blocked、audit-only、discovered-only、placeholder 来源间接产生 mutation。
- 失败动作、blocked listener、blocked queue、blocked formula、unsupported condition 污染 state。

仅在修改可能破坏提交边界时补相应失败零提交检查；已由共同边界覆盖的机制不逐个复制负例。

## 验证红线

禁止：

- 以挑选的样例通过冒充未验证内容或同族内容通过。
- 为了让旧 smoke 继续通过而降低 runtime 来源边界。
- 只验证 replay、字段完整或审计通过，却不与游戏实际数值对照就宣称内容正确。
- 合并输出目录导致不同阶段验证产物互相覆盖。

允许：

- 测试可直接选择具体角色、技能、装备或场景，优先复用已有样例；无需为选例建立动态扫描。
  核心 runtime 仍不得按内容名称或固定 ID 特判。
- 无真实依据的 synthetic fixture 只证明组件行为，不冒充整场；有可靠资料支持的人工规则
  绑定可以进入正式链路，按实际来源标注。
- 根据改动风险减少重复测试；具体选择见 `docs/AGENT_WORKFLOW_AND_VALIDATION.md`。
- condition 跳过原因、formula 项来源、modifier applied/skipped 等逐项审计记录不再是强制要求；
  已有的可以保留，新内容不以补齐它们为完成条件。

## 文档红线

禁止：

- 为每个小机制新增一份长期文档。
- 写大量推荐式文档替代硬约束。
- 让文档数量膨胀到影响索引和上下文检索。
- 文档与代码事实冲突后继续保留旧说法。

v8 长期文档只保留少数高密度约束文档。普通阶段说明进入 live validation report。

## 提交红线

禁止：

- 把 `AGENTS.md` 混入 v8 检查点提交。
- 把 `__pycache__` 或 `.pyc` 混入提交。
- 在未说明的情况下引入新依赖。
- 为追求短期验证通过删除 coverage 或降低静态检查。
