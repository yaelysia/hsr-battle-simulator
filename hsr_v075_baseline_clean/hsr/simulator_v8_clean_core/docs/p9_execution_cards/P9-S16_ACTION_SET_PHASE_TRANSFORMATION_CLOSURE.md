# P9-S16 动作集、形态与阶段切换闭合执行卡

## 执行配置

- 对应问题：P9-I16；机制包 M14。
- 硬前置：P9-S15 已验收并形成检查点。
- 推荐：5.6 Sol / `max` / Goal 模式。
- 理由：形态切换会改变动作查询、资源、状态和生命周期，若用角色特判实现会永久污染 UnitState 与 executor。

## 当前事实与阶段结果

当前 M14 有 2 个顶层来源族、38 次出现，涉及8条角色；动作阶段绑定和技能映射还分布在
S1/S2/S12。现有 phase machine、action definition、availability 和 provider 可复用。

完成后，强化形态、阶段和动作集切换通过类型化 transformation plan 改变 active action set、
必要资源/状态引用和可用动作视图。角色数据卡预先持有所有来源动作定义；UnitState 不变成
每个角色一套 schema，推演器在切换后查询新的合法动作。

## 详细目标

1. 闭合 CharacterChangePhase、ChangeCharacterConfigParam 及 S1 转交的 action-set/phase 来源关系。
2. 定义 base/enhanced/temporary/ultimate-window action set 的身份、进入/退出条件和优先级。
3. transformation plan 在提交前校验来源 graph、当前 phase、资源/状态、owner 和旧 action set fingerprint。
4. 切换原子更新 action availability、技能映射、目标契约和相关 provider；旧动作提交必须失效。
5. 临时形态结束、死亡/复活、波次和状态移除时按来源恢复或保留，不用默认 reset。
6. 多阶段动作内部 phase 与角色长期形态严格区分。

## 本阶段不做

- 不实现模型/动画替换、HUD 技能按钮和 cut-in。
- 不创建角色专属 UnitState subclass 或 phase handler。
- 不把独立行动实体、召唤或记忆子卡当作角色形态；S17/未来计划负责。
- 不通过技能名猜 action-set membership。

## 架构与负例

- 错 phase、重复进入、过期 plan、未知 action ref、跨角色 action 和伪 config identity 必须 blocked。
- 旧 action 在形态切换后提交不能执行。
- 形态切换任一关联更新失败时 state/resource/action view 全部回滚。
- presentation model change 不得触发 action-set transformation。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| M14 来源闭合 | 当前 phase/action-set shape 零 gap | transformation matrix |
| 动作视图正确 | 切换前后 query 只返回合法动作 | availability trace |
| 原子/过期 | stale action/plan 和部分更新被拒绝 | negatives |
| 生命周期正确 | enter/exit/death/wave 恢复按来源 | lifecycle matrix |
| 无专属 schema | 数据卡 action refs 驱动通用 plan | code audit |

## 结构化通过谓词

```text
current_action_set_phase_family_gap_count=0
action_set_membership_source_backed=true
long_lived_form_and_action_phase_distinct=true
transformation_plan_atomic=true
stale_pre_transformation_action_rejected=true
action_availability_updates_after_commit=true
form_exit_and_lifecycle_rules_source_backed=true
presentation_model_change_not_gameplay_form=true
character_specific_unit_state_variants=0
sampled_transformation_replay_equal=true
```

## Gap 与停止条件

- S1 action source 仍缺失/多义：回 S1/S3，不在 S16复制相似动作。
- 来源切换需要新通用 action-set concept：可在本阶段设计，但必须先检查 executor/availability 影响。
- 规则实际属于 independent entity：交 S17，不将子实体摊平为角色形态。
- 需要 UI 状态才能决定形态：阶段阻断；规则必须来自 core state/choice。

## 拟改范围

- `systems/phase_machine.py`、`action_availability.py`、`action_contract.py`、`ability_provider.py`。
- `rules/ir.py`、角色 action-set/transformation lowering。
- `scenarios/build_state.py` 只消费已装配初始 action set，不理解角色规则。
- 主验证 `tools/validate_p9_s16_action_set_phase_transformation_closure.py` 和报告。

## 验证与资源

- 按 M14/source action-set shape 窄选样；不固定某角色为通用通过条件。
- 正式 action query -> transformation command/effect -> new query -> stale action negative -> replay。
- direct 最多 2 项：action availability、phase atomicity，仅实际触达时运行。
- 预算：10 分钟、1 GiB、8 MiB、1,000 行；不跑 UI、全角色或召唤聚合。

## 唯一执行清单

- [ ] 当前 action-set/phase/transformation 来源零内部 gap。
- [ ] 长期形态与动作内部阶段严格区分。
- [ ] 切换原子更新 action view，旧动作/计划失效。
- [ ] 进入、退出、死亡和波次生命周期来源真实。
- [ ] 无角色专属 UnitState/handler 或 UI 规则输入。
- [ ] 主验证、必要 direct 和资源审计通过并提交 `ready_for_review`。
