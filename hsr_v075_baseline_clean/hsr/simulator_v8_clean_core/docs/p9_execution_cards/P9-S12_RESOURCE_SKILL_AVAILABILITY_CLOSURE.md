# P9-S12 资源、技能成本与可用性闭合执行卡

## 执行配置

- 对应问题：P9-I12、P9-I09 资源部分；机制包 M10、M07。
- 硬前置：P9-S11 已验收并形成检查点，S9 event partition 当前。
- 推荐：5.6 Sol / `xhigh` / 普通聚焦。
- 理由：来源族数量有限，但必须统一战技点、能量、特殊资源、技能成本和动作查询，防止 UI/推演器复制规则。

## 当前事实与阶段结果

当前 M10 有 13 个来源族、411 次出现，涉及72条角色。已有 `ResourceSystem`、action
availability 和技能 continuation 可复用；旧来源还混有 UI 能量条、特殊资源命名和技能映射。

完成后，所有角色资源由类型化 resource definition/ledger 表达；花费、恢复、上限变化、团队
资源、特殊资源和技能禁用/映射通过原子事务执行。动作查询只读取内核结果，推演器不能提交
“资源足够”或最终可用性答案。

## 详细目标

1. 区分角色能量、团队战技点、团队/实体 boost point 和角色特殊资源，不能共享错误命名空间。
2. 闭合 ModifySP/ModifySPNew/ModifySpecialSP/team/entity boost、上限和来源标签。
3. 闭合技能成本、技能属性变化、技能类型禁用和控制映射，并更新 action availability。
4. S0 的能量条/特殊条只提供定义投影，不执行 UI state task。
5. 资源 mutation 与 S12-owned change/spend/gain 事件同一提交；不足、越界和 stale cost plan 原子失败。
6. 新角色命名资源用通用 definition 和来源键表达，不在 core 出现角色名称。

## 本阶段不做

- 不模拟 UI 条、按钮、提示和自动技能选择。
- 不实现敌方 AI 的资源策略。
- 不把 P8 装备或行迹静态资源贡献重复计入 runtime。
- 不为特定角色建立专属 resource field。

## 架构与负例

- 资源 kind/owner/team 错配、负花费、越界、非有限值、重复事件和 stale plan 必须拒绝。
- BP、能量和特殊资源不能因名称/字段相似互相读取。
- 技能禁用、成本不足和目标非法分别返回结构化 action unavailability reason。
- UI 提交 final resource 或 availability 结果不能绕过内核。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 资源 family 闭合 | 当前 M10 来源零内部 gap | resource matrix |
| 命名空间正确 | unit/team/kind 不混淆 | identity matrix |
| 成本原子 | 查询、预占、提交和事件一致 | cost trace |
| 动作查询权威 | availability 由内核资源/状态产生 | query matrix |
| 来源/replay | resource mutation 可追溯重放 | audit samples |

## 结构化通过谓词

```text
s9_event_partition_current=true
current_resource_skill_family_gap_count=0
s12_resource_event_family_gap_count=0
energy_bp_special_resources_distinct=true
resource_mutation_and_event_atomic=true
skill_cost_and_availability_core_authoritative=true
skill_disable_and_mapping_source_backed=true
stale_or_invalid_cost_plan_rejected=true
ui_submitted_rule_result_rejected=true
sampled_resource_replay_equal=true
character_specific_resource_fields=0
```

## Gap 与停止条件

- 新资源需要当前模型不存在的通用维度：扩展 typed definition，经架构审查后实施，不加角色字段。
- 资源 UI 节点没有独立战斗来源：只保留 S0 projection，不执行 task。
- 成本/可用性依赖 S13 queue 或 S16 action set：建立引用，端到端 obligation 转交对应阶段。
- 旧 P8/P7 资源脚本含过时 MaxSP/BP 假设：不修改生产迎合。

## 拟改范围

- `systems/resource.py`、`action_availability.py`、`action_contract.py`。
- `systems/skill_continuation.py` / ability provider 仅实际需要时修改。
- `rules/ir.py`、资源/技能 lowering、构筑资源引用。
- 主验证 `tools/validate_p9_s12_resource_skill_availability_closure.py` 和报告。

## 验证与资源

- 按 M10 和 S12-owned events 窄投影，一次最小 RuleBook；不加载完整角色目录。
- 通过正式 action query/submit 和 resource transaction 证明，不手改 state 后调用 checker。
- direct 最多 2 项：resource atomicity、action availability，仅实际触达时运行。
- 预算：10 分钟、1 GiB、8 MiB、1,000 行；不跑 UI/P8/full 聚合。

## 唯一执行清单

- [ ] 当前资源、成本、技能属性和禁用/映射来源零内部 gap。
- [ ] 能量、BP、团队和特殊资源身份/上限严格分离。
- [ ] 资源事务、事件和动作可用性由内核原子决定。
- [ ] 非法/stale/越界/UI 伪结果负例 fail-closed。
- [ ] 无角色专属资源字段，audit/replay 完整。
- [ ] 主验证、必要 direct 和资源审计通过并提交 `ready_for_review`。
