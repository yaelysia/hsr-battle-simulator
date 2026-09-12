# P9-A2-P4 SetEntityVisible process-only presentation retirement

> 状态：`planned`
>
> 父阶段：`P9-A2 Route A predecessor chain`
>
> 固定基线：`master@4beebe293f74e37e709d5cfc978f098d1e804128`
>
> pinned TBGD：`14c1d18f91a8101d610e6c523447a7517de3fae1`
>
> 风险模式：`STRICT`
>
> 本卡是 PR11/A2 前的单一 authority predecessor。只处理 `SetEntityVisible` 已有 presentation-only 来源事实到 process-only formal task 的缺失投影；不得顺手实现 S11、FireProjectile/其它 S8C、PR11/A2 runtime 或 PR9 RNG caller。

## 1. Fresh merged-master 归因

PR16 / A2-P3 已验收合并，生产 merge 为 `dae1441e3227b3c0ab86cb4ca847368594832c1b`，随后 governance checkpoint 把 `master` 推进到本卡固定基线 `4beebe293f74e37e709d5cfc978f098d1e804128`。P3 已把 source-proven `WaitAnimState` presentation barrier 从错误的 `hit_random_sequence` obligation 中退休；PR11 仍必须保留原 Fast 与真实 `CombatExecutor.execute(ActionCommand)` Direct，不能通过降低 A1 formal admission 来绕过前置。

PR11 已证明真实 action-window status owner 是 Silver Wolf / avatar `1006`，可用 ordinary outer producer 至少包括 basic `avatar_skill:1100601@1` 与 skill `avatar_skill:1100602@1`。重新核 pinned source 的 basic ability chain：

- `Avatar_Advanced_Silwolf_00_Skill01_Phase01` 含多个已由 P3 处理的 `WaitAnimState`；
- 同一 phase 含两个 `RPG.GameCore.SetEntityVisible` occurrence；
- 其 nested `...Skill01_Phase02` 为伤害节点及 `DamagePerformFinish` / `SkillPerformFinish`，后者属于后续 S11 settlement authority；
- 该 basic chain 没有 FireProjectile/RandomConfig，因此 P3 后不应再靠该 action 产生 WaitAnimState 的 `hit_random_sequence` provenance。

更关键的是，当前权威范围账本 `CHARACTER_ABILITY_SCOPE_LEDGER.md` 对 `SetEntityVisible` 的完整扫描结果为 **233 occurrences / 30 files，effective scope 233/233 全部 `presentation_only`**。但当前生产：

- `tbgd/coverage.py::PROCESS_ONLY_ABILITY_TASK_OPCODES` / `ability_task_execution_mode(...)` 未包含 `SetEntityVisible`；
- `tbgd/lowering.py::_lower_ability_task_tree(...)` 因而把该 family 当 runtime effect，并经现有 effect coverage 路径得到 `unsupported`；
- PR11 旧真实 blocker provenance 已实际出现 `effect_coverage_status:unsupported:SetEntityVisible` 与对应 `task_graph_definition_not_admitted:effect:unsupported`；
- P1/P2/P3 分别只闭合 process-only source identity、process-only TriggerAbility admission identity、WaitAnimState task-graph obligation，没有把 `SetEntityVisible` 改成 gameplay semantics。

因此当前最早、可独立于 S11/A2 闭合的缺口是：**已证明 presentation-only 的 SetEntityVisible family 没有进入现有 process-only ability-task source contract。**

若 EXEC 的 fixed-base Direct 不能复现这一归因，或发现任何当前有效 `SetEntityVisible` occurrence 的 effective scope 不是 `presentation_only`，立即 `NEEDS_REPLAN`；不得为了满足卡面强行放行。

## 2. 唯一目标

让 raw/source-scope 已证明为 presentation-only 的 `SetEntityVisible` occurrence 通过现有 process-only ability-task contract 进入正式 CanonicalIR：

`raw SetEntityVisible -> source-backed AbilityTaskIR(execution_mode=process_only) -> exactly-one same-source audit-only EffectIR -> formal task graph process-only leaf`

该投影只保留审计 identity；它不执行可见性、模型、目标或任何 gameplay mutation。

完成后必须同时成立：

1. `SetEntityVisible` 的合法 source shape 不再产生 `effect_coverage_status:unsupported:SetEntityVisible`。
2. 与这些 occurrence 一一对应的 unsupported effect-definition blocker 不再进入 A1 outer-action blocker provenance。
3. 其 AbilityTaskIR/EffectIR 继续满足现有 process-only exact source/opcode/effect identity 契约。
4. 任何未知字段、错误字段类型、source-scope 非 presentation-only、source identity 不一致都继续 fail-closed。
5. 不把任何 sibling family（包括 `SetEntityForceVisible`、其它 presentation opcode）随本卡自动准入。
6. 不关闭/绕过 S11 `damage_heal_shield`、settlement barrier 或其它真实 blocker；outer action 本卡完成后仍可合法 fail-closed。

## 3. 唯一生产 authority 与正式消费者

### 3.1 单一语义 authority：process-only ability-task source contract

