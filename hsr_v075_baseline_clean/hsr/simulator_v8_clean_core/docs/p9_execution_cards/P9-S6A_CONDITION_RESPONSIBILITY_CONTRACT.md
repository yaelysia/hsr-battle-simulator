# P9-S6A 条件责任与来源分区契约执行卡

## 执行配置

- 对应问题：P9-I07 的责任边界；机制包 M05 的来源层。
- 硬前置：P9-S5D1 已验收，S5D2 的目标机制部分已验收。
- 推荐：5.6 Sol / xhigh / 普通聚焦。
- 状态：accepted。

## 前因后果

旧 S6 同时要求重新发现完整条件范围、决定状态/瞬时上下文归属、排除纯表现分支并实现
committed-state evaluator。范围过大，而且“条件名以 By 开头”不能代表它一定属于条件语义。
本卡先固定唯一责任目录；后续实现只能消费该目录，不能重新用名称或错误字符串划分范围。

## 闭合地图

### 权威分母

- 当前角色 scope projection 中，`nominal_semantic_kind=combat_condition` 且属于正式 gameplay
  来源的全部 typed occurrence。
- 不使用 `By*` 名称前缀、历史数量或 evaluator 当前支持列表反向定义分母。

### 输入与输出权威

- 输入：同一来源指纹下的角色 raw snapshot 与完整 scope projection。
- 输出：递归不可变的条件责任目录。每条未由现有 family 拥有的记录只能归入 S6B、S7、
  明确非战斗排除或 fail-closed 未分类。
- lowering 继续只生成 blocked 条件；本卡不新增 evaluator 行为。

### 生产不变量

- 分区互斥且穷尽，未知 family、未知同级字段和未知嵌套责任均 fail-closed。
- 责任行保存精确 raw 路径、字段签名、所需上下文、权威域和生产阶段。
- 表现分支只有在完整受控末端均为非战斗操作时才可排除。
- `TriggerAbility`、`IncludeTaskListTemplate` 等未解析跳转禁止作为纯表现依据。
- 已有 family 集合只有 evaluator 一处权威；lowering 不保留复制列表。

## 详细目标

1. 建立条件责任 IR、问题 IR 和目录模型，构造与 JSON 边界严格、递归不可变。
2. 从类型化 scope 动态重建当前条件记录集合，并与责任目录一一对账。
3. 对当前未拥有的 family 保存全部真实字段签名；来源变化产生新字段时立即阻断。
4. 为每条 gameplay 条件记录明确 committed-state 或 transient-context 的数据权威与生产者。
5. 对明确的预演配置和纯表现末端按 occurrence 排除，不按 family 整体排除。
6. 将旧“所有角色条件都交 S7”的 lowering blocker 替换为精确 S6B/S7/未知原因。
7. 保证现有 family admission 不因本卡改变，未知嵌套条件保留最内层真实阻断原因。

## 本阶段不做

- 不实现任何新条件求值、operand、comparator 或量词。
- 不修改 runtime、事件、伤害、状态、资源、队列或 UI。
- 不宣称现有 family 的每个 payload 都 executable。
- 不以 validation fixture 冒充真实条件执行。

## 验收目标

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 分母正确 | 由 typed semantic scope 重建且非空 | source summary |
| 分区完整 | existing/S6B/S7/excluded/blocked 互斥穷尽 | responsibility ledger |
| 来源真实 | 每条责任行可逆回 raw 节点和字段签名 | source audit |
| 排除保守 | 排除分支无未解析 ability/template 跳转 | exclusion audit |
| 变化阻断 | 新 family、字段或嵌套生产者不被默认接纳 | minimal negatives |
| lowering 单一权威 | 已有 family 复用 evaluator 权威，缺口原因精确 | focused lowering |

## 验证与预算

- 唯一主入口：`validate_p9_s6a_condition_responsibility_contract`。
- 只构建一次 raw snapshot、一次 scope projection、一次责任目录；完整 Canonical IR 为零。
- 预算：6 分钟、512 MiB、1 MiB evidence、600 行验证代码。
- 只运行 `compileall` 和 `git diff --check`；不运行 P1-P8、S5 或全角色动作聚合。
- 验收后验证器冻结为 `historical_evidence`。

## 唯一执行清单

- [x] 条件分母来自类型化语义 scope，不依赖名称启发式。
- [x] 现有 family 与全部缺口记录形成互斥穷尽责任目录。
- [x] 字段签名、来源、上下文与后续生产阶段完整且 fail-closed。
- [x] 表现分支排除沿实际末端闭合，未解析跳转不被排除。
- [x] lowering 使用唯一 family 权威并保留精确 blocker。
- [x] 聚焦验证、代码审查与资源审计通过。
