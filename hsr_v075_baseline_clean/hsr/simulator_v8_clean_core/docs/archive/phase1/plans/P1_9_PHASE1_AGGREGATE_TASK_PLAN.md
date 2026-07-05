# P1-9 第一阶段聚合验证与阶段验收总体性执行计划

本文档是 `FIRST_PHASE_TASK_CHECKLIST.md` 中 `P1-9 聚合验证与阶段验收` 的实现级拆解。目标是让一个没有前序对话上下文的新实现线程，可以只依赖本文件、项目入口文档和当前代码完成 P1-9 的实现、验证和阶段报告。

P1-9 的一句话目标：

```text
把 P1-0 到 P1-8 已经形成的第一阶段底座，收束成一个资源受控、可重复、可审计的聚合验证入口和阶段报告，明确当前哪些能力已 executable，哪些仍是 source_gap_blocked，哪些才是真正的 implementation_missing。
```

P1-9 不是“新增一批战斗机制”，也不是“把所有未完成项一次性补完”。它是第一阶段的聚合验收层：

- 确认已有底座能从结构化 BattleSetup 构建战斗、执行 route、产生 transition、replay、source audit。
- 确认 action boundary、unit lifecycle、wave、summon、status、queue/window、target、RNG、BattleSetup 的关键契约没有互相破坏。
- 确认 blocked / audit_only / discovered_only / source_gap 不会伪造 mutation。
- 确认验证输出轻量，不默认跑高 IO 全量脚本。
- 生成给下一阶段和交接文档使用的事实报告。

## 0. 给新实现线程的背景

### 0.1 项目背景

本项目正在构建《崩坏：星穹铁道》战斗模拟器 v8 clean core。最终目标不是让 core 自己做敌方 AI，而是：

```text
外部推演器枚举敌我动作、随机分支和路线
-> v8 core 校验输入是否合法
-> v8 core 执行规则并输出完整 BattleTransition / snapshot / settlement / audit
-> 外部推演器搜索达成目标的通关方式
```

因此 P1-9 的验收重点不是“自动打赢一场战斗”，而是“这个内核是否已经能作为推演器的可审计结算器使用”。

v8 的事实来源固定为：

```text
turnbasedgamedata-main
-> TBGD compiler/lowering
-> Canonical IR / 数据卡 IR
-> Combat Core
```

runtime 只能读取 Canonical IR / 数据卡 IR / scenario setup 形成的初始条件。runtime 不能读取 raw TBGD、TextMap、旧 v7、旧 model pack，也不能用观测答案、固定角色名、固定怪物名或硬编码技能 ID 作为主路径规则来源。

### 0.2 P1-9 的全局位置

第一阶段目标是“外部推演器驱动下的最小完整战斗闭环”。当前前置阶段事实：

- P1-0：action boundary 已建立；core 不主动决定敌人动作，外部可枚举合法输入。
- P1-1：UnitLifecycle 已建立；spawn、defeat、remove 均通过 mutation 表达。
- P1-2：WaveSystem 已建立；可从真实 wave definition 生成当前波和推进下一波。
- P1-3：Summon / Assistant / Servant 已有分类、runtime schema 和至少一种真实 summon 正例；servant 仍有 source gap。
- P1-4：StatusSystem 已有生命周期、chance/resist、DoT、dispel、control gating 等底座；部分机制因当前数据库无真实来源，只能 source gap。
- P1-5：Queue / Window 已有 follow-up、counter、extra-turn、assistant、ultimate window 等队列/窗口语义底座；部分完整正例仍可能受来源覆盖限制。
- P1-6：TargetSystem 已有 sort/fetch/adjacent/random/unique/summon target 的第一阶段关键子集；仍有 toughness/formation sort、owner fetch、servant target 等 source gap。
- P1-7：RNG branch 已有统一 RNG request / event / choice ledger 基础；某些随机机制仍因无真实来源不能当正例完成。
- P1-8：BattleSetup / ScenarioSpec 已能配置两波、初始状态、初始召唤、timeline、RNG 和 objective，并能生成 setup audit records。

P1-9 承接这些阶段，形成：

```text
Scenario JSON / BattleSetup
-> ScenarioLoader / IdentityResolver / ScenarioStateBuilder
-> Action availability / Scheduler or Executor
-> BattleTransition
-> replay / source audit / settlement traceability / static checks
-> phase1 aggregate report
```