该 authority 当前由两个紧耦合 production surface 共同表达，二者不是两个独立机制：

1. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/coverage.py`
   - `PROCESS_ONLY_ABILITY_TASK_OPCODES`
   - `ability_task_execution_mode(...)`
2. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py`
   - `_PROCESS_ONLY_TASK_FIELD_TYPES`
   - `_process_only_ability_task_source_blocked_reason(...)`
   - 既有 `_lower_ability_task_tree(...)` generic process-only projection

实现必须复用现有 generic process-only 路径，只增加 `SetEntityVisible` 的 source-backed classification/schema；禁止新建第二套 presentation lowering、角色/技能/文件白名单或 runtime handler。

### 3.2 只读 authority / consumer

以下正式语义只读：

- `tbgd/character_ability_scope.py`
- `tbgd/character_control_flow_contracts.py`
- `tbgd/task_graph_materializer.py`
- `rules/ir.py`
- `rules/task_graph.py`
- `systems/ability_task_contract.py`
- `systems/action_contract.py`
- `systems/task_graph.py`
- `core/executor.py`
- PR11 的 `systems/event_dispatch.py` / `systems/status_callbacks.py` / `systems/ability.py` 未合并实现

如果正确闭合需要修改上述任一正式语义、改变 public IR/equality、task-graph materialization、A1 ActionContract、runtime state/event/RNG/settlement/replay 或 PR11/PR9 代码，返回 `NEEDS_REPLAN`；若需要新的产品语义、公共接口、依赖、权限或付费资源，返回 `NEEDS_DECISION`。

## 4. 允许写集合与提交粒度

### 生产

1. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/coverage.py`
2. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py`

### 聚焦验证 / 报告

3. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_p9_a2_p4_set_entity_visible_process_only_retirement.py`
4. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p4_set_entity_visible_process_only_retirement.py`
5. `hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2-P4_SET_ENTITY_VISIBLE_PROCESS_ONLY_RETIREMENT_execution_report.md`
6. `.github/workflows/p9-a2-p4-pr-validation.yml`

本执行卡由 PLAN 提交，EXEC 不得修改本卡。

不要求一次完成全部允许文件才提交。形成最小可编译 production + focused test 纵切后即可提交；validator、workflow、report 可按实际验证闭环继续追加最小提交。不得以“报告尚未写完”作为不提交已完成最小纵切的理由。

## 5. Source-shape denominator

Direct 必须从 pinned TBGD + 当前 production source-scope projection 动态枚举正式角色 ability denominator 中全部 `SetEntityVisible` occurrence；静态账本的 233/233 是规划依据，不是测试硬编码答案。

对每个可准入 occurrence 至少证明：

- raw family 精确为 `SetEntityVisible`；
- current effective scope 为 `presentation_only`；
- source path、JSON path、content fingerprint 可回到 exact pinned raw occurrence；
- 实际字段集合/字段类型由 raw denominator 枚举并进入显式 process-only source schema；不得把未知字段吞掉；
- `TargetType`、`Visible` 等字段只作为 presentation source-shape evidence，不建立 gameplay target/mutation semantics；
- AbilityTaskIR `execution_mode=process_only`，source contract admitted；
- task 有非空 `effect_id`，exactly one EffectIR 与 task opcode/source/effect_id 对齐，`coverage_status=audit_only`，process-only contract admitted；
- formal graph 仍保留 canonical 要求的 exactly-one audit-only effect reference，但该 reference 不成为 gameplay execution requirement。

若 denominator 出现 source-scope 非 presentation-only、无法解释的字段形状或来源指纹不闭合，只阻断该 shape 并报告；若无法在本卡 authority 内安全分组，`NEEDS_REPLAN`。

## 6. 必须保留的 fail-closed 不变量

### 6.1 不能用 family 名称覆盖来源事实

合法 positive 必须由 pinned raw occurrence + source-scope + explicit source schema共同证明。synthetic `SetEntityVisible` 若携带未声明字段、错误类型或 source identity 不一致，必须 blocked。

### 6.2 不能扩大 presentation admission

`SetEntityForceVisible`、`SetEntityPosition`、其它 visibility/model/presentation sibling 不因本卡改变 execution mode。若以后需要闭合，fresh attribution 后另卡规划。

### 6.3 audit identity 不等于 gameplay execution

process-only `SetEntityVisible` 必须保留同源 audit-only EffectIR/reference，且不得调用 task-graph effect execution、condition evaluation、gameplay RNG、mutation reducer、event commit、settlement 或 replay mutation。

### 6.4 A1 与后续 blocker 不降低

本卡不得修改 `ActionContractSystem` 或 `ability_task_runtime_blocked_reason(...)`。真实 same-owner outer action 的 SetEntityVisible-specific unsupported provenance消失后，S11 `task_graph_control_requires_domains:damage_heal_shield`、其 settlement/effect blocker及任何其它非本卡 blocker必须继续 fail-closed。

### 6.5 P3 retirement 不回退

Silver Wolf basic 的 `WaitAnimState` 不得重新贡献 `hit_random_sequence`；本卡不得改 `task_graph_materializer.py` 或 P3 source disposition。

## 7. Fast

