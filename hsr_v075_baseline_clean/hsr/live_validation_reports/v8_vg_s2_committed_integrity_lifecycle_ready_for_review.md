# VG-S2 Committed Integrity 协议与生命周期试点执行报告

执行交付状态：`ready_for_review`

代码基线：`c01ce5cae179a074911b5bf2aeea448909b68362`

## 1. 只读事实核对与范围

实施前先对基线实际调用链进行只读核对，结果未发现会改变本卡目标、职责或验收
谓词的事实偏差：

- executor 正式动作、独立能力和 scheduler transition 均汇入
  `finalize_selected_execution_graph()`；未发现正式 successor 绕过原子提交发布。
- `MutationReducer.apply_all_result()` 只在私有候选状态顺序应用 Mutation；
  普通 reduction 没有领域完整性职责。
- 正式 damage defeat 在交给后续 consumer 前已经形成 HP、生命周期和
  `defeat_record` 的完整子批次；spawn/remove 也能形成完整原子批次。
- `ScenarioStateBuilder.build()` 在 provider/startup/setup 前和最终返回前都有
  可用的统一检查插入点。
- 未发现已准入的 revive/re-entry 生产链。
- 未读取或修改 Canonical IR、RuleBook、lowering、角色/怪物/装备内容规则，也未
  引入依赖。

首次验收随后发现 `systems/status_callbacks.py` 的两条 `AliveOnly` 分支遗漏在
typed authority 迁移之外，仍以 `hp > 0` 判断存活；这属于本卡职责内漏迁移，不
改变目标或验收谓词。当前差量已经：

- 用纯 `runtime_unit_is_active()` 判断 typed lifecycle active；
- 保持 target group/可选中规则与存活过滤为两个独立步骤；
- 用真实 `StatusCallbackSystem.execute()` 覆盖分组和单目标两条计数分支；
- 将 HP 生命周期推断纳入生产 AST 静态扫描；
- 拆分全部超长组合断言，当前验证器最长源码行 108 字符。

首次验收前的 VG-S2 绿灯证据覆盖不完整，不再作为当前交付依据。

本轮未修改执行卡 checklist，未提交 Git，未开始 VG-S3。工作区中先于本轮存在的
`CODEX_HANDOFF.md`、`VALIDATION_GOVERNANCE_AND_STATE_INTEGRITY_PLAN.md`、
UI 草稿和 UI 计划均不属于本卡 patch，已原样保留。

## 2. 实际修改文件与关键符号

### 2.1 生产代码

