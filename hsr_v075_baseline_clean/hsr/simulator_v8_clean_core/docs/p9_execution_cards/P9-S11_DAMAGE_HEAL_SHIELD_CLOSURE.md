# P9-S11 伤害、治疗、护盾与结算事件闭合执行卡

## 执行配置

- 对应问题：P9-I11、P9-I09 结算部分；机制包 M09、M07。
- 硬前置：P9-S10 已验收并形成检查点，S9 event partition 当前。
- 推荐：5.6 Sol / `max` / Goal 模式。
- 理由：结算跨公式、目标、状态修正、窗口、原子提交和 replay，是角色正确性的核心高风险路径。

## 当前事实与阶段结果

当前 M09 有 9 个顶层来源族、987 次出现，覆盖全部79条角色，但 `AttackData`、伤害标签、
修正项和事件窗口包含多种结构。P7/P8 已证明普通和装备结算底座，P9 只补角色真实来源形状。

完成后，当前角色的普通/附加/持续/真实/分摊伤害、治疗和护盾来源均通过统一 plan ->
atomic transition -> settlement 执行；S11-owned before/hit/after、heal、shield 等事件由同一结算
原生产生。削韧 emission 继续交 S15，但与伤害 hit identity 一一对应。

## 详细目标

1. 闭合 DamageByAttackProperty、ModifyDamageData、HitDamageSplit、HealHP、ModifyHealData、Init/Stack/RemoveShield 等来源形状。
2. 使用 typed scaling basis、数值表达式、target 和 status modifiers；不得从观测最终值反推公式。
3. 保留 damage kind/tag/custom name/source action/hit/target 和窗口身份。
4. 计划创建后校验 before-state、目标、来源、公式、事件和防护状态；stale plan 拒绝。
5. 正式结算产生 S11-owned 事件，callback 能影响同一合法窗口但不能重复提交。
6. damage/toughness emission 共享 hit profile 身份；S15 负责 toughness 数值和 break 结果。
7. settlement、source audit、snapshot/replay 保留逐次结算，不从日志事后重建。

## 本阶段不做

- 不重新设计 P7 damage pipeline 或 P8 装备效果。
- 不实现削韧/击破结算；留 S15。
- 不用角色专属公式、技能文本或固定伤害答案。
- 不把动画命中、damage text 或视觉 projectile 当结算来源。

## 架构与负例

- 缺 scaling basis、非有限数值、非法 target、伪 hit identity、stale plan 和重复 settlement 均 blocked。
- 同一事件身份不同伤害内容、source/target 交换和标签篡改 fail-closed。
- 伤害为零是合法结果时必须与 blocked 区分。
- callback 失败导致所属原子窗口回滚，不能保留半次 damage/heal/shield。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 结算 family 闭合 | 当前 M09 family/shape 零内部 gap | settlement matrix |
| 事件原生 | S11-owned 事件由 plan/commit 产生 | event trace |
| 顺序正确 | pre-modify -> plan -> commit -> post-event 连续 | window ledger |
| 失败原子 | stale/伪造/冲突零副作用 | negative matrix |
| replay/source | 逐次结算可追溯并重放一致 | audit samples |

## 结构化通过谓词

```text
s9_event_partition_current=true
current_damage_heal_shield_family_gap_count=0
s11_settlement_event_family_gap_count=0
damage_heal_shield_use_common_pipeline=true
damage_and_toughness_hit_identities_aligned=true
zero_result_and_blocked_distinct=true
stale_or_forged_settlement_plan_rejected=true
failed_window_has_no_partial_commit=true
sampled_settlements_source_audited=true
sampled_transitions_replay_equal=true
character_specific_settlement_handlers=0
```

## Gap 与停止条件

- 来源公式缺字段或多义：返回 S3/S4，不用样例答案补齐。
- 现有 pipeline 无法表达真实共享修正顺序：提出通用阶段模型，不能在角色 handler 绕过。
- 只缺 S15 toughness consumer：记录 producer obligation，不阻断伤害 identity，但阻断最终 S20。
- event partition 与真实窗口冲突：回 S9 修订，不复制第二事件。

## 拟改范围

- `systems/damage.py`、`damage_formula.py`、`damage_pipeline.py`、`dot_formula.py`。
- `systems/shield.py`、通用 heal/effect 路由、atomic transition。
- `rules/ir.py`、角色 AttackData/damage emission lowering。
- 主验证 `tools/validate_p9_s11_damage_heal_shield_closure.py` 和报告。

## 验证与资源

- 在来源层按结算 shape 选样，一次窄 IR；不为每个角色重复同构公式。
- 正式 action/ability 产生 plan、mutation、events、settlement、replay。
- direct 最多 2 项：damage atomic pipeline、shield/heal contract，实际触达才运行。
- 预算：10 分钟、1 GiB、8 MiB、1,000 行；不跑 P7/P8 结算聚合。

## 唯一执行清单

- [ ] 当前伤害、治疗、护盾来源形状零内部 gap。
- [ ] 结算计划、修正顺序和 hit identity 来源真实。
- [ ] S11-owned 事件由正式结算链原生产生。
- [ ] stale/伪造/冲突/回调失败原子 blocked。
- [ ] settlement、audit、snapshot/replay 闭合且无角色公式。
- [ ] 主验证、必要 direct 和资源审计通过并提交 `ready_for_review`。
