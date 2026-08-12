# P9-S8B3 动作与 standalone ability 迁移执行卡

## 执行配置

- 对应问题：P9-I08；原 P9-S8B 的 ability 消费域迁移。
- 硬前置：P9-S8B2 已验收并提交检查点。
- 推荐：5.6 Sol / `high` / 普通聚焦。
- 本卡只迁移 `AbilityTaskSystem` 及其 queue standalone 调用链，不迁移状态 callback。
- 开工只读：本卡、S8B1/S8B2 公共 API、`AbilityTaskSystem.execute_callback`、
  `AbilityTaskSystem.execute_standalone`、scheduler 和 core executor 的正式 ability 调用点。
  最多两轮 CodeGraph 定位。

## 闭合地图

| 项目 | 本卡权威 |
|---|---|
| 正式入口 | 普通 action callback 与 scheduler 已准入的 standalone ability |
| 图来源 | S8B1 按 phase/callback/owner 物化并由 RuleBook 唯一返回的任务图 |
| 控制执行 | 仅 S8B2 通用执行器 |
| 领域 leaf | 现有 ability effect、damage、summon、condition、target 和 numeric 能力适配器 |
| 结果 | `AbilityTaskExecutionResult` 运输共享事务结果和 graph-qualified 节点投影 |
| 后续归属 | status callback 归 S8B4；跨 event active stack 最终运输归 S8B5 |

## 阶段目标

1. `AbilityTaskSystem.execute_callback` 通过 RuleBook 取得正式任务图并调用 S8B2；不得再按
   `parent_task_id` 搜 root 或在 `_execute_task` 中解释 Predicate、循环、template、TriggerAbility。
2. ability 领域适配器只负责一个 leaf 的准入和结果，不持有 child runner，不递归调用旧 task 树。
3. `execute_standalone` 与 scheduler 复用同一图入口。queue 只提供已准入 ability、actor、target 和
   queue 身份，不创建临时 action 规则来绕过图准入。
4. standalone root 在进入时写入 active graph stack；A 直接调用 A、A 调 B 再回 A 均 fail-closed。
   跨事件同步回调中的 stack 运输若尚需修改 event/status 域，精确交给 S8B5，不在本卡扩域。
5. 删除或退役 ability 域旧 Predicate、固定循环、template 和 TriggerAbility 控制解释路径；
   leaf 专用执行代码可以保留，但必须只由共享执行器适配器调用。
6. 任一图、leaf 或下游领域 blocker 使整个 callback 事务遵守 S8B2 原子失败，不能保留前半段动作结果。
7. `_ability_task_damage_graph_authoritative` 等只读旧拓扑的派生消费者统一由 S8B6 在移除旧字段
   时迁移；本卡不得新增对旧字段的依赖。

## 本卡明确不做

- 不修改 `StatusCallbackSystem`、`systems/status.py` 的 callback task 拓扑或 status event 语义。
- 不实现 projectile、RandomConfig、parallel、barrier 或新 RNG 规则。
- 不改角色卡、构筑、动作选择、UI 或推演器接口。
- 不用固定角色/技能/ability 名称写生产分支或主验证选样。

## 允许修改的生产范围

- `systems/ability.py`
- `systems/scheduler.py`
- `core/executor.py` 仅限正式 ability 调用签名和结果运输
- 必要时最小修改 `systems/ability_task_contract.py` 和 `tbgd/lowering.py` 的正式 slice 参数运输。

若需要修改 status/event 生产域，或两个以上未列出的生产文件，返回 `plan_mismatch`。不得把
S8B5 的跨入口问题塞进本卡。

## 验收谓词

```text
ability_control_flow_uses_shared_executor_only=true
standalone_ability_uses_same_graph_authority=true
ability_domain_has_no_second_control_interpreter=true
queue_cannot_bypass_graph_admission=true
standalone_root_is_present_in_active_graph_stack=true
ability_selected_path_failure_is_atomic=true
status_callback_behavior_changed=false
full_canonical_ir_build_count=0
```

## 验证与止损

- 一个主入口：`validate_p9_s8b3_ability_standalone_migration.py`。
- 从当前来源动态选择一个包含已准入确定性控制结构的普通 action slice，以及一个 standalone
  slice；若真实 leaf 因后续领域阶段 blocked，可用最小 domain fixture 证明运输，但必须分栏报告。
- 独立检查 ability 正式调用图和旧控制解释器残留；字符串/AST 只能证明旧生产者不存在，不能
  代替行为正例。
- 不跑 S8B1/S8B2 主入口；只运行其稳定小型 active-contract slice（若已明确保留）。
- 预算：90 秒、640 MiB、512 KiB evidence、验证器目标不超过 300 非空行。
- 45 分钟内必须使普通 callback 的一个 root 经共享执行器形成可编译纵切；否则停止并报告缺少的
  精确 API 或调用者，不得继续全项目探索。

## 唯一执行清单

- [ ] 普通 action callback 已迁移到共享图执行器。
- [ ] standalone/scheduler 已复用同一准入和图执行链。
- [ ] ability 域第二套控制解释器已移除，leaf 职责保持单一。
- [ ] 共享执行结果运输与失败原子性经正式入口证明。
- [ ] 唯一主验证和资源门通过，提交 `ready_for_review`。
