# P8-S17 套装剩余 gameplay 机制闭合执行卡

## 执行配置

- 对应问题：P8-I13 剩余 gameplay 机制。
- 硬前置：P8-S16 已验收，其 S16/S17 分区账本当前且完整。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`max`。
- 推荐模式：Goal 模式，目标严格限定为本卡；遗器轨独立 worktree。
- 选择理由：跨资源、HP、伤害、行动、队伍、波次、目标和 RNG，并承担遗器轨全 gameplay 零 gap 收口，是高复杂度长任务。

## 当前事实与阶段结果

S16 已关闭状态/条件/监听 family，并留下精确 S17 剩余集合。开始时必须验证 S16 evidence 的源码指纹、schema 和集合完整性，不能消费任意历史 `/tmp` 结果。

完成后，S16/S17 合集覆盖当前全部已发布套装 gameplay 图。资源、治疗、生命变化、伤害修正、行动变化、队伍增益、波次进入、剩余目标和 RNG 均通过通用内核执行；当前普通玩家套装图 blocked 数、unknown gameplay 数和四类实现 gap 均为零。每类结算有真实正例、条件失败/非法来源负例、原子 transition、来源反查和 replay。

## 本阶段只做

- 关闭 S17 剩余 family，确认与 S16 无遗漏/重叠。
- 通过通用 resource、HP/shield、damage、timeline、wave、target 和 RNG 系统执行真实效果。
- 验证同一事件中最终静态面板、条件求值、计划创建、mutation 提交的正确顺序；状态改变后不消费过期计划。
- 覆盖低生命治疗/回能、入场资源、速度阈值队伍增益等实际结构，但主样例按 IR 谓词选。
- 验证多个 wearer、跨波次、重复事件、队伍 target 和 actual owner 不重复注册/累计。
- 对 client-only/animation 节点逐项给出结构化排除，unknown 为零。
- 运行一次当前源码 focused 全套装 gameplay aggregate。

## 本阶段不做

- 不建立套装专用资源、伤害、时间线、队伍 flag 或 RNG 系统。
- 不以历史底层 backlog 为由跳过当前已发布套装真实使用的通用语义。
- 不从描述、攻略或 UI 计算效果与条件。
- 不把最终数值变化当作事件时机、owner、来源和 replay 的替代证据。

## 结算与顺序不变量

1. S16/S17 并集等于当前 gameplay 全集，交集为空，source fingerprint 当前。
2. 所有 mutation 经 P7 原子 transition；缺目标、来源、参数或 unsupported 分支时 state unchanged。
3. 静态面板和当前状态先确定，条件再求值，mutation plan 在提交前校验；任何前置状态变化使旧计划失效。
4. 队伍效果真正作用目标单位，不存成 wearer 私有标志冒充。
5. 跨波次 provider 生命周期和重新触发由真实事件定义；不重复启动永久效果。
6. 多个独立 RNG 事件具有稳定 identity，外部推演器只选择分支，不计算概率/效果。
7. 每个 mutation 可回到 set threshold、来源实例集合、wearer、graph 节点和 raw source。

## 目标与证据映射

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 剩余集合可信 | S16 当前且 S16/S17 穷尽互斥 | inherited partition check |
| S17 family 零 gap | 每行 raw/lowered/admitted/executable/validated 一致 | remaining-family matrix |
| 全套装图可执行 | 当前普通玩家已发布套装 blocked graph 数为零 | full set aggregate |
| 顺序正确 | 面板/条件/plan/mutation 顺序及 stale plan 负例通过 | ordering matrix |
| owner/team/wave 正确 | 多 wearer、队伍、跨波次不串线或重复 | lifecycle attribution matrix |
| RNG/replay 正确 | choice identity 稳定，多事件独立，回放一致 | RNG/replay matrix |
| 来源闭合 | 每个结算族至少一条完整 walkback | audit samples |
| 无专用 runtime | 共享 P7 routes，set-specific handler 为零 | code audit |

## 拟改文件与关键符号

- P7 resource/HP/shield/damage/timeline/wave/target/RNG 通用模块：仅修当前套装触发的共享缺口。
- 通用 ability lowering/admission/settlement；不得添加套装 ID dispatch。
- `builds/equipment_assembler.py`：全图闭合后解除对应 blocker，不执行结算。
- `tools/validate_p8_s17_relic_set_remaining_gameplay_closure.py` 和阶段报告。
- 直接触达的 P7 focused regression fixtures。

修改前用 CodeGraph 跟踪 task -> plan -> transition -> reducer -> settlement 路径。发现需要新通用概念时先建类型化 IR 和失败语义，再接套装来源。

## 结构化验收谓词

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

## Gap 与停止条件

- S17 任一 lowering/admission/implementation/validation gap 非零阻断验收。
- raw 真缺源必须排除扫描、lowering 和谓词错误；若导致已发布套装图不完整，仍阻断 P8。
- 特殊 CUSTOM 套装/模板是否属于普通玩家构筑必须沿 S9 分类诚实处理；不能从 aggregate 静默过滤。
- 当前套装触发的 wave/target/resource 底层缺口不是 deferred，必须修复或保持阶段未通过。
- 若跨轨光锥分支也修改同一共享 runtime，合并前必须人工处理并运行双方直接回归，禁止自动选择一方。

## 验证命令与资源

```bash
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p8_s17_relic_set_remaining_gameplay_closure --tbgd-root ../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s17_relic_set_remaining_gameplay_closure
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p7_s12_damage_toughness_pipeline --output-dir /tmp/hsr_v8_p8_s17_p7_damage_regression
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p7_s13_shield_hp_routing --output-dir /tmp/hsr_v8_p8_s17_p7_hp_regression
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p7_s10_timeline_control_semantics --output-dir /tmp/hsr_v8_p8_s17_p7_timeline_regression
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p7_s17_wave_lifecycle_events --output-dir /tmp/hsr_v8_p8_s17_p7_wave_regression
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p7_s15_rng_identity_replay --output-dir /tmp/hsr_v8_p8_s17_p7_rng_regression
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s17_pycache python3 -m compileall -q hsr/simulator_v8_clean_core
git diff --check
```

S17 主验证必须从当前源码重新生成并核对 S16/S17 分区，已验收 S16 报告只作为证据索引，不能依赖历史 `/tmp` summary。主聚合只允许一次 focused full set ability build，所有重验证串行。只跑实际触达专项；未修改的共享模块可由主验证等价矩阵替代并说明。禁止 P1-P7 聚合和 `validate_v0_209`，除非直接修改其独有 schema 并获确认。

## Ready-for-review 产物

- 当前 source fingerprint、S16/S17 联合集合和全套装零 gap aggregate。
- S17 各结算族 transition/negative/replay 索引和 non-gameplay 排除。
- ordering/stale plan、多 wearer/team/wave/RNG 证据。
- 每类 mutation 来源反查、共享底座 diff、回归和资源报告。

## 唯一执行清单（仅验收线程可勾）

- [ ] S16/S17 合集完整覆盖当前套装 gameplay，交集为空且指纹当前。
- [ ] S17 各 family 和普通玩家已发布套装完整图严格零 gap、零 unknown。
- [ ] 资源、HP、伤害、行动、队伍、波次、目标和 RNG 全部走通用系统。
- [ ] 面板/条件/计划/mutation 顺序与 stale plan 失败语义正确。
- [ ] 多 wearer、跨波次、队伍目标和 replay 不串线，来源反查完整。
- [ ] 无套装专用 runtime、固定 ID、文本解释或部分执行。
- [ ] `ready_for_review` evidence、回归和资源审计完整。
