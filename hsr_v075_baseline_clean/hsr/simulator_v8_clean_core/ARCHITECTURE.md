# v8 Clean Core 架构设计

## 目标

v8 的目标是复刻星穹铁道战斗运行时，而不是继续修补 v7 的单体模拟器。核心边界固定为：

```text
turnbasedgamedata-main -> TBGD compiler -> Canonical IR -> Combat Core
```

运行时只消费 Canonical IR。TBGD raw schema 只能出现在 `tbgd/` 编译层，不能进入 `core/`、`rules/`、`systems/`。

## 不变量

- 所有状态变化必须通过 `Mutation` 表达。
- `BattleState` 不允许被系统模块原地修改。
- 每个动作必须产生 `BattleTransition`。
- 每个 `BattleTransition` 必须包含 before snapshot、after snapshot、events、mutations、settlement。
- `before snapshot + mutations` 必须能 replay 到 after snapshot。
- settlement record 必须能追溯到 mutation，或显式标记为 process-only event。
- runtime 不允许引用 `simulator_v7_7`、`model_pack_v3_0`、`SimulatorRuntimeAdapter`、`_legacy_effects`、`action_ctx`。
- 未支持的 TBGD opcode、condition、formula 必须进入 coverage matrix，不允许静默跳过。
- 角色、敌人、技能、状态、装备、关卡机制不能硬编码在核心系统里。

## 模块边界

`core/` 只负责战斗事实：

- `BattleState`：完整战斗状态。
- `ActionCommand`：外部动作输入。
- `ActionTransaction`：单次动作事务。
- `Mutation`：状态变化事实。
- `BattleTransition`：动作前后完整转移。
- `MutationReducer`：mutation replay 与状态落地。

`rules/` 只负责 Canonical IR 的查询和执行判断：

- `RuleBook`：只读规则索引。
- `RuleEvaluator`：condition 和 formula 执行。
- `ir.py`：Canonical IR schema。

`systems/` 按游戏机制分组：

- `target`：目标解析。
- `resource`：HP、护盾、能量、战技点和特殊资源。
- `status`：状态、层数、持续时间、动态值。
- `timeline`：速度、AV、提前、延后、回合窗口。
- `queue`：终结技插队、立即行动、额外回合、召唤物行动。
- `trigger`：事件窗口、触发器匹配。
- `effect`：EffectIR opcode 分发。
- `damage`：直伤、削韧、击破、超击破、DoT、真实伤害、生命流失。

`tbgd/` 只负责 raw TBGD 到 Canonical IR：

- discovery：发现文件、raw type、GameCore opcode、事件、公式。
- lowering：生成 Canonical IR。
- coverage：输出支持矩阵。

`tools/` 只负责离线验证与输出，不承载战斗规则。

## 动作执行生命周期

完整动作生命周期按固定顺序推进：

1. `ActionCommand` 进入 executor。
2. 捕获 before snapshot。
3. 解析 actor、action、target。
4. 校验并支付费用。
5. 发出 action begin / before skill use 事件窗口。
6. 生成 hit plan。
7. 对每个 hit 执行目标、命中、伤害、削韧、击破。
8. 发出 after hit / after attack / after skill use 事件窗口。
9. 处理能量、击杀、击破延迟、状态持续时间。
10. 处理回合结束、AV、队列 drain。
11. 汇总 settlement。
12. 捕获 after snapshot。
13. 校验 replay。

任何机制都只能插入到这些明确窗口里，不允许绕开生命周期直接改状态。

## 规则来源

Canonical IR 必须携带来源证据：

- `source_path`
- `raw_type`
- `raw_id`
- `evidence`
- `coverage_status`

IR 的支持状态含义：

- `executable`：runtime 已执行该规则。
- `supported_alias`：已经归一化为受支持语义。
- `audit_only`：已收集并可追查，但尚未执行。
- `unsupported`：已发现但尚未支持。
- `skipped_with_reason`：有意跳过，并记录原因。

## 验收门槛

每个结构检查点至少满足：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir validation_outputs_v0_200
```

每个机制检查点额外满足：

- coverage matrix 中对应 opcode 从 `unsupported/audit_only` 推进到 `executable`。
- 新增最小 scenario。
- 新增 snapshot replay 校验。
- settlement record 能追溯到 mutation 或 process-only event。
- 不能引入 v7/model-pack/legacy context 依赖。