### 0.3 当前 P1-9 的关键约束

P1-9 必须区分两个完成口径：

1. **P1-9 聚合底座完成**
   - 聚合验证入口存在。
   - 已有 executable 能力都能通过聚合检查。
   - source gap 被诚实记录。
   - blocked / audit_only / discovered_only 不产生 mutation。
   - 无 implementation_missing / regression。

2. **第一阶段全正例完成**
   - P1-4 / P1-5 / P1-7 等所有列项都有真实来源正例并通过。
   - 只有当前 RuleBook / Canonical IR 中确实存在真实来源时才允许勾全正例 DONE。

如果 P1-9 发现某个机制当前仍无真实来源，不能为了让 `P1-9-DONE` 好看而 synthetic 正例。正确做法是：

```text
source_gap_blocked + state unchanged + process-only report + 后续阶段待来源覆盖
```

### 0.4 当前代码事实

P1-9 直接相关文件：

```text
simulator_v8_clean_core/FIRST_PHASE_TASK_CHECKLIST.md
simulator_v8_clean_core/P1_0_ACTION_BOUNDARY_TASK_PLAN.md
simulator_v8_clean_core/P1_1_UNIT_LIFECYCLE_TASK_PLAN.md
simulator_v8_clean_core/P1_2_WAVE_SYSTEM_TASK_PLAN.md
simulator_v8_clean_core/P1_3_SUMMON_ASSISTANT_SERVANT_TASK_PLAN.md
simulator_v8_clean_core/P1_4_STATUS_SYSTEM_TASK_PLAN.md
simulator_v8_clean_core/P1_5_QUEUE_WINDOW_TASK_PLAN.md
simulator_v8_clean_core/P1_6_TARGET_SYSTEM_TASK_PLAN.md
simulator_v8_clean_core/P1_7_RNG_BRANCH_TASK_PLAN.md
simulator_v8_clean_core/P1_8_BATTLE_SETUP_TASK_PLAN.md
simulator_v8_clean_core/scenarios/
simulator_v8_clean_core/core/
simulator_v8_clean_core/systems/
simulator_v8_clean_core/tools/
simulator_v8_ui/
```

当前 P1 系列验证脚本：

```text
tools/validate_p1_0_action_boundary.py
tools/validate_p1_1_unit_lifecycle.py
tools/validate_p1_2_wave_system.py
tools/validate_p1_3_summon_assistant_servant.py
tools/validate_p1_4_status_system.py
tools/validate_p1_5_queue_window_system.py
tools/validate_p1_6_target_system.py
tools/validate_p1_7_rng_branch_system.py
tools/validate_p1_8_battle_setup.py
```

注意：

- 大多数 P1 脚本已有 `run_validation(package_root, tbgd_root, output_dir)`。
- `validate_p1_7_rng_branch_system.py` 当前是老式 `main()`，P1-9 若要导入聚合，应先把它改成同样的 `run_validation(...) -> dict` 接口，保持 CLI 兼容。
- `validate_v0_204`、`validate_v0_209` 等旧脚本可能写完整 canonical / coverage / fidelity，是高 IO 脚本，不是 P1-9 默认主验证。

## 1. P1-9 的非目标

P1-9 不做以下内容：

- 不做敌方 AI、敌方策略、路线搜索或自动通关。
- 不新增角色、光锥、遗器、环境、关卡机制。
- 不把 P1-4 / P1-5 / P1-7 的 source gap 强行变成 executable。
- 不为当前数据库不存在的机制构造 synthetic 正例。
- 不用固定角色名、固定怪物名、固定 action id、固定 stage id、固定文件 hash 作为聚合主样例选择条件。
- 不从旧 v7、旧 model pack、TextMap 或 raw TBGD runtime 读取规则。
- 不默认运行高 IO 全量验证。
- 不把旧验证输出当作新聚合验证的事实来源；可以作为回归信号，但聚合报告必须能从当前代码和 RuleBook 重新生成。
- 不让 `ok=true` 掩盖 source gap；报告必须单独列 `phase1_full_acceptance` 是否满足。

## 2. 设计原则

### 2.1 聚合验证不是 subprocess 脚本串联

P1-9 应新增主验证脚本：

```text
tools/validate_p1_9_phase1_aggregate.py
```

