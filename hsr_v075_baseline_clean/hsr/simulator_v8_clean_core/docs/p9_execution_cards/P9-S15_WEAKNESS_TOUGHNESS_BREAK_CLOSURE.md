# P9-S15 弱点、韧性、击破与超击破闭合执行卡

## 执行配置

- 对应问题：P9-I15、P9-I09 击破部分；机制包 M13、M07。
- 硬前置：P9-S14 已验收并形成检查点，S11 hit identity 与 S9 event partition 当前。
- 推荐：5.6 Sol / `max` / Goal 模式。
- 理由：弱点、削韧、击破、延迟和超击破跨伤害、状态、行动轴与事件窗口，结算顺序高度敏感。

## 当前事实与阶段结果

当前 M13 有 7 个顶层来源族、80 次出现，涉及22条角色。现有 toughness、break、super-break
系统和 damage/toughness emission identity 可复用；角色来源仍有弱点植入、攻击属性替代、
韧性修改、红韧性、无视弱点削韧和击破窗口形状。

完成后，当前角色弱点与韧性来源均进入通用 hit/toughness plan。削韧、击破状态、击破伤害、
行动延后和超击破按真实顺序执行，S15-owned 事件由同一 hit/lifecycle 原生产生，并与 S11
damage identity 对账。

## 详细目标

1. 闭合 AddWeakness/AddWeakByTeamAttackType、attack-type regard/clear、SetResilience、StackWeakness/RedStance 等来源。
2. 弱点集合、攻击属性替代、无视弱点和削韧倍率均为 typed data，不按角色名判断。
3. 每个 damage hit 对应唯一 toughness emission；无削韧来源时不能凭伤害自动生成。
4. toughness 归零、break 触发、恢复/延迟和 super-break 条件使用 S4-S7 统一表达。
5. 生产 weakness/toughness/break 等 S15-owned 事件；同一 break identity 不重复。
6. 控制抵抗、效果抵抗和韧性状态若来源语义不同保持独立，不因字段相似合并。

## 本阶段不做

- 不实现弱点 UI、韧性条动画或击破提示。
- 不从攻略/观测伤害反推击破公式。
- 不为波提欧、阮梅等角色建立专属 break pipeline。
- 不重算 S11 已验收普通伤害；只消费共享 hit identity。

## 架构与负例

- weakness kind、target、duration/source 错配，重复 break、伪 hit identity 和 stale toughness plan 均 blocked。
- 伤害提交失败时没有 toughness/break event；toughness 失败不能保留半个 damage window 的附属结果。
- 无弱点削韧只能在明确来源允许时发生。
- presentation stance hint 不得改变 weakness/toughness 状态。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| M13 family 闭合 | 当前来源零内部 gap | weakness/toughness matrix |
| hit 对账 | damage/toughness emission 一一对应 | hit identity ledger |
| 顺序正确 | hit -> toughness -> break -> delay/status 连续 | break trace |
| 事件真实 | S15-owned 事件由正式结算产生 | event matrix |
| replay/source | break 结算可追溯重放 | audit samples |

## 结构化通过谓词

```text
s9_event_partition_current=true
current_weakness_toughness_family_gap_count=0
s15_break_event_family_gap_count=0
damage_toughness_hit_identity_bijection=true
weakness_and_attack_type_rules_source_backed=true
break_and_super_break_order_correct=true
control_effect_resistance_not_conflated=true
duplicate_or_stale_break_rejected=true
presentation_stance_nodes_gameplay_effect_count=0
sampled_break_replay_equal=true
character_specific_break_handlers=0
```

## Gap 与停止条件

- 当前公式字段未 lower：回 S4/S11，不用固定答案补。
- hit identity 不完整：回 S11 修复共享 emission，不在 toughness 中猜 source。
- 新弱点/韧性状态需要通用模型扩展：最小修改并运行实际触达 direct。
- event partition 与 break 顺序冲突：回 S9，不生成平行事件。

## 拟改范围

- `systems/toughness.py`、`break_system.py`、`super_break.py`。
- `systems/damage_pipeline.py` 只处理 hit/toughness identity 对接。
- `systems/timeline.py` 只处理来源明确的 break delay。
- weakness/toughness/break lowering、主验证 `tools/validate_p9_s15_weakness_toughness_break_closure.py`。

## 验证与资源

- 按 M13 与 S15-owned events 窄投影；通过正式 damage action 产生 hit/toughness/break 链。
- 覆盖弱点命中、无弱点但来源允许、未击破、击破和 super-break 的结构差异，不按角色枚举。
- direct 最多 2 项：toughness atomicity、break replay，仅触达时运行。
- 预算：10 分钟、1 GiB、8 MiB、1,000 行；不跑完整 damage 或角色目录聚合。

## 唯一执行清单

- [ ] 当前弱点、韧性、攻击属性替代和红韧性来源零内部 gap。
- [ ] damage/toughness hit identity 一一对账。
- [ ] 击破、延迟、状态和超击破顺序来源真实。
- [ ] S15-owned 事件正式生产、去重和原子失败正确。
- [ ] 无角色专属 break 逻辑，audit/replay 完整。
- [ ] 主验证、必要 direct 和资源审计通过并提交 `ready_for_review`。
