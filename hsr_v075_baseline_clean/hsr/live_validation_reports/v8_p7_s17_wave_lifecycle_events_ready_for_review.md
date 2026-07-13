# P7-S17 波次生命周期与事件源接入待验收报告

状态：`ready_for_review=true`。本报告仅作为统一验收证据索引，不宣告阶段完成，不修改 P7 checklist。

## 本阶段结果

- 初始波次以 `pending_start` 建立，scheduler 通过显式 `wave_transition` phase 派发 `wave.started` 与逐单位 `wave.monster`，再回到 `idle`。
- 清场换波是单个 selected graph 原子提交：旧波清理、wave runtime/index、`UnitBirthTemplateIR` 出生、统一事件派发和 phase 恢复任一节点失败都会回滚。
- `wave.started`、`wave.monster`、`wave.cleared`、`battle.victory/defeat/completed` 均经过 phase admission 与 EventDispatchSystem。没有 listener 时只记录 process-only，不伪造 callback。
- wave phase Mutation 使用 `wave_system` 与真实 wave definition/plan identity，不再冒充 timeline 来源；start、advance、complete 三类正式 transition 均通过 replay 和 RuntimeSourceAuditor。
- wave runtime 的稳定 definition/plan identity 决定准入，完整 source trace 只用于审计；裁剪或展开审计详情不改变 plan 行为。缺 stage/wave/birth/event payload、残留未完成 queue 或 typed identity 不一致时 blocked/state unchanged；末波进入显式 `ended`。

## 结构化验证证据

S17 复用 S16 最终真实 lowering/RuleBook，不进行第二次重构建：

```text
run_validation_with_rules(ir, rules, /tmp/p7_s4_repair_real/s17)
```

结果：`ok=true`、`ready_for_review=true`、`rows=5`。

- `initial_wave_start=true`
- `real_two_wave_advance=true`
- `battle_complete=true`
- `event_payload_negative=true`
- `source_and_residual_negative=true`（同时覆盖 audit-expanded state variant，以及 definition/entry IRSource 全清空后的真实 plan 行为等价）

正例选择谓词为“coverage executable、恰好两波、两波均有 executable entry 的 WaveDefinitionIR”。本次证据记录 stage `103060220`，但代码没有用固定 stage/monster ID 选样。

输出：

- `/tmp/p7_s4_repair_real/s17/validation_summary_p7_s17_wave_lifecycle_events.json`
- `/tmp/p7_s4_repair_real/s17/p7_s17_wave_lifecycle_matrix.json`
- `/tmp/p7_s4_repair_real/s17/p7_s17_wave_lifecycle_evidence.json`

## 直接回归与资源边界

- P3-S9 lifecycle cleanup：`ok=true`，复用 RuleBook，`rulebook_build_count=0`。
- P7-S9 phase machine：`ok=true`，包含非法/损坏 phase state unchanged 与 wave source audit。
- P7-S10 timeline、S11 queue terminal progress：均 `ok=true`。
- 最终真实 lowering 仅一次，由 S16/S17 共享；没有写完整 CanonicalIR/RuleBook/transition dump。
- 未运行 P4 聚合、P5/P6 全聚合、P1-5 或无关全量数据验证。

## 明确未做

- 未实现全部关卡环境、特殊玩法或无真实来源的 custom event。
- 未把环境规则写进怪物卡，也未为缺失 payload/source 制造 fallback。
- 未修改 P7 checklist，未提交 Git 检查点。