它的职责是生成第一阶段聚合报告，而不是盲目 subprocess 运行 P1-0 到 P1-8。原因：

- subprocess 串联会重复 TBGD lowering / RuleBook 构建，资源不可控。
- 子脚本只知道自己的局部矩阵，无法形成跨系统 transition / replay / source audit 结论。
- 子脚本 `ok=true` 不能表达 `source_gap_blocked` 是否为预期状态。

P1-9 主脚本应优先：

```text
构建一次 TBGDLowering / CanonicalIR / RuleBook
-> 选择结构化样例
-> 构造聚合 BattleSetup scenario
-> 执行 route / scheduler / executor
-> 运行 replay/source audit/settlement/static checks
-> 输出轻量矩阵和抽样记录
```

可选的直接回归命令在 P1-9 验收阶段串行运行，但不应成为聚合脚本内部默认行为。

### 2.2 聚合报告必须三态化

每个系统项不要只输出布尔值。建议统一矩阵记录：

```json
{
  "item_id": "p1_4.status.initial_add_modifier",
  "phase_item": "P1-4",
  "source_state": "executable",
  "validation_state": "passed",
  "positive_case_count": 1,
  "negative_case_count": 2,
  "mutation_count": 1,
  "blocked_count": 0,
  "source_trace_count": 1,
  "replay_ok": true,
  "source_audit_ok": true,
  "notes": []
}
```

推荐枚举：

```text
source_state:
  executable
  source_gap_blocked
  implementation_missing
  audit_only
  discovered_only
  not_touched

validation_state:
  passed
  expected_blocked
  failed
  skipped_by_scope
```

`summary.ok` 的口径：

```text
ok=true
  当且仅当所有 mandatory 聚合项 passed 或 expected_blocked，
  且没有 implementation_missing / regression / source audit failure / replay failure。

phase1_full_acceptance=false
  只要仍存在 P1 要求的全正例 source gap，例如 servant target、random dispel 等。
```

### 2.3 Source gap 是一等输出

P1-9 必须明确输出 source gap，而不是把它藏在文本里。至少包含：

- source gap 名称。
- 归属阶段。
- 当前为什么不能 executable。
- runtime 是否已有 guarded path。
- blocked 时是否 state unchanged。
- 是否需要后续 discovery、IR lowering、runtime admission 或真实来源。

当前已知需要特别关注的 source gap：

- P1-4：`stack + duration refresh` 同一 AddModifier 正例缺口。
- P1-4：`DispelStatus(Order=Random)` 当前未找到真实来源时只能 source gap。
- P1-6：toughness / formation sort 无安全正例。
- P1-6：owner fetch 当前数据库无正例。
- P1-6：servant target 无 executable runtime registry。
- P1-7：当前数据库无真实随机来源的 RNG path 只能 blocked / coverage gap。
- P1-8：servant initial setup 和 battle_unit_summon initial setup 当前 source gap。

执行时不能把这份列表当硬编码 truth。应优先用结构化扫描重新确认；确实暂时无法结构化扫描的，报告里要标注 `evidence_mode="known_checkpoint"`，并说明待后续工具化。

### 2.4 聚合场景要真实、轻量、可审计

P1-9 应至少构造一个聚合 scenario，覆盖：

- BattleSetup root/alias 解析。
- 当前波来自真实 wave definition。
- ally + enemy roster。
- 初始 SP / max SP。
- HP ratio / energy ratio。
- source-backed initial AddModifier status。
- source-backed summoned monster。
- servant source gap blocked。
- explicit timeline action value。
- scenario-level RNG ledger。
- objective metadata non-interference。
- route command 执行至少一个 transition。

聚合 scenario 必须通过结构化谓词选择样例：

- 可执行角色 action：从 CharacterDataCardIR + ActionDefinitionIR 中选。
- 可执行敌人：从 CombatantProfileIR / MonsterDataCardIR 结构选。
- two-wave definition：从 WaveDefinitionIR 中选 executable 且至少两波。
- initial status：从 EffectIR(opcode=AddModifier) 且 EffectRegistry coverage executable 中选。
- summoned monster：从 SummonMonsterIntentIR executable 中选。

禁止主路径按固定名称、固定 ID、固定 hash 选样例。

### 2.5 验证输出必须轻量

P1-9 默认输出目录建议：

```text
/tmp/hsr_v8_p1_9_phase1_aggregate
```

