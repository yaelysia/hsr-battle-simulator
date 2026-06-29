# v8 项目目标

## 最终目标

v8 的最终目标是复刻《崩坏：星穹铁道》战斗系统，使用户可以在不打开游戏的情况下设定敌我双方、路线输入和战斗环境，并得到与游戏机制一致的完整战斗过程、快照、结算和来源审计。

项目优先级固定为：

```text
最终成品完整性 > 内核干净程度 > 来源可追查 > 验证可重复 > 旧版兼容
```

旧版兼容不是目标。旧 v7、旧 model pack、旧 CLI、旧 JSON、旧 Python API 都不能阻碍 v8 形成干净内核。

## 事实来源目标

v8 的规则事实来源只承认：

```text
turnbasedgamedata-main -> TBGD compiler/lowering -> Canonical IR -> Combat Core
```

最终必须满足：

- 战斗 runtime 只读取 Canonical IR / 数据卡 IR。
- Canonical IR 可追溯到 TBGD source。
- 每条规则对象都有 `source_path/raw_type/raw_id/evidence`。
- 每个 opcode、condition、formula、target expression、event 都进入 coverage matrix。
- 观测到的游戏伤害和旧模拟器输出只能用于验证，不能作为规则输入。
- TextMap、中文名、英文名、技能说明只能用于 UI/审计展示，不能驱动 runtime 规则。

## 完整快照目标

每个动作都必须产生完整 `BattleTransition`。

完整 transition 至少包含：

- 动作输入：actor、action、目标输入、队列来源、手动或推演器来源。
- before snapshot。
- after snapshot。
- target resolution。
- trigger windows。
- state mutations。
- process events。
- rng events。
- settlement。
- coverage 状态。
- source audit 与 replay 信息。

完整 snapshot 最终必须覆盖：

- 战斗元信息：波次、阶段、行动序号、当前窗口、全局 flags。
- 队伍与单位：角色、敌人、召唤物、站位、阵营、模板来源。
- 基础属性与派生属性：HP、攻击、防御、速度、暴击、暴伤、增伤、抗性、击破、效果命中、效果抵抗等。
- 资源：HP、护盾、能量、战技点、可回复生命、特殊资源条。
- 韧性：当前韧性、最大韧性、弱点、弱点锁定、击破状态、击破延迟。
- 状态：buff、debuff、其他 modifier、层数、持续时间、动态值、来源、施加者、可驱散性。
- 时间线：AV、速度重算、行动提前、行动延后、额外回合、立即行动。
- 队列：终结技插队、interrupt、follow-up、counter、extra turn、summon action。
- 目标：原始目标输入、合法目标、最终目标、随机目标、溅射/扩散/弹射结果、effect/callback target expression 解析结果。
- RNG：随机种子、随机调用、随机结果。
- 结算：伤害、治疗、护盾、削韧、击破、能量、击杀、状态变化、资源变化。

最终要求：

```text
before snapshot + action input + Canonical IR + RNG events + mutations == after snapshot
```

## 机制一致性目标

v8 最终必须覆盖星穹铁道战斗运行时的核心机制：

- 动作生命周期：回合开始、费用、目标、行动前、命中、伤害、行动后、回合结束。
- 目标系统：单体、扩散、全体、随机、自己、队友、敌方、召唤物、servant、特殊目标别名、目标序列、过滤、重定向。
- 伤害族：direct、toughness、break、DoT、super-break、true damage、hp loss。
- 生存机制：治疗、护盾、减伤、承伤、生命锁定、复活、濒死。
- 资源机制：能量、战技点、额外战技点、特殊资源、资源上限变化。
- 状态机制：添加、移除、刷新、层数、持续时间、动态值、驱散、抵抗、免疫、控制。
- modifier 机制：属性项、公式项、条件项、作用域、来源、applied/skipped 原因。
- 时间线机制：速度、AV、提前、延后、额外回合、立即行动、召唤物行动。
- 队列机制：终结技、插队、interrupt、extra turn、follow-up、counter、delayed action。
- 触发机制：GameEvent、status callback、trigger window、condition、effect、失败原因。
- 敌人机制：怪物卡、敌方技能、固定序列行动候选、复杂 AI、阶段、召唤、波次、关卡机制。

## 结算与审计目标

最终每条结算记录必须可追查。

必须能回答：

