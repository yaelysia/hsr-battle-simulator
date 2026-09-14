# P9-A2-P4 SetEntityVisible formal ability-task presentation retirement

> 状态：`planned-revised-v2`
>
> 父阶段：`P9-A2 Route A predecessor chain`
>
> 固定基线：`master@4beebe293f74e37e709d5cfc978f098d1e804128`
>
> pinned TBGD：`14c1d18f91a8101d610e6c523447a7517de3fae1`
>
> 风险模式：`STRICT`

本文件是 PR17 当前唯一执行卡。旧卡错误地要求全部 raw `SetEntityVisible` occurrence 都必须对应 `AbilityTaskIR`。修订后仍保留完整 raw/source-scope denominator，但按真实 formal producer 分类；本卡只闭合 PR11 外层 A1 gate 实际触达的 **formal ability-task producer**。

## 1. Replan 事实

head `af2ff8843c6b253bcd19a461395a0ccf8b9095c5` 的 Direct run `34727024041` 已排除 task fingerprint、audit-reference 比较和候选扫描等 validator 假阳性，仍有 `10` 条 selected presentation-only `SetEntityVisible` 没有对应 `canonical.ability_tasks`：

- `9` 条位于 `Modifiers` / `GlobalModifiers` status-callback 子树；production 路径是 `_lower_status_callback_task_tree(...) -> StatusCallbackTaskIR`，不是 AbilityTask producer；
- `1` 条真实样本位于 `Avatar_Feixiao_00_Ability.json::$.GlobalTemplates[13].TaskList[0]`，属于 template definition 来源；source-scope 选中不等于必须独立生成 AbilityTask；
- `task_graph_materializer._status_task(StatusCallbackTaskIR)` 当前独立决定 status formal task execution mode。把 status callback 也并入本卡会形成第二 formal authority，违反单卡单 authority。

因此不能删除这 10 条，也不能强行把它们改成 AbilityTask。Direct 必须完整记账并区分 producer kind。

## 2. 唯一目标

仅让已有 formal AbilityTask producer、且 source-scope 已证明为 `presentation_only` 的 `SetEntityVisible` 进入现有 process-only ability-task contract：

```text
raw SetEntityVisible
 -> presentation_only scope
 -> AbilityTaskIR(execution_mode=process_only)
 -> exactly-one same-source audit-only EffectIR
 -> existing formal ability task graph leaf
```

只保留审计 identity，不执行可见性、模型、目标或任何 gameplay mutation。

完成条件：

1. ability-task slice 不再产生 `effect_coverage_status:unsupported:SetEntityVisible`；
2. 这些 exact occurrence 的 unsupported effect-definition provenance 从真实 same-owner A1 blocker 中消失；
3. task/effect source、opcode、effect-id 与 process-only contract保持严格一致；
4. status-callback 与 template occurrence仍在完整 denominator 中并被精确归因，但本卡不修改其 formal semantics；
5. `SetEntityForceVisible`、其它 presentation family、S11、其它 S8C、PR11 runtime、PR9 RNG 均不改变；
6. outer action 可继续因后续真实 blocker fail-closed。

## 3. 唯一生产 authority

只允许修改既有 **formal AbilityTask process-only source contract**：

- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/coverage.py`
  - `PROCESS_ONLY_ABILITY_TASK_OPCODES`
  - `ability_task_execution_mode(...)`
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py`
  - `_PROCESS_ONLY_TASK_FIELD_TYPES`
  - `_process_only_ability_task_source_blocked_reason(...)`
  - generic `_lower_ability_task_tree(...)` process-only projection

必须复用现有 generic path；禁止角色/技能/action/文件/hash 白名单和第二套 presentation lowering。

以下正式语义只读：`character_ability_scope.py`、`character_control_flow_contracts.py`、`task_graph_materializer.py`、`rules/**`、`systems/ability_task_contract.py`、`systems/action_contract.py`、`systems/task_graph.py`、`core/executor.py`、PR11/PR9 未合并业务代码。

Status callback process-only formal semantics 是后续独立 authority；P4 不修改 `StatusCallbackTaskIR`、`_lower_status_callback_task_tree` 的公共语义或 `_status_task(...)` execution mode。

## 4. 允许写集合

生产：

1. `tbgd/coverage.py`
2. `tbgd/lowering.py`

验证/报告：

3. `tests/test_p9_a2_p4_set_entity_visible_process_only_retirement.py`
4. `tools/validate_p9_a2_p4_set_entity_visible_process_only_retirement.py`
5. `../live_validation_reports/P9-A2-P4_SET_ENTITY_VISIBLE_PROCESS_ONLY_RETIREMENT_execution_report.md`
6. `.github/workflows/p9-a2-p4-pr-validation.yml`

本卡由 PLAN 提交，EXEC 不修改本卡。已有 production/validator/workflow 成果不回退重做；按修订契约继续最小提交。

## 5. STRICT denominator：完整保留并分账

Direct 从 pinned TBGD + production source-scope 动态枚举全部 selected `SetEntityVisible`。历史数量和本次 `10` 条只作证据，不硬编码。

每个 occurrence 必须恰好归入一类：

### A. `formal_ability_task`

exact source path + JSON path 对应 `AbilityTaskIR`。本卡要求该类全部满足：

- scope=`presentation_only`；
- `execution_mode=process_only`；
- explicit source schema admitted；
- 非空 `effect_id`；
- exactly-one own EffectIR，source/opcode/effect identity一致；
- EffectIR=`audit_only`；
- formal ability graph只保留 canonical audit reference，不执行 gameplay effect。

