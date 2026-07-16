# P8-S7 光锥属性、状态、条件与监听机制闭合执行卡

## 执行配置

- 对应问题：P8-I07 第一批 gameplay 机制。
- 硬前置：P8-S6 已验收，动态能力图和启动入口真实可用。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`max`。
- 推荐模式：Goal 模式，目标严格限定为本卡；光锥轨独立 worktree。
- 选择理由：需要遍历当前全部已发布光锥能力并可能回修状态、条件和事件共享底座，耗时长且跨系统；Goal 适合持续推进，但禁止自动进入 S8。

## 当前事实与阶段结果

S0 保存装备能力机制基线，S6 应建立当前源码下的真实图和参数入口。开始时必须重新从当前 source fingerprint 和 Canonical IR 生成 family inventory，不能直接信任历史 S0 数量，也不能按光锥名称手工列清单。

完成后，分配给 S7 的全部已发布光锥 gameplay family 均通过通用属性、状态、条件、动态值和事件监听系统执行。每个 family 有完整来源总数、admitted/executable 数、真实正例、条件失败负例和缺源/unsupported 负例；本阶段范围内 `lowering_gap`、`admission_gap`、`implementation_missing`、`validation_gap` 全为零。

S7 不负责伤害、治疗、护盾、资源、行动条、复杂目标和 RNG 等 S8 结算族，但必须输出一份互斥且穷尽的 S7/S8 分配账本。

## 本阶段只做

- 从当前能力图按 raw task、condition、event、target 和 value family 生成 S7/S8 分区，验证无遗漏、无重叠、非空。
- 接通真实使用的属性堆叠、modifier 添加/移除、状态生命周期、动态值定义/复制/比较。
- 接通生命比例、技能类型、目标队伍、状态数量等真实条件，条件真假都经 IR 求值。
- 接通本阶段真实出现的 OnStart、OnStack、OnEnterBattle、OnHPChange、攻击前后、受击、击杀等事件源。
- 验证 wearer、自身状态、敌方状态、队伍目标、actual owner 和多个 wearer 的归属。
- 通用底座缺语义时在 P2/P5/P7 层修复，不在装备层增加 handler。
- 对每个产生 mutation 的 family 抽取来源反查和 replay 样本。

## 本阶段不做

- 不处理 S8 分区中的直接/附加伤害、治疗、护盾、资源、行动、目标变换和 RNG。
- 不为某件光锥建立专属函数、ID switch、名称匹配或文本解释。
- 不把 unknown、未 lower 或验证未覆盖项归为 non-gameplay/source gap。
- 不因某个容易样例通过就按 raw type 粗粒度宣称整个 family 完成。

## Family 闭合规则

1. family 身份至少由 raw task/condition/event 结构和消费语义共同决定；同一个 `$type` 的不同分支不能被一个样例代替。
2. S7/S8 分区必须以当前发现全集为基准，集合并集等于 gameplay 全集、交集为空；新增源码条目必须使旧摘要 stale。
3. `non_gameplay` 必须有明确字段/节点语义证据；未知节点不能批量归 client-only。
4. 条件为 false 是正常 committed/no-effect 分支，不应 blocked；条件缺字段、目标不完整或 selected graph unsupported 才 blocked。
5. 状态叠层、持续时间、刷新和移除遵循 P2 通用生命周期，不按装备文本另写默认值。
6. 一个图包含 S7 已支持节点和 S8 未支持节点时，正式 battle admission 仍 blocked，直到 S8 闭合；S7 只证明自己的 family，不允许部分战斗。

## 目标与证据映射

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 当前 family 全集可信 | 实时 source fingerprint；发现文件集合非空；S7/S8 穷尽且互斥 | family partition ledger |
| S7 family 零 gap | 每行 raw/lowered/admitted/executable/validated 数相等 | coverage matrix |
| 条件语义正确 | true/false/缺结构三种结果区分 | condition matrix |
| 状态生命周期正确 | add/stack/refresh/remove/expiry 按真实来源覆盖 | lifecycle samples |
| 监听时机正确 | 注册一次，在真实阶段触发且不重复 | event timing matrix |
| owner/target 正确 | wearer、敌人、队伍和多 owner 不串线 | attribution matrix |
| 来源与回放闭合 | mutation -> settlement -> graph -> raw source，replay 相同 | audit/replay samples |
| 通用性未退化 | 直接触达的 P2/P5/P7 回归通过，无装备专用 handler | code audit + regressions |