| 文件 | 关键符号与实际修改 |
|---|---|
| `simulator_v8_clean_core/core/state_integrity.py` | 新增 `StateIntegrityIssue`、`StateIntegrityScope`、`StateIntegrityResult`、`CommittedStateIntegrityError`、`CommittedStateIntegrityGate`；实现固定 lifecycle domain、path-driven touched selector、full/touched gate、最终状态与转换检查、确定排序及 detached JSON |
| `simulator_v8_clean_core/core/model.py` | 新增 `UnitLifecycleStatus`、`UNIT_LIFECYCLE_STATUSES`、`LEGACY_UNIT_LIFECYCLE_FLAG_KEYS` 和 `UnitState.lifecycle_status`；构造边界只校验单字段枚举和 legacy 保留键；snapshot 全部从 typed field 派生 |
| `simulator_v8_clean_core/core/unit_state_codec.py` | `unit_state_to_payload()` / `unit_state_from_payload()` 显式编解码 typed lifecycle；拒绝缺字段、非法枚举和 legacy flags；复用生产 full gate，不复制跨字段规则 |
| `simulator_v8_clean_core/core/reducer.py` | `ReplayResult` 携带 typed integrity；完整 replay 在 snapshot 比较前复用 touched gate；legacy nested/whole flags、非法 typed 值及直接 unit delete 结构化拒绝；普通 `apply_all_result()` 仍只负责 candidate reduction |
| `simulator_v8_clean_core/core/atomic_commit.py` | `AtomicCommitResult.integrity`；schema 升级为 `vg_s2_atomic_commit_v2`；candidate 一致后、发布前执行 touched gate；新增 `events_for_atomic_result()`、`rng_events_for_atomic_result()` 并延续 `records_for_atomic_result()` 的失败规范化 |
| `simulator_v8_clean_core/core/__init__.py` | 仅导出本卡需要的公开 integrity 类型 |
| `simulator_v8_clean_core/core/snapshot_contract.py` | 正式 unit snapshot 必须有 `lifecycle_status` 和 `lifecycle` 视图；未复制 HP/lifecycle invariant |
| `simulator_v8_clean_core/core/executor.py` | 失败提交统一经 atomic helper 将事件/settlement 规范化为 process-only，并清空正式 RNG event |
| `simulator_v8_clean_core/systems/scheduler.py` | scheduler 两条正式 transition 发布路径复用相同 event/record/RNG 规范化 |
| `simulator_v8_clean_core/unit_eligibility.py` | 新增纯 typed `runtime_unit_is_active()`；target/action/timeline admission 在该 lifecycle 判断之上再组合 on-field、source targetability 和 unselectable 规则 |
| `simulator_v8_clean_core/systems/unit_lifecycle.py` | spawn/defeat/remove producer 改为 typed lifecycle path；remove 保留正 HP 语义 |
| `simulator_v8_clean_core/systems/unit_spawn.py` | 正式 materialized spawn payload 显式携带 `lifecycle_status="active"` |
| `simulator_v8_clean_core/systems/mutation_events.py` | unit-removed event 只认 typed lifecycle Mutation；legacy flags path 不再产生正式事件 |
| `simulator_v8_clean_core/systems/status.py` | 单位可用性读取 typed lifecycle；status instance detail 自身的 `lifecycle_state` 保持原义 |
| `simulator_v8_clean_core/systems/status_callbacks.py` | 两条 `SetDynamicValueByCharacterCount + AliveOnly` 分支改用 `runtime_unit_is_active()`；不再以 HP 推断存活，也不以 targetability helper 代替存活规则 |
| `simulator_v8_clean_core/systems/summon_runtime.py` | summon runtime owner/member 生命周期读取 typed field |
| `simulator_v8_clean_core/rules/evaluator.py` | condition/evaluator 生命周期判断改为 typed field |
| `simulator_v8_clean_core/scenarios/build_state.py` | 移除全局 legacy lifecycle flag；provider/startup/setup 前与最终返回前分别执行 full lifecycle gate |

`systems/damage.py` 经只读核对无需修改：它通过现有 lifecycle producer 生成完整
defeat artifacts，并在完整子批次应用后才交给下游 consumer。P7-S2、P7-S3
验证器也无需 fixture 修改。

### 2.2 验证与报告

| 文件 | 实际修改 |
|---|---|
| `simulator_v8_clean_core/tools/validate_vg_s2_committed_integrity_lifecycle.py` | 纯内存聚焦验证器；14 个正例、25 个负例、46 个结构化谓词；新增真实 status callback 双分支探针和 HP fallback AST 扫描；组合断言拆成具名检查 |
| `simulator_v8_clean_core/tools/validate_vg_s1_committed_state_immutability.py` | direct fixture 将旧 lifecycle flag 替换为无关 `runtime_marker`，继续验证 VG-S1 所有权语义 |
| `simulator_v8_clean_core/tools/validate_p8_r1_summon_runtime_halo_lifecycle.py` | runtime-only direct fixture 迁移为 typed lifecycle + 审计记录；对递归冻结 JSON 的测试副本改用生产 `thaw_json()` |
| `live_validation_reports/v8_vg_s2_committed_integrity_lifecycle_ready_for_review.md` | 本报告 |

## 3. Typed lifecycle authority 迁移

