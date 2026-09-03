# v8 第一阶段总结

日期：2026-07-05

## 结论

第一阶段已经完成，可以进入 P2。

P1 的目标不是完整复刻《崩坏：星穹铁道》战斗，而是让 v8 clean core 具备“外部推演器驱动下的最小完整战斗纵切”。当前最终验收结果：

```text
ok=True
p1_9_done_eligible=True
phase1_repair_substrate_accepted=True
phase1_minimum_battle_slice=True
phase1_minimum_battle_slice_blocked_by=[]
```

这表示 P1 范围内有真实来源的关键机制已经能执行、结算、回放和审计；无当前来源或仅作为边界的机制已明确 blocked / process-only，不会产生假 mutation。

P1 验收相关检查点：

```text
1b88c70 v8 p1 final counter acceptance
8513659 docs: add P1 final repair plan
```

最终验收报告归档在：

```text
live_validation_reports/archive/phase1/v8_p1_final_acceptance_checkpoint_v0_292.md
```

## 已完成范围

P1 已经打通以下战斗底座：

- 外部推演器显式选择我方、敌方、召唤物行动；core 只判断合法性和执行规则，不做敌方 AI。
- `BattleTransition`、snapshot、mutation replay、settlement traceability、source audit 作为通用执行边界。
- 单位出生、死亡、退场、死亡目标过滤、死亡 actor 行动阻塞、队列项 actor 失效处理。
- 多波战斗最小推进：当前波清场、下一波生成、波次状态 mutation、跨波基础清理。
- 普通召唤物和 servant / 忆灵的第一阶段纵切：生成、目标注册、行动可用性、开局 setup、负例不假执行。
- 状态系统第一阶段底座：添加、叠层、刷新、持续时间、过期、DoT tick、概率成功/失败、效果抵抗、免疫、确定性驱散、控制阻塞行动。
- 队列和行动窗口底座：普通插入行动、插入能力、额外行动、终结技可选窗口、强制队列 drain、actor/target 生命周期保护。
- 反击端到端正例：受击触发、反击入队、普通行动等待队列结算、调度器执行反击、伤害/效果结算、回放和来源审计。
- 目标系统第一阶段关键子集：明确目标、群体目标、上下文目标列表、队形/韧性排序、owner fetch、servant target、确定性过滤和重定向。
- RNG 和分支基础：概率事件进入 transition，显式 choice ledger 可回放，缺 choice 或不合法 choice 不假执行。
- BattleSetup 最小入口：两波、有状态、有普通召唤物、有 servant、有 deterministic RNG 的验证场景。
- P1-9 聚合验证：一次聚合报告能展示 P1 各系统的 executable / boundary / source-absent 状态和最小纵切结论。

## 重要边界

这些内容仍未完整，但不阻塞 P1：

- assistant：当前是边界项，不冒充完整执行。
- battle unit summon / `SummonUnitData`：当前按定义或 catalog 边界处理，不等于战斗开局自动生成。
- random dispel：当前数据库/IR 中没有第一阶段真实结构化来源，不合成正例。
- 叠层同时刷新持续时间的组合正例：当前没有组合来源，不合成正例。
- follow-up：当前未发现第一阶段可执行来源，不阻塞 P1。

这些内容属于后续 P2+ 的主要工作：

- 完整状态系统扩面：更多叠层/刷新组合、控制抵抗、更多 tick 时点、更多驱散分支。
- 完整角色面板和全角色机制：晋阶、行迹、星魂、角色专属数据卡。
- 光锥、遗器、套装、环境、关卡机制。
- 全怪物技能、全怪物被动、阶段切换、复杂召唤、关卡倍率。
- assistant、battle unit summon、servant / 召唤物完整行为扩展。
- 更完整的目标系统：更多排序、fetch、随机、相邻、唯一实体、特殊玩法目标。

## 验收记录

最终验收时运行的最小验证集：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_5_queue_window_system --output-dir /tmp/hsr_v8_p1_5_counter_final_accept_review
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_counter_final_accept_review
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_after_counter_final_accept_review
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_after_counter_final_accept_review
git diff --check
```

验收结论：

```text
compileall 通过
validate_p1_5_queue_window_system ok=True
validate_p1_9_phase1_aggregate ok=True
phase1_minimum_battle_slice=True
phase1_minimum_battle_slice_blocked_by=[]
validate_p1_0_action_boundary ok=True
validate_p1_4_status_system ok=True
git diff --check 通过
```

没有默认运行 `validate_v0_204` / `validate_v0_209` 等高负载全量脚本。后续只有改到它们覆盖的共享底座且轻量验证不能覆盖风险时，才应串行运行。

## 文档归档

一阶段执行过程文档已经归档，后续默认不要从这些过程文档接续当前工作。

计划归档：

```text
simulator_v8_clean_core/docs/archive/phase1/plans/
```

报告归档：

```text
live_validation_reports/archive/phase1/
```

当前事实入口按优先级是：

1. `CODEX_HANDOFF.md`
2. `simulator_v8_clean_core/docs/archive/phase1/PHASE1_SUMMARY.md`
3. `live_validation_reports/archive/phase1/v8_p1_final_acceptance_checkpoint_v0_292.md`

归档文档保留历史执行和验收过程，其中部分中间报告会记录当时的阻塞项，例如 servant 缺口、counter 缺口、`phase1_minimum_battle_slice=false`。这些是历史状态，不是当前事实。

## P2 建议起点

P2 不应继续修 P1 checklist，而应在 P1 底座上扩大真实机制覆盖。

建议优先级：

1. 状态系统扩面：控制抵抗、更多生命周期时点、更多状态公式和驱散分支。
2. 角色/怪物数据卡扩面：把专属机制进入数据卡槽位，再接通用系统，避免 runtime 特判。
3. 召唤物、servant、assistant 完整行为：在已有 P1 纵切上补完整生命周期、行动和目标语义。
4. 装备、遗器、关卡和环境机制：继续保持 TBGD-first、IR-first 和可审计来源链路。
