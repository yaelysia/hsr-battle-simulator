# P9-A2-P3 / S8C WaitAnimState process-only barrier retirement

> 状态：`planned-revised-v2`
>
> 父阶段：`P9-A2 Route A predecessor chain`
>
> 固定基线：`master@eedebb406b85ab2611e8345b3fe7a75e9a7c53a0`
>
> 风险模式：`STRICT`
>
> 本文件是 PR16 当前唯一执行任务权威。它替代此前 FireProjectile P3 卡及本文件较早版本；EXEC 不得把旧卡范围、旧评论建议或后续 FireProjectile/S11 目标并入本卡。

## 0. 本次 replan：保留 canonical audit-only effect identity

EXEC 在当前实现和适用 CI 上证明了一个卡面契约错误：WaitAnimState 虽然是零 gameplay 语义的 `process_only` task，但正式 CanonicalIR/process-only contract **仍要求保留其唯一 audit-only EffectIR identity/reference**。

PLAN 独立复核当前 head 后确认：

- `rules/ir.py` 的 task-graph closure 以 `AbilityTaskIR.effect_id` 为 formal definition reference 真相；非空 `effect_id` 必须在对应 graph node 上恰好出现同一 effect reference，否则 CanonicalIR 拒绝 `task graph formal definition references are inconsistent`；
- `systems/ability_task_contract.py::_process_only_task_blocked_reason` 要求 process-only task 具有非空 `effect_id`，对应 EffectIR 必须存在、opcode/source 一致、`coverage_status=audit_only`，并携带 admitted `process_only_contract`；
- `systems/action_contract.py::_formal_action_task_graph_projection` 对 process-only task不把 unresolved graph definition reference 当 gameplay blocker；因此保留该 audit-only effect reference 不会把 WaitAnimState 恢复成 gameplay effect，也不会降低 A1 admission；
- 当前生产写集合已经足够，不需要修改 `rules/ir.py`、lowering、ability-task contract、action admission 或 runtime/schema。

所以本卡把旧文字“不得产生 effect definition reference”修正为：**必须保留 canonical 要求的 exactly-one audit-only process-only effect reference，但不得建立 executable/gameplay effect requirement。** 其余 Route-A success delta、写集合和 fail-closed 边界不变。

## 1. 重规划依据

PR14/P2 accepted Direct 的同 owner 普通外层 action `avatar_skill:100101@1` 上，`task_graph_control_requires_domains:hit_random_sequence` 不是单一 FireProjectile 来源，而有三个精确 provenance：

1. `OnStart[0]:WaitAnimState`
2. `OnStart[2]:WaitAnimState`
3. `OnStart[4]:FireProjectile`

pinned TBGD `14c1d18f91a8101d610e6c523447a7517de3fae1` 的 March 该 `FireProjectile` 没有 `MaxNumber`。项目永久规则禁止把缺失来源字段猜成 `1`；而同一 pinned revision 中存在显式 `MaxNumber: 1` 的 FireProjectile shape，因此当前没有证据可把 omission 解释成通用默认值。

同时，现有生产权威已经给出 WaitAnimState 的更窄事实：

- `tbgd/coverage.py` 明确把 `WaitAnimState` 列为 `PROCESS_ONLY_ABILITY_TASK_OPCODES`；
- `tbgd/lowering.py` 已按 source contract 校验 `AnimStateName + NormalizedTimeEnd`，合法 shape 以 `execution_mode=process_only`、`coverage_status=audit_only` 和同源 audit EffectIR 进入正式 CanonicalIR；
- `character_control_flow_contracts.py` 中 WaitAnimState 的已知字段责任均为 `presentation_excluded / excluded`；
- 但其 control role `presentation_barrier` 当前仍归 `p9_s8c`，而 `task_graph_materializer._node_status` 先处理 open downstream domain、后处理 `process_only`，导致这些已经被正式 lowering 判定为 process-only 的 presentation wait 仍被误记为 `hit_random_sequence` obligation；
- S8C 聚合契约明确规定：纯动画/帧/timeline wait 为 process-only，携带 settlement/window 语义的字段才形成 typed barrier。

