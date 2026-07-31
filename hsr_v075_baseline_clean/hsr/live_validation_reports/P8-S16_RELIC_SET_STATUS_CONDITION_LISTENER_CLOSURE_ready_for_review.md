# P8-S16 套装状态、条件与监听机制闭合验收报告

## 状态

- 阶段状态：`ready_for_review`
- 本线程验收结论：通过
- Git 基线：`746637c`
- 完整 lowering：0 次
- 套装专用 runtime handler：0
- P8-S17：尚未实施

## 完成范围

本阶段把当前遗器套装使用的属性读取、状态生命周期、条件、动态值和监听器接入通用内核：

1. 能力属性 watcher 与区间成为类型化 Canonical IR，并在 RuleBook 构建时闭合 watcher、区间、callback、modifier 和 effect 来源。
2. 状态实例保存 watcher 身份与区间状态；战斗初始化、状态变化、正式 mutation-backed 属性变化都会触发重评。
3. 区间进入和退出只执行 Canonical callback；callback 失败时整次 dispatch 回到原状态，mutation、event 和 RNG 均不泄漏。
4. 速度、生命比例、攻击类型、状态数量、队伍、波次和行为标记条件读取当前 runtime 状态；条件为假是合法零效果。
5. 多装备者状态互不串线，队伍目标保留实际 owner、caster 和来源身份。
6. watcher 状态 mutation 原生生成 settlement，来源审计与 replay 可闭合。

## 代码审查修复

最终只读审查发现三项真实缺口，均在替代最终验证前修复：

- 已提交在 dispatch 前的生命、护盾、能量等正式 mutation，现在可由 mutation-backed event 的规范单位路径触发 watcher 重评。
- watcher 状态 mutation 必须携带 Canonical watcher 来源；来源缺失或篡改会被 source audit 拒绝。
- 重复 `StatusCallbackIR.callback_id` 不再静默覆盖，RuleBook 构建直接 fail-closed。

审查另提出 `MaxSP` 应表示队伍战技点。该判断经原始能力记录和项目正式资源契约复核后否决：

- TBGD 的 SP 是角色终结技能量，`MaxSP` 对应单位 `max_energy`。
- 队伍战技点在 TBGD 中使用 BP，对应独立的 team skill point 契约。

代码中补充了这一命名说明，未改变正确的运行时映射。

## 验收结果

替代最终 summary 的 `ok=true`，以下 19 项谓词全部满足：

```text
current_set_gameplay_inventory_non_empty
s16_s17_partition_complete
s16_s17_partition_disjoint
s16_family_gap_count=0
s16_unknown_gameplay_count=0
conditions_read_runtime_state
condition_false_is_not_blocked
condition_lifecycle_re_evaluates_on_real_events
multi_wearer_stacking_source_driven
team_and_owner_attribution_correct
listener_registration_idempotent
unsupported_selected_branch_blocks_atomically
mutation_backed_property_change_rechecks_target
duplicate_callback_identity_blocked
watcher_mutation_source_trace_strict
max_sp_uses_unit_energy_semantics
sampled_mutations_source_audited
sampled_transitions_replay_equal
set_specific_runtime_handlers=0
```

当前来源结果：

- 套装动态图：62
- 可执行图：56
- 仍阻断图：6
- watcher：13
- property range：22
- S16 family 行：764
- S17 family 行：628
- S16 gap：0
- unknown gameplay：0
- 来源指纹：`3226efe771227410e8844600a9223bdf9e131126b85aad287ca75fb3f081e314`

真实 4+2 正例使用来源选出的二件套速度阈值和四件套速度变化：

```text
速度 129.292 -> 135.352 -> 129.292
条件 false -> true -> false
```

同一链覆盖状态添加、状态移除、区间重评、mutation、settlement、source audit 和 replay。

## S17 继承边界

剩余 6 张阻断图仅包含 S17 family，没有部分执行：

- 条件：`ByCompareDamageTag`
- 事件：`OnAfterAttackEnd`、`OnBeforeHitAll`、`OnListenBattleEventCreate`
- 事件：`OnListenDepartedStart`、`OnListenDepartedEnd`、`OnStack`
- 任务：`DIHCJLDIMNA`、`SetDynamicValueByBehaviorFlagCount`

这些是 P8-S17 的精确输入，不是 S16 source gap。

## 验证成本

替代最终主验证：

```text
exit status: 0
external wall clock: 12.31s
peak RSS: 350564 KiB
focused RuleBook builds: 1
full lowering builds: 0
artifact bytes before summary: 46571
all evidence bytes: 51110
validator non-empty lines: 997
validator maximum line length: 239
```

实施期有一次完整诊断因验证器错误地把 status detail 当作动态绑定来源而失败；修正验证器后首次 final 通过。代码审查随后改变了生产契约，因此只增加一次替代最终运行，阶段累计仍远低于 25 分钟预算。

直接回归：

- P7-S3 原子提交：9/9 通过。
- P7-S7 历史验证器在进入目标矩阵前，因把已退役的 `lifecycle_status` 写进 `flags` 而失败。该 fixture 与当前 `UnitState` 完整性契约冲突，未要求生产代码兼容，也未消耗第三次 direct；S16 主验证已直接覆盖本阶段队伍目标与 owner attribution。

最终静态检查：

- S16 验证器及本阶段生产文件 `py_compile`：通过。
- `compileall`：通过。
- `git diff --check`：通过。

## Evidence

- `/tmp/hsr_v8_p8_s16_relic_set_status_condition_listener_closure_review/`
- `/tmp/hsr_v8_p8_s16_review_time_v.txt`
