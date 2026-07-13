# P7-S5 类型化可执行表达式 IR 待验收报告

状态：`ready_for_review=true`。本报告仅作为统一验收的证据索引，不宣告阶段完成，不修改 P7 checklist。

## 本阶段结果

- numeric raw 语法只在 `tbgd/expression_lowering.py` 解析；runtime 只消费 `hsr.numeric_expression.v1` 的 fixed、dynamic hash 或 program 指令。
- target lowering 生成 `hsr.target_expression_node.v1`，runtime 固定读取 `TargetExpressionIR.payload.typed_node`；`audit_raw` 仅保留来源证据，不进入执行分支。
- condition lowering 生成 `hsr.condition_expression_node.v1`，包括嵌套条件、目标 operand 和数值 operand；未 lower 的 `ConditionIR` 在 runtime 明确阻断。
- status callback task payload 已从完整 raw task 改为最小类型化 runtime payload；break、super-break、status callback 和 action plan 不再从 raw Postfix 中提取动态哈希。
- RuleBook 对 target、condition、formula ID 使用唯一索引；重复 ID 不再覆盖或取首项，missing 与 ambiguous 返回不同结构化原因。
- 动态哈希解析同时检查“同一索引多个 entry”和“多个 binding source 命中”两类歧义；任一歧义均返回 `dynamic_hash_binding_ambiguous`，不产生结果值。

## 结构化验证证据

主验证：

```text
python3 -m simulator_v8_clean_core.tools.validate_p7_s5_typed_expression_ir --output-dir /tmp/p7_s5_main
```

结果：`ok=true`、`ready_for_review=true`、`rows=6`。

验证实际覆盖：

- numeric：raw fixed 与 Postfix 被 lowering 为 typed IR；unsupported opcode 得到独立 unsupported 结果；runtime raw 输入被拒绝；同源多 entry 歧义被阻断。
- target：Caster alias typed 正例由 runtime 执行；未知 Target kind 保留 source/audit raw 并 blocked；runtime 静态检查确认只读取 typed node。
- condition：AlwaysTrue typed 正例执行；未知 opcode blocked；缺表达式 schema 的旧 payload 被拒绝。
- reference linking：target、condition、formula 的 missing 与 ambiguous 六个结果均可区分，重复 ID 不再可通过普通 RuleBook lookup 取到。
- committed transition 的 source audit 与 mutation replay 均通过，验证表达式边界收紧未破坏正式后继契约。
- 对七个 runtime 消费文件扫描 `$type`、Postfix token、`get("raw")`，未发现 raw parser 入口；raw numeric parser 只存在于 lowering 层。

输出：

- `/tmp/p7_s5_main/validation_summary_p7_s5_typed_expression_ir.json`
- `/tmp/p7_s5_main/p7_s5_typed_expression_ir_matrix.json`
- `/tmp/p7_s5_main/p7_s5_typed_expression_ir_evidence.json`

## 直接回归与资源情况

- P5-S4 ValueResolver admission：`ok=true`，7 行，分类为 `executable=6`、`boundary_only=1`。
- v0_288 target expression IR：`ok=true`。
- P6-S4/S5 boundary static：`ok=true`，6 行。
- P7-S3：`ok=true`，9 case。
- P7-S4：`ok=true`，11 ownership rows。
- `compileall`：通过。
- `git diff --check`：通过。
- P5 与 target IR 重验证严格串行，以 `nice -n 10` 运行且仅写 `/tmp` 摘要；未写完整 CanonicalIR、RuleBook 或 transition dump。
- 未运行已知会默认写约 1.6GB 产物的 P1-5。

## 明确未做

- 未要求一次支持全部 TBGD target/numeric/condition 表达式；未知子集继续 blocked。
- 未删除 raw 来源证据；只隔离其执行职责。
- 未修改 P7 checklist，未提交 Git 检查点。

## 统一验收反例修正补充

验收发现原 `typed_node` 仍复制 `TargetType` / `Sequence` / `Predicate` 等 raw 字段，runtime 还会现场构造 `ConditionIR`。现已新增不可变 `TargetExpressionNodeIR`：children、candidate、predicate、target、query、fetch、sort/index/take 等均为显式字段；嵌套 predicate 在 lowering 时即生成 `ConditionIR`。`TargetSystem` 只读取 `expression.node`，不再读取旧字段或调用 `_condition_from_raw`。

新增 `TargetSequence -> TargetFilter(ByTargetTeam)` 反例：清空整个 audit payload 后仍得到相同目标，typed child 中直接持有 `ConditionIR`。修正后 S5 主验证 `ok=true`。

S16 真实来源补充覆盖了此前主验证未覆盖的复杂 typed 组合：`ByCompareCharacterNumber` 的 `CompareNumber` 在 lowering 时成为 numeric IR；ability 文件内 `GlobalTargetAlias` 在 lowering 时递归展开为 `TargetSequence/TargetFilter/ConditionIR`，带循环保护。runtime 只通过 `TargetSystem.resolve_expression_node` 与 evaluator 的已解析 target group 消费这些节点，不读取旧 `TargetType/Sequence/Predicate` 字典。本轮 `/tmp/p7_s5_final` 复跑仍为 `ok=true`。