### B. `formal_status_callback_task`

raw occurrence 位于正式 status callback subtree，且能 exact 对应 `StatusCallbackTaskIR`/status formal ledger。记录 callback/task/event/coverage/blocker/task-graph disposition，并标记 `deferred_status_callback_formal_authority`。不得改成 AbilityTask，不得修改 materializer。

### C. `template_definition_no_formal_producer`

对 `GlobalTemplates` / `TaskListTemplate` / global template occurrence，必须用现有 template definition/reference ledger fresh attribution：

- 无正式 ability/status consumer：记录 `no_formal_producer`，不得 synthetic 生成 task；
- 有正式 reference：继续追踪 production expansion。若能形成 exact AbilityTask/StatusCallbackTask，转入 A/B；若有正式 reference 却缺 formal expansion，`NEEDS_REPLAN`，不得假装 no-producer。

run `34727024041` 暴露的 Feixiao GlobalTemplate occurrence 必须动态经过此规则，不写文件特例。

### D. `blocked_or_unresolved`

source fingerprint、scope、producer identity或字段 shape 无法解释时进入 D 并使 Direct 失败。

必须断言：

```text
total_selected == A + B + C + D
```

D 必须为空；B/C 可以非空但必须证据闭合。不能把 B/C 从 denominator 删除。

## 6. Fast

串行运行：

```bash
python -m pytest hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_p9_a2_p4_set_entity_visible_process_only_retirement.py -q
python -m compileall -q \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/coverage.py \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_p9_a2_p4_set_entity_visible_process_only_retirement.py \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p4_set_entity_visible_process_only_retirement.py
PYTHONPATH=hsr_v075_baseline_clean/hsr python -B -m simulator_v8_clean_core.tools.validate_p9_formal_action_graph_admission_authority --fast
git diff --check 4beebe293f74e37e709d5cfc978f098d1e804128...HEAD
```

focused test 至少覆盖：ability positive；`TargetType/UniqueKey/Visible` strict schema；unknown/wrong-type/source mismatch negatives；`SetEntityForceVisible` unchanged；task/effect identity；status callback 不误判为 missing AbilityTask；template no-producer与referenced-template-gap反例；零 graph execution/condition/RNG/state side effect。

此前 relay `25 passed`、compileall `0`、diff-check `0` 仅算中间证据，最终以修订卡后的 committed head 为准。

## 7. 真实 Direct

```bash
python hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p4_set_entity_visible_process_only_retirement.py --direct
```

必须使用 pinned TBGD 与 production source-scope/lowering/control-flow/template/materializer/CanonicalIR/RuleBook/A1 ActionContract；不得用 synthetic CanonicalIR 或 PR11 未合并实现。

Direct 必须证明：

1. A/B/C/D 完整恒等式成立且 D=0；
2. A 非空且全部通过 process-only/audit identity；
3. B（若非空）exact 归因且 production semantics 未被本卡修改；
4. C 完成 template reference/producer attribution；有 formal reference 却缺 expansion 必须失败；
5. same-owner action/window/action candidate动态发现，不以角色名/action id白名单；
6. 至少一条真实 same-owner outer action 不再含 A 类造成的 `unsupported:SetEntityVisible` / corresponding unsupported effect-definition provenance；
7. P3 WaitAnimState retirement不回退；S11和其它非本卡 blocker保持；outer action不要求 executable；
8. RNG/mutation/event/settlement/replay 零泄漏。

推荐 Direct：wall `<300s`、peak RSS `<2GiB`；超预算优化枚举，不缩 denominator。

## 8. CI / 报告 / 完成

最终 workflow：`ubuntu-latest`、`contents: read`、exact PR head、`persist-credentials:false`、recursive pinned submodule；运行 scoped compile、focused Fast、A1 Fast、P4 Direct、fixed-base diff check。禁止 workflow 临时 patch validator 后把结果当最终门禁；diagnostic runner patch必须固化到 committed head。

execution report 记录 final production diff、A/B/C/D 计数与样本、GlobalTemplate attribution、same-owner blocker delta、Fast/Direct/CI exact-head evidence和残余 authority。

`ready_for_review` 仅当：生产只改本卡 authority；A/B/C/D穷尽且D=0；A全部闭合；B未越权；C均正确归因；same-owner A1 delta成立；P3/A1不回退；S11等保留；final-head Fast/Direct/CI通过；报告已提交并留 `[HANDOFF:REVIEW]`。

`NEEDS_REPLAN`：A 类仍需 materializer/public IR/A1/runtime；C 类有正式 reference 却缺 formal expansion；出现未归类 occurrence；same-owner blocker delta不能由当前 ability authority解释；实际触达第二独立 gameplay authority。

`NEEDS_DECISION`：只有确需改变公开语义/authority、采用来源无法证明的默认值、增加依赖/权限/付费资源时使用。

## 9. 后续顺序

P4 accepted+merged 后 PLAN 从新 master 重算 PR11 same-owner outer-action blocker。B 类 status-callback authority虽已登记，但不会仅因存在就自动成为下一 predecessor；只有 fresh attribution 证明其在 PR11/A2 前形成真实 blocker时才单独规划。若有其它更早 blocker，只拆最早一个。predecessor chain 为空后恢复 PR11 原实现和真实 `CombatExecutor.execute(ActionCommand)` Direct；PR9 继续等待 PR11。P4 不宣告 P9 COMPLETE。