因此 Route A 当前最早、可独立闭合的 authority 是 **WaitAnimState 已证明 process-only 的 presentation barrier retirement**。PR11 继续暂停。

## 2. 唯一目标

让正式 task-graph projection 对**已经由现有 lowering/source contract 证明为 process-only 且仅含 presentation-excluded 责任的 WaitAnimState source shape**停止产生 `hit_random_sequence` obligation，并将其作为零 gameplay 语义的 process-only leaf materialize。

本卡不改变 WaitAnimState 的 lowering 分类，不模拟动画时间，不创建 timeline/barrier runtime，不改变任何 committed state/event/RNG/settlement/replay 规则。

完成后必须同时成立：

1. 合法 WaitAnimState 仍由 raw source -> control-flow node -> AbilityTaskIR -> audit-only EffectIR -> formal task graph 的既有 identity 链决定；不得按角色、技能、文件、ID、hash 白名单。
2. 只有 `execution_mode=process_only`、source contract 未 blocked、control family 精确为 WaitAnimState、且 control node 没有 gameplay field owner/child branch/termination obligation 的 shape 可以退休 S8C barrier obligation。
3. 这些节点 materialize 为 process-only leaf，并保留 **exactly one** 与 `task.effect_id` 一致的 `reference_kind=effect` formal reference；该 reference 只指向现有同源 `coverage_status=audit_only` process-only EffectIR，不得成为 executable/gameplay effect requirement。
4. 除上述 audit-only effect identity reference 外，节点不得新增 condition/target/gameplay numeric/ability/template gameplay requirement；不得产生 mutation/event/RNG/settlement/replay mutation record。
5. 任何未来或当前 shape 若出现非 presentation-excluded 字段责任、child graph、gameplay termination、source contract blocked，必须继续 fail-closed/deferred；不得被 family 名称一刀切放行。
6. `WaitSecond`、`WaitFrame`、`WaitTimelineFinish`、`WaitCustomString`、其它 barrier family 不因本卡自动改变 disposition。
7. `DamagePerformFinish` / `SkillPerformFinish` 的 S11 settlement barrier 不能因其 `execution_mode=process_only` 被放行。
8. FireProjectile 的 `hit_random_sequence`、`unsupported:FireProjectile`、`effect:unsupported` blocker 必须原样保留；本卡不推断缺失 `MaxNumber`。

## 3. 唯一生产权威与正式消费者

### 3.1 唯一生产改动

本卡唯一生产写路径：

- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py`

允许的生产语义仍只包括：

- 在 `_node_status` 邻近的 source-backed gate 中，先识别**已由正式 source/lowering 事实证明的 WaitAnimState process-only presentation-only shape**，使其 materialize 为现有 leaf contract；
- 在 source disposition 回写时只退休这些已 materialized WaitAnimState control node 的 `hit_random_sequence` obligation；
- 保留普通 `_references` 契约为该 process-only task生成 canonical 所要求的唯一 audit-only effect reference；不得为 WaitAnimState 特判 suppress `task.effect_id` 对应的 formal reference。

不得通过把全部 `process_only` 提前返回 materialized 来实现；那会错误越过 S11 settlement barrier。不得修改 `_OWNER_DOMAIN_BY_STAGE` 把整个 `p9_s8c` 或 `presentation_barrier` 视为 closed。

### 3.2 只读事实源/消费者

以下路径只读：

- `tbgd/coverage.py`
- `tbgd/lowering.py`
- `tbgd/character_control_flow_contracts.py`
- `rules/ir.py`
- `rules/control_flow_contract.py`
- `rules/task_graph.py`
- `systems/task_graph.py`
- `systems/ability.py`
- `systems/action_contract.py`
- `systems/ability_task_contract.py`

如果正确实现需要修改这些文件中的任一正式语义，或需要新增 runtime timer/barrier/timeline consumer，立即 `NEEDS_REPLAN`；不得扩大权限。

## 4. 允许写集合

### 生产

1. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py`