| 边界 | 唯一权威/行为 | 旧路径处理 |
|---|---|---|
| 模型 | `UnitState.lifecycle_status`，值域仅 `active/defeated/removed` | 顶层 unit flags 的 `lifecycle_status/lifecycle_state` 在构造时拒绝 |
| Codec | payload 必须显式带 typed lifecycle | 缺字段、legacy flags、非法值均拒绝，不自动补 active |
| Spawn | payload 显式 active；不存在单位只能合法 spawn 为 active | defeated/removed spawn 拒绝 |
| Damage/defeat | 同批 HP=0、typed defeated、非空 defeat record | 不再由 HP 猜 defeated |
| Remove | 同批 typed removed、非空 removed record | 不要求 HP=0；不直接删除 unit |
| Consumer | action、target、timeline、status callback、summon、halo、condition 全部读 typed field | 不双读 flags，不用 HP fallback；存活与可选中分层判断 |
| Event | typed removed path 产生 unit-removed mutation event | legacy flags path 结构化拒绝且不生成事件 |
| Snapshot | `lifecycle_status/defeated/removed/lifecycle` 从 typed field 确定派生 | 公开输出键保留，但不是 runtime 输入权威 |
| Scenario | setup 前和最终状态执行 full gate | 非法初态不能进入 provider/startup consumer |

生产代码 AST 静态扫描覆盖 `core/`、`systems/`、`rules/`、`scenarios/`、
`builds/`、`equipment/` 及 `unit_eligibility.py`，共 77 个 Python 文件：

- legacy unit lifecycle `.flags.get`/下标权威读取：`0`
- legacy lifecycle Mutation path 写入：`0`
- integrity/scenario 输入检查之外的 `.hp` 对零生命周期推断：`0`
- 合计 `production_runtime_legacy_lifecycle_authority_refs=0`

HP 扫描显式排除 `core/state_integrity.py` 的 committed invariant 和
`scenarios/build_state.py` 的 `PanelInput` 数值准入；二者检查的是状态合法性或
输入合法性，不是 runtime consumer 的存活推断。

以下不属于 legacy runtime authority，未为追求字符串归零而误改：

- snapshot 的公开 `lifecycle_status` 和 `lifecycle` 输出键；
- status instance detail 内部自己的 `lifecycle_state`；
- TBGD/source trace、验证报告和源码证据字符串；
- 聚焦验证器中用于证明 fail-closed 的刻意负例。

## 4. Lifecycle 矩阵

### 4.1 最终状态

| 状态 | 覆盖输入 | 实际裁决 |
|---|---|---|
| active | 有限 `0 < hp <= max_hp`，无 defeat/removed record | 通过 |
| active | `hp=0`，或任一 lifecycle record 存在 | 拒绝 |
| defeated | `hp=0`、非空 defeat record、无 removed record | 通过 |
| defeated | HP 非零、缺/空 defeat record、存在 removed record | 拒绝 |
| removed | HP 仍在合法范围、非空 removed record；defeat record 可保留 | 通过；正 HP 明确允许 |
| removed | 缺/空 removed record | 拒绝 |
| 任意 | NaN/Infinity、负 HP、HP 超 max HP、非正 max HP | 拒绝 |

### 4.2 转换闭合

| before -> after | 必须触达 | 实际裁决 |
|---|---|---|
| 不存在 -> active | 完整 unit spawn/replace | 通过 |
| 不存在 -> defeated/removed | 即使最终字段齐全 | 拒绝 |
| active -> active | 最终 invariant | 通过 |
| active -> defeated | HP、typed status、defeat record 同批 | 三者齐全通过；分别缺任一路径均拒绝 |
| active -> removed | typed status、removed record 同批 | 齐全通过；正 HP 允许 |
| defeated -> defeated | 最终 invariant | 通过 |
| defeated -> removed | typed status、removed record 同批 | 通过并保留 defeat record |
| defeated -> active | revive 未准入 | 拒绝 |
| removed -> active/defeated | re-entry 未准入 | 拒绝 |
| 已存在 -> 从 units 删除 | 不准入 | reducer 结构化拒绝 |

正式 damage defeat 的实测 canonical paths 为：

```text
units/enemy:target/hp
units/enemy:target/lifecycle_status
units/enemy:target/flags/defeat_record
```

