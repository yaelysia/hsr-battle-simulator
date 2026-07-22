# P8-S8 光锥剩余 gameplay 机制闭合执行卡

## 执行配置

- 对应问题：P8-I07 剩余 gameplay 机制。
- 硬前置：P8-S7 已验收，其 S7/S8 分区账本已绑定当前 source fingerprint。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`max`。
- 推荐模式：Goal 模式，目标严格限定为本卡；光锥轨独立 worktree。
- 选择理由：本阶段跨伤害、资源、HP、护盾、目标、时间线、召唤关系和 RNG，是光锥轨最复杂的机制闭合阶段，需要长时间自主执行和最高推理。

## 当前事实与阶段结果

S7 已关闭属性、状态、条件和监听类 family，并留下精确的 S8 剩余集合。开始时必须用当前源码重新验证 S7 摘要、source fingerprint 和分区集合，拒绝旧 `/tmp`、空集合和手写 gap=0。

完成后，当前全部已发布光锥 gameplay 图本身都能作为完整图通过装备侧 admission，并通过现有通用结算系统执行。S7 与 S8 合集覆盖全量 gameplay，`lowering_gap`、`admission_gap`、`implementation_missing`、`validation_gap` 和 unknown gameplay 均为零；每个结算族有真实正例、失败分支、来源审计和 replay。

光锥机制完整与“所有命途当前都有可进入战斗的角色构筑”是两个不同事实。若某命途没有可用角色构筑，只有在空装备角色装配结果明确表明：角色面板已经装配、装备结果已准入、唯一阻断原因是角色所属派生战斗单位尚未构筑时，才允许记为 `external_character_build_dependency`。该项不阻断 S8 的光锥机制闭合，但必须保持可见，并继续阻断全目录正式角色入战完成声明。不得把它记为已启动、装备成功案例或零缺口 P8 总验收。

## 本阶段只做

- 继承并关闭 S8 剩余 family：伤害修正/附加伤害、治疗、护盾、战技点/能量等资源、生命变化、行动延后/拉条、队伍和特殊目标、目标变换、独立 RNG。
- 复用 P7 统一伤害/HP/护盾/资源/target/timeline/RNG 路由，缺通用语义则在共享层修复。
- 检查 actual owner、wearer、队伍成员、召唤物/servant 等真实目标关系，不默认效果只作用装备者。
- 为每个独立随机决策建立稳定 `choice_key`/event identity，支持外部指定分支和 replay。
- 对纯客户端/动画节点逐项给出结构化排除，不留 unknown gameplay。
- 运行一次当前源码 focused 光锥 ability aggregate，证明完整图可 admission 和执行。
- 对每个已发布光锥给出目录启动分类：使用同命途真实角色完成正式启动，或以结构化证据记录独立角色构筑外部依赖；装备侧失败必须为零。

## 本阶段不做

- 不实现装备之外的角色/怪物全量内容；但光锥真实依赖的共享底座缺口必须在本阶段解决。
- 不在 S8 内实现记忆角色及忆灵的 owned-combatant 构筑；该工作归独立角色构筑任务。除这一种被结构化证明的角色侧依赖外，其他匹配角色缺失仍视为 S8 验收失败。
- 不建立光锥专用伤害公式、资源系统、目标解析器或随机系统。
- 不让 UI/推演器计算规则结果；它们只能选择合法动作、目标或 RNG 分支。
- 不用 S7 摘要替代当前源码检查，不把 unknown 批量标成 client-only。

## 机制与原子性不变量

1. S7/S8 并集必须等于当前 gameplay 全集，交集为空，任何新增能力文件或节点都会使摘要失效。
2. 图内所有 gameplay 节点一起 admission；不允许仅执行已支持部分。
3. 伤害、治疗、护盾、资源和行动 mutation 必须由通用 transition 生成 settlement，不能从日志反推。
4. 条件失败和目标集合为空按真实语义产生 no-effect/blocked；缺目标规则或非法目标必须 state unchanged。
5. 同一图中的多个 RNG 决策、多个 wearer 和多目标事件 identity 不得串线；replay 必须消费同一 choice ledger。
6. 召唤物/servant 是否受益由 action/target/owner IR 决定，不用“通常只作用角色”默认。
7. 任一 mutation 必须可回到光锥实例、叠影参数、能力图节点和 raw source。

## 目标与证据映射

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 剩余集合可信 | 与已验收 S7 合集穷尽当前 gameplay，指纹一致 | inherited partition check |
| 每个 S8 family 可执行 | raw/lowered/admitted/executable/validated 数一致且非空 family 有真实 transition | remaining-family matrix |
| 完整图 admission | 当前发布光锥 blocked gameplay graph 数为零 | full graph aggregate |
| 目录启动分类诚实 | 装备侧失败为零；未正式启动项只能是有角色装配诊断证明的 owned-combatant 外部依赖 | catalog startup matrix |
| 结算路由通用 | 无 equipment 专用 reducer/formula；代表结算进入 P7 pipeline | code audit + settlement samples |
| 目标和 owner 正确 | wearer/team/enemy/summon 关系按 IR 执行 | target attribution matrix |
| RNG 可推演可回放 | 独立 choice identity、指定分支和 replay 一致 | RNG ledger matrix |
| 来源闭合 | 每类 mutation 至少一条完整 walkback | audit samples |
| 非 gameplay 诚实 | 每个排除节点有结构证据，unknown 为零 | exclusion ledger |

