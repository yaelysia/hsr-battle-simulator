# v8 机制实现工作流

## 基本原则

每个机制都按同一条链路进入系统：

```text
TBGD source -> Canonical IR -> RuleBook -> system handler -> Mutation -> Settlement -> Snapshot replay
```

不允许因为某个角色、敌人、遗器或关卡急需而直接在 runtime 里补特判。

## 新机制准入流程

1. 确认 TBGD 来源。
   - 找到 Excel 表、ConfigAbility、GlobalModifier、SummonUnit、Monster 或 Stage 来源。
   - 记录 `source_path/raw_type/raw_id/evidence`。

2. 更新 coverage。
   - discovery 能看到相关 opcode、condition、formula、event。
   - 未支持项必须显示为 `unsupported` 或 `audit_only`。

3. 定义 Canonical IR。
   - 确定该机制属于 action、effect、condition、formula、status、trigger、modifier、target 中哪一类。
   - payload 只保留机制语义，不泄漏 TBGD raw 结构到 runtime。

4. 实现 RuleEvaluator。
   - condition 返回 `True/False/None`，`None` 表示不能安全执行。
   - formula 返回数值或 `None`，不能执行时必须保留审计记录。

5. 实现 system handler。
   - handler 只读 `BattleState` 和 `RuleBook`。
   - handler 输出 `GameEvent` 和 `Mutation`。
   - handler 不直接修改 state。

6. 汇入 settlement。
   - damage/resource/status/queue/timeline 都要有对应 settlement record。
   - record 需要标明来源、目标、计算输入、输出、是否 process-only。

7. 增加验证。
   - 最小 scenario。
   - snapshot replay。
   - coverage 状态变化。
   - 静态隔离检查。

## 机制实现顺序

优先顺序从通用骨架到复杂窗口：

1. identity 和 scenario。
2. target。
3. resource。
4. direct damage。
5. formula 和 modifier ledger。
6. status lifecycle。
7. toughness。
8. break。
9. trigger windows。
10. queue 和 timeline。
11. DoT。
12. super-break。
13. heal 和 shield。
14. summon。
15. enemy AI 和 wave。
16. C0-C8 route replay。

## Definition of Done

一个机制只有同时满足以下条件，才算进入 v8：

- TBGD 来源明确。
- Canonical IR 有 schema。
- coverage matrix 有状态变化。
- runtime handler 不依赖旧模拟器。
- 所有状态变化都产生 mutation。
- before + mutations 可以 replay 到 after。
- settlement 可以追溯到 mutation 或 process-only event。
- 有最小 scenario 或验证样例。
- live validation report 记录范围、命令、结果和剩余风险。

## 禁止模式

- 直接读取 TBGD raw 字段完成 runtime 判断。
- 在 `systems/` 中判断具体角色名、技能名或关卡名。
- 在 handler 内原地改 `BattleState`。
- 为了跑通单个 case 隐式跳过未知 opcode。
- 把公式计算结果写死为观测值。
- settlement 从日志事后反推。
- snapshot 缺字段但仍标记通过。