reducer 应用第一条 HP Mutation 后允许出现私有 `hp=0 + active` 中间候选；完整
子批次闭合后才交给规则 consumer 和 committed gate。

### 4.3 原子失败、replay 与 scenario

| 边界 | 实际证据 |
|---|---|
| Atomic failure | `commit_status=state_integrity_failed`；`after_state is before_state`；0 committed Mutation；candidate 未发布 |
| Outcome | `category=diagnostic`，不是 gameplay blocked；`successor_eligible=false` |
| Artifact | settlement record 和 mutation-derived event 全部 process-only；正式 RNG event 数为 0 |
| Evidence | schema `vg_s2_atomic_commit_v2`，同时保存不可变 typed result 和 detached `state_integrity` JSON |
| Replay 正例 | 合法 spawn、defeat、remove 完整批次均可 replay |
| Replay 负例 | 非法批次即使 expected snapshot 与非法 reducer candidate 相同仍失败 |
| Scenario 正例 | setup 前、setup 后两次 full lifecycle check 均执行后返回 |
| Scenario 负例 | `hp=0 + 默认 active` 首次 full check 抛出携带结构化 result 的 `CommittedStateIntegrityError`；provider/startup 未运行 |

真实 status callback 存活计数：

| 分支 | fixture | 实际 callback 结果 |
|---|---|---|
| 特殊 group alias 分支 | active 但 unselectable 的 enemy + removed 且保留 50 HP 的 enemy；`AllEnemyWithUnSelectable`、`AliveOnly=true` | `value=1`，target IDs 仅含 active-unselectable；证明存活与可选中没有混成同一规则 |
| 通用单目标分支 | callback owner 为 removed 且保留 50 HP，写入目标为 active caster；`ModifierOwnerEntity`、`AliveOnly=true` | `value=0`，target IDs 为空；直接覆盖首次验收复现的错误 |

聚焦矩阵结果：

- 正例 `14/14`：`active_nonlethal_hp_commit`、
  `unrelated_mutations_skip_lifecycle_units`、`touched_unit_only`、
  `legal_active_spawn`、`production_damage_defeat_batch`、
  `private_intermediate_then_complete_handoff`、
  `active_to_removed_keeps_positive_hp`、
  `defeated_to_removed_preserves_defeat_record`、
  `legal_spawn_defeat_remove_replay`、`typed_removed_event_only`、
  `shared_consumers_use_typed_lifecycle`、`scenario_two_full_checks`、
  `typed_codec_snapshot_roundtrip`、`snapshot_contract_requires_lifecycle`。
- 负例/反假设 `25/25`：`active_hp_zero_atomic_failure`、
  `active_status_only_defeated_rejected`、
  `active_defeat_record_only_rejected`、
  `defeat_closure_each_missing_path_rejected`、
  `defeated_hp_nonzero_rejected`、`defeated_record_constraints`、
  `active_records_rejected`、`remove_status_without_record_rejected`、
  `removed_missing_record_rejected`、`removed_positive_hp_allowed`、
  `defeated_to_active_not_admitted`、`removed_reentry_not_admitted`、
  `spawn_defeated_or_removed_rejected`、`direct_unit_delete_rejected`、
  `numeric_lifecycle_bounds_rejected`、
  `legacy_lifecycle_all_boundaries_reject`、
  `invalid_typed_lifecycle_all_boundaries_reject`、
  `invalid_expected_snapshot_cannot_bless_replay`、
  `integrity_failure_artifacts_are_diagnostic`、
  `integrity_failure_is_diagnostic_not_blocked`、
  `invalid_scenario_rejected_before_consumers`、
  `removed_positive_hp_excluded_by_group_alive_count`、
  `removed_positive_hp_excluded_by_single_alive_count`、
  `integrity_result_recursive_immutability`、
  `deterministic_issue_and_conflict_order`。

## 5. Touched scope 实际证据