## 拟改文件与关键符号

- P7 damage/HP/shield/resource/target/timeline/RNG 的现有通用模块：只修被真实光锥触发的共享缺口。
- 通用 ability task/effect lowering 和 admission；不得增加光锥专用 task 分发。
- `builds/equipment_assembler.py`：在全图闭合后解除对应 battle blocker，不执行结算。
- `tools/validate_p8_s8_light_cone_remaining_gameplay_closure.py`：剩余机制和全光锥 aggregate。
- 直接触达的 P7 focused fixtures 和阶段报告。

修改前使用 CodeGraph 从能力 task 到 transition/reducer/settlement 追踪实际路径。若一个能力需要尚不存在的通用概念，应先明确建模，不得以单件光锥特判完成。

## 结构化验收谓词

```text
s7_evidence_current=true
s7_s8_union_equals_current_gameplay=true
s7_s8_intersection_empty=true
s8_remaining_family_gap_count=0
published_light_cone_blocked_graph_count=0
unknown_gameplay_node_count=0
non_gameplay_rows_have_structured_evidence=true
damage_hp_shield_resource_use_common_routes=true
target_owner_summon_relations_source_driven=true
rng_choices_have_stable_identity=true
independent_rng_events_do_not_collide=true
blocked_transition_state_unchanged=true
sampled_mutations_source_audited=true
sampled_transitions_replay_equal=true
equipment_specific_runtime_handlers=0
catalog_equipment_failure_count=0
catalog_external_dependencies_structurally_proven=true
catalog_started_or_external_dependency_covers_catalog=true
```

`formal_catalog_startup_complete` 和 `catalog_external_character_build_dependency_count` 必须同时输出为事实字段，但前者在独立角色构筑任务完成前允许为 `false`，后者允许非零。二者不能从报告中删除，也不能改名伪装成全部正式启动完成。

## Gap 与停止条件

- 任何 S8 family 的 lowering/admission/implementation/validation gap 非零都阻断 S8。
- raw 真缺源只有在全能力文件和关联表扫描、lowering 审计及谓词复核后才能成立；若导致已发布光锥图不完整，仍阻断 P8。
- 历史 P2/P3/P7 backlog 只要被当前已发布光锥真实触发，就不再是 deferred，必须修复或保持阶段未通过。
- 发现需要角色卡/怪物卡特有规则才能解释且来源不在光锥图时，不得猜测；停止并报告跨内容归属问题。
- 匹配角色缺失只有在至少一个真实同命途空装备角色满足“角色装配完成、装备已准入、诊断全部且仅为 owned-combatant 构筑缺失”时，才可归为外部角色依赖；否则仍是当前阶段失败。

## 验证命令与资源

先跑主聚合，绿后才串行跑实际触达回归：

```bash
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p8_s8_light_cone_remaining_gameplay_closure --tbgd-root ../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s8_light_cone_remaining_gameplay_closure
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p7_s12_damage_toughness_pipeline --output-dir /tmp/hsr_v8_p8_s8_p7_damage_regression
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p7_s13_shield_hp_routing --output-dir /tmp/hsr_v8_p8_s8_p7_hp_shield_regression
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p7_s10_timeline_control_semantics --output-dir /tmp/hsr_v8_p8_s8_p7_timeline_regression
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p7_s15_rng_identity_replay --output-dir /tmp/hsr_v8_p8_s8_p7_rng_regression
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p3_s8_summon_target_relations --tbgd-root ../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s8_summon_target_regression
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s8_pycache python3 -m compileall -q hsr/simulator_v8_clean_core
git diff --check
```

S8 主验证必须从当前源码重新生成并核对 S7/S8 分区，已验收 S7 报告只作为证据索引，不能依赖历史 `/tmp` summary。只运行实际触达的专项；若未修改某共享模块，可由主验证等价矩阵替代并说明。主聚合最多一次 focused full light-cone ability build，不落完整图或 transition。禁止并行重验证、P1-P7 聚合和 `validate_v0_209`，除非直接修改其独有 schema 且先获用户确认。

## Ready-for-review 产物

- 当前 source fingerprint 和 S7/S8 联合集合证明。
- 全光锥 gameplay coverage、non-gameplay 排除和零 gap summary。
- 每个 S8 结算族的真实 transition/negative/replay 索引。
- mutation 来源反查、owner/target/RNG 独立性样本。
- 共享底座修改、直接回归和资源使用报告。

## 唯一执行清单（仅验收线程可勾）

- [x] S7/S8 合集完整覆盖当前 gameplay，交集为空且 source fingerprint 当前。
- [x] S8 所有 family 与全部已发布光锥完整图均达到 executable，装备侧严格 gap 为零。
- [x] 全目录启动结果逐项分类；正式启动项真实通过，外部角色构筑依赖有结构化证明且未伪装为正式启动完成。
- [x] 伤害、HP、护盾、资源、行动、目标、召唤关系和 RNG 全部复用通用系统。
- [x] 非 gameplay 有逐项结构证据，unknown 为零。
- [x] 代表 mutation 均有 settlement、来源反查和 replay，失败分支 state unchanged。
- [x] 无光锥专用 runtime、固定 ID、文本解释或部分执行路径。
- [x] `ready_for_review` evidence、回归和资源审计完整。
