# v8 P1-9 phase1 aggregate checkpoint

日期：2026-07-03

## 结论

P1-9 第一阶段聚合验证底座已完成并通过；返工后必须区分“验证报告有效”和“第一阶段最小可用战斗纵切完成”。

关键输出：

```text
/tmp/hsr_v8_p1_9_phase1_aggregate/validation_summary_p1_9_phase1_aggregate.json
/tmp/hsr_v8_p1_9_phase1_aggregate/phase1_system_matrix_p1_9.json
/tmp/hsr_v8_p1_9_phase1_aggregate/phase1_source_gap_matrix_p1_9.json
/tmp/hsr_v8_p1_9_phase1_aggregate/phase1_transition_audit_samples_p1_9.json
```

当前 summary：

```text
ok=true
p1_9_done_eligible=true
phase1_repair_substrate_accepted=true
phase1_minimum_battle_slice=false
```

这表示 P1-9-DONE / repair substrate 可以验收，但第一阶段最小可用战斗纵切不能验收。`ok=true` 不能再被解释为阶段完成；`implementation_missing` 会阻塞 `phase1_minimum_battle_slice`。

## 本次实现

- 新增 `simulator_v8_clean_core/tools/validate_p1_9_phase1_aggregate.py`。
- 将 `validate_p1_7_rng_branch_system.py` 统一为 `run_validation(package_root, tbgd_root, output_dir)`，CLI 输出保持兼容。
- P1-9 聚合脚本默认只构建一次 `TBGDLowering(...).build()` 和一次 `RuleBook`。
- 聚合报告输出返工矩阵：`executable`、`boundary_only`、`source_absent_not_required`、`implementation_missing`。
- 聚合 scenario 覆盖 two-wave、source-backed initial status、source-backed summoned monster、servant admission-missing boundary、explicit timeline、scenario RNG ledger、objective metadata 和至少一个 route transition。
- P1-4/P1-5 细分验证结果被 compact 纳入 P1-9：状态 refresh/stack/chance/duration/expire/DoT/deterministic dispel 和 queue mandatory insert action / insert ability / selectable ultimate / lifecycle guard 均不再只靠单个 setup 或 direct-contract 口径表达。
- route transition 作为 route contract 样本接入 `TransitionContractValidator`；当前 route 样本无 mutation 时，在 transition samples 中明确标为 `route_contract_only_no_mutation`。
- core snapshot replay / source audit 的 mutation 正例改用 source-backed direct status transition，要求 `mutation_count>0`、`RuntimeSourceAuditor.checked_mutations>0`、`SettlementTraceabilityValidator.checked_records>0`。
- executable 矩阵项只有在 `replay_ok=true` 且 `source_audit_ok=true` 时才允许随聚合 `ok=true` 通过；setup status mutation 的 `source_trace_count` 会识别嵌套的 `lifecycle_plan.source_trace` / `status_instance.source_trace`。
- 输出 validation inventory、system matrix、source gap matrix、transition audit samples、static boundary、resource budget。
- 更新 `FIRST_PHASE_TASK_CHECKLIST.md` 与 `CODEX_HANDOFF.md`。

## 聚合矩阵摘要

`phase1_system_matrix_p1_9.json` 当前核心计数会区分 executable 与 implementation_missing；`phase1_source_gap_matrix_p1_9.json` 另含 boundary/source-absent/implementation-missing 行。

```text
passed=12
expected_blocked=2
failed=0
implementation_missing=1
executable=12
boundary_only=1
source_absent_not_required=0
```

`phase1_source_gap_matrix_p1_9.json` 当前计数：

```text
passed=8
expected_blocked=4
failed=0
executable=3
boundary_only=2
source_absent_not_required=5
implementation_missing=2
source_gap_blocked=0
```

核心检查均通过：

- aggregate scenario：通过。
- route transition contract：通过，当前 route 样本为 no-op mutation，已标注 `route_contract_only_no_mutation`，不作为 core source audit 正例。
- direct status transition snapshot replay：通过，`mutation_count=2`。
- direct status transition source audit：通过，`checked_mutations=2`、`checked_records=3`。
- settlement traceability：通过。
- static boundary：通过。
- blocked no mutation：通过。

## 当前 executable 范围

- P1-0：action boundary 聚合检查通过；core 暴露 route command / availability，不做敌方 AI 决策。
- P1-1：unit lifecycle direct contract 通过；defeat / replay / repeat skip 口径稳定。
- P1-2：two-wave setup 可从真实 `WaveDefinitionIR` 构建当前波；下一波不提前进入 state。
- P1-3：source-backed summoned monster 可通过 setup 产生 `UnitSpawn` mutation；servant/忆灵不伪造，并作为 `implementation_missing` 单独列出。
- P1-4：source-backed initial `AddModifier` status 可通过 setup 产生 status mutation，`source_trace_count=2` 来自嵌套 lifecycle/status instance source trace；专项 compact regression 覆盖 refresh、stack、chance/resist/immunity、duration、expire、DoT、deterministic dispel、blocked status。
- P1-5：queue/window IR scope 和 source contract 通过；专项 compact regression 覆盖 mandatory insert action、insert ability、selectable ultimate、actor/target lifecycle guard。follow-up/counter/assistant family 不由该行冒充完成。
- P1-6：普通 target resolution / invalid target blocked 通过。
- P1-7：RNG helper、target random missing/invalid choice、explicit/deterministic schema 通过。
- P1-8：BattleSetup 聚合入口可构建两波、有状态、有召唤、有 timeline/RNG/objective 的初始态。
- Core：route transition contract、direct status mutation snapshot replay、direct status mutation settlement traceability、direct status mutation runtime source audit、static boundary 均通过。

