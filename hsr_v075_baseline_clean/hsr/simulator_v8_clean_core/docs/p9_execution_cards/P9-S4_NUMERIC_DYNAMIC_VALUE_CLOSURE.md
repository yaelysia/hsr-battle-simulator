# P9-S4 数值表达式与动态值通用闭合执行卡

## 执行配置

- 对应问题：P9-I05；机制包 M03，包含 S3 转交的动态值来源。
- 硬前置：P9-S3 已验收并形成检查点。
- 推荐：5.6 Sol / `max` / 普通聚焦。
- 理由：动态值贯穿条件、状态、伤害、资源和队列，错误作用域或绑定会产生难以追踪的跨机制污染。

## 当前事实与阶段结果

当前来源至少有 24 个明确动态值族、2,371 次出现。现有 typed numeric evaluator、binding
source 和 dynamic-value runtime 可以复用，但 property/status/damage/heal/shield/resource 读取、
复制、变换和 callback 准入仍不统一。

完成后，所有当前动态值来源都归入同一“typed operand -> finite calculation -> scoped write”
契约。普通 ability、状态 callback 和事件消费者引用同一计划/handler；S4 只证明普通生产入口
和公共调用面，callback 端到端由 S10 复核。

## 详细目标

1. 统一 fixed、dynamic hash、表达式程序及 source-backed property/status/event/resource operand。
2. 明确动态值作用域、owner、target、ability/status instance 和生命周期；同名不同作用域不串值。
3. 将 define/set/add/copy 和按属性、状态数、modifier value、伤害/治疗/护盾等读取归入通用操作模型。
4. 计算前闭合来源、目标、数值有限性和 operand 唯一性；提交时检测 stale before-state。
5. Runtime 转换遵循现有数值边界，不允许 bool、NaN、Infinity、缺失 binding 或 float 显示值伪装来源。
6. S3 解码并转交 M03 的来源必须通过同一模型，不建立混淆 opcode handler。

## 本阶段不做

- 不执行依赖具体事件 payload 的条件；S7 负责。
- 不修改具体伤害、状态、资源公式，只提供它们消费的 typed value。
- 不为 callback 复制 dynamic-value executor。
- 不从 source trace 或 UI 值读取 runtime operand。

## 架构与负例

- 动态值缺失、多来源冲突、作用域错配、owner/target 交换、stale plan 均原子 blocked。
- 同一 task 重放不能意外累加；明确 add 操作按事件身份幂等。
- 修改输入容器或 source trace 不改变已建表达式和 fingerprint。
- 除零、栈下溢、未知表达式 opcode 和非有限结果不能产生 mutation。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 来源形状完整 | 当前 M03 family 全部 lower 为 typed operation | family matrix |
| 作用域正确 | unit/ability/status/event scope 不串线 | scope matrix |
| 单一执行面 | ability 和公共 effect contract 共用计划 | call-path audit |
| 失败原子 | 缺值/冲突/过期/非有限均零副作用 | negative matrix |
| 可重放 | operation identity、settlement、replay 一致 | focused transition |

## 结构化通过谓词

```text
current_dynamic_value_families_all_typed=true
numeric_operands_source_backed=true
dynamic_value_scopes_distinct=true
read_calculate_write_contract_shared=true
ambiguous_or_missing_binding_blocked=true
non_finite_numeric_rejected=true
stale_dynamic_value_plan_rejected=true
blocked_operation_state_unchanged=true
sampled_settlement_source_audited=true
sampled_replay_equal=true
character_specific_numeric_handlers=0
```

## Gap 与停止条件

- raw operand 有结构但 expression lowering 丢字段：本阶段 lowering gap，必须修。
- 需要新领域状态才能取值：建立 typed operand contract，并标记对应 S10-S15 生产者，不合成值。
- 同一来源形状具有两种无法区分语义：退回 S3，不选择首项。
- 公共执行面只有验证器调用：阶段阻断，必须有非 tools 生产调用者。

## 拟改范围

- `rules/expression_ir.py`、`rules/evaluator.py`、`rules/value_binding.py`。
- `systems/dynamic_values.py`、`systems/ability.py`、`systems/effect.py` 的公共计划/执行面。
- `tbgd/expression_lowering.py`、角色能力 lowering。
- 主验证 `tools/validate_p9_s4_numeric_dynamic_value_closure.py` 和报告。

## 验证与资源

- 按 M03 family 在来源层过滤，构建一次窄 IR；选取结构不同的真实来源，不枚举全部 task 实例。
- 一个正式 ability action 正例、结构化 family matrix 和固定负例；callback 只验证公共调用面，不伪造事件。
- direct 最多 2 项，仅在改 evaluator 或 atomic commit 时运行现行小型契约。
- 预算：8 分钟、1 GiB、5 MiB、900 行；不跑 P5/P7 聚合。

## 唯一执行清单

- [x] 当前动态值 family 全部进入统一 typed operation。
- [x] operand、作用域、生命周期和操作身份来源真实。
- [x] 普通 ability 与公共 effect 路由唯一，无 callback 第二套实现。
- [x] 缺值、冲突、非有限和 stale plan 原子 blocked。
- [x] 正式 transition、settlement、audit 和 replay 证据闭合。
- [x] 主验证、必要 direct 和资源审计通过并提交 `ready_for_review`。
