# P8-S16 套装属性、状态、条件与监听机制闭合执行卡

## 执行配置

- 对应问题：P8-I13 第一批 gameplay 机制。
- 硬前置：P8-S15 已验收，套装动态图、参数和启动入口真实可用。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`max`。
- 推荐模式：Goal 模式，目标严格限定为本卡；遗器轨独立 worktree。
- 选择理由：需要全套装能力扫描，并可能修复状态、动态条件、事件重评、多 wearer 和波次事件共享底座，适合长目标和最高推理。

## 当前事实与阶段结果

S15 应留下当前套装 gameplay family 总账，动态图仍可能因 unsupported family 阻止正式战斗。开始时必须从当前 source fingerprint 重新生成全集，并与 S15 账本核对，不能信任历史 S0 数量或套装名称列表。

完成后，分配给 S16 的全部套装属性、modifier、状态、动态值、条件和监听 family 都通过通用 P2/P5/P7 系统执行。静态面板条件、入场条件、战斗中状态/属性变化重评、多个 wearer 和队伍目标均有真实正负例。本阶段范围严格零 lowering/admission/implementation/validation gap，并输出与 S17 互斥穷尽的分区账本。

## 本阶段只做

- 按 raw task/condition/event/value/target 结构生成 S16/S17 family 分区，集合防空、互斥、穷尽。
- 接通真实套装使用的属性变化、modifier/status 生命周期、动态值和比较条件。
- 覆盖速度、生命比例、攻击类型、状态数量、目标队伍、波次/回合等真实条件，不用 UI 预计算。
- 覆盖入场成立/不成立、战斗中重新满足/失效、状态移除后的重评时机。
- 验证 wearer 与 team/enemy/actual owner attribution；多个 wearer 按 raw stacking/uniqueness 规则执行。
- 若真实 family 暴露共享 event/condition 缺口，在通用层修复并跑直接回归。
- 为代表 mutation 生成 settlement、source audit 和 replay。

## 本阶段不做

- 不处理 S17 的资源、治疗、生命变化、伤害、行动、剩余目标/RNG 结算族。
- 不按套装 ID/名称写 handler，不从描述提取门槛或 stacking。
- 不只测试入场快照后声称动态条件完成。
- 不把 unknown、未 lower 或验证未覆盖项标成 non-gameplay/source gap。

## Family 与生命周期不变量

1. S16/S17 并集等于当前套装 gameplay 全集，交集为空；source fingerprint 变化使摘要 stale。
2. 条件值由当前战斗状态和 IR 在正确事件阶段求值；UI/preset 不能提交 `condition_met`。
3. 条件 false 是正常 no-effect，不 blocked；缺结构、unsupported target/event 或矛盾来源才 blocked。
4. 条件何时重评由真实 callback/event 图决定，不能每帧轮询或永远锁定入场快照。
5. 多 wearer 的同类效果按 raw modifier stacking/unique identity 处理，不无条件相加或覆盖。
6. 一张完整图含 S17 未支持节点时正式 battle admission 仍 blocked，S16 不能部分执行。
7. 状态 mutation 必须走 P2 生命周期并能追溯到 set threshold、wearer 和 raw graph。

## 目标与证据映射

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 当前 family 分区可信 | S16/S17 穷尽互斥且非空，绑定实时指纹 | family partition ledger |
| S16 零 gap | 每行 raw/lowered/admitted/executable/validated 数一致 | coverage matrix |
| 动态条件正确 | 入场 true/false、战中满足/失效和缺结构分开 | lifecycle condition matrix |
| 多 owner/队伍正确 | 多 wearer stacking、team target 和 actual owner 不串线 | attribution matrix |
| 事件时机正确 | 波次/回合/攻击/状态变化在真实 phase 触发一次 | event timing matrix |
| 来源/回放闭合 | 代表 mutation 完成 walkback 和 replay | audit/replay samples |
| 通用性 | 无 set handler/轮询，P2/P5/P7 触达回归通过 | code audit |