## 拟改文件与关键符号

- 通用 ability lowering/condition/event/value IR 和 RuleBook；具体文件由 CodeGraph 调用链确定。
- P2 状态 lifecycle、P5 ValueResolver、P7 event phase/executor/target relation：只修真实共享缺口。
- `builds/equipment_assembler.py`：更新 family admission，不解释具体效果。
- `tools/validate_p8_s7_light_cone_status_condition_listener_closure.py`：主验证和当前 family 总账。
- 对应的聚焦 regression fixture 与 `v8_p8_s7_..._ready_for_review.md`。

禁止新建 `light_cone_handlers.py` 一类按装备分发的 runtime 模块。若现有架构无法在通用层表达某 family，必须报告设计缺口，而不是局部绕过。

## 结构化验收谓词

```text
current_gameplay_inventory_non_empty=true
s7_s8_partition_complete=true
s7_s8_partition_disjoint=true
s7_family_gap_count=0
s7_unknown_gameplay_count=0
s7_non_gameplay_has_structured_evidence=true
condition_false_is_not_blocked=true
unsupported_selected_branch_blocks_atomically=true
listener_registration_idempotent=true
status_mutations_follow_common_lifecycle=true
owner_target_attribution_correct=true
all_sampled_mutations_source_audited=true
all_sampled_transitions_replay_equal=true
equipment_specific_runtime_handlers=0
```

## Gap 与停止条件

- raw 有结构而 IR 缺失：`lowering_gap`，本阶段必须修。
- IR 有节点但 admission 未接：`admission_gap`，本阶段必须修。
- 通用状态/条件/事件不能执行：`implementation_missing`，本阶段修通用层并回归。
- 实现存在但 family 总账或正例不足：`validation_gap`，不得以 blocked 代替正例。
- 只有完整扫描证明 raw 不含所需来源时才可 `source_gap_blocked`；若影响已发布光锥完整图，仍阻断本阶段和 P8。
- 新发现 family 无法明确分配 S7/S8，或需要角色/装备特判时，停止并交回规划线程。

## 验证命令与资源

主验证允许一次 focused 全光锥 ability build，但 transition 只跑结构抽样，全部串行低优先级：

```bash
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p8_s7_light_cone_status_condition_listener_closure --tbgd-root ../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s7_light_cone_status_condition_listener_closure
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p2_s4_status_lifecycle --tbgd-root ../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s7_p2_lifecycle_regression
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p5_s4_value_resolver_admission --tbgd-root ../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s7_p5_value_regression
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p7_s9_explicit_turn_event_phase_machine --output-dir /tmp/hsr_v8_p8_s7_p7_phase_regression
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p7_s3_selected_graph_atomic_commit --output-dir /tmp/hsr_v8_p8_s7_p7_atomic_regression
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s7_pycache python3 -m compileall -q hsr/simulator_v8_clean_core
git diff --check
```

按实际改动追加 P2 状态概率/驱散、P7 target 或 wave 专项；未触达则不跑。不得运行 P2/P5/P7 聚合、S8 全结算或 `validate_v0_209`。验证 summary 必须记录读取文件数、能力图数、各 family case 数、RuleBook build 次数和输出大小。

## Ready-for-review 产物

- 当前 source fingerprint 下的完整 S7/S8 分区账本。
- S7 family coverage、condition/event/status 负例、代表 transition、source audit、replay。
- 通用底座修改的调用链和直接回归结果。
- S8 继承的准确 family 行，不得混入 S7 gap。
- 未关闭 blocker；若非零，不得声称本卡可验收。

## 唯一执行清单（仅验收线程可勾）

- [ ] 当前 gameplay 全集已实时发现，S7/S8 分区穷尽、互斥且防空。
- [ ] S7 每个 family 的 lowering、admission、implementation、validation gap 均为零。
- [ ] 条件真假、状态生命周期、事件时机、owner/target 与多 wearer 均有真实正负例。
- [ ] 代表 mutation 的 settlement、来源和 replay 完整闭合。
- [ ] 未新增装备专用 runtime 或文本/ID 特判，通用底座回归通过。
- [ ] S8 未支持节点仍阻断完整图，没有部分执行。
- [ ] `ready_for_review` evidence 与资源审计完整。
