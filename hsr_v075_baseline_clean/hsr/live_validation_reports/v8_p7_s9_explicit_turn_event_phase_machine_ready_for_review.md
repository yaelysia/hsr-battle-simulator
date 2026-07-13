# P7-S9 显式回合与事件阶段机待验收报告

状态：`ready_for_review=true`。本报告仅作为统一验收的证据索引，不宣告阶段完成，不修改 P7 checklist。

## 本阶段结果

- 新增一等 `CombatPhaseMachine`，权威阶段存于 `BattleState.global_flags.combat_phase`；不复用场景层 `phase`，不从调用顺序猜当前阶段。
- 阶段契约明确 idle、timeline advancing、turn begin、pre-action、awaiting decision、action execution、post-action、turn end、insert window、extra action、wave transition、ended 的合法迁移和操作准入。
- 自然回合推进由一个原子 scheduler transition 完成：`idle → timeline_advancing → turn_begin → pre_action → awaiting_decision`。每次迁移均有 Mutation、event、settlement record、timeline rule source audit。
- 动作提交由同一原子链完成：`awaiting_decision → action_execution → post_action → turn_end → idle`。phase Mutation 与 action/cursor/status/timeline Mutation 按前置值串联，子 transition 不完整时整链不发布。
- turn begin/end 不再由 TimelineSystem 和 scheduler 重复产生；二者各只通过统一 EventDispatchSystem 派发一次。修正了 `turn.begin` 错误包含 `OnEnterBattle` alias 的问题，battle start 与 turn begin 分离。
- 移除 scheduler 的 `admit_turn_end_listener_dispatch` global flag。turn end 必须先进入 `turn_end` phase，再通过统一 dispatcher，最后清理 turn owner/active turn 并回到 idle。
- DoT 所使用的 `ModifierPhase1End` 状态生命周期从旧 turn-end 位置移到 pre-action：turn.begin dispatch 之后、决策和动作之前；turn end 使用独立 `TurnEnd` 生命周期点，避免重复 tick。
- Decision 输出新增当前 combat phase 与合法下一阶段；查询仅在 awaiting-decision/insert-window phase 可 ready。
- EventDispatchSystem 对 turn begin、turn end、battle start、wave monster 执行 phase admission；非法 phase 派发返回 blocked/state unchanged。
- extra-action 与 insert/wave phase 已有合法迁移槽位；extra-action phase path 不增长普通 turn sequence、不派发普通 turn begin/end。具体 queue invalid policy 和 wave spawn 来源仍归后续阶段。

## 结构化验证证据

主验证：

```text
python3 -m simulator_v8_clean_core.tools.validate_p7_s9_explicit_turn_event_phase_machine --output-dir /tmp/p7_s9_main
```

结果：`ok=true`、`ready_for_review=true`、`rows=6`。

验证实际覆盖：

- 普通回合完整 phase path 精确等于 8 段预期；最终为 idle。
- `turn.begin=1`、`turn.end=1`；decision 明确报告 awaiting-decision 与 action-execution 合法下一阶段。
- 事件索引证明 `turn.begin < ModifierPhase1End lifecycle < decision opened < scheduler.action.before`。
- advance 与 submit 两个 transition 均 replay/source audit 通过，submit 为可信后继。
- extra-action phase path 为 `post_action → extra_action → action_execution → post_action`，turn sequence/owner 不变，普通 turn begin/end 均为 0。
- `idle → post_action` 非法迁移无 Mutation；idle 派发 turn.end 得到 `event_not_allowed_in_phase`、state unchanged。
- wave.monster 只有在 wave-transition ingress 后可进入 dispatcher；idle 下同事件被拒绝。
- 静态检查确认旧 turn-end flag 已移除，scheduler/decision/event dispatcher 都实际调用 phase admission。

输出：

- `/tmp/p7_s9_main/validation_summary_p7_s9_explicit_turn_event_phase_machine.json`
- `/tmp/p7_s9_main/p7_s9_turn_event_phase_matrix.json`
- `/tmp/p7_s9_main/p7_s9_turn_event_phase_evidence.json`

## 状态伤害直接回归

```text
nice -n 10 python3 -m simulator_v8_clean_core.tools.validate_p2_s8_status_damage --output-dir /tmp/p7_s9_p2s8_final
```

总结果：`ok=false`，不记为整体验证通过。

分层结果：

- `ordinary_dot_lifecycle.ok=true`：真实 TBGD OnPhase1 DoT case 存在；damage mutation/record、damage hit event、damage-before-duration、remaining duration、source frame、transition contract、replay、source audit 全部通过。
- `true_damage.ok=true`。
- `break_dot.ok=true` 仅表示 gap 被结构化记录且未合成 mutation；当前 `executable_break_damage_emission_count=0`、`runtime_linked=0`，不是 break-DoT 正例完成。
- `multi_dot.ok=false`：数据库/IR 有 multi source，但当前验证未找到完整 executable runtime case；保持 validation/payload gap。
- `status_damage_matrix.ok=false`：继承 break executable source count 为 0 等真实缺口。
- 旧验证 wrapper 已补显式 S1 outcome，普通 DoT/true damage 的 transition contract 从误失败恢复为 true；没有改宽 runtime 或断言。

## 轻量回归与资源情况

- P7-S1：`ok=true`。
- P7-S3：`ok=true`，9 cases。
- P7-S4：`ok=true`，11 ownership rows。
- P7-S5：`ok=true`，6 rows。
- P7-S6 runtime：query/submit、负例和 state unchanged 为 true。
- P7-S7：`ok=true`，6 rows、10 negatives。
- P7-S8：`ok=true`，6 rows。
- P7-S9：重跑 `ok=true`，6 rows。
- `compileall`：通过。
- `git diff --check`：通过。
- P2-S8 全量 lowering 低优先级串行，只写 `/tmp`；未运行 P1-5。

## 明确未做

- 未修速度变化、tie break、控制跳过和立即行动；归 P7-S10。
- 未完成 invalid queue entry 的取消/等待/前进保证；归 P7-S11。
- 未实现完整 wave spawn/cleanup 来源；归 P7-S17。
- 未把 P2-S8 的 multi/break source gap 伪装为 executable。
- 未修改 P7 checklist，未提交 Git 检查点。

## 统一验收反例修正补充

验收发现非法 `combat_phase` 曾静默回退 `idle`。现只有字段缺失/None 表示未初始化 idle；未知字符串或非字符串值在 operation/event/transition 三个入口均返回 `unknown_current_combat_phase`，不产生 mutation。

波次阶段 mutation 不再标为 `timeline_system`：scheduler 的 phase enter/exit 显式使用 `wave_system`，并携带 `wave_definition_id`、`wave_transition_plan` 与 `source_trace`。新增最小单波胜利反例直接验证 committed transition、两个 phase mutation、replay 和 source audit；S9 主验证修正后 `rows=7`、`ok=true`。S17 验证器也已把 source audit 加入 start/advance/complete 门禁，但本轮按资源约束未重跑其完整 lowering。

最终统一验收前已实际复跑 S17：复用同一真实 RuleBook，五行全部通过，start/advance/complete 的 replay/source audit 均为 true。因此上一段“未重跑 S17”的临时风险已消除；仍未运行无关 P4 聚合。