从仓库根目录串行运行：

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

focused test 至少覆盖：

1. source-backed `SetEntityVisible` accepted shape -> process-only task + audit-only own effect；
2. optional/实际字段形状按 denominator 允许，不猜测缺失字段含义；
3. unknown field / wrong type / source mismatch fail-closed；
4. non-SetEntityVisible sibling execution mode不变；
5. exact task/effect source/opcode/effect-id identity；
6. A1 process-only consumer正例及 mismatch negative；
7. 无 task graph execution / condition / RNG / committed state side effect。

Fast 目标：focused pytest + scoped compile + A1 Fast 均通过；推荐 wall `< 60s`、peak RSS `< 768 MiB`。

## 8. 必须运行的真实 Direct

运行：

```bash
python hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p4_set_entity_visible_process_only_retirement.py --direct
```

validator 必须使用 pinned TBGD 与 production builders/lowering/materializer/CanonicalIR/RuleBook/A1 ActionContract；不得手工构造一套替代 CanonicalIR 来冒充真实 Direct，也不得读取/依赖 PR11 未合并 business implementation。

Direct 至少输出并断言：

1. `SetEntityVisible` formal source denominator 非空，逐组报告 total/admitted/blocked 与 blocked reasons；
2. admitted occurrence 的 effective scope 全为 `presentation_only`，source path/json path/content fingerprint/task/effect identity闭合；
3. 当前 same-owner action-window status owner 与可用 outer action候选由 merged production 数据动态发现，不把 Silver Wolf 名称/action id 作为唯一通过白名单；
4. 至少一条真实 same-owner ordinary outer action 在 A1 formal blocker provenance 中不再出现 `effect_coverage_status:unsupported:SetEntityVisible`，也不再出现由这些 exact occurrence 引起的 `task_graph_definition_not_admitted:effect:unsupported`；
5. 同一 action 的 P3 `WaitAnimState -> hit_random_sequence` 错误 provenance 不得回归；
6. S11 `damage_heal_shield` / settlement barrier 与其它非本卡 blocker继续保留，因此本 predecessor **不要求 outer action executable**；
7. Direct 不消费 gameplay RNG，不提交 mutation/event/settlement/replay state。

如果 fresh Direct 发现 SetEntityVisible-specific blocker消失后还有另一个早于 S11/A2、属于不同 authority 的 blocker，只报告并停止本卡；不得顺手修第二 authority。合并后由 PLAN 再 fresh attribution。

推荐 Direct 预算：wall `< 300s`，peak RSS `< 2 GiB`。超预算先优化 validator 枚举/流式证据，不得降低 denominator、source fingerprint、A1 consumer或 fail-closed 门禁。

## 9. GitHub Actions / 报告

EXEC 可新增 `.github/workflows/p9-a2-p4-pr-validation.yml`，要求：

- `ubuntu-latest`；
- `permissions: contents: read`；
- checkout exact PR head，`persist-credentials: false`；
- recursive pinned submodule，明确断言 TBGD=`14c1d18f91a8101d610e6c523447a7517de3fae1`；
- scoped compile、focused Fast、A1 Fast、P4 Direct、fixed-base diff check；
- 不新增 secret、write permission、self-hosted/paid runner。

execution report 必须记录实际 production diff、source denominator、same-owner blocker delta、测试/Direct/CI exact-head 证据与残余 blocker；不得把本 predecessor 写成 PR11/A2 已完成。

## 10. 完成与停止条件

### ready_for_review

仅当：

- 生产改动严格限制在本卡 process-only authority；
- Fast/Direct 全部通过；
- SetEntityVisible-specific unsupported provenance 在真实 same-owner A1 action 上闭合；
- P3 与 A1 不回退，S11/其它非本卡 blocker保留；
- final committed head 的适用 CI 通过；
- 已提交 execution report 与 `[HANDOFF:REVIEW]`。

### NEEDS_REPLAN

出现以下任一情况立即正式回 PLAN：

- fixed-base Direct 不复现本卡根因；
- 任一需要准入的 `SetEntityVisible` occurrence 不是 presentation-only，且无法在现有 source contract 中安全分组；
- 正确闭合需要改 `task_graph_materializer.py`、A1 ActionContract、ability-task runtime contract、public IR、executor/event/status runtime、S11 或第二 opcode family；
- source denominator / exact fingerprint 无法在现有生产链闭合。

### NEEDS_DECISION

只有确需改变项目公开语义/authority 边界、引入新依赖/权限/secret/付费资源，或必须对来源缺失事实采用不可由当前 authority 证明的默认语义时使用。

## 11. 后续顺序

本卡 accepted+merged 后，PLAN 必须从新的 merged `master` 再次计算同一真实 status owner 的 outer-action formal blocker denominator：

- 若仍有独立且逻辑早于 A2 的 blocker，只拆下一最早单一 authority；
- 只有 predecessor chain 为空，才恢复现有 PR11，并保留其实现与原 Fast / 真实 `CombatExecutor.execute(ActionCommand)` Direct；
- PR9 继续等待 PR11 accepted+merged；
- 本卡不宣告 P9 COMPLETE。
