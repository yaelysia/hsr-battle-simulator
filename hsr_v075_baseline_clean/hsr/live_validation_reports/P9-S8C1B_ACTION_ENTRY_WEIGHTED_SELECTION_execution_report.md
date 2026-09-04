# P9-S8C1B Action Entry Weighted Selection Materialization — Execution Report

Execution handoff result: `ready_for_review`.
Independent review result: `accepted`.

## 1. Identity

- Card: `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-S8C1B_ACTION_ENTRY_WEIGHTED_SELECTION_MATERIALIZATION.md`
- PR: `#2`
- Branch: `exec/p9-s8c1b-action-weighted-selection`
- Base: `master@2cd1239f52cd39136576d4920302bafa671d5471`
- Code-validation head: `759e00e91cfece2a87b979139a9d1b4bebb29459`
- Code-validation CI: `https://github.com/yaelysia/hsr-battle-simulator/actions/runs/33827486941`
- Report-containing execution head before acceptance governance: `5493f3bea97b01d4b8657fb995b18f396c2e6312`
- Final pre-governance CI: `https://github.com/yaelysia/hsr-battle-simulator/actions/runs/33827733088`
- The acceptance-governance commit containing this amendment is intentionally not self-referenced; its exact final PR head and final CI are recorded by PR metadata and the independent acceptance result.

## 2. Authorized write set actually present at code-validation head

The PR contains one planner-owned execution card plus the five execution-authorized paths. The card was created before execution and remained byte-identical through the execution handoff.

Execution-authorized paths:

- `.github/workflows/p9-s8c1b-pr-validation.yml`
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py`
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py`
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1b_action_entry_weighted_selection.py`
- `hsr_v075_baseline_clean/hsr/live_validation_reports/P9-S8C1B_ACTION_ENTRY_WEIGHTED_SELECTION_execution_report.md`

Planner-owned card path:

- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-S8C1B_ACTION_ENTRY_WEIGHTED_SELECTION_MATERIALIZATION.md`

No production files outside the card write set were changed. The execution phase after handoff added/adjusted only the validator and scoped CI; the two production files were already present on the PR branch and required no further repair after validation.

## 3. Authority and caller map

- Raw authority: the repository-pinned `turnbasedgamedata-main` submodule at `14c1d18f91a8101d610e6c523447a7517de3fae1`, consumed through the exact signed `CharacterAbilityRawSnapshot`.
- Formal source authority: the existing character ability source graph plus `CharacterControlFlowContractCatalog`, bound to the same signed snapshot fingerprint.
- S8C1B materialization authority: existing `TaskGraphWeightedSelectionIR` / numeric-definition contracts from S8C1A plus the shared action task-graph materializer.
- Direct caller parity: the same representative action graph is produced by `materialize_ability_phase_task_graph(...)` and appears identically in `materialize_ability_task_graph_catalog(...)`.
- Runtime ownership is unchanged: `RandomConfig` remains deferred to `hit_random_sequence`; this card does not execute or sample the weighted choice.

## 4. CI and resource evidence

Code-validation run `33827486941`, job `100883134447`, completed `success` for the code-validation PR tree. GitHub Actions checked out PR merge ref `f92ca75e4ee7073f3e4b352111b7043a0d6a3bc7`; independent review confirmed that merge ref has zero file diff from code-validation head `759e00e91cfece2a87b979139a9d1b4bebb29459`. Checkout initialized the repository-pinned TBGD submodule before validation.

After this report was committed, final pre-governance run `33827733088` also completed `success`. It checked out merge ref `3aeb8b40e65f88a0babcc4000d0520eaa53c5a45`; independent review confirmed zero file diff from execution head `5493f3bea97b01d4b8657fb995b18f396c2e6312`.

### Compile

Command:

`PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1b_action_entry_weighted_selection.py`

- Exit: `0`
- Wall: `0.14s`
- Max RSS: `18,368 KiB`
- CI additionally executes `test -f` for the S8C1B validator before compile, and the subsequent Fast module invocation imports the validator and its production dependencies fail-closed.

### Upstream S8C1A

Command:

`PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1a_weighted_selection_ir`