| 输入 | checked domain/entity/path | 结果 |
|---|---|---|
| 只改 skill point/global flag | domain `()`；scope `()`；unit `()` | passed；零 lifecycle unit 扫描 |
| 两单位场景只改 `ally:a.hp` | `lifecycle` / `ally:a` / `units/ally:a/hp` | 只检查 `ally:a`，未扫描另一单位 |
| 非法 active HP 归零 | 同上 | failed；issue `active_unit_hp_not_positive` |
| 合法 damage defeat | `lifecycle` / `enemy:target` / HP、typed status、defeat record 三条 path | passed |
| full scenario gate | `lifecycle` / 当前全部 unit / 无 transition path | setup 前和最终状态各执行一次 |

非法 HP 归零样本的 issue 同时给出：

- `entity_id=ally:a`
- paths：`units/ally:a/hp`、`units/ally:a/lifecycle_status`
- 确定性 mutation ID：`mutation:74974e448ee47220`
- outcome reason：
  `state_integrity_failed:active_unit_hp_not_positive`

调换语义等价 Mutation 和映射输入顺序后，scope/issue 排序保持一致；before 链不
等价时仍由 reducer conflict 拒绝。

## 6. 结构化验收谓词

聚焦 summary：
`/tmp/hsr_v8_vg_s2_committed_integrity_lifecycle/validation_summary_vg_s2_committed_integrity_lifecycle.json`

| 谓词 | 实际值 |
|---|---:|
| `typed_lifecycle_is_single_runtime_authority` | `true`（legacy refs `0`，HP fallback refs `0`，真实 callback 双分支通过） |
| `legacy_lifecycle_flag_constructor_rejected` | `true` |
| `legacy_lifecycle_flag_codec_rejected` | `true` |
| `legacy_lifecycle_flag_mutation_rejected` | `true` |
| `hp_is_not_used_as_lifecycle_fallback` | `true`（静态命中 `0`；group/single callback 值分别为 `1`/`0`） |
| `unit_codec_round_trip_preserves_typed_lifecycle` | `true` |
| `snapshot_derives_lifecycle_from_typed_field` | `true` |
| `snapshot_contract_requires_lifecycle_view` | `true` |
| `touched_domain_selector_is_path_driven` | `true` |
| `unrelated_mutation_checks_zero_lifecycle_units` | `true` |
| `touched_lifecycle_checks_only_selected_units` | `true` |
| `intermediate_candidate_may_be_temporarily_inconsistent` | `true` |
| `partial_lifecycle_candidate_not_exposed_to_rule_consumers` | `true` |
| `active_final_state_requires_positive_hp` | `true` |
| `defeated_final_state_requires_zero_hp_and_record` | `true` |
| `removed_final_state_requires_record_not_zero_hp` | `true` |
| `spawn_transition_requires_active_valid_unit` | `true` |
| `defeat_transition_requires_atomic_closure` | `true` |
| `remove_transition_requires_atomic_closure` | `true` |
| `revive_transition_not_admitted` | `true` |
| `removed_reentry_not_admitted` | `true` |
| `direct_unit_deletion_not_admitted` | `true` |
| `legal_damage_defeat_commits` | `true` |
| `legal_removal_commits` | `true` |
| `invalid_lifecycle_commit_is_diagnostic` | `true` |
| `invalid_lifecycle_commit_preserves_before_identity` | `true` |
| `invalid_lifecycle_commit_has_zero_committed_mutations` | `true` |
| `invalid_lifecycle_commit_is_not_successor_eligible` | `true` |
| `integrity_failure_records_are_process_only` | `true` |
| `integrity_failure_events_are_process_only` | `true` |
| `integrity_failure_has_zero_formal_rng_events` | `true` |
| `atomic_evidence_contains_structured_integrity_result` | `true` |
| `atomic_evidence_schema_version_updated` | `true` |
| `legal_lifecycle_replay_passes` | `true` |
| `invalid_lifecycle_replay_fails` | `true` |
| `scenario_pre_setup_state_runs_full_lifecycle_check` | `true` |
| `scenario_final_state_runs_full_lifecycle_check` | `true` |
| `invalid_scenario_initial_state_rejected` | `true` |
| `issue_order_is_deterministic` | `true` |
| `integrity_result_recursively_immutable` | `true` |
| `production_runtime_legacy_lifecycle_authority_refs` | `true`（实际计数 `0`） |
| `tbgd_read_count` | `true`（实际计数 `0`） |
| `full_rulebook_build_count` | `true`（实际计数 `0`） |
| `catalog_validation_count` | `true`（实际计数 `0`） |
| `focused_output_bytes_below_1_mib` | `true`（实际 `9,636` bytes） |
| `focused_validator_does_not_duplicate_production_invariants` | `true`（私有 checker `[]`，生产 gate 调用 `4` 次） |

