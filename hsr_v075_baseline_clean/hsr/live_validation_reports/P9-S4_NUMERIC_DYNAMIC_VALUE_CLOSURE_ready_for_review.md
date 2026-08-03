# P9-S4 数值表达式与动态值通用闭合验收报告

## 验收结论

`P9-S4` 通过验收。当前角色能力来源中的 33 个动态值 family、2,527 次出现均已进入同一
类型化操作模型；这表示来源形状和执行责任已经完整分类，不表示依赖后续领域生产者的每个
family 都已可执行。

本阶段没有增加角色名、角色 ID 或混淆 opcode 专属 runtime handler。普通能力任务和状态
callback 都经公共 `EffectRegistry` 进入同一计划与执行入口，旧 callback 动态值执行分支已删除。

## 生产实现

- `NumericOperandIR` 和 `DynamicValueOperationIR` 统一 fixed、表达式、动态值复制、属性、状态、
  modifier、资源及后续领域 operand 的类型、来源、准入和稳定身份。
- `DynamicValueExecutionRequest -> plan_dynamic_value_operation -> execute_dynamic_value_plan` 是唯一
  read/calculate/write 管线。计划绑定完整前态、请求、操作、mutation 和 settlement；伪造或过期
  计划 fail-closed。
- unit、ability、status、event 四种作用域按 owner、target 和对应生命周期身份隔离。同名值不会
  跨单位、动作实例、状态实例或事件实例读取。
- 操作 ledger 使同一事件身份的重放幂等；同身份不同内容、损坏索引、伪造 ledger、畸形状态
  动态值容器和跨状态写入均保持零副作用。
- S3 解码的两个混淆动态值 family 被规范化为同一通用操作模型；runtime 不识别混淆名称。
- 动态值 mutation 通过原生 settlement 和 `RuntimeSourceAuditor.validate_execution` 审计。runtime
  准入只读取正式 IR 和状态身份，不读取 `source_trace` 决定行为。
- bool、NaN、Infinity、除零、表达式栈错误和超大整数转换均在模型或计算边界拒绝。

## 代码审查

验收除运行验证外，定向检查了模型闭包、lowering、普通能力调用链、callback 调用链、状态写入、
operation ledger、settlement、source audit 和 replay。审查期间关闭了以下执行层最初未覆盖完整的
问题：

1. 可自行构造或篡改动态值计划。
2. 状态身份只做单向核对，或由审计 trace 参与 runtime 准入。
3. 损坏的状态动态值和索引容器可能抛出异常。
4. 非有限超大整数可能在 `float` 转换时抛出 `OverflowError`。
5. callback 保留第二套动态值执行器。
6. S3 解码来源没有通过通用操作模型进入后续 lowering。

清理后，S4 修改涉及的 `status_callbacks.py` 和主验证器没有新增未使用导入；验证器为 899 个
非空行，未以拆文件或压缩证据绕过 900 行预算。

## 聚焦证据

主验证结果：

```text
ok=true
family_count=33
occurrence_count=2527
current_dynamic_value_families_all_occurrences_typed=true
numeric_operands_source_backed_per_occurrence=true
dynamic_value_scopes_distinct=true
decoded_dynamic_sources_use_shared_operation_model=true
real_formal_action_uses_shared_contract=true
character_specific_numeric_handlers=0
```

来源投影在读取和 IR 构建前按 family 过滤；source snapshot、projection 和 source graph 各构建
一次，完整 Canonical IR lowering 为 0 次。

正式正例由当前目录结构化选出一个真实动作及其真实动态值任务，而非按角色名或固定 ID 选样。
该效果通过生产目标解析、公共 `EffectRegistry` 和 `CombatExecutor.commit_eventful_transition` 产生
1 个 mutation、1 个 settlement，source audit 与 replay 均通过且无 RNG。

这里证明的是“真实动作关联效果经过正式生产提交链”，不宣称该技能的其余 15 个 callback root
已在 S4 全部执行。完整动作还依赖 S5-S17；状态 callback 生命周期端到端由 S10 复核。

固定负例矩阵全部通过，覆盖作用域串线、跨状态身份、缺失/歧义 binding、计划全部字段篡改、
stale plan、重放冲突、伪造 ledger、畸形状态容器、非有限值、除零和表达式栈错误。

## 验证与资源

- P9-S4 主验证：exit 0；验证器墙钟 4.403 秒，进程墙钟 4.83 秒，峰值 RSS 214,304 KiB，
  evidence 46,954 bytes。
- P9-S3 直接回归：`ok=true`；13.40 秒，峰值 RSS 335,416 KiB，224,295 bytes。
- P7-S5 typed expression IR 直接回归：`ok=true`，6 行矩阵通过；0.32 秒，峰值 RSS 68,168 KiB。
- `compileall`：通过，缓存写入 `/tmp`。
- `git diff --check`：通过。

未运行完整 lowering、P1-P8 聚合、P9 相邻阶段主验证或完整技能目录启动。

## Deferred 与边界

- 依赖目标关系、事件 payload、伤害、治疗、击破、波次、随机数等领域值的 operand 已类型化并
  指向 S5、S9-S15 的真实生产者；生产者闭合前继续 blocked，不合成数值。
- 两个 client-only 动态值 family 已分类为非战斗输入，不进入 gameplay runtime。
- ability/status/event 过期条目当前在读取层不可见，语义上不会跨生命周期串值；其物理回收和
  ledger 压缩应随 S9/S10 生命周期入口统一实现，并在 S20 做长战斗体积审计。这是长期资源治理
  项，不改变 S4 当前战斗语义结论。
- 本报告不表示 79 条角色已全部正式准入，也不开始 P9-S5。
