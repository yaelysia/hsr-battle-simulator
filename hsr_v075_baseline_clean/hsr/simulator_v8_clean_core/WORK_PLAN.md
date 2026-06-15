# v8 工作计划

## 当前基线

当前提交基线为 `v0_200`：

- v8 独立目录已建立。
- TBGD discovery、Canonical IR、coverage matrix 已可生成。
- 核心状态、mutation、snapshot replay 合约已建立。
- v8 runtime 静态隔离检查已建立。

`v0_201` 的目标是冻结工作流与阶段顺序，防止后续机制实现再次变成临时补丁。

## 阶段计划

### v0_201 工作流冻结

目标：

- 固定架构不变量。
- 固定机制准入流程。
- 固定阶段推进顺序。

验收：

- `ARCHITECTURE.md` 完成。
- `MECHANIC_WORKFLOW.md` 完成。
- `WORK_PLAN.md` 完成。
- live validation report 完成。

### v0_202 Scenario 与身份解析

目标：

- 定义 v8 scenario 格式。
- scenario 只描述战斗输入和路线，不承载规则。
- 角色、敌人、技能、状态必须通过 TBGD ID 或 Canonical IR ID 解析。

交付：

- `ScenarioIR`
- `ScenarioLoader`
- `IdentityResolver`
- 最小单角色打木桩 scenario。

验收：

- scenario 可加载为 `BattleState + ActionCommand[]`。
- 不读取旧 compiled case。
- snapshot replay 仍通过。

### v0_203 Target、Resource、Timeline 基础

目标：

- 实现显式目标选择。
- 实现 HP、能量、战技点基础 mutation。
- 实现基础 AV 字段与回合 owner 选择。

交付：

- `TargetResolution`
- resource settlement records
- timeline settlement records

验收：

- 单体、自己、敌方全体三类目标可解析。
- 资源变化能 replay。
- settlement 可追溯 mutation。

### v0_204 Direct Damage 纵切链路

目标：

- 跑通第一条完整战斗链路：

```text
ActionCommand -> target -> cost -> direct damage -> HP mutation -> settlement -> snapshot replay
```

交付：

- `DamagePacket`
- direct damage formula scaffold
- damage settlement
- 最小 direct damage scenario。

验收：

- direct damage 不依赖 v7。
- HP 变化只通过 mutation。
- damage record 与 mutation 一一对应。

### v0_205 Formula 与 Modifier Ledger

目标：

- 建立公式执行路径。
- 建立 modifier ledger 原生生成。
- applied/skipped term 都在判断点记录。

交付：

- `FormulaEvaluator`
- `ModifierLedger`
- status modifier query scaffold

验收：

- 至少一个 applied term。
- 至少一个 skipped term。
- 每个 term 有 source、bucket、scope、condition、reason。

### v0_206 Status Lifecycle

目标：

- 实现状态 add/remove/refresh/stack/duration。
- 状态动态值通过 Canonical IR 进入 runtime。

交付：

- `StatusInstance`
- status settlement
- duration tick mutation

验收：

- 状态层数和持续时间可 replay。
- 状态来源可追查到 TBGD。

### v0_207 Toughness 与 Break

目标：

- 实现削韧、弱点击破、击破延迟和击破伤害骨架。

交付：

- toughness mutation
- break event
- break damage settlement

验收：

- toughness 变化可 replay。
- break 事件进入 trigger window。
- break damage 进入统一 damage settlement。

### v0_208 Trigger Windows 与 Queue

目标：

- 建立 HSR 事件窗口。
- 实现终结技插队、立即行动、额外回合基础队列。

交付：

- `GameEvent` window map
- `TriggerSystem`
- queue settlement

验收：

- trigger 条件失败可审计。
- queue 入队/出队都通过 mutation。

### v0_209 DoT、Super-break、Heal、Shield

目标：

- 扩展非直伤与生存机制。

交付：

- DoT tick。
- super-break damage。
- heal settlement。
- shield mutation。

验收：

- 所有伤害族走统一 damage settlement。
- heal/shield 不绕过 resource/status 系统。

### v0_210 Enemy、Wave、Summon 与 C0-C8 重建

目标：

- 加入敌人行动、波次切换、召唤物行动。
- 用 v8 scenario 重建 C0-C8 对照案例。

交付：

- enemy action selection scaffold
- wave transition
- summon unit timeline
- C0-C8 v8 scenario

验收：

- v8 route replay 可执行。
- 关键 settlement 可审计。
- Tribbie 与 Seele 关键数值进入回归对照。

## 每阶段固定输出

每个阶段都必须新增或更新：

- v8 代码或文档。
- `validation_outputs_v0_xxx/`。
- `live_validation_reports/*_v0_xxx.md`。

每个阶段都必须记录：

- 改动范围。
- 验证命令。
- coverage 变化。
- snapshot replay 状态。
- 未支持机制和风险。

