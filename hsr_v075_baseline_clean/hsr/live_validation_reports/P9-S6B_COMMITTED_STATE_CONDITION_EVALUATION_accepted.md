# P9-S6B committed-state 条件统一求值验收报告

## 结论

状态：accepted。

S6B 完整继承 S6A 当前来源指纹下的 178 条责任记录和 21 个条件 family。当前已有事实的
145 条记录进入统一三态求值；依赖后续领域生产者的 33 条记录分别精确归属 P9-S11、S15、
S17，并继续 fail-closed。本阶段不宣称这些外部事实已经可执行。

## 生产结果

- 新增递归不可变的事实请求与解析结果，明确值类型、事实权威、来源身份和阻断原因。
- 建立已提交状态事实提供器，统一读取战技点、生命、生命周期、角色命途、怪物档位、特殊资源、
  状态抗性、召唤关系、敌我关系和目标可选性。
- 韧性分段、红韧性、共享生命、部位实体和战斗事件实体保持类型化外部 producer blocker，
  没有通过 fixture 写入伪正式状态。
- 21 类条件完成严格 lowering、比较、反转、组合及 any/all 三态短路；解析成功的空集合遵循
  `any=false`、`all=true`，集合解析失败仍为 blocked。
- 同能力文件内目标别名必须存在于真实 `GlobalTargetAlias` 注册表；未知别名仍由正式目标解析
  fail-closed。`Mask_AliveOnly` 复用既有生命周期权威，没有角色专属放行。
- ability、trigger、status callback、target filter 和伤害 modifier 的正式条件入口统一携带事实
  提供器。业务 false 选择失败分支或跳过 trigger；未知事实阻断当前原子事务，不能静默当作 false。
- 状态抗性比较与状态施加复用同一抗性计算，不建立第二套公式。

## 五面审查

1. 来源范围：责任目录、raw 反查、family 集合及字段签名完整一致；来源指纹与 S6A 验收基线一致。
2. 生产不变量：错误事实种类、参数、身份、值类型、非有限数值和 provider 返回均 fail-closed。
3. 正式调用者：所有非 tools 的 `evaluate_condition_result` 调用路径已审计；没有残留旧上下文组装。
4. gap 归属：当前 145 条；S11 3 条；S15 8 条；S17 22 条；未归属记录为零。
5. 验证独立性：来源账本直接反查 raw 行；运行时期望由手写语义切片给出；业务 `ok` 只由业务
   谓词决定。验证器 899 个非空行，低于 900 行预算。

## 验证结果

最终主入口：

```text
python3 -B -m simulator_v8_clean_core.tools.validate_p9_s6b_committed_state_condition_evaluation
```

- `ok=true`，27/27 谓词通过。
- 178/178 条责任记录来源可逆并严格 lowered；21/21 family 与 runtime 注册表一致。
- 墙钟 3.43 秒；峰值 RSS 342,296 KiB；evidence 120,450 bytes。
- raw snapshot、scope projection、责任目录各构建一次；完整 Canonical IR 构建 0 次。
- S5D1 现行 direct：35/35，通过；墙钟 4.61 秒，峰值 RSS 269,108 KiB。
- `compileall`、最小运行时/非法数值探针和 `git diff --check` 通过。

首次主入口有两项失败：6 条真实来源使用文件内目标别名或 `Mask_AliveOnly`，以及验证器仍期待
错误的 schema 常量。生产修正采用通用文件级别名与生命周期契约，验证断言改为当前真实 schema；
最终主入口只重跑一次。

S5B 历史 direct 的目标、来源和关系检查均通过，但总门仍要求随机 shuffle 保持
`random_target_pending_s5d`。该期待已被验收后的 S5D1 正式实现淘汰，因此没有修改生产代码或
冻结的历史验证器；改用现行 S5D1 direct 证明随机目标未回退。

## 后续边界

- P9-S7 负责动作、事件、伤害、资源和队列等瞬时上下文条件。
- P9-S11、S15、S17 分别补充共享生命/结算、韧性和部位/战斗事件实体等正式事实生产者。
- S6B 验证器冻结为 `historical_evidence`，后续阶段不得继续扩写或默认重跑。
