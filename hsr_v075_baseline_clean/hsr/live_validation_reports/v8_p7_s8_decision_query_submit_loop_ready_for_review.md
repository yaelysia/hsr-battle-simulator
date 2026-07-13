# P7-S8 查询、决策与提交闭环待验收报告

状态：`ready_for_review=true`。本报告仅作为统一验收的证据索引，不宣告阶段完成，不修改 P7 checklist。

## 本阶段结果

- 新增 `DecisionSystem`、可序列化 `DecisionToken`、`CurrentDecision` 和 `DecisionAdvanceResult`，形成唯一的“推进到决策点—只读查询—token 绑定提交”接口。
- token 同时绑定完整 battle snapshot revision 与当前 choices 语义 revision；状态、行动者、窗口、动作、目标或资源集合变化都会使旧 token 失效。
- `current_decision` 只读取 `ActionAvailabilitySystem`，连续查询不改变 snapshot、event index 或 turn owner，且返回相同 token。
- `advance_to_decision` 只运行 `requires_scheduler_step` 的内部步骤，检测重复 state revision 和步数上限；到达 external/queued selectable 后停止，不替控制器选动作。
- scheduler 提交新增独立 `DecisionSubmissionAuthorization`。直接调用 `scheduler.step(state, command)` 会以 `decision_token_required` 阻断；外部 metadata/source 不能伪造授权。
- 修正 scheduler 已有活动决策时仍二次 `advance_to_next_turn` 的缺陷。token 提交直接作用于当前 turn owner，提交 transition 不再重复 `turn.begin`。
- `advance_to_next_turn` 在 turn begin 后通过 TimelineSystem 的显式 Mutation 打开 `turn_active` 决策窗口；不再依赖验证或 UI 手工写 global flag。
- TimelineSystem turn end 明确删除 `turn_owner_id` 与 `active_turn`，使一次提交真正消费一次决策。
- ally 与 enemy 共用 `DecisionSystem`。enemy fixed sequence 只以 `candidate_constraint_kind=forced_sequence` 限制 choices，selection controller 固定为 external，`enemy_ai_runtime_execution_admitted=false`。
- enemy command helper 不再把 auto impact group 写进命令，也不再标记 `source=ai`；aoe 等额外目标继续由 S7 target policy 派生。

## 结构化验证证据

主验证：

```text
python3 -m simulator_v8_clean_core.tools.validate_p7_s8_decision_query_submit_loop --output-dir /tmp/p7_s8_main_rerun
```

结果：`ok=true`、`ready_for_review=true`、`rows=6`。

验证实际覆盖：

- 查询幂等：相同状态连续查询的 snapshot、event index、availability 和 token 完全相同。
- ally round trip：idle 状态推进一次产生一个 turn begin 与一个可查询决策；查询暴露的每个 action/target 组合均可在同 token 下提交，replay/source audit 通过。
- 一次提交：提交 transition 内 `turn.begin` 数为 0，turn sequence 不二次增长，turn owner/active turn 被清除；下一次 advance 才增长一个 turn sequence 并产生下一决策。
- stale token：在后继状态提交旧 token，得到 `stale_decision_token`、blocked、state unchanged、zero mutation。
- bypass：直接 scheduler command 得到 `decision_token_required`、blocked、state unchanged、zero mutation。
- enemy round trip：通过同一个 DecisionSystem 查询/提交；choice 为 external，forced sequence 仅约束候选；提交 committed、cursor 只前进一次、replay/source audit 通过。
- 静态边界：scheduler 不调用 `command_from_candidate` 自动选敌方动作；token 由 full snapshot 与 choices digest 构成。

输出：

- `/tmp/p7_s8_main_rerun/validation_summary_p7_s8_decision_query_submit_loop.json`
- `/tmp/p7_s8_main_rerun/p7_s8_decision_query_submit_matrix.json`
- `/tmp/p7_s8_main_rerun/p7_s8_decision_query_submit_evidence.json`

## 真实来源直接回归

```text
nice -n 10 python3 -m simulator_v8_clean_core.tools.validate_v0_283 --output-dir /tmp/p7_s8_v0283_final
```

结果：`ok=true`。

- 验证场景先清除 builder 遗留的伪 active decision，再由 timeline 根据 action value 推进到真实 enemy。
- 真实 `UseSequencedSkill + AISkillSequence` 候选可生成，candidate event/record 为 process-only，不产生 combat mutation，来源审计和 replay 通过。
- 当前结构化选中的真实 monster action 存在完整 selected graph 缺口：PredicateTaskList、视觉任务和 audit-only damage 等节点未 executable。验证将该行诚实分类为 `implementation_missing`，并要求 ActionAvailability 不暴露 choice、cursor 不前进；未把“有 binding/damage emission”冒充完整可执行动作。
- 缺 card、缺 sequence、缺 action、complex AI、无合法目标均保持 blocked；queue priority 仍优先于自然 enemy 候选。

## 轻量回归与资源情况

- P7-S1：`ok=true`。
- P7-S3：`ok=true`，9 cases。
- P7-S4：`ok=true`，11 ownership rows。
- P7-S5：`ok=true`，6 rows。
- P7-S6 runtime query/submit：round trip、负例、state unchanged 均为 true。
- P7-S7：`ok=true`，6 rows、10 negatives。
- P7-S8：重跑 `ok=true`。
- `compileall`：通过。
- `git diff --check`：通过。
- `v0_283` 全量 lowering 低优先级串行，只写 `/tmp`；未运行 P1-5，未写完整 CanonicalIR。

## 明确未做

- 未建立完整 turn/pre-action/action/post-action/turn-end/wave 显式阶段机；归 P7-S9。
- S8 初始 evidence 曾记录 turn-end listener 的旧 runtime flag；该门已在 S9 改由显式阶段契约取代。
- 未实现 queue expiration/invalid-entry drain 策略；归 P7-S11。
- 未实现敌方 AI；固定序列只限制合法候选集合，选择仍由外部控制器完成。
- 未修改 P7 checklist，未提交 Git 检查点。

## 统一验收反例修正补充

验收发现调用者可公开构造 `DecisionSubmissionAuthorization` 绕过 decision token。现 decision authorization 由 `DecisionSystem` 在完成 token、snapshot revision、choice membership 校验后通过内核 issuer 签发，并带绑定全部 claims 的进程内 capability seal；scheduler 同时校验 seal 与当前 state revision。公开构造和篡改授权均 blocked/state unchanged。

新增伪造对象直调 scheduler 的反例，结果为 `decision_submission_authorization_not_issued`、零 mutation、state unchanged。S8 主验证修正后 `ok=true`。

S16 真实数据进一步修正敌方候选边界：复杂 AI policy 本身 blocked 不等于数据卡动作不可查询；当 `selection_controller=external` 时，ActionAvailability 逐项使用同一个 ActionContract 暴露已类型化且完整的卡片动作。只有 `candidate_constraint_admitted=true` 的真实 fixed sequence 才强制单一候选并推进 cursor。最终 `/tmp/p7_s8_final` 复跑 `ok=true`，真实 Svarog summon action 也经同一 DecisionToken 路径提交。
