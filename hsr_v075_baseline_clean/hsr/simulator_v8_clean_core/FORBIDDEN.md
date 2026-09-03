# v8 禁止事项

## 总红线

v8 不为了旧版兼容牺牲最终成品完整性。旧版本没有稳定用户，不能把兼容旧半成品当成工程目标。

禁止把“少改一点”“暂时能跑”“复用旧接口”放在内核正确性、结构干净程度和完整快照之前。

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
- runtime 根据角色名、技能名、文件名、固定 action id、固定 hash 判断机制。
- runtime 根据怪物名、展示名、中文名、英文名、TextMap 名称判断机制。
- 使用 `model_pack_v3_0` 补齐 v8 规则。
- 用观测伤害、旧模拟器输出、手工答案作为规则输入。
- 在 scenario 里写规则结果。
- 在测试里写死战斗结算作为模拟逻辑的一部分。
- 把 `engine_convention` 写成 TBGD 来源。
- 用数据库中已存在的来源可以证明的规则，却继续保留自造默认值或硬映射。

所有规则必须经过 Canonical IR。

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

- 为某个角色、敌人、遗器、关卡、路线写硬编码特判。
- 在核心系统里判断具体角色名、技能名或 case id。
- 跳过未知 opcode 后仍把机制标记为 supported。
- 把 `audit_only` 当成 executable。
- condition 失败不记录 skipped reason。
- formula 项不记录来源。
- modifier 项不记录 applied/skipped。
- 伤害族各自输出不同 settlement 结构。
- trigger window 顺序不明确时继续扩展机制。
- 队列行为不进入 snapshot。
- RNG 调用不记录事件。
- 把本该统一的机制拆成特殊路径，例如普通 buff/debuff 生命周期、普通状态 tick/expire、伤害 source frame、资源 mutation、队列 window、事件 listener。
- 把文本命中、名称相似、文件路径相似当成机制事实。
- 把角色专属机制写进核心系统；角色专属内容必须进入角色卡槽位，再接通用系统。
- 把怪物专属机制写进核心系统；怪物专属内容必须进入怪物卡机制/数据槽位，再接通用系统。
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

目标表达式必须从 Canonical IR 中的 `TargetExpressionIR` 读取，解析步骤必须进入 mutation metadata、settlement、source audit 或 replay 中可追踪的位置。

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
- 只记录最终数值，不记录计算路径。
- 只记录 applied term，不记录 skipped term。
- settlement record 无法对应 mutation，也没有 process-only 标记。
- 使用游戏观测值校正公式。
- 用常数补洞掩盖未知公式或未知状态。
- blocked、audit-only、discovered-only、placeholder 来源间接产生 mutation。
- 失败动作、blocked listener、blocked queue、blocked formula、unsupported condition 污染 state。

每个新增 mutation 类机制都必须有至少一个 source audit 样例和至少一个负例。负例必须证明 state unchanged。

## 验证红线

禁止：

- 可信主路径按固定角色名、固定 action id、固定文件名、固定 hash、固定观测值选择样例。
- 为了让旧 smoke 继续通过而降低 runtime 来源边界。
- 只验证 replay/字段完整，却不验证机制来源真实。
- 合并输出目录导致不同阶段验证产物互相覆盖。

允许：

- 用户明确指定的角色卡示例可以在对应验证脚本中点名，例如希儿示例卡；但核心 runtime 仍不得出现角色名特判。
- synthetic/manual binding 只能用于负例或能力单测，不能作为 trust matrix 主路径。

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