`predicate_mismatches={}`；46 个谓词全部满足。

## 7. 验证器成本与输出

- 聚焦验证器源码：`58,806` bytes，超过 `48 KiB = 49,152` bytes 的建议值
  `9,654` bytes。该超限是有意保留可审查性的结果：首次验收要求新增两条真实
  status callback IR/task 行为探针，同时原有强制矩阵不能删减；现有历史 callback
  fixture 会进入 TBGD/catalog，不能在本卡复用。当前已复用同一个小型内存
  RuleBook，并将组合断言拆为具名检查，最长源码行从 462 字符降为 108 字符；未再
  通过压缩代码规避建议值。
- 聚焦输出：`9,636` bytes，低于 `1 MiB`。
- 输出仅有 summary、positive matrix、negative matrix 和小型 integrity samples；
  未写完整 snapshot、RuleBook、transition、settlement 或 replay dump。
- `tbgd_read_count=0`
- `full_rulebook_build_count=0`
- `catalog_validation_count=0`
- 仅构造 `1` 个小型内存 RuleBook。
- P8-R1 runtime-only：
  `catalog_builder_count=0`、`full_s8_aggregate_count=0`、
  `full_tbgd_lowering_count=0`、`large_ir_artifact_written=false`。

## 8. 串行验证命令与资源

验收差量修复后，所有命令从头严格按执行卡顺序串行运行，工作目录均为
`hsr_v075_baseline_clean/hsr/`；资源值由
`/usr/bin/time -v` 实测，时间为 wall clock，内存单位为 KiB。

| 顺序 | 命令 | exit | elapsed | peak RSS | 结果 |
|---:|---|---:|---:|---:|---|
| 1 | `PYTHONPYCACHEPREFIX=/tmp/hsr_v8_vg_s2_pycache python3 -m compileall -q simulator_v8_clean_core` | 0 | 0:00.11 | 24416 | 通过 |
| 2 | `python3 -B -m simulator_v8_clean_core.tools.validate_vg_s2_committed_integrity_lifecycle --output-dir /tmp/hsr_v8_vg_s2_committed_integrity_lifecycle` | 0 | 0:01.06 | 54624 | 14/14 正例，25/25 负例，46/46 谓词 |
| 3 | `git diff --check` | 0 | 0:00.01 | 6284 | 通过 |
| 4 | `python3 -B -m simulator_v8_clean_core.tools.validate_vg_s1_committed_state_immutability --output-dir /tmp/hsr_v8_vg_s2_vg_s1_immutability` | 0 | 0:00.13 | 24384 | 29/29 |
| 5 | `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s2_mutation_reducer_contract --output-dir /tmp/hsr_v8_vg_s2_p7_s2_reducer` | 0 | 0:00.58 | 50088 | 14/14，conflicts 9 |
| 6 | `python3 -B -m simulator_v8_clean_core.tools.validate_p7_s3_selected_graph_atomic_commit --output-dir /tmp/hsr_v8_vg_s2_p7_s3_atomic_commit` | 0 | 0:00.32 | 40284 | 9 cases |
| 7 | `python3 -B -m simulator_v8_clean_core.tools.validate_p8_r1_summon_runtime_halo_lifecycle --tbgd-root ../../turnbasedgamedata-main --runtime-only --output-dir /tmp/hsr_v8_vg_s2_p8_r1_runtime` | 0 | 0:01.21 | 45820 | `mode=runtime_only`，`ok=true`，catalog/full 计数为 0 |

