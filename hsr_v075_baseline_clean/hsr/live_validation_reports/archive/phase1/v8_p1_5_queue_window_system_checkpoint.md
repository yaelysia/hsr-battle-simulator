# v8 P1-5 行动队列与窗口语义阶段检查点

## 本阶段完成

本检查点按 `P1_5_QUEUE_WINDOW_TASK_PLAN.md` 推进 queue/window 底座，结论是 `P1-5-SUBSTRATE-ACCEPTED`，不宣称 `P1-5-DONE` 全正例完成。

已完成的底座能力：

- `QueueEntry` 补齐 owner/source、expiration/cancel policy、target resolution、window policy 等 replay / audit 可见字段。
- `QueueWindowPlan` 与 `QueueDrainPlan` 增加 `control`、`family_order`、`ordering_source_kind`、`ordering`、`tie_breaker` 输出。
- queue family order 明确标为 `engine_scheduling_convention`，不伪装成 TBGD source。
- priority ordering 与 family ordering 分离：
  - `priority_order_source_kind` 来自 TBGD priority table、manual route input 或 source gap。
  - family order / tie breaker 只作为 deterministic runtime convention。
- scheduler queue drain 成功路径补齐 process event / settlement：
  - `queue.drain.begin`
  - `queue.drained`
  - `queue.action.before` / `queue.action.after`（有 child action 时）
  - `queue.drain.end`
  - `queue_drain_begin` / `queue_drain_end` process-only settlement。
- scheduler queue blocked 路径保留既有 `scheduler_blocked`，并额外输出 `queue.drain.blocked` 和 `queue_drain_blocked`。
- action availability 对 queue 形成稳定三态：
  - mandatory queue 阻止自然 turn 和普通外部 command。
  - selectable queue 暴露 selectable window；即使 action event/resource preflight 有缺口，也不隐藏 window。
  - blocked queue 保持 state unchanged，并输出 blocked reason。
- selectable window metadata 补齐：
  - actor、queue entry、queue intent / resolution / window。
  - drain plan。
  - target policy / target resolution。
  - resource preflight。
  - queue source 与 engine scheduling convention。
- actor removed / defeated、target defeated 对 pending queue 的执行前 gate 已验证：不产生 child action，不静默丢弃 queue entry，不默认 retarget。
- 新增 `validate_p1_5_queue_window_system`，按结构化谓词输出 queue source matrix、window order matrix、mandatory/selectable/extra-turn/source-gap/negative validation。

## 当前状态范围

当前 IR 结构化统计：

- `QueueWindowIR` 总数：1449。
- `QueueWindowIR.coverage_status`：
  - `executable`: 577。
  - `blocked`: 872。
- `QueueWindowIR.window_family`：
  - `insert_ability`: 1363，其中 executable 564。
  - `insert_action`: 76，其中 executable 10。
  - `extra_turn`: 6，其中 executable 3。
  - `assistant`: 4，全部 blocked。
- `QueueResolutionIR.resolved_kind`：
  - `standalone_ability_graph`: 564。
  - `action_definition`: 10。
  - `extra_turn_action_choice`: 3。
  - `blocked_intent`: 860。
  - `standalone_ability_graph_blocked`: 6。
  - `unresolved_ability_name`: 6。

可信 executable：

- `insert_action`：真实 executable `TurnInsertAction -> action_definition` 可入队、mandatory drain、child action、source audit、replay。
- `insert_ability`：真实 executable `TurnInsertAbility -> standalone_ability_graph` 可入队、mandatory drain、standalone ability runner、source audit、replay。
- `extra_turn`：真实 executable `TurnInsertAction + PrepareAbilityName -> extra_turn_action_choice` 可通过 after-kill / after-skill source chain 入队，route command drain，产生 `extra_turn.begin/end`，不推进自然 AV，不提前自然 turn end。
- manual ultimate queue request：manual route input 可 enqueue，并在 action availability 中以 selectable window 暴露；缺 command / mismatch command blocked 且 state unchanged。

当前 source gap / blocked：

- `follow_up`: 当前 RuleBook 未发现结构化 `QueueWindowIR.window_family == follow_up` 正例，记录为 `source_gap_blocked`。
- `counter`: 当前 RuleBook 未发现结构化 `QueueWindowIR.window_family == counter` 正例，记录为 `source_gap_blocked`。
- `assistant`: 当前发现 4 条 assistant queue window，但全部 blocked，原因样例包括：
  - `queue_actor_target_alias_not_admitted:missing`
  - `queue_priority_key_not_admitted:InsertAbilityPriority:missing`
- `interrupt` / `immediate` / `unknown`: 当前无结构化 executable 正例，保持 source gap。
- manual ultimate matching command 当前不能作为成功释放正例：所有 ultimate 对应 `ActionEventIR` 当前仍是 blocked，匹配 command 会以 `queue_action_event_not_admitted:*` blocked 且 state unchanged。验证把这记录为 `implementation_missing_or_source_gap_blocked`，不合成扣能量或 child action mutation。

## 正例与负例

正例：