## 当前 minimum battle slice blockers

当前 `phase1_minimum_battle_slice=false` 的阻塞项：

- `p1_3.servant_runtime`：servant/忆灵定义已发现，但 owner/stat/timeline/action/lifecycle admission 未完成。
- `p1_6.servant_target`：servant target registry 当前未 executable。
- `p1_8.servant_initial_setup`：servant/忆灵 initial setup blocked/no mutation，只证明 guard 正确。

不再作为第一阶段 blocker 的项：

- `p1_4.random_dispel_order_random`：当前数据库没有 `Order=Random` 驱散来源，标为 `source_absent_not_required`，deterministic dispel 是当前 executable 范围。
- `p1_4.stack_duration_refresh`：当前没有组合来源正例，禁止 synthetic positive case。
- `p1_5.follow_up` / `p1_5.counter` / `p1_5.assistant`：按当前 queue family 来源矩阵分别标为 `source_absent_not_required` 或 `boundary_only`，不由 P1-5 executable 行冒充完成。
- `p1_8.battle_unit_summon_initial_setup`：`SummonUnitData` 是 catalog/definition，不是自动 battle spawn trigger，当前标为 `boundary_only`。

## 验证命令

在 `hsr_v075_baseline_clean/hsr` 下已串行运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_1_unit_lifecycle --output-dir /tmp/hsr_v8_p1_1_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_2_wave_system --output-dir /tmp/hsr_v8_p1_2_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_5_queue_window_system --output-dir /tmp/hsr_v8_p1_5_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_6_target_system --output-dir /tmp/hsr_v8_p1_6_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_7_rng_branch_system --output-dir /tmp/hsr_v8_p1_7_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_8_battle_setup --output-dir /tmp/hsr_v8_p1_8_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_phase1_aggregate
git diff --check
```

结果：

```text
compileall: pass
P1-0..P1-8: ok=true
P1-9: ok=true, phase1_repair_substrate_accepted=true, phase1_minimum_battle_slice=false
git diff --check: pass
```

高 IO 旧脚本未运行：`validate_v0_204`、`validate_v0_209` 默认不属于 P1-9 验收范围。本次未改 direct damage / crit / RNGEvent schema，也未改 legacy scenario loader，因此没有触发它们。

## 距离最小可用战斗纵切还缺什么

P1-9 之后，core 已能作为外部推演器驱动下的可审计结算器底座使用：可从 BattleSetup 构建初始态、执行 route command、产出 transition、replay、source audit 和 settlement traceability。但这不是“包含 servant/忆灵和全部 queue family 的最小可用战斗纵切完成”。

注意：当前 P1-9 route transition 样本本身不产生 mutation，只证明 route contract / replay no-op 口径；core mutation replay/source audit 正例来自同一结构化来源选择链路下的 direct status transition。

最小可用战斗纵切仍缺：

- servant/忆灵数据卡与 runtime admission：owner、stat、timeline、action、lifecycle、target registry。
- 更完整的队列窗口实战正例覆盖，尤其 follow-up / counter / assistant 的跨系统路线；当前无来源或 boundary 项不能冒充完成。
- 外部推演器侧 route / RNG branch 枚举，不应放进 core。

## 距离完整复刻还缺什么

- 完整角色面板装配：晋阶、全角色行迹、光锥、遗器和套装。
- 大量角色卡、怪物卡、被动、阶段切换、召唤、波次和关卡倍率。
- 完整状态系统：控制、抵抗、免疫、驱散、DoT tick、失败分支。
- 完整目标系统：排序、fetch、随机、相邻、唯一实体、召唤物/servant、特殊玩法目标。
- 环境、关卡机制、特殊战斗模式。
- UI 仍只能展示/编排/审计，不能成为规则来源。

## 下一步建议

下一阶段不要继续扩大动作入口。先按三态分流：

- `executable`：当前 RuleBook / IR 已有真实来源，补正例、replay、source audit。
- `boundary_only`：当前只验证 blocked/process-only/no mutation，不代表机制完成。
- `source_absent_not_required`：当前数据库无必做真实来源，且不作为第一阶段 blocker。
- `implementation_missing`：当前已有真实来源但 runtime admission 或 mutation 缺失，才进入编码修复。

优先建议从 P1-4 状态系统缺口重审开始：stack/refresh/chance/duration/dispel。