默认输出建议：

```text
validation_summary_p1_9_phase1_aggregate.json
phase1_system_matrix_p1_9.json
phase1_transition_audit_samples_p1_9.json
phase1_source_gap_matrix_p1_9.json
phase1_static_boundary_p1_9.json
phase1_resource_budget_p1_9.json
```

禁止默认输出：

- 完整 `CanonicalIR.to_json()`。
- 完整 coverage/fidelity。
- 完整 RuleBook 派生对象。
- 全量 transition dump。
- 全量 TBGD discovery 结果。

如确实需要大产物，必须加显式开关：

```text
--write-large-artifacts
```

默认关闭，并在报告中记录：

```json
{
  "large_artifacts_written": false
}
```

## 3. 建议实现结构

### 3.1 新增主验证脚本

新增：

```text
simulator_v8_clean_core/tools/validate_p1_9_phase1_aggregate.py
```

CLI：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_phase1_aggregate
```

参数：

- `--output-dir`：必填。
- `--tbgd-root`：可选，默认 `find_tbgd_root(hsr_root)`。
- `--write-large-artifacts`：可选，默认 false。
- `--include-direct-regression-summaries`：可选，默认 false；只允许读取同一 run 内轻量生成的 summary，不允许默认 subprocess 跑全套旧验证。

主入口建议：

```python
def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path, *, write_large_artifacts: bool = False) -> dict[str, Any]:
    ...
```

`main()` 只负责 argparse、调用 `run_validation`、打印：

```text
v8 p1_9_phase1_aggregate validation ok=True phase1_full_acceptance=False
```

### 3.2 P1-7 验证接口统一

如果 P1-9 需要读取 P1-7 的 summary 结构，应先把：

```text
tools/validate_p1_7_rng_branch_system.py
```

改成和其它 P1 脚本一致：

```python
def run_validation(package_root: Path, tbgd_root: Path, output_dir: Path) -> dict[str, Any]:
    ...
