# P9-S5D2 弹射目标机制组件验收

状态：`mechanism_accepted_external_e2e_dependency`

日期：2026-08-06

## 验收结论

弹射目标机制与 S5 来源聚合已通过验收，但 P9-S5D2 阶段尚未完成。真实动作的完整能力图仍
依赖 P9-S8，故动作 transaction、settlement 和 replay 的端到端项保留未证明状态。

## 已证明范围

- 当前可执行弹射策略均闭合到唯一角色卡、动作等级、主命中与连续弹射命中描述。
- 真实 `RandomSelectInTargetList` 来源按原始任务顺序绑定，每次命中复用 S5D1 随机计划。
- 候选池排除 defeated、removed、off-field、来源不可选和运行时不可选单位；初始目标身份和
  敌我关系在生产边界拒绝非法输入。
- 不同弹射段具有独立调用身份，允许重复命中；全部敌人失效时结束序列，不会重定向到尸体。
- 候选变化后旧事件不能重放，事件来源、命中序号或结果篡改均被拒绝。
- 唯一客户端编队排序节点保留真实来源与表现键，在战斗层作为不改变候选的表现顺序操作处理。
- S5 目标与动作目标完整分母均唯一归属，S5 自身 gap 为零；后续 gameplay gap 均有精确 owner。
- runtime 没有角色、技能或固定 ID 特判，也没有第二套随机账本。

## 未证明范围

动态选取的真实弹射动作 `avatar_skill:1100402` 已通过目标 query、提交、影响范围和公式投影，
但完整执行被真实 `IncludeTaskListTemplate` 与 `TriggerEffect` 任务阻断。失败保持原状态且没有
业务 mutation 或 RNG。P9-S8 完成后必须返回本卡，使用届时已准入的真实动作证明：

1. 所有弹射选择在首次可见 mutation 前完成。
2. 多段伤害、目标 RNG、settlement 和来源审计在同一原子 transaction 中提交。
3. replay 从连续快照重算候选、命中顺序和 mutation，并拒绝删改或交换事件。

在上述三项通过前，总计划中的 P9-S5D2 保持未勾选。

## 验证证据

权威入口：

```text
python3 -B -m simulator_v8_clean_core.tools.validate_p9_s5d2_bounce_dynamic_target_and_aggregate \
  --output-dir /tmp/p9_s5d2_accepted_20260806
```

结果：

- 39/39 谓词通过。
- 墙钟 27.41 秒。
- 峰值 RSS 546,108 KiB。
- evidence 145,433 bytes。
- 完整 Canonical IR 构建 0 次；目标来源、动作目标目录和真实动作切片各构建 1 次。
- 验证器 560 个非空行，低于 620 行预算。
- `compileall` 与 `git diff --check` 通过。

验证对象按阶段构建并及时释放后，峰值从约 650 MiB 降至约 533 MiB，避免完整角色卡目录、
目标目录和动作切片同时常驻。

## 流程复盘

本轮在最终验收前捕获了四类问题：lowering 准入与 IR 构造不同步、运行时不可选单位仍进入
弹射池、陈旧事件负例验证错层，以及 `all([])` 形成的空集假证据。对应规则已更新到
`AGENT_WORKFLOW_AND_VALIDATION.md` 与工作区 `AGENTS.md`。这些问题均在内部验收闭合，没有把
局部绿灯误报为阶段完成。
