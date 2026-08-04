# P9-S8 能力图控制流、命中序列与模拟时序闭合执行卡

## 执行配置

- 对应问题：P9-I08；机制包 M06、M16 控制流部分。
- 硬前置：P9-S7 已验收并形成检查点。
- 推荐：5.6 Sol / `max` / Goal 模式。
- 理由：模板、循环、触发、并行和命中顺序决定整个能力图执行，错误会造成漏结算、重复结算或死循环。

## 当前事实与阶段结果

当前来源有 31 个控制流/模拟时序族、8,651 次出现。现有 `AbilityTaskSystem` 支持部分
Predicate、固定循环、TriggerAbility 和伤害 emission，但模板引用、循环形状、random config、
projectile 命中序列和 Wait* 范围仍不完整。

完成后，当前控制流 family 全部 lower 为类型化 graph node。模板唯一解析，循环有有限进展，
随机分支使用 RNG ledger，projectile 只表达命中/目标迭代和结算顺序。动画时间线与视觉等待
process-only，不模拟物理飞行。

## 详细目标

1. 闭合本地/全局 template 引用、child/parent 身份、触发 ability 和 parallel task list。
2. 支持固定循环、条件循环、目标列表循环和 interval 的模拟顺序；必须证明有限进展或明确上限来源。
3. 将 projectile/wave/multi-projectile 投影为目标迭代、hit identity 和 ordering，不建立坐标/速度物理。
4. RandomConfig 和随机分支先列完整候选，消费统一 choice identity，并可 replay。
5. 只保留会改变 gameplay ordering/window 的 barrier；动画、音频、camera wait 归 process-only。
6. child 任一 blocked 时按来源定义原子回滚或停止，不能提交前半图后忽略后半图。

## 本阶段不做

- 不执行各领域 effect 的具体数值；复用 S4-S7 和现有 EffectRegistry。
- 不实现 timeline 演出、帧同步、物理弹道或客户端 parallel 表现。
- 不在验证器手工展开 task plan。
- 不以默认最大循环次数掩盖缺失 count/termination 来源。

## 架构与负例

- template 缺失、多候选、递归环、child parent 错配、非正循环数和无进展循环全部 blocked。
- 随机候选集为空/变化、choice 过期和 replay 篡改必须拒绝。
- presentation wait 包含 gameplay-looking child 时仍继承完整分支范围。
- parallel 结果顺序和 mutation identity 确定，不依赖 Python dict/file order。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| family 闭合 | 当前 M06 family lowering/admission 零 gap | control-flow matrix |
| 模板唯一 | local/global 引用和递归检查正确 | template graph |
| 循环终止 | 每个循环有来源上限或可证明进展 | termination matrix |
| 命中顺序正确 | target/hit/settlement identity 稳定 | formal action sample |
| 随机可回放 | 候选、选择、分支和 replay 一致 | RNG branch matrix |
| 表现退役 | presentation waits 零 gameplay 副作用 | scope negatives |

## 结构化通过谓词

```text
current_control_flow_families_all_typed=true
template_resolution_unique_and_acyclic=true
loop_termination_source_backed=true
projectile_lowered_as_hit_sequence_not_physics=true
parallel_execution_order_deterministic=true
random_branch_uses_common_rng_ledger=true
presentation_waits_process_only=true
blocked_child_prevents_partial_commit=true
sampled_action_settlement_replay_equal=true
manual_validation_task_expansion=false
```

## Gap 与停止条件

- 当前来源存在无法证明终止的 gameplay loop：保持 blocked 并暂停阶段，不设任意 cap。
- 模板引用缺失：source gap；不得复制相邻模板内容。
- projectile 需要真实战斗距离公式且来源存在：退回 S5B relation 扩展；纯视觉距离不实现。
- effect 领域缺口记录给 S10-S17，S8 只证明 graph 能正确到达并原子阻断。

## 拟改范围

- `systems/ability.py`、`systems/ability_task_contract.py`、`systems/trigger.py`。
- `tbgd/lowering.py`、`rules/ir.py` 的 graph/template/loop/hit-sequence IR。
- `systems/rng.py` 通用分支选择；不创建角色 RNG。
- 主验证 `tools/validate_p9_s8_control_flow_sequence_closure.py` 和报告。

## 验证与资源

- 按 M06 family 窄投影一次；每个结构形状一个最小真实 case，不按角色重复。
- 正式 ability/action 入口产生 graph、mutation、settlement 和 replay；不手工调 child executor。
- direct 最多 2 项：ability task atomicity、RNG replay，仅实际触达时运行。
- 预算：8 分钟、1 GiB、5 MiB、900 行；不跑完整角色目录或旧 task/event 聚合。

## 唯一执行清单

- [ ] 当前模板、循环、触发、并行和命中序列 family 全部类型化。
- [ ] 引用唯一、图无非法环、循环有限且来源真实。
- [ ] projectile 只表达 gameplay 命中顺序，表现时序退役。
- [ ] 随机分支统一 RNG ledger 并可 replay。
- [ ] blocked child 不产生部分提交或半图 settlement。
- [ ] 主验证、必要 direct 和资源审计通过并提交 `ready_for_review`。
