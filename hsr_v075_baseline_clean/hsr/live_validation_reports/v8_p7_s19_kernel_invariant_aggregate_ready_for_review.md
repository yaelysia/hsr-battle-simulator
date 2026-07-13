# v8 P7-S19 内核不变量聚合 ready_for_review

## 状态与权限边界

```text
ready_for_review=true
p7_done=false
completion_authority=unified_acceptance_thread
checklist_changed=false
git_checkpoint_created=false
```

验收线程已勾选 P7-S5、P7-S16、P7-S17。执行线程仅修复 P7-S19，未勾选 P7-S19 或 P7-DONE。

## 本轮修复

S19 先前已经绑定当前摘要，但仍存在空 `checks` 被 `all()` 真空通过、旧证据负例依赖工作机历史 `/tmp` 文件的问题。本轮继续收紧证据信任边界：

1. P4-S2、P4-S3、P6-S1 支持注入共享 RuleBook；P6-S4/S5 静态边界在同一串行任务中执行。
2. P1/P2/P3、P4-S2/P4-S3、P6-S1/P6-static、S16/S17 共九项使用当前源码和一次共享 RuleBook 生成。
3. 每份摘要内嵌 `current_source_binding`，包含当前 Python 源码树指纹、共享验证版本和 RuleBook 构建次数。
4. S19 同时校验摘要 SHA-256、摘要内嵌源码指纹、manifest 源码指纹、结构化语义谓词和精确 entry/sequence 集合。
5. P4-S2/P4-S3 必须包含 `matrix`、`static`，P6-S1/P6-static 必须包含 `matrix`；检查集合必须非空，所有子项必须是 `ok is True` 的对象。
6. 共享验证与最终聚合都执行正常正例、空集合、缺必需项、顶层错误类型、子项错误类型和非布尔 `ok` 六类纯函数门禁。
7. 旧证据负例由当前 P4-S2 摘要现场派生错误源码指纹，摘要哈希同步更新；不再读取任何历史摘要。

## 当前源码定向回归

```text
/tmp/p7_current_shared_regressions_v11/p7_current_tree_shared_regression_manifest.json
schema=p7_current_tree_shared_regressions_v3
ok=true
completed_sequence=9/9
tbgd_lowering_build_count=1
rulebook_build_count=1
serial_execution=true
source_tree_stable_during_run=true
large_artifacts_written=false
structured_check_gate_negatives_ok=true
```

分项结果：

```text
P1       current_tree_regression_passed
P2       retained_action_delay_content_gap
P3       reopened_servant_action_content_gap
P4-S2    current_tree_regression_passed
P4-S3    current_tree_regression_passed
P6-S1    current_tree_regression_passed
P6-static current_tree_regression_passed
S16      current_tree_regression_passed
S17      current_tree_regression_passed
```

P4-S2、P4-S3、P6-S1 各自记录：

```text
lowering_build_count=0
rulebook_build_count=0
shared_rulebook_reused=true
large_artifacts_written=false
```

P5 当前证据由当前 P4-S3 公式/动态来源扫描与当前 S12/S14/S15/S16 消费侧不变量共同组成；没有把历史 P5 checkpoint 单独当成当前代码回归。

## 非真空检查门禁

共享验证和最终聚合分别对同一必需检查契约执行纯函数反例：

```text
valid_control_accepted=true
empty_checks_rejected=true
missing_required_check_rejected=true
wrong_checks_type_rejected=true
wrong_check_item_type_rejected=true
non_boolean_ok_rejected=true
```

## 自包含旧证据替换负例

负例复制当前 P4-S2 摘要，只把内嵌源码指纹改成确定性错误值，并同步更新 manifest 中的摘要 SHA-256：

```text
synthetic_stale_summary=/tmp/p7_current_shared_regressions_v11/p7_synthetic_stale_p4_s2_summary.json
tampered_manifest=/tmp/p7_current_shared_regressions_v11/p7_synthetic_stale_p4_p6_replacement_negative_manifest.json
synthetic_stale_summary_written=true
source_fingerprint_changed=true
attacker_updated_summary_hash=true
source_binding_rejected=true
tampered_manifest_rejected=true
negative_ok=true
```

本次以全新的空目录 `/tmp/p7_s19_empty_regression_v11` 作为旧 CLI 参数运行 S19，目录始终为空，聚合仍通过；负例不依赖该目录或任何历史文件。

## S19 最终结果

```text
/tmp/p7_s19_current_acceptance_v11/validation_summary_p7_s19_kernel_invariant_aggregate.json
schema=p7_s19_kernel_invariant_aggregate_v4
ok=true
ready_for_review=true
p7_done=false
issue_rows=24/24
stage_validation_evidence=18/18
current_shared_regression_manifest_matches_worktree=true
p4_p6_current_targeted_evidence_ok=true
structured_check_gate_negatives_ok=true
stale_p4_p6_summary_replacement_rejected=true
executor_pending_checklist_unchanged=true
```

## 资源与范围

没有运行 P4/P5/P6 全量聚合、`validate_v0_209` 或其他无关高负载验证。所有真实来源验证串行运行，只构建一次 TBGD lowering/RuleBook，未写完整 Canonical IR、完整 RuleBook 或全量 transition dump。

P2 action-delay callback graph、P3 servant action graph、P4 action formula 和 P6 上游动作图等内容缺口继续保留，不因 P7-S19 聚合变绿而被解释为全内容完成。