### 聚焦测试 / Direct evidence

2. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_p9_a2_p3_wait_anim_state_process_only_barrier_retirement.py`
3. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p3_wait_anim_state_process_only_barrier_retirement.py`
4. `hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2-P3_S8C_WAIT_ANIM_STATE_PROCESS_ONLY_BARRIER_RETIREMENT_execution_report.md`

本执行卡由 PLAN 提交，EXEC 不得修改本卡。

## 5. STRICT source-shape denominator

Direct 必须从当前 formal ability denominator 枚举 WaitAnimState source occurrences，并按 source/control/lowering 事实分组，不得以 March 作为固定答案。

每个 admitted occurrence 至少证明：

- raw family = `WaitAnimState`；
- lowering `execution_mode=process_only` 且 source contract 未 blocked；
- AbilityTaskIR 具有非空 `effect_id`，对应 EffectIR opcode/source 与 task 一致、`coverage_status=audit_only` 且 process-only source contract admitted；
- control role = `presentation_barrier`；
- 当前字段责任全部是 `presentation_excluded` 且 owner=`excluded`；
- 无 gameplay child branch；
- 无 gameplay termination/numeric obligation；
- formal source path/content fingerprint/json path 与 control node、AbilityTaskIR、EffectIR、TaskGraphNodeIR 双向一致；
- graph node 恰好保留一个指向上述 `task.effect_id` 的 audit-only effect reference。

出现任何不满足上述不变量的 WaitAnimState occurrence，不得静默 admission；报告其精确 disposition/reason。分母为空不能算通过。

## 6. 生产不变量与最小反例

### 6.1 不得全局放行 process-only

**反例**：`DamagePerformFinish` 或 `SkillPerformFinish` 仍必须保留 `damage_heal_shield` owner obligation；若因本卡 materialized，测试失败。

### 6.2 不得全局关闭 presentation_barrier

**反例**：至少核一条非 WaitAnimState barrier/presentation family，其 disposition 与基线一致。本卡不能通过修改 role owner/domain 映射把 sibling 一起关闭。

### 6.3 source contract 必须继续 fail-closed

**反例**：缺 `AnimStateName` 或 `NormalizedTimeEnd` 的 WaitAnimState，lowering 已标 blocked 的 process-only task，或 effect/source/process-only contract identity 不一致的 task，不得因 task-graph gate 被升级为 materialized。

### 6.4 gameplay shape 不得借 presentation 规则穿透

**反例**：若 synthetic control fixture 给 WaitAnimState 增加非 `presentation_excluded/excluded` field responsibility、child branch 或 gameplay termination，必须 deferred/blocked。

### 6.5 audit identity reference 不等于 gameplay execution

WaitAnimState materialized node必须保留 exactly-one `effect` formal reference，与 `task.effect_id` 及同源 audit-only EffectIR 一致；该 reference 可以保持其真实 audit-only/deferred definition disposition，但不得被 action admission 当作 process-only gameplay blocker，也不得产生 effect execution、mutation、event、RNG、settlement 或 replay mutation record。

**反例**：零 effect reference 必须被 CanonicalIR invariant 拒绝；两个/错误 effect reference、指向 executable/错 source/错 opcode effect，或新增其它 gameplay definition reference，也必须失败。

### 6.6 zero gameplay leakage

真实 outer action 仍会因后续 FireProjectile/S11 blocker fail-closed，before/after state 与 formal mutation/event/RNG/settlement/replay channels 保持零泄漏。本卡只退休 WaitAnimState 的错误 S8C topology obligation，不把 audit evidence 转成 runtime 行为。

## 7. Fast

从仓库根目录串行运行：