- 这个数值来自哪个 TBGD 文件和 raw id。
- 哪个 Canonical IR 节点 admission 了这条机制。
- 哪些公式项参与了计算。
- 哪些公式项被跳过，以及原因。
- 哪些状态或 modifier 提供了影响。
- 哪些目标表达式参与了 effect/callback 的目标解析。
- 哪些 mutation 改变了最终状态。
- 哪些记录只是过程事件，不改变状态。

最终 settlement 不允许从日志事后反推；必须由执行路径原生生成。

## 当前阶段

v8 当前已推进到：

```text
v0_289 target expression sequence filter retarget
最近代码检查点提交：f1fe9ce
```

当前已落地的核心范围：

- TBGD lowering、Canonical IR、RuleBook、coverage/static checks。
- 完整快照、Mutation replay、transition contract、settlement traceability、source audit。
- action definition、ability binding、ability phase/task、effect/status callback、event dispatch。
- target、resource、timeline scheduler、queue/window、extra action 语义的当前可信底座。
- direct、DoT、hp loss、break、break DoT、super-break、target group、bounce、damage source frame、击杀归因。
- 普通状态生命周期，buff/debuff 统一按 unit-attached status lifecycle 处理，特殊生命周期必须有显式来源。
- 动态值绑定、状态实例动态值、DynamicValueStore。
- 角色数据卡接口、公式槽位、行迹/星魂通用接口，以及加强版希儿示例卡。
- 怪物卡规范、`MonsterDataCardIR`、普通怪物技能动作、固定序列行动候选、怪物技能附带状态。
- 状态监听事件族矩阵、mutation-backed 事件源、状态回调安全执行边界。
- 银鬃尉官基础反击纵切：技能挂监听状态、受击触发、条件判断、插入反击、反击伤害、清理/计数审计。
- 目标表达式系统：简单别名、明确群体、上下文目标列表、`TargetSequence`、`TargetFilter`、确定性 `Retarget`。
- 本地 UI 测试台：用于 scenario 编排、战场式查看、事件回放、审计详情展示，不进入规则系统。

当前仍未完整落地的大块：

- 完整角色面板装配：晋阶、全量角色行迹、光锥、内圈/外圈遗器及套装效果。
- 更多角色卡人工解释与验证。
- 状态系统主体：叠层、刷新、概率、失败分支、持续时间、tick、DoT tick、控制、抵抗、免疫、驱散。
- 目标系统剩余部分：排序、随机、fetch、相邻目标、唯一实体、召唤物/servant 目标、特殊玩法目标。
- 全怪物技能、全怪物被动、阶段切换、召唤、波次、关卡倍率。
- 敌方完整行动推演策略、波次系统。
- summon、assistant、servant、特殊战斗模式。
- 光锥、遗器、环境、关卡机制。
- `OnCustomEvent`、`OnWaveMonster` 等需要真实事件源或波次系统的回调。

## 下一阶段建议

v0_289 之后，目标表达式底座已经能支撑更多状态和怪物技能。建议下一阶段优先补状态系统主体：

1. `stack/refresh/chance`。
2. `duration/tick/expire`。
3. DoT tick、控制、抵抗、免疫、驱散。

原因：

- 目标表达式已经覆盖了大量 effect/callback 目标解析需求。
- 怪物技能附带状态和状态监听已经能把更多真实状态挂进系统。
- 当前最容易继续阻塞真实机制的是状态自身生命周期和判定语义，而不是动作入口。

## 每个机制的完成定义

每个新机制完成时必须同时满足：

- runtime 只读 Canonical IR / 数据卡 IR。
- 可执行路径有真实 TBGD / 数据卡 source trace。
- 缺来源、缺条件、缺目标、缺公式、缺 payload 时 blocked/process-only 且 snapshot unchanged。
- 验证样例主路径按结构化谓词选择，不靠固定文件、固定 hash、固定角色、固定怪物、固定技能 ID 或观测结果。
- mutation metadata、settlement、source audit、replay 能互相反查。
- 如果该机制只是 `engine_convention`，必须显式标记，不得伪装为 TBGD 来源。

## 最终完成定义

v8 只有在满足以下条件时，才算接近最终成品：

- 运行时不依赖旧模拟器和旧 model pack。
- 用户可以通过 scenario 设定敌我双方、环境和路线。
- 动作输入可以得到完整 transition。
- transition 可以 replay。
- 关键战斗机制覆盖到游戏实用范围。
- TBGD coverage 能显示已支持和未支持机制。
- 未支持机制不会被误判为已支持。
- 结算数值可以追溯到来源、公式、状态、目标解析和 mutation。
- 关键高难案例可以复现，并且差异能定位到具体机制。