实施期间保留的失败诊断，不作为当前成功证据：

| 命令阶段 | exit | elapsed | peak RSS | 根因与处理 |
|---|---:|---:|---:|---|
| 聚焦验证首次运行 | 1 | 0:00.37 | 44680 | 最小 Scenario fixture 缺正式 setup status event family，触发 `event_alias_missing`；只补齐小型内存 IR event family 后从顺序 1 重启 |
| P8-R1 runtime-only 首次运行 | 1 | 0:00.82 | 47288 | 历史 fixture 对递归冻结 `moved_runtime` 使用 `deepcopy()`；改用生产 `thaw_json()` 后从顺序 1 重启 |
| P8-R1 runtime-only 第二次运行 | 1 | 0:00.90 | 46620 | 同一 direct validator 的 forged evidence 仍有 `deepcopy()`；统一迁移该 fixture 的冻结 JSON 副本后从顺序 1 重启 |

## 9. 明确未运行：全部 `not_proven`

| 未运行入口/类别 | 状态 | 原因 |
|---|---|---|
| `validate_p1_1_unit_lifecycle` | `not_proven` | 会进入完整 TBGD lowering；S2 当前生产契约由聚焦矩阵覆盖 |
| `validate_p7_s17_wave_lifecycle_events` | `not_proven` | 会进入完整 TBGD lowering；typed remove/event 由聚焦正负例覆盖 |
| P1-P8 任一阶段 aggregate | `not_proven` | 不增加 S2 committed invariant 证明，成本超出本卡 |
| `validate_v0_209` | `not_proven` | 执行卡明确排除 |
| `validate_p7_current_tree_shared_regressions` | `not_proven` | 执行卡明确排除 |
| P8-S8 | `not_proven` | catalog/full 路径不属于本卡 |
| P8-R1 catalog/full 模式 | `not_proven` | 只准入 runtime-only；本轮 catalog builder 计数保持 0 |
| 完整 TBGD discovery/lowering | `not_proven` | 本卡禁止读取，且不增加提交门证明 |
| 完整 Canonical IR、RuleBook、coverage、fidelity 输出 | `not_proven` | 本卡限制大产物和 catalog/full 成本 |

上述未运行项均未被描述为通过。

## 10. 未迁移历史 fixture 清单

以下仅是静态确认的 legacy unit lifecycle key 触点；本轮未修改、未运行，状态均为
`not_proven`。位置是当前基线文件行号，后续迁移时仍需按实际触达域复核，不能
反向要求生产保留兼容层。

### 10.1 建议交由 VG-S8 的 source/catalog 重验证迁移

| 文件 | legacy 触点位置 | 分类 |
|---|---|---|
| `validate_p1_1_unit_lifecycle.py` | 103、172、204、225、247；helper 405 | 构造/辅助函数 |
| `validate_p1_2_wave_system.py` | 273、275、489 | flags 断言/构造 |
| `validate_p1_3_summon_assistant_servant.py` | 234、754 | flags 断言/构造 |
| `validate_p1_4_status_system.py` | 547、1060、1141 | unit flags 构造/断言 |
| `validate_p1_5_queue_window_system.py` | 676、680 | unit flags 构造 |
| `validate_p1_6_target_system.py` | 359、457；helper 1013 | unit flags fixture |
| `validate_p2_s4_status_lifecycle.py` | 232、233；helper 326-332 | unit lifecycle helper |
| `validate_p2_s6_status_control_gate.py` | 119 | unit flags fixture |
| `validate_p2_s8_status_damage.py` | 421 | unit flags fixture |
| `validate_p3_s2_summon_runtime_schema.py` | 285 | flags 断言 |
| `validate_p3_s5_servant_lifecycle.py` | 286 | flags 断言 |
| `validate_p3_s6_summon_action_execution.py` | 297；helper 511 | unit flag helper |
| `validate_p3_s8_summon_target_relations.py` | helper 671-676 | unit flags fixture |
| `validate_p3_s9_summon_lifecycle_cleanup.py` | 222、384 | flags 断言/构造 |
| `validate_p3_s10_summon_status_resource_damage.py` | 435、482 | flags 断言 |
| `validate_p4_s4_target_query_admission.py` | 374、380；helper 908 | unit flags fixture |
| `validate_p6_s2_s3_unit_spawn_birth_plan.py` | 322 | spawn flags fixture |
| `validate_p7_s16_in_combat_summon_lifecycle.py` | 337、374、566、582 | unit flags fixture |
| `validate_p7_s17_wave_lifecycle_events.py` | 155 | flags 断言 |
| `validate_p8_s7_light_cone_status_condition_listener_closure.py` | 1803、2802、2833、2879、2887 | unit flags fixture/payload |
| `validate_p8_s8_light_cone_remaining_gameplay_closure.py` | 1500、1520、1535、1554、1771、1784、1798、2078、6708、7812 | unit flags fixture/payload |