- Exit: `0`
- Cases: `7`
- Validator elapsed: `0.008002s`
- Wrapper wall: `0.52s`
- Max RSS: `38,528 KiB`

### S8C1B Fast

Command:

`timeout --signal=TERM --kill-after=5s 30s env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1b_action_entry_weighted_selection --fast`

- Exit: `0`
- Cases: `6`
- Validator elapsed: `0.002188s`
- Wrapper wall: `1.19s`
- Max RSS: `88,020 KiB`
- Budget: `<30s`, `<512 MiB` — satisfied.

Fast predicates proved:

- weighted attachment strict codec/round-trip;
- invalid `OddsList` type fails closed;
- `OddsList`/branch cardinality mismatch fails closed;
- weighted choice attached to the wrong branch fails closed;
- forged child-source content identity fails closed;
- unknown strict-codec field fails closed;
- `RandomConfig` runtime ownership remains deferred to `hit_random_sequence`.

### S8C1B Direct

Command:

`timeout --signal=TERM --kill-after=5s 120s env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1b_action_entry_weighted_selection --direct`

- Exit: `0`
- Validator elapsed: `14.564729s`
- Wrapper wall: `15.35s`
- Max RSS: `398,396 KiB`
- Budget: `<120s`, `<1 GiB` — satisfied.
- Full `CanonicalIR` build count: `0`; the validator replaces `TBGDLowering.build` with a fail-closed sentinel during Direct.

Final execution-head rerun `33827733088` independently repeated the same gates and remained in budget: Fast exit `0`; Direct exit `0`, validator elapsed `20.200372s`, wrapper wall `21.30s`, max RSS `398,488 KiB`; upstream S8C1A and committed diff check also exited `0`.

### Base diff check

Command:

`git diff --check 2cd1239f52cd39136576d4920302bafa671d5471 HEAD`

- Exit: `0`
- Wall: `0.00s`
- Max RSS: `6,476 KiB`

## 5. Real signed action source evidence

The Direct representative was discovered dynamically from formal action bindings and control-flow `RandomConfig` sources; no business ID or source path is hardcoded in the validator.

- Entry kind: `ability_phase_callback`
- Callback: `OnStart`
- Phase: `ability_phase:avatar_skill:1100601:1:2:Avatar_Advanced_Silwolf_00_PassiveSkill_RandomBug`
- Signed source: `Config/ConfigAbility/Avatar/Advanced/Avatar_Advanced_Silwolf_00_Ability.json`
- `RandomConfig` JSON path: `$.AbilityList[8].OnStart[0].SuccessTaskList[0].SuccessTaskList[0].SuccessTaskList[0]`
- Source occurrence: `task_graph_source:022add319654dc3e4c5d1f3d57fafaa5a0970fc9d242999f907b287b9fe5db4c`
- Selection: `task_graph_weighted_selection:431ead4594e3e198cee890932d5c2853290ffb2dc90fdb0cfd186f67ba601428`
- The validator independently re-hashes the signed `source_bytes` against `content_sha256` before reading the raw `OddsList`.

The raw `OddsList` has three entries and Direct closed each chain as:

