# P9-S6B committed-state 条件求值执行卡

## 执行配置

- 对应问题：P9-I07 第一部分；机制包 M05 committed-state 求值层。
- 硬前置：P9-S6A 已验收，责任目录来源指纹仍与当前 raw 一致。
- 推荐：5.6 Sol / max / Goal。
- 状态：accepted。

## 阶段目标

把 S6A 归给 committed state、数据卡、实体关系和目标集合的条件统一接入 evaluator。
完成后，每个当前 S6B family 都有类型化 operand、比较或量词语义；可用生产事实返回 true/false，
缺少后续领域生产者时返回精确 blocked。S6B 内部不得再有未知 family、字段或默认 false。

## 权威边界

- 唯一范围：实时重建的 S6A `p9_s6b_committed_state` 责任集合。
- `BattleState`、RuleBook 数据卡、S5B 实体关系与目标查询是只读事实权威。
- S11/S15/S17 等后续领域拥有的事实只建立 typed provider 契约；生产者未完成前保持 blocked，
  不在 fixture 中写入伪正式状态。
- evaluator 返回 `true`、`false`、`blocked` 三态；业务 false 不能掩盖缺事实或非法关系。

## 详细目标

1. 建立统一 operand resolution result，包含值类型、来源身份、状态和 blocked reason。
2. 复用现有数值比较、目标解析、关系与状态查询，不在 evaluator 复制第二套取值逻辑。
3. 闭合生命、战技点、特殊资源、角色/怪物定义、命途、队伍关系、召唤关系、可选状态等
   当前已有生产事实。
4. 为韧性分段、body-part、battle-event entity、HP shared group 等后续事实定义窄 provider；
   provider 缺失时按 S6A producer owner 阻断。
5. 实现列表 any/all 与组合条件短路。集合解析成功时 empty any=false、empty all=true；
   集合解析失败仍 blocked。
6. lowering 对每个 S6B family 生成严格 typed payload；未知字段、错误枚举、错误数值或目标种类阻断。
7. 逐项迁移 RuleEvaluator 正式调用者，禁止角色名、固定 ID 和专属 handler。

## 本阶段不做

- 不处理动作、事件、伤害、状态 callback、资源变化或队列瞬时上下文；这些只属于 S7。
- 不提前实现 S11-S17 领域生产者，也不把 external producer gap 计成 S6B 内部成功正例。
- 不运行全角色动作、完整 Canonical IR 或历史 P1-P8 聚合。

## 验收目标

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 范围继承 | 当前 S6B 责任集合与 S6A 完全一致 | responsibility diff |
| family 内部闭合 | 每个 family 有 typed lowering 与 evaluator 分支 | family ledger |
| 三态严格 | true、false、blocked 不混淆 | focused matrix |
| 关系复用 | 正式调用链使用现有查询权威 | CodeGraph audit |
| 外部依赖诚实 | 每条缺生产事实记录精确 owner，零伪 executable | provider ledger |
| 组合正确 | any/all/and/not 的短路、空集和 blocked 传播正确 | quantifier slice |

## 停止条件

- S6A 指纹、分母或字段签名变化：返回 `plan_mismatch`，先重建 S6A。
- 需要修改事件、伤害、状态、资源或队列生产语义：停止并交回对应后续阶段。
- 同一 operand 出现两个事实权威，或只能靠角色特判实现：停止，不提交 ready_for_review。

## 验证与预算

- 一个 S6B 聚焦主入口，只扫描 S6A 分区并构建最小 RuleBook/state fixture。
- 每条新生产不变量一个最小负例；目录完整性只保留一份聚合账本。
- direct 最多两个，仅限实际修改的 evaluator 与 S5B 查询切片。
- 预算：8 分钟、1 GiB、5 MiB evidence、900 行验证代码。

## 唯一执行清单

- [x] S6A committed-state 责任集合被当前指纹完整继承。
- [x] 全部 S6B family 完成严格 lowering 与统一三态求值。
- [x] 当前生产事实正例、非法输入负例和外部 producer blocker 均诚实。
- [x] comparator、关系和目标集合复用现有权威，无角色专属分支。
- [x] 正式 evaluator 调用者完成迁移且无旧语义残留。
- [x] 聚焦验证、必要 direct、代码审查与资源审计通过。
