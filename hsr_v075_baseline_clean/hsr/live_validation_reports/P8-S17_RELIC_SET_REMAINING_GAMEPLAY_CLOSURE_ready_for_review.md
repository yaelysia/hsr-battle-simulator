# P8-S17 套装剩余 Gameplay 机制闭合验收报告

## 状态

- 阶段状态：`ready_for_review`
- 本线程验收结论：通过
- Git 基线：`a36a9d1`
- 完整 lowering：0 次
- 聚焦 RuleBook 构建：1 次
- 套装专用 runtime handler：0
- P8-S18：尚未实施

## 完成范围

P8-S17 关闭了 S16 留下的遗器套装剩余 gameplay family，并修复了正式角色动作与通用事件链之间的真实架构缺口：

1. 正式角色动作中的能力任务伤害现在原生产生攻击前、每段伤害后和攻击结束事件，并在同一原子 transition 中执行监听回调。
2. 正式动作和独立能力使用不同的类型化伤害来源身份；击杀归属、事件身份、来源审计和 replay 不再把角色动作伪装成独立能力。
3. 伤害标签从真实 `DamageTag` 枚举映射进入 IR；字段语义确定枚举类型，原始 `EnumIndex` 被保留并校验类型，不再错误地把 JSON 字典顺序当作枚举索引。
4. 状态叠层变化值、行为标记计数、战斗事件创建、单位离场开始/结束及攻击结束监听进入通用 callback/event 路径。
5. 单位离场使用来源绑定的 presence 记录；添加、移除、重复身份、冲突身份和事件派发均 fail-closed。
6. client-only 相机能力和视觉任务被结构化标为 process-only，不进入 gameplay mutation。
7. 引擎零下限数值绑定只消费 Canonical IR 中已准入的规则，不再由 runtime 按固定 hash 分派。

## 代码审查修复

执行层主验证通过后，本线程继续检查生产代码和调用链，并修复以下问题：

- 引擎数值绑定仍在 runtime 中维护固定 hash 规格。现改为遍历已装入 RuleBook 的类型化引擎规则，并严格核对版本、来源、执行状态和表达式形状。
- 正式角色动作伤害仍标成独立能力伤害。现根据 action definition 的来源模式生成正式动作或独立能力来源身份。
- `DamageTagList` 最初只核对枚举值；随后审查修正又错误地把 `ConfigList` 字典位置当作 `EnumIndex`。真实来源证明 `DamageTagList` 使用索引 3，而字典当前位置是 4。最终实现由字段上下文确定枚举域、由真实枚举表解析值，并保留原始索引，不再推断不存在的顺序契约。
- 状态变化值拒绝 `NaN` 和无穷值。
- 离场事件生成与正式 presence 解析统一使用同一严格结构，不再保留一套较弱的重复校验。
- 历史 S7 定向调用点已迁移为显式传入 RuleBook 的引擎规则，不保留隐式默认 registry。

未发现套装名、套装 ID、角色名、技能名或固定能力文件驱动的 runtime 分支。

## 验收结果

当前源码最终 summary 为 `ok=true`，所有阶段谓词满足：

```text
s16_evidence_current=true
s16_s17_union_equals_current_gameplay=true
s16_s17_intersection_empty=true
s17_remaining_family_gap_count=0
published_player_set_blocked_graph_count=0
unknown_gameplay_node_count=0
non_gameplay_rows_have_structured_evidence=true
resource_hp_damage_timeline_use_common_routes=true
static_condition_mutation_order_correct=true
stale_plan_rejected=true
team_effects_mutate_real_targets=true
multi_wearer_and_wave_lifecycle_correct=true
rng_choices_have_stable_identity=true
blocked_transition_state_unchanged=true
sampled_mutations_source_audited=true
sampled_transitions_replay_equal=true
set_specific_runtime_handlers=0
```

当前目录事实：

- 套装动态图：62
- 可执行图：62
- S16 family：764
- S17 family：628
- S17 gap：0
- 已发布普通玩家套装阻断图：0
- unknown gameplay：0
- 抽样原子 transition：4
- 离场来源候选：1
- 来源指纹：`3226efe771227410e8844600a9223bdf9e131126b85aad287ca75fb3f081e314`

正式动作证据覆盖：

- 每个伤害序列的 before / hit / after 顺序闭合。
- 所有 after 事件完成后仅产生一次 attack-end 事件。
- 行为标记计数读取真实状态。
- 伤害标签与伤害自定义名称严格区分。
- 旧决策 token 在前置状态变化后被拒绝。
- 离场开始、离场结束、重复来源和来源身份冲突均通过正式原子路径。

## 验证成本

审查后最终主验证：

```text
exit status: 0
external wall clock: 92.05s
validator elapsed: 91.284s
peak RSS: 917316 KiB
focused RuleBook builds: 1
full lowering builds: 0
focused character ability files: 2
artifact bytes before summary: 11182
all evidence bytes: 14831
```

审查阶段先使用小型边界探针确认：

- 伤害标签真实枚举、未知名称、非法索引类型和未知枚举值。
- 离场来源完整、缺字段、非 executable 和身份篡改。
- 所有引擎数值绑定调用点显式消费 RuleBook registry。

第一次审查后聚合在 14 秒时因错误的 `EnumIndex == ConfigList 字典位置` 假设停止，尚未进入业务执行。修正来源解释后先运行 8 秒窄投影确认唯一真实遗器伤害标签条件恢复 executable，再进行上述唯一成功终局聚合。

最终静态检查：

- 触达文件 `py_compile`：通过。
- `compileall`：通过。
- `git diff --check`：通过。

P7 已验收的资源、生命、护盾、时间线、波次和 RNG 契约按执行卡继承，未恢复历史聚合或完整 lowering。

## Evidence

- `/tmp/hsr_v8_p8_s17_reviewer_final_2/`
- `/tmp/hsr_v8_p8_s17_reviewer_time_v_2.txt`