1. ordinal `0` → `$.AbilityList[8].OnStart[0].SuccessTaskList[0].SuccessTaskList[0].SuccessTaskList[0].OddsList[0]` → source occurrence `task_graph_source:bd1de09c36a44b9e996c3d785e94087f20cbc70efddf6d9a42498053c293684b` → numeric `task_graph_numeric:b499c69cf567bc2b93f6fe2e3ade0165560fd2f06bad38f0d753ea86d9b32852` → branch `task_graph_branch:edee546a295b0f4c3482a256130ba817a18db84d31258a80d16daf02520e7948` → choice `task_graph_weighted_choice:f69725942414e3424c6e7e461b181e4cb634a3526216a53aa87a5d0525f3ac42`.
2. ordinal `1` → `$.AbilityList[8].OnStart[0].SuccessTaskList[0].SuccessTaskList[0].SuccessTaskList[0].OddsList[1]` → source occurrence `task_graph_source:6d996e531786dd9edef12327a1a95537f55068e146770be612dcc52cc23f6669` → numeric `task_graph_numeric:4352a471419a771f38e91347097ac708a26a1728c7af80534b02303ab9733e04` → branch `task_graph_branch:088dacf385f0a1ba14bbd2b2d42941f0b210682cfcd9a21161727c72f1360d11` → choice `task_graph_weighted_choice:bbfbffd78770baa70897954b57380de203331edf404db63218e4976e9e442166`.
3. ordinal `2` → `$.AbilityList[8].OnStart[0].SuccessTaskList[0].SuccessTaskList[0].SuccessTaskList[0].OddsList[2]` → source occurrence `task_graph_source:9e6f0a11e8b242af6de739da76a038a515fee7e015f4b066dd2e8cadda8312ae` → numeric `task_graph_numeric:fc19554c231ae55e2cad2ce1df394078b19283636ebb00d906ceeeacbc615581` → branch `task_graph_branch:450678440f890c42dc816694683187cb3a35f38851c3c124bf1111ed1d362ab6` → choice `task_graph_weighted_choice:2fb74b8d24e36a19d9972c5cb0b7277ec8960e96608a5ad4671fbe4eaa754830`.

The selected single-entry graph and the corresponding action-catalog graph serialize identically, proving they share the same formal materialization result.

## 6. Unaffected-path evidence

### Non-RandomConfig action

- Callback: `OnStart`
- Phase: `ability_phase:avatar_skill:1100601:1:1:Avatar_Advanced_Silwolf_00_Skill01_Phase02`
- Graph: `task_graph:c35ad084cb0a159f3ce5df6cb18623078ff93d356f2c99907489ad378a9ade86`
- It contains no `RandomConfig`; single-entry and catalog materializations serialize identically and no weighted-selection attachment is introduced.

### Status callback

Status evidence is discovered independently through the authoritative formal status source context, not by scanning the complete status denominator. Files are ranked by formal control-source count and the probe is capped at `24`; the first materializable non-`TriggerAbility` callback wins.

- Probe rank: `0 / 24`
- Source: `Config/ConfigAbility/Avatar/Avatar_Feixiao_00_Ability.json`
- Callback: `status_callback:Config/ConfigAbility/Avatar/Avatar_Feixiao_00_Ability.json:MAvatar_Feixiao_00_AttackProperty:34:OnStack`
- Event: `OnStack`
- Graph: `task_graph:9a24516a873b26362d65dcf2213440384766dad5750c2230c78f461e6ba83502`
- Repeated status materialization serializes identically and contains no S8C1B weighted-selection attachment.

## 7. Remediation trace

- The initial PR CI could not import the not-yet-created validator. This execution added it and made validator existence fail closed before compile.
- Run `33825981909`: Fast passed; Direct showed the repository-pinned TBGD submodule was not initialized in Actions. Workflow checkout was changed to initialize the existing pinned submodule.
- Run `33826118830`: Direct reached signed data; the validator's independent evidence reader incorrectly treated frozen snapshot arrays as mutable lists. Evidence reading was moved to signed raw `source_bytes` plus digest verification.
- Run `33826531583`: weighted-selection proof succeeded, but the initial status comparison was too narrowly tied to action slices. A bounded formal status-source probe was added.
- Run `33827184681`: bounded status probe had a validator-only `TBGDLowering.root` typo; corrected to the authoritative `tbgd_root` attribute.
- Run `33827486941`: compile, S8C1A, Fast, Direct, and base diff check all passed.
- Run `33827733088`: report-containing execution head reran compile, S8C1A, Fast, Direct and base diff successfully; the PR merge ref was independently shown tree-equivalent to the execution head.

No remediation required a production-scope expansion or authority change.

## 8. Deferred / unfinished scope

This report does **not** claim any of the following:

- runtime weighted-choice sampling/execution;
- migration of `hit_random_sequence` runtime ownership;
- a complete denominator of every weighted-selection source or every action entry;
- S8C1C or any remaining entry-family materialization;
- behavior changes to status callbacks or non-`RandomConfig` actions.

Those remain outside P9-S8C1B. The accepted slice is limited to formal action-entry weighted-selection IR materialization plus its focused Fast/Direct evidence.
