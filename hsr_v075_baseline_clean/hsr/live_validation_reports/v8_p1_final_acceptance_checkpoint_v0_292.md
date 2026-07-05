# v8 P1 final acceptance checkpoint v0.292

日期：2026-07-05

## 结论

P1 最终收口完成。当前 P1-9 聚合结果：

```text
ok=True
p1_9_done_eligible=True
phase1_repair_substrate_accepted=True
phase1_minimum_battle_slice=True
phase1_minimum_battle_slice_blocked_by=[]
```

这表示第一阶段最小完整战斗纵切已通过，可以进入 P2。该结论不等于完整复刻；它只表示 P1 范围内有真实来源的关键机制已 executable，无来源或边界项已诚实分类且不产生假 mutation。

## 本次最终修复

### Counter queue

P1-FINAL 的唯一机制 blocker 是反击队列语义。现在 P1-5 已新增正式 counter route case：

- 按结构化谓词选样，不按固定角色名、怪物名、技能名、文件名或 hash。
- 选择条件包括 `OnAfterBeingAttacked` / 受击相关 callback、`TurnInsertAbility`、攻击者目标 alias、可执行 queue intent/window/resolution、可执行 standalone ability graph。
- 反击仍由通用 `insert_ability` queue family 承载，但 P1-5 记录 `semantic_family=counter` 和 `semantic_e2e_executable_count=1`，不会把普通 insert ability 冒充为反击。
- 端到端链路覆盖 setup listener、受击事件 dispatch、queue enqueue、mandatory queue drain、反击伤害/效果、settlement、replay、source audit。
- 负例覆盖无 listener、非敌对 attacker、actor 控制/破韧、已使用、attacker missing、来源 blocked 等不入列或不产生假 queue mutation。

P1-9 source-gap matrix 中：

- `p1_5.counter`: `source_state=executable`
- `p1_5.follow_up`: `source_absent_not_required`
- `p1_5.assistant`: `boundary_only`

### Servant / 忆灵

v0.290 已完成 servant/忆灵 P1 纵切：

- `AvatarServantConfig` / `AvatarServantSkillConfig` lowering 到 `ServantDefinitionIR`。
- runtime 支持 servant spawn/remove、action availability、target registry 和 initial setup。
- P1-6 servant target、P1-8 servant initial setup、P1-9 servant 聚合均有真实来源正例。
- flag-only servant 和缺 ref/缺 source 负例不产生假执行。

## 非 blocker 边界

以下仍未完整，但不阻塞 P1 minimum：

- assistant：`boundary_only`。
- battle_unit_summon / `SummonUnitData`：catalog/definition，不是自动 battle spawn trigger，当前 `boundary_only`。
- random dispel：当前数据库/IR 无第一阶段真实结构化来源，`source_absent_not_required`。
- stack + duration refresh 组合：当前无组合来源正例，不合成 synthetic case。
- follow-up：当前未发现第一阶段可执行来源，不阻塞 P1。

## 验证

在 `hsr_v075_baseline_clean/hsr` 下运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_5_queue_window_system --output-dir /tmp/hsr_v8_p1_5_counter_final
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_counter_final
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_after_counter_final
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_after_counter_final
```

关键输出：

```text
v8 p1_5_queue_window_system validation ok=True
v8 p1_9_phase1_aggregate validation ok=True phase1_repair_substrate_accepted=True phase1_minimum_battle_slice=True
v8 p1_0_action_boundary validation ok=True
v8 p1_4_status_system validation ok=True
```

P1-9 summary 抽查：

```text
ok=True
p1_9_done_eligible=True
phase1_repair_substrate_accepted=True
phase1_minimum_battle_slice=True
phase1_minimum_battle_slice_blocked_by=[]
```

## 下一阶段

下一步进入 P2。继续扩展状态、角色/怪物、装备、关卡、assistant、battle_unit_summon、servant 完整行为时，仍必须遵守：

- runtime 只读 Canonical IR / 数据卡 IR。
- 有真实来源才 executable。
- 无来源或缺 admission 时 blocked/process-only/state unchanged。
- 验证按结构化谓词选样，不能按固定角色/怪物/技能/文件/hash 作为主路径。