```

要求：

- 保持原 CLI 行为和输出文件名不变。
- 不新增 TBGD 依赖；P1-7 当前主要是纯 runtime helper 验证，`tbgd_root` 可接受但不使用。
- P1-7 summary 返回 dict，便于 P1-9 或验收读取。

### 3.3 聚合报告顶层结构

建议 summary：

```json
{
  "version": "p1_9_phase1_aggregate",
  "baseline_version": "...",
  "ok": true,
  "p1_9_done_eligible": true,
  "phase1_full_acceptance": false,
  "phase1_full_acceptance_blocked_by": [
    "P1-4 random dispel source gap",
    "P1-6 servant target source gap"
  ],
  "build": {
    "tbgd_root": "...",
    "selection_policy": {
      "mode": "structured_ir_predicates",
      "fixed_character_or_monster_name_used_for_main_samples": false
    }
  },
  "matrix_counts": {
    "passed": 0,
    "expected_blocked": 0,
    "failed": 0,
    "implementation_missing": 0,
    "source_gap_blocked": 0
  },
  "checks": {
    "aggregate_scenario": {"ok": true},
    "transition_contract": {"ok": true},
    "snapshot_replay": {"ok": true},
    "source_audit": {"ok": true},
    "settlement_traceability": {"ok": true},
    "static_boundary": {"ok": true},
    "blocked_no_mutation": {"ok": true}
  }
}
```

### 3.4 聚合系统矩阵

`phase1_system_matrix_p1_9.json` 至少包含：

| item_id | 目标 | 完成口径 |
|---|---|---|
| `p1_0.action_boundary` | core 暴露合法输入，不做 AI | ally/enemy/summon 当前态可解释，enemy action 由外部输入 |
| `p1_1.lifecycle` | spawn/defeat/remove 可 replay | lifecycle mutation path 有 source/audit/replay |
| `p1_2.wave` | 当前波/下一波语义可追踪 | WaveRuntime source trace，下一波不提前进 state |
| `p1_3.summon` | 真实 summon 正例可 spawn | SummonMonsterIntentIR -> UnitSpawn mutation |
| `p1_3.servant_gap` | servant 不伪造 | blocked/process-only/no mutation |
| `p1_4.status` | source-backed AddModifier 可 setup/执行 | StatusSystem mutation/source trace/replay |
| `p1_4.status_gap` | 无真实来源项不伪造 | source_gap_blocked/no mutation |
| `p1_5.queue_window` | queue/window 不破坏 transition | mandatory/selectable/window 记录可审计 |
| `p1_6.target` | target resolution 可审计 | target trace、blocked target no mutation |
| `p1_7.rng` | RNG choices 进入 RNGEvent | explicit ledger / deterministic seed replay |
| `p1_8.battle_setup` | scenario setup 能构建聚合初始态 | setup records/mutations/blocked records 正确 |
| `core.snapshot_replay` | mutation replay 到 after snapshot | replay ok |
| `core.source_audit` | mutation/settlement 来源可追踪 | source audit ok |
| `core.static_boundary` | runtime 不越界 | no raw TBGD/TextMap/v7/model pack |

每项都要有 `source_state` 和 `validation_state`，不要只写 `ok`。

### 3.5 聚合 transition audit samples

`phase1_transition_audit_samples_p1_9.json` 应抽样保存少量 transition/audit 记录：

- setup mutation sample：initial status 或 initial summon。
- route action transition sample：至少一个实际 route action。
- queue/window sample：如果聚合 route 没触发，则记录 direct queue validation summary 或 `skipped_by_scope` 原因。
- blocked sample：servant setup、missing RNG choice、unsupported target/status 等至少一种。
- replay sample：before hash、mutation ids、after hash、replay ok。
- source audit sample：mutation id -> settlement record -> source trace。

不要保存完整 transition 大对象；保存摘要即可：

```json
{
  "transition_id": "...",
  "mutation_count": 3,
  "rng_event_count": 1,
  "settlement_record_count": 4,
  "blocked_record_count": 0,
  "replay_ok": true,
  "source_audit_ok": true,
  "sample_mutation_ids": ["..."],
  "sample_record_types": ["damage", "resource", "status"]
}
```

## 4. 详细任务拆解

### P1-9.1 审查 P1-0 到 P1-8 当前验证输入输出

目标：明确现有阶段验证能提供什么，P1-9 需要补什么。

需要做：

- 阅读 `validate_p1_0` 到 `validate_p1_8` 的 summary 结构。
- 记录哪些脚本已有 `run_validation`，哪些只有 CLI。
- 记录每个脚本默认输出文件和资源风险。
- 确认没有脚本默认写完整 CanonicalIR 或全量 coverage/fidelity。

验收：

- P1-9 计划实现中有 `phase1_validation_inventory` 或等价输出。
- P1-7 接口差异被处理。

### P1-9.2 统一 P1-7 run_validation 接口

目标：让 P1-7 可被聚合器或验收工具以函数形式调用。

需要做：

- 将 `validate_p1_7_rng_branch_system.py` 的主体提取为 `run_validation(...) -> dict`。
- 保持 CLI 输出和文件名不变。
- `main()` 返回 exit code，和其它 P1 脚本风格一致。

验收：

- 直接运行 P1-7 CLI 仍返回 `v8 p1_7_rng_branch_system validation ok=True`。
- 函数调用能返回 summary dict。

### P1-9.3 新增聚合报告 schema

目标：先定义报告结构，再填充 case。

需要做：

- 在 `validate_p1_9_phase1_aggregate.py` 中定义 matrix item helper。
- 统一 `source_state`、`validation_state`、`phase_item`、`item_id`。
- 统一计数和 `ok` 计算规则。

验收：

- 空/最小矩阵也能输出合法 JSON。
- `ok`、`p1_9_done_eligible`、`phase1_full_acceptance` 三者语义分离。

### P1-9.4 构建 RuleBook 一次并选择结构化样例

目标：P1-9 主验证默认只做一次 TBGD lowering / RuleBook 构建。

需要做：

- 调用 `TBGDLowering(tbgd_root).build()` 一次。
- 创建 `RuleBook(ir)` 一次。
- 按结构化谓词选择 action、enemy、wave、status、summon、target/RNG 样例。
- 选择结果写入 `selection_policy`。

验收：

- 报告中说明没有固定角色名/怪物名/action id 作为主样例选择条件。
- 找不到样例时，按 `implementation_missing` 或 `source_gap_blocked` 分类，而不是 fallback 固定 ID。

### P1-9.5 构造聚合 BattleSetup scenario

目标：用 P1-8 的配置入口生成第一阶段聚合初始态。

需要做：

- 构造 scenario dict 或临时 JSON。
- 使用 `battle_setup.wave` 选真实 two-wave definition。
- 使用 source-backed initial status。
- 使用 source-backed summoned monster。
- 增加 servant initial setup negative case。
- 增加 timeline explicit action value。
- 增加 scenario-level RNG ledger。
- 增加 objective metadata。

验收：

- `ScenarioLoader`、`IdentityResolver`、`ScenarioStateBuilder` 全链路通过。
- `build.setup_records`、`build.setup_mutations`、`build.blocked_setup` 被纳入报告。
- servant / unsupported setup 只产生 blocked/process-only，不产生 mutation。

### P1-9.6 执行聚合 route 并验证 transition contract

目标：不止构建初始态，还要至少执行一个 action transition。

需要做：

- 使用 `CombatScheduler` 或 `CombatExecutor` 执行聚合 scenario 的第一条 route。
- 保留 before/after snapshot 摘要。
- 运行 `TransitionContractValidator`。
- 运行 `MutationReducer.replay_snapshot`。
- 运行 `RuntimeSourceAuditor`。
- 运行 `SettlementTraceabilityValidator`。

验收：

- route transition `contract.ok=true`。
- replay ok。
- source audit ok。
- settlement traceability ok。
- transition 的 mutations / process events / rng events / settlement 计数写入摘要。

### P1-9.7 聚合 action boundary 验证

目标：确认 P1-0 语义在聚合状态里仍成立。

需要做：

- 对聚合 build 后 state 调用 `ActionAvailabilitySystem` 或 scheduler 当前行动视图。
- 验证 active ally 可由外部 route 驱动。
- 验证 enemy 侧不会由 core 自动 AI 决策；只有外部 command 或已排队 mandatory queue 能推进。
- 验证 selectable action 与 mandatory queue/window 不混淆。

验收：

- action boundary matrix 有 passed 项。
- enemy AI missing 只能是 blocked/process notice，不是 runtime 自动选择。

### P1-9.8 聚合 lifecycle / wave / summon 验证

目标：确认 P1-1/P1-2/P1-3 的 mutation 语义在同一报告中可审计。

需要做：

- 从聚合 setup 中抽取 initial summon UnitSpawn mutation。
- 从 wave runtime 中记录当前波/下一波信息。
- 如聚合 route 能造成击杀/波次推进，则记录 route transition；若不能，使用轻量 direct case 验证 lifecycle/wave contract，并说明 `case_kind=direct_contract`。
- 验证 removed/defeated/spawned 不会破坏 target/timeline/queue。

验收：

- 至少一个 spawn mutation replay/source audit 通过。
- wave runtime source trace 存在。
- 下一波单位不会提前进入 `state.units`。

### P1-9.9 聚合 status / queue-window / target / RNG 验证

目标：把 P1-4 到 P1-7 的横向系统契约放进同一矩阵。

需要做：

- status：source-backed AddModifier 正例、blocked effect negative。
- queue/window：mandatory/selectable/window 至少一个轻量 case；若聚合 scenario 未触发，引用 direct contract case。
- target：普通目标 resolution、random target missing choice blocked、invalid target blocked。
- RNG：explicit ledger、deterministic seed replay、missing/invalid choice blocked。

验收：

- 每个系统至少一个 `passed` 或 `expected_blocked` 矩阵项。
- missing choice / invalid target / unsupported status 不产生 mutation。
- RNG event schema 与 replay 稳定。

### P1-9.10 输出 source gap / blocked / process-only 矩阵

目标：把“不做假正例”的结果显式记录。

需要做：

- 汇总 known source gap，并尽量通过结构化扫描确认。
- 汇总 blocked records，检查 `produced_mutation=false` 或等价证据。
- 汇总 audit_only / discovered_only / blocked 是否有 mutation。
- 对无法结构化扫描的 gap 标注 evidence_mode。

验收：

- `phase1_source_gap_matrix_p1_9.json` 存在。
- source gap 不影响 `ok`，但影响 `phase1_full_acceptance`。
- 如果发现真实来源存在但 runtime 未实现，必须标 `implementation_missing`，不能标 source gap。

### P1-9.11 增加 static boundary 检查

目标：确认 runtime 仍保持 v8 clean core 边界。

需要做：

- 调用现有 `run_static_checks(package_root)`。
- 额外检查 `scenarios/` 入口不读取 raw TBGD、TextMap、旧 v7、旧 model pack。
- 额外检查新增 P1-9 工具没有写仓库内大产物。

验收：

- `phase1_static_boundary_p1_9.json` 存在。
- runtime 不引用旧 simulator、旧 model pack、TextMap、raw TBGD。

### P1-9.12 资源预算与输出约束

目标：P1-9 本身不要成为新的高负载脚本。

需要做：

- 默认只输出 summary/matrix/sample。
- 不默认写完整 CanonicalIR。
- 不并行跑多个 TBGD lowering。
- 报告中写出 `resource_policy`。

验收：

- 默认输出文件数量和大小可控。
- 没有 `CanonicalIR.to_json()` 全量写盘。
- 没有全量 transition dump。

### P1-9.13 新增 live validation report

目标：给后续线程一个阶段事实快照。

新增：

```text
live_validation_reports/v8_p1_9_phase1_aggregate_checkpoint.md
```

报告必须包含：

- 当前 P1-9 结论。
- P1-0 到 P1-8 聚合矩阵摘要。
- 当前 executable 范围。
- 当前 source gap 范围。
- 当前 implementation_missing 范围，如果有。
- 验证命令和结果。
- 距离最小可用战斗纵切还缺什么。
- 距离完整复刻还缺什么。

验收：

- 报告不把 source gap 写成已完成。
- 报告明确 P1-9-DONE 与 PHASE1 full acceptance 的区别。

### P1-9.14 更新交接文档

目标：让下一个线程知道 P1-9 后该从哪里继续。

需要更新：

```text
CODEX_HANDOFF.md
```

或当前项目入口文档要求的长期交接摘要。

需要写：

- 最近检查点。
- P1-9 聚合报告路径。
- 当前可信底座。
- 当前 source gap。
- 下一阶段建议。

验收：

- 交接摘要中没有把 P1-4/P1-5/P1-7 的未完成 source gap 写成全完成。

### P1-9.15 更新 checklist 状态

目标：让 `FIRST_PHASE_TASK_CHECKLIST.md` 与 P1-9 真实口径一致。

需要做：

- 勾选 P1-9 已完成子项。
- 若 P1-9 聚合底座通过，勾 `P1-9-DONE`。
- 不自动勾 `第一阶段已完成`，除非 PHASE1-ACCEPT 全部满足。
- 对 PHASE1 accept 项如果仍因 source gap 未满足，保持未勾并说明。

验收：

- checklist 中 `P1-9-DONE` 和 `PHASE1-ACCEPT-*` 不混淆。

## 5. 分层验证范围

### 5.1 必跑最小集

每次 P1-9 实现或修正后必跑：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
```

