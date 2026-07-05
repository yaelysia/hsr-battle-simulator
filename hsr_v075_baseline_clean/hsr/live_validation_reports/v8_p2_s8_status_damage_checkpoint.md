# v8 P2-S8 状态伤害检查点

日期：2026-07-05

## 本步完成

- 新增 `validate_p2_s8_status_damage`。
- `DamageSystem.apply_packet` 在没有 `DamageWindowLedger` 的状态 lifecycle tick 路径中，也会统一检查目标生命周期。
- 已阵亡、移除或缺失目标的状态伤害变为 `damage_source_skipped` process-only settlement，不再产生 HP mutation。
- 验证普通 DoT lifecycle tick、break DoT、状态触发 true damage、多段状态伤害。
- 验证状态缺失、DoT 公式绑定缺失、目标已阵亡负例均 blocked / process-only / state unchanged。

## 状态伤害矩阵

```text
ordinary_dot executable source_count=81
break_dot executable source_count=3
status_true_damage executable source_count=1
multi_status_damage executable source_count=11
blocked_status_damage boundary_only source_count=403
status_hp_loss_effects admission_gap_blocked source_count=146
```

`status_hp_loss_effects` 当前有真实 callback task 来源，但 task admission 仍 blocked；本步不合成可执行生命损失正例，留给 S10 callback opcode/admission 覆盖。

## 关键正例

```text
ordinary DoT: MMonster_W2_Beast01_04_SkillP02_GoldBlood_DOT
break DoT: MCommon_Element_Burn
true damage: MAvatar_Advanced_Seele_Rank06_Flag
multi DoT: MMonster_W4_Manta_00_Virus_Avatar executed_damage_count=4
```

关键断言：

```text
source_audit=True
replay=True
settlement_traceability=True
duration_tick_after_damage=True
dead_target_skip_record=True
missing_status_no_mutation=True
missing_dot_formula_no_mutation=True
```

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_s8_status_damage --output-dir /tmp/hsr_v8_p2_s8_status_damage
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

关键输出：

```text
v8 p2_s8_status_damage validation ok=True
```

## 剩余范围

- S8 完成当前 StatusDamageEmissionIR 可执行状态伤害与边界负例。
- callback task 下的 hp loss / healing / HP lock 等仍按 S10 callback opcode/admission 继续分层推进。
- S9 继续覆盖移除、驱散、净化、不可驱散。