- mandatory insert action：
  - 按 `QueueWindowIR.window_family == insert_action`、`QueueResolutionIR.resolved_kind == action_definition`、三者 coverage executable 选择。
  - 验证 `ActionAvailabilityView.mode == queued_mandatory`。
  - scheduler 无 external command 时优先 drain queue。
  - transition 含 `queue.drain.begin/end`，dequeue mutation 可 replay/source audit。
- insert ability：
  - 按 `QueueWindowIR.window_family == insert_ability`、`QueueResolutionIR.resolved_kind == standalone_ability_graph`、`executable_task_ids` 非空选择。
  - 验证 standalone ability drain、process events、source audit、replay。
- extra turn：
  - 按 executable `TurnInsertAction + PrepareAbilityName`、`QueueWindowIR.window_family == extra_turn`、`QueueResolutionIR.resolved_kind == extra_turn_action_choice` 选择。
  - 验证 after kill / after skill source chain、route command、`extra_turn.begin/end`、不消费普通 turn lifecycle。
- manual ultimate selectable：
  - 由 manual route input enqueue。
  - action availability 暴露 selectable window、resource preflight、target policy。
  - no command / mismatch command blocked 且 state unchanged。

负例：

- blocked / audit-only / discovered-only queue intent 不会产生 executable window。
- text-only queue window hint 不会 executable。
- assistant family 当前不会 executable 入队。
- unknown / interrupt / immediate 当前无正例时记录 source gap，不写 synthetic queue mutation。
- actor removed pending queue blocked，state unchanged，无 child action。
- target defeated pending queue blocked，state unchanged，无 child action。
- selectable ultimate 缺 command blocked，state unchanged。
- selectable ultimate mismatch command blocked，state unchanged。
- selectable ultimate matching command 在 action event admission 缺口下 blocked，state unchanged，不扣能量。
- unsupported PredicateTaskList 父任务不直接执行 child queue；child intent executable 不代表父条件可跳过。

## 来源边界

runtime 仍只读取 Canonical IR / RuleBook / runtime state，不读取 raw TBGD、TextMap、旧 v7 或旧 model pack。

source/convention 分离：

- `queue_intent_source`、`queue_resolution_source`、`queue_window_source`、`queue_lifecycle_policy_id`、`extra_action_policy_id` 保留真实 IR 链路。
- `engine_scheduling_convention` 只用于 family order 和 tie breaker，写入 plan/metadata，但不作为 TBGD source。
- blocked / discovered-only / audit-only / source gap 只产生 process-only settlement 或 static matrix，不产生 queue mutation。

## 验证结果

已通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_5_queue_window_system --output-dir /tmp/hsr_v8_p1_5_queue_window_system
```

`validate_p1_5_queue_window_system` 输出 `ok=True`，并生成：

- `/tmp/hsr_v8_p1_5_queue_window_system/validation_summary_p1_5_queue_window_system.json`
- `/tmp/hsr_v8_p1_5_queue_window_system/queue_source_matrix_p1_5.json`
- `/tmp/hsr_v8_p1_5_queue_window_system/queue_window_order_matrix_p1_5.json`
- `/tmp/hsr_v8_p1_5_queue_window_system/queue_mandatory_drain_case_p1_5.json`
- `/tmp/hsr_v8_p1_5_queue_window_system/queue_selectable_ultimate_case_p1_5.json`
- `/tmp/hsr_v8_p1_5_queue_window_system/queue_extra_turn_case_p1_5.json`
- `/tmp/hsr_v8_p1_5_queue_window_system/queue_family_source_gaps_p1_5.json`
- `/tmp/hsr_v8_p1_5_queue_window_system/queue_actor_removed_case_p1_5.json`
- `/tmp/hsr_v8_p1_5_queue_window_system/queue_unknown_family_blocked_case_p1_5.json`
- `/tmp/hsr_v8_p1_5_queue_window_system/queue_insert_ability_case_p1_5.json`

## 距离最小可用战斗纵切还缺什么

- manual ultimate 的 successful drain 仍缺 action event admission；当前只完成 selectable window、command 校验和 blocked/state unchanged。
- follow-up / counter 当前没有结构化 executable queue window 来源；后续需要 discovery/lowering 出真实 family source 后再做 positive drain。
- assistant queue 当前有发现但未 admitted；需要 actor/owner/target/priority/source runner 全链路来源。
- queue cancel/expiration 当前只有 blocked/process-only 策略；真实过期、跨波清理、retarget policy 仍待来源。
- queue 随机顺序、随机 target、随机触发还未接入 P1-7 RNG ledger。

## 距离完整复刻还缺什么

- 完整角色/怪物追击、反击、插队、额外回合、assistant/servant 机制扩面。
- 完整 target sort/fetch/random/adjacent/retarget。
- 完整 enemy AI / route 搜索器不属于 core，但推演器输入接口仍需 P1-8 扩展。
- 光锥、遗器、环境、关卡机制带来的 queue/window 还未接入。
- 全部 queue mutation 仍需随角色/怪物扩面持续做 mutation -> settlement -> IR -> TBGD source 抽样审计。