```bash
python -m pytest hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_p9_a2_p3_wait_anim_state_process_only_barrier_retirement.py -q
python -m compileall -q hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_p9_a2_p3_wait_anim_state_process_only_barrier_retirement.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p3_wait_anim_state_process_only_barrier_retirement.py
git diff --check eedebb406b85ab2611e8345b3fe7a75e9a7c53a0...HEAD
```

聚焦 pytest 至少覆盖：

1. valid WaitAnimState -> materialized process-only leaf + exactly-one audit-only effect reference；
2. March/P2 同形两个 WaitAnimState 均不再贡献 S8C domain；
3. source-contract/effect-identity blocked WaitAnimState negative；
4. gameplay field/branch/termination negative；
5. non-WaitAnimState presentation/barrier sibling isolation；
6. DamagePerformFinish/SkillPerformFinish S11 isolation；
7. source identity / canonical round-trip 稳定；
8. zero/multiple/wrong effect reference 不能通过 formal CanonicalIR closure。

## 8. 必须运行的真实 Direct

运行：

```bash
python hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p3_wait_anim_state_process_only_barrier_retirement.py
```

validator 必须复用现有 production builders/materializer/CanonicalIR/RuleBook/正式 action admission；不得重写 action、task graph、process-only 或 barrier 语义。

### 8.1 WaitAnimState denominator

报告 formal ability denominator 中 WaitAnimState occurrence 总数、admitted/blocked 分组，并证明 admitted 集满足第 5 节全部 source-shape 与 audit-reference 不变量。

### 8.2 PR14 同一真实 action provenance delta

复用 PR14 的生产构建链与同 owner 普通 action 选择规则，不硬编码 actor/action/file/hash 作为通过条件。

对 PR14 当前真实 action，基线 `hit_random_sequence` provenance 为：

- WaitAnimState × 2
- FireProjectile × 1

P3 完成后必须精确变为：

- WaitAnimState × 0
- FireProjectile × 1

因此顶层 blocker reason `task_graph_control_requires_domains:hit_random_sequence` **预期仍存在**；本卡验收的是 provenance 由 3 个 source obligations 降为 1 个，不得把 reason 仍存在误判为失败，也不得为消 reason 顺带实现 FireProjectile。

同时必须原样保留：

- `effect_coverage_status:unsupported:FireProjectile`
- `task_graph_definition_not_admitted:effect:unsupported`
- `task_graph_definition_not_admitted:effect:audit_only`
- `task_graph_control_requires_domains:damage_heal_shield`

### 8.3 formal node、audit reference 与 fail-closed boundary

证明两个真实 WaitAnimState 节点已成为 materialized process-only leaf，并且：

- 每个 node 恰好有一个 `reference_kind=effect`，definition id 等于对应 `AbilityTaskIR.effect_id`；
- 对应 EffectIR 为同源、同 opcode、`coverage_status=audit_only`、process-only contract admitted；
- node 不具有 condition/target/gameplay numeric/ability gameplay reference；
- action admission 不因该 audit-only process-only effect reference新增 blocker；
- 同一 outer action 仍在 FireProjectile/S11 authority 处 fail-closed，state unchanged，mutation/event/RNG/settlement/replay channel 无泄漏。

### 8.4 适用历史门回归

除本卡 Fast/Direct 外，final head 必须通过实际触发的现有 formal-action/S8C1B/S8C1C 适用门。若旧门仍失败，先读完整日志；同一 canonical reference invariant 根因必须一次收敛，不得通过降低旧门或跳过 real Direct 解决。

## 9. 非目标 / deferred

本卡明确不做：

- 不修改 CanonicalIR reference invariant；
- 不修改 process-only EffectIR/lowering/runtime contract；
- 不实现或准入 FireProjectile；
- 不推断 omitted `MaxNumber == 1`；
- 不研究/实现 projectile physics、flight time、collision；
- 不闭合 WaitSecond/WaitFrame/WaitTimelineFinish/WaitCustomString；
- 不实现真正 settlement/window barrier；
- 不改 S11 damage/heal/shield；
- 不恢复 PR11；
- 不启动 PR9。