建议在 VG-S8 实际注册这些 catalog/source 验证时，将 fixture 原子迁移为 typed
status + 所需记录，并在资源限额内重跑；当前不能推断其结果。

### 10.2 建议交由 VG-S3 的本地 validator registry 迁移

| 文件 | legacy 触点位置 | 分类 |
|---|---|---|
| `validate_p7_s7_target_selection_impact_contract.py` | 250；同矩阵另有 HP-only defeated fixture | 本地 target fixture |
| `validate_p7_s9_explicit_turn_event_phase_machine.py` | 405 | 本地 wave/turn fixture |
| `validate_p7_s10_timeline_control_semantics.py` | 306；同矩阵另有 HP-only defeated fixture | 本地 timeline fixture |
| `validate_p7_s18_compact_semantic_state.py` | 184、199、210 | 本地 compact-state fixture |

建议 VG-S3 注册时按 touched domain 迁移并运行；本轮不为全局 grep 归零而维护未运行
脚本。静态 key 清单也不证明不存在其他 HP-only fallback fixture，因此未运行历史
验证整体仍为 `not_proven`。

### 10.3 已分类为非 unit lifecycle authority

| 引用 | 分类 |
|---|---|
| `validate_p7_s0_kernel_trust_baseline.py:210,664` | 源码证据字符串和 status instance detail |
| `validate_p7_s11_queue_terminal_progress.py:470` | status instance detail |
| `validate_v0_217.py:323` | status instance detail |
| `validate_v0_272.py:189` | 报告文本 |
| 历史验证中的 `snapshot["units"][...]["lifecycle_status"]` | 允许保留的 snapshot 公开输出键 |
| `validate_vg_s2_committed_integrity_lifecycle.py` 内 legacy 字符串/path | 本卡刻意的 fail-closed 负例 |
| 已迁移并通过的 P8-R1 runtime-only fixture | typed lifecycle，不属于待迁移项 |

## 11. 剩余风险与 deferred

当前风险：

- 未运行 catalog、完整 TBGD lowering 或阶段 aggregate；其历史结果均
  `not_proven`，部分旧 fixture 会因 legacy flags 或 HP fallback 被新边界拒绝。
- 生产静态扫描是针对已界定 Python runtime 的语法级权威扫描，不覆盖 TBGD/source
  文本和未运行工具的全部语义。
- S2 只注册 lifecycle domain；其他领域矛盾状态尚不由统一 gate 拒绝。
- revive/re-entry 尚未准入，因此本轮明确 fail-closed。

按执行卡 deferred：

- revive 及 revive 后 defeat record 保留策略；
- source-backed 初始 defeated scenario 输入；
- status details/粗索引完整性；
- summon registry/UnitState 双向完整性；
- halo 父子状态完整性；
- wave/turn/queue/window 完整性；
- snapshot 文件载入边界的 full-domain 检查；
- event root/child closure 所有权；
- validator registry、共享 RuleBook、catalog cache；
- 所有未运行历史 catalog/full 验证；
- 未运行历史验证中的 legacy lifecycle fixture 迁移。

本报告不对上述 deferred 或 `not_proven` 项作通过声明。