## 拟改文件与关键符号

- 通用 ability condition/value/event/status lowering 和 runtime；实际文件由 CodeGraph 调用链确定。
- P2 status、P5 ValueResolver、P7 event phase/wave/target relation：仅修真实共享缺口。
- `builds/equipment_assembler.py`：更新 S16 family admission，不解释具体效果。
- `tools/validate_p8_s16_relic_set_status_condition_listener_closure.py` 和阶段报告。

禁止新增 `relic_set_handlers`、按套装 switch 或运行时文本解释。若共享内核模型不足，先建立通用 IR/语义并补非装备回归。

## 结构化验收谓词

```text
current_set_gameplay_inventory_non_empty=true
s16_s17_partition_complete=true
s16_s17_partition_disjoint=true
s16_family_gap_count=0
s16_unknown_gameplay_count=0
conditions_read_runtime_state=true
condition_false_is_not_blocked=true
condition_lifecycle_re_evaluates_on_real_events=true
multi_wearer_stacking_source_driven=true
team_and_owner_attribution_correct=true
listener_registration_idempotent=true
unsupported_selected_branch_blocks_atomically=true
sampled_mutations_source_audited=true
sampled_transitions_replay_equal=true
set_specific_runtime_handlers=0
```

## Gap 与停止条件

- raw 有来源、IR 缺投影：`lowering_gap`，本阶段修。
- IR 完整但 condition/event 未 admission：`admission_gap`，本阶段修。
- 通用系统无法重评/stack/target：`implementation_missing`，修共享层并直接回归。
- 只有验证没覆盖：`validation_gap`，不得用 blocked 代替真实正例。
- 波次/事件源若 raw 和 IR 确实存在，不能以历史 backlog 为由 deferred；当前套装依赖即必须闭合。
- 新 family 无法明确分入 S16/S17 或需套装特判时停止交回规划线程。

## 验证命令与资源

```bash
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p8_s16_relic_set_status_condition_listener_closure --tbgd-root ../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s16_relic_set_status_condition_listener_closure
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p2_s4_status_lifecycle --tbgd-root ../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s16_p2_status_regression
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p5_s4_value_resolver_admission --tbgd-root ../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s16_p5_value_regression
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p7_s9_explicit_turn_event_phase_machine --output-dir /tmp/hsr_v8_p8_s16_p7_phase_regression
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p7_s17_wave_lifecycle_events --output-dir /tmp/hsr_v8_p8_s16_p7_wave_regression
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s16_pycache python3 -m compileall -q hsr/simulator_v8_clean_core
git diff --check
```

主验证允许一次 focused 全套装 ability inventory，但 transition 只做结构抽样。按实际触达选择状态概率、target 或原子提交专项；不得跑阶段聚合、S17 结算或 `validate_v0_209`。summary 记录文件、图、family、case、RuleBook build 和输出大小。

## Ready-for-review 产物

- 当前指纹的 S16/S17 分区、S16 零 gap coverage 和 non-gameplay 分类。
- 动态条件重评、多 wearer、team/owner、event timing 的正负例。
- mutation audit/replay 和共享底座直接回归。
- S17 继承的精确剩余集合及当前完整图 blocker。

## 唯一执行清单（仅验收线程可勾）

- [ ] S16/S17 当前 family 分区穷尽、互斥、防空并绑定实时指纹。
- [ ] S16 每个 family 的 lowering/admission/implementation/validation gap 为零。
- [ ] 条件入场与战中重评、状态生命周期、事件时机均有真实正负例。
- [ ] 多 wearer、队伍目标和 owner attribution 按来源执行。
- [ ] 代表 mutation 来源与 replay 闭合，无套装专用 runtime/文本特判。
- [ ] S17 未支持节点仍阻断完整图，没有部分执行。
- [ ] `ready_for_review` evidence、回归和资源审计完整。
