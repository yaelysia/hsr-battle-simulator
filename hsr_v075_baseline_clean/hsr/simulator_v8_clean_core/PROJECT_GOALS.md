# v8 项目目标

## 最终目标

v8 的最终目标是复刻星穹铁道战斗体系，使用户可以在不打开游戏的情况下设定敌我双方、路线输入和战斗环境，并得到与游戏机制一致的战斗过程、完整快照和结算结果。

项目优先级固定为：

```text
最终成品完整性 > 内核干净程度 > 来源可追查 > 验证可重复 > 旧版兼容
```

旧版兼容不是目标。旧 v7、旧 model pack、旧 CLI、旧 JSON、旧 Python API 都不能阻碍 v8 形成干净内核。

## 事实来源目标

v8 的规则事实来源只承认：

```text
turnbasedgamedata-main -> TBGD compiler -> Canonical IR -> Combat Core
```

最终必须满足：

- 战斗 runtime 只读取 Canonical IR。
- Canonical IR 可追溯到 TBGD source。
- 每条规则对象都有 `source_path/raw_type/raw_id/evidence`。
- 每个 opcode、condition、formula、event 都进入 coverage matrix。
- 观测到的游戏伤害和旧模拟器输出只能用于验证，不能作为规则输入。

## 完整快照目标

每个动作都必须产生完整 `BattleTransition`。

完整 transition 至少包含：

- 动作输入：actor、action、目标输入、队列来源、手动或 AI 来源。
- before snapshot。
- after snapshot。
- target resolution。
- trigger windows。
- state mutations。
- process events。
- rng events。
- settlement。
- coverage 状态。

完整 snapshot 最终必须覆盖：

- 战斗元信息：波次、阶段、行动序号、当前窗口、全局 flags。
- 队伍与单位：角色、敌人、召唤物、站位、阵营、模板来源。
- 基础属性与派生属性：HP、攻击、防御、速度、暴击、暴伤、增伤、抗性、击破、效果命中、效果抵抗等。
- 资源：HP、护盾、能量、战技点、可回复生命、特殊资源条。
- 韧性：当前韧性、最大韧性、弱点、弱点锁定、击破状态、击破延迟。
- 状态：buff、debuff、其他 modifier、层数、持续时间、动态值、来源、施加者、可驱散性。
- 时间线：AV、速度重算、行动提前、行动延后、额外回合、立即行动。
- 队列：终结技插队、interrupt、immediate、extra-turn、summon action。
- 目标：原始目标输入、合法目标、最终目标、随机目标、溅射/扩散/弹射结果。
- RNG：随机种子、随机调用、随机结果。
- 结算：伤害、治疗、护盾、削韧、击破、能量、击杀、状态变化、资源变化。

最终要求：

```text
before snapshot + action input + Canonical IR + RNG events + mutations == after snapshot
```

## 机制一致性目标

v8 最终必须覆盖星穹铁道战斗运行时的核心机制：

- 动作生命周期：回合开始、费用、目标、行动前、命中、伤害、行动后、回合结束。
- 目标系统：单体、扩散、全体、随机、自己、队友、敌方、召唤物、特殊目标别名。
- 伤害族：direct、toughness、break、DoT、super-break、true damage、hp loss。
- 生存机制：治疗、护盾、减伤、承伤、生命锁定、复活、濒死。
- 资源机制：能量、战技点、额外战技点、特殊资源、资源上限变化。
- 状态机制：添加、移除、刷新、层数、持续时间、动态值、驱散、抵抗。
- modifier 机制：属性项、公式项、条件项、作用域、来源、applied/skipped 原因。
- 时间线机制：速度、AV、提前、延后、额外回合、立即行动、召唤物行动。
- 队列机制：终结技、插队、interrupt、extra turn、follow-up、delayed action。
- 触发机制：GameEvent、trigger window、condition、effect、失败原因。
- 敌人机制：敌方技能、AI、冷却、波次、关卡机制。

## 结算与审计目标

最终每条结算记录必须可追查。

必须能回答：

- 这个数值来自哪个 TBGD 文件和 raw id。
- 哪些公式项参与了计算。
- 哪些公式项被跳过，以及原因。
- 哪些状态或 modifier 提供了影响。
- 哪些 mutation 改变了最终状态。
- 哪些记录只是过程事件，不改变状态。

最终 settlement 不允许从日志事后反推；必须由执行路径原生生成。

## 阶段目标

v8 里程碑按结果划分：

- `v0_200`：TBGD-first 独立基线，Canonical IR、coverage、snapshot replay 基础可用。
- `v0_201`：工作流设计冻结。
- `v0_202`：项目目标与禁止事项冻结。
- `v0_203`：完整快照规格和 fidelity matrix 可验证。
- `v0_204`：scenario 与身份解析可用。
- `v0_205`：target、resource、timeline 基础可用。
- `v0_206`：direct damage 完整纵切链路可用。
- `v0_207`：formula 与 modifier ledger 可用。
- `v0_208`：status lifecycle 可用。
- `v0_209`：toughness、break、trigger、queue 可用。
- `v0_210`：DoT、super-break、heal、shield、summon、enemy、wave 可用。
- `v0_211+`：C0-C8 与更多实战案例重建，并逐步收敛到游戏一致结算。

## 完成定义

v8 只有在满足以下条件时，才算接近最终成品：

- 运行时不依赖旧模拟器和旧 model pack。
- 用户可以通过 scenario 设定敌我双方、环境和路线。
- 动作输入可以得到完整 transition。
- transition 可以 replay。
- 关键战斗机制覆盖到游戏实用范围。
- TBGD coverage 能显示已支持和未支持机制。
- 未支持机制不会被误判为已支持。
- 结算数值可以追溯到来源、公式、状态和 mutation。
- 关键高难案例可以复现，并且差异能定位到具体机制。

