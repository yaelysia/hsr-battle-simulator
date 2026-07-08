# v8 P3-S7 AssistantAvatar queue boundary checkpoint

## 结论

P3-S7 已按当前数据库和 IR 事实收口为 `out_of_scope` + queue boundary audit。

当前 raw TBGD 中存在 `TurnInsertAssistantAbility` 结构化来源，且已投影到 `QueueIntentIR`、`AssistantAbilityResolutionIR`、`QueueResolutionIR`、`QueueWindowIR` 和 RuleBook 查询入口：

- assistant raw count: 5
- assistant queue intent IR count: 5
- assistant resolution IR count: 5
- assistant queue window IR count: 5
- executable assistant resolution count: 0
- executable assistant queue window count: 0

复核后确认它属于 AssistantAvatar / avatar assistant ability 系统，不是 P3 summon monster、UnitSpawn、servant lifecycle 或 SummonUnit runtime entity 语义。因此它不再作为 P3 admission gap；S0/S1/S7/S12 统一归类为 `out_of_scope`，后续单独处理。runtime 仍不得把 AssistantAvatar 当作 servant、summoned monster 或普通 P3 summon action 执行。

## 本次修改

- `AssistantAbilityResolutionIR.attribution_policy` 保留 blocked metadata 作为 AssistantAvatar 审计证据。
- 新增 `validate_p3_s7_assistant_queue_execution`，覆盖：
  - raw / IR / RuleBook 分层一致性。
  - blocked assistant intent 不派生 executable queue resolution/window。
  - missing owner alias、missing actor source、missing stats source、missing action graph source、dynamic ability id、unsupported target alias、priority missing 负例。
  - validation-only assistant queue entry 的 drain / action availability boundary，确认 state unchanged、无 selectable window、无 action choices。
- P3-S12 新增 `p3_summon_scope_exclusions.json`，把该类来源移出 P3 summon/servant acceptance。

## 验证结果

所有验证均串行运行，输出到 `/tmp`，未写完整 Canonical IR 或全量 transition dump。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/tbgd/lowering.py simulator_v8_clean_core/tools/validate_p1_3_summon_assistant_servant.py simulator_v8_clean_core/tools/validate_p3_s7_assistant_queue_execution.py
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s7_assistant_queue_execution --output-dir /tmp/hsr_v8_p3_s7_assistant_queue_execution
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_summon_assistant_servant_p3_s7_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_5_queue_window_system --output-dir /tmp/hsr_v8_p1_5_queue_window_system_p3_s7_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_s10_status_callback_coverage --output-dir /tmp/hsr_v8_p2_s10_status_callback_coverage_p3_s7_regression
```

结果：

- P3-S7 main: `ok=True`
- P1-3 summon / assistant / servant direct regression: `ok=True`
- P1-5 queue / window direct regression: `ok=True`
- P2-S10 status callback coverage direct regression: `ok=True`

S7 summary:

```json
{
  "assistant_raw_count": 5,
  "assistant_queue_intent_ir_count": 5,
  "assistant_resolution_ir_count": 5,
  "assistant_queue_window_ir_count": 5,
  "assistant_executable_resolution_count": 0,
  "assistant_executable_window_count": 0,
  "classification": "out_of_scope",
  "negative_case_count": 7,
  "queue_drain_classification": "boundary_only",
  "failed_group_count": 0
}
```

代表性 drain boundary：

- queue drain blocked reason: `queue_intent_not_executable:queue_actor_target_alias_not_admitted:missing`
- action availability mode: `blocked`
- choice count: 0
- selectable window count: 0
- state unchanged: true

## 后续处理

AssistantAvatar / avatar assistant ability 目前不是 P3 召唤物/servant 验收项。若后续要实现，应另立阶段确认 actor 身份、stats、ability graph、target resolution、queue priority 和 attribution policy 的真实来源；不能在 P3 里把它伪装成 servant 或 summoned monster。

P3-S8 只继续处理 summon / servant 目标关系；`FriendServantSelect` / AssistantAvatar target boundary 归类为 `out_of_scope`。