目的：语法和 import 基础检查。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_phase1_aggregate
```

目的：P1-9 主聚合验证。

```bash
git diff --check
```

目的：静态 diff 空白检查。

### 5.2 直接回归集

如果 P1-9 只新增工具和文档，不改 runtime，可优先不全跑 P1-0 到 P1-8。但以下触发条件必须跑对应回归：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_7_rng_branch_system --output-dir /tmp/hsr_v8_p1_7_after_p1_9
```

触发条件：改 P1-7 验证接口、RNG helper、RNG schema、choice ledger。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_8_battle_setup --output-dir /tmp/hsr_v8_p1_8_after_p1_9
```

触发条件：改 scenario / BattleSetup / aggregate scenario 构造逻辑。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_5_queue_window_system --output-dir /tmp/hsr_v8_p1_5_after_p1_9
```

触发条件：改 queue/window reporting、scheduler、mandatory/selectable 逻辑。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_6_target_system --output-dir /tmp/hsr_v8_p1_6_after_p1_9
```

触发条件：改 target resolution、target blocked、target random/RNG。

### 5.3 阶段验收扩展集

P1-9 完工验收时建议串行跑：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_1_unit_lifecycle --output-dir /tmp/hsr_v8_p1_1_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_2_wave_system --output-dir /tmp/hsr_v8_p1_2_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_5_queue_window_system --output-dir /tmp/hsr_v8_p1_5_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_6_target_system --output-dir /tmp/hsr_v8_p1_6_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_7_rng_branch_system --output-dir /tmp/hsr_v8_p1_7_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_8_battle_setup --output-dir /tmp/hsr_v8_p1_8_after_p1_9
```