FireProjectile 与其它 S8C sibling 必须在本卡 accepted+merged 后，由下一 PLAN 从最新 merged master 重新归因，不能在本卡预先批准后续实现。

## 10. 资源预算

- Fast + Direct 目标总墙钟 `< 8 min`；
- 单进程峰值 RSS 目标 `< 3 GiB`；
- evidence 默认写 `/tmp`，只提交精简 execution report；
- 不跑 full suite，不新建环境/依赖/workflow/cache；
- CI 失败先读完整日志并合并同根因修复，不围绕首个错误反复触发完整 CI。

## 11. stop conditions

出现任一情况立即 `NEEDS_REPLAN`：

1. WaitAnimState 的真实 admitted shape出现 gameplay field owner、child graph、gameplay termination 或不可忽略的 settlement/window 语义；
2. 必须修改 lowering/coverage/control-flow source authority才能判定 process-only；
3. 必须修改 `rules/ir.py` canonical reference invariant、task-graph schema、TaskGraphExecutor、AbilityTaskSystem、ability-task process-only contract、action admission 或 committed-state/runtime authority；
4. 正确实现需要把 audit-only process-only EffectIR/reference升级为 executable，或无法在现有 process-only admission下保留唯一 audit reference；
5. 修复必须同时关闭 WaitSecond/其它 barrier family、FireProjectile 或 S11；
6. 只能用固定 actor/action/source file/hash 才能让 Direct 通过；
7. 首次集中自审发现三个以上新的系统性问题类别。

只有真实 GitHub 权限、pinned source 不可读或既有环境不可用等外部问题才 `BLOCKED`。普通实现/测试/CI问题由 EXEC 在本卡范围内自行处理。

## 12. ready_for_review 交付

EXEC 完成后在 PR16 留：

- `[HANDOFF:REVIEW]`
- `role=EXEC`
- `status=ready_for_review`
- `stage=P9-A2-P3`
- `dispatch_id=<正式 EXEC dispatch id>`
- `final_head=<实际 40 SHA>`
- `fast=<命令/exit code>`
- `direct=<validator exit code + WaitAnimState provenance 2->0, total hit_random_sequence provenance 3->1>`
- `audit_reference=<WaitAnimState exactly-one audit-only effect reference closure>`
- `denominator=<WaitAnimState source-shape total/admitted/blocked>`
- `remaining=<FireProjectile hit_random_sequence + unsupported blockers; S11 audit_only + damage_heal_shield; PR11 paused>`
- `next=REVIEW`

execution report 必须写实际 head、passed/skipped/not-run 和残余风险。EXEC 不勾总 checklist、不合并、不恢复 PR11、不启动 FireProjectile/S11/下一卡。

## 13. REVIEW 验收边界

REVIEW 必须独立核对：

- production diff 仅修改 task-graph materializer 的 WaitAnimState process-only presentation shape gate/disposition，并保留普通 canonical effect-reference closure；
- WaitAnimState node 恰好保留一个同 `task.effect_id` 的 audit-only effect reference，且没有被升级为 executable/gameplay requirement；
- 没有把全部 process-only 或整个 presentation_barrier/p9_s8c domain 标 closed；
- denominator 与 Direct 不是固定 March 夹具；
- PR14 真实 provenance 精确为 WaitAnimState 2->0、FireProjectile 1->1；
- FireProjectile 三个上游 blocker口径与 S11 两个 blocker均未被本卡错误消除；
- blocked outer action state/channel 仍零泄漏；
- final head 本卡 Fast/Direct 与实际触发的 formal-action/S8C1B/S8C1C CI 一致。

通过后只接受 P3。P3 合并后由下一 PLAN 从最新 merged master 重新归因；只有剩余前置链为空才恢复 PR11。