要求：

- 串行运行。
- 不与 P1-9 主验证并发。
- 若验收为了节省时间跳过部分子验证，必须说明跳过理由和剩余风险。

### 5.4 高 IO 脚本默认禁跑

默认不跑：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_204 --output-dir /tmp/hsr_v8_v0_204_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_209 --output-dir /tmp/hsr_v8_v0_209_after_p1_9
```

触发条件：

- 改到 direct damage / crit / RNGEvent schema 且 P1-7/P1-9 无法覆盖时，才考虑 `validate_v0_209`。
- 改到 legacy scenario loader / UI legacy case 且 P1-8/P1-9 无法覆盖时，才考虑 `validate_v0_204`。

要求：

- 必须串行运行。
- 输出到 `/tmp`。
- 不并发其它重验证。
- 如果资源风险高，先只读脚本确认输出规模。

## 6. P1-9-DONE 验收标准

可以勾 `P1-9-DONE` 的条件：

- `validate_p1_9_phase1_aggregate` 存在且通过。
- 聚合报告明确输出 `ok=true`。
- 聚合报告明确输出 `p1_9_done_eligible=true`。
- 聚合报告明确输出 `phase1_full_acceptance`，即使它是 false。
- executable 项有正例、negative validation、replay、source audit。
- source gap 项有 blocked/state unchanged/process-only 证据。
- blocked / audit_only / discovered_only 不产生 mutation。
- static boundary 通过。
- live validation report 已更新。
- `CODEX_HANDOFF.md` 或等价交接摘要已更新。
- `compileall` 和 `git diff --check` 通过。

不能勾 `P1-9-DONE` 的情况：

- 聚合脚本只是 subprocess 跑一串旧脚本，没有聚合矩阵。
- 聚合报告只有 `ok=true`，没有 source gap / implementation_missing 分类。
- 发现真实来源存在但 runtime 缺 admission，却被写成 source gap。
- source gap 机制产生 mutation。
- runtime 或 scenario builder 读取 raw TBGD / TextMap / v7 / model pack。
- 主样例选择依赖固定角色名、怪物名、技能 ID、stage ID、文件 hash。
- 默认写完整 CanonicalIR / coverage / fidelity 大产物。
- P1-4/P1-5/P1-7 的未完成项被静默当作已全完成。

## 7. 文件改动范围

预计新增：

```text
simulator_v8_clean_core/P1_9_PHASE1_AGGREGATE_TASK_PLAN.md
simulator_v8_clean_core/tools/validate_p1_9_phase1_aggregate.py
live_validation_reports/v8_p1_9_phase1_aggregate_checkpoint.md
```

预计修改：

```text
simulator_v8_clean_core/FIRST_PHASE_TASK_CHECKLIST.md
simulator_v8_clean_core/tools/validate_p1_7_rng_branch_system.py
hsr/CODEX_HANDOFF.md
```

按实际实现可能修改：

```text
simulator_v8_clean_core/tools/validate_p1_*.py
simulator_v8_clean_core/tools/static_checks.py
```

原则：

- 不修改 runtime，除非 P1-9 发现真实 regression 或 implementation_missing。
- 如果必须修改 runtime，立即扩大对应直接回归集。
- 不引入新依赖。

## 8. 给执行层的实现顺序建议

建议按以下顺序做：

1. 只读审查 P1 验证脚本和当前报告。
2. 统一 P1-7 `run_validation` 接口。
3. 搭建 `validate_p1_9_phase1_aggregate.py` 的 summary/matrix 框架。
4. 构建一次 RuleBook，完成结构化样例选择。
5. 构造 BattleSetup 聚合 scenario。
6. 执行 route transition 并接 replay/source audit/settlement traceability。
7. 填充 action/lifecycle/wave/summon/status/queue/target/RNG matrix。
8. 填充 source gap / blocked no mutation matrix。
9. 接 static boundary。
10. 输出 live validation report。
11. 更新 `CODEX_HANDOFF.md` 和 checklist。
12. 跑必跑验证。
13. 根据实际触达范围跑直接回归。

实现过程中如果遇到“当前计划要求正例，但 RuleBook 中没有真实来源”，不要合成正例。应把该项改为 `source_gap_blocked`，并在报告里说明结构化扫描结果。

