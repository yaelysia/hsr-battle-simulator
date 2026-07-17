# P8-S7 光锥状态、条件与监听闭合 ready_for_review

## 状态

- 结论：`ready_for_review`。
- 基线：P8-S6 检查点 `15088be`。
- 本轮没有修改 P8 Checklist，没有创建 Git commit，没有进入 P8-S8。
- 两份无关 UI 草稿保持未提交、未修改。

## 本阶段产物

- 新增按 raw task、condition、event、target、value 结构与消费语义分类的装备能力 family 账本；分类不依赖光锥、角色、能力或技能 ID。
- 正式 lowering 只读取已发布光锥目录绑定的装备能力记录，并把对应 modifier、callback、condition、target 和动态值来源投影进 Canonical IR。
- 纯 S7 图可以正式准入；同时包含 S8/unknown 分支的图整体 blocked，不执行局部 S7 分支。
- 状态新增、叠层、来源声明的 Replace 刷新、显式移除、自移除和到期均复用 P2 通用生命周期、Mutation、settlement、source audit 与 replay。
- 条件统一通过 `RuleEvaluator` 求值；false 是正常无效果结果，缺字段、缺目标、缺上下文或未准入分支 fail-closed。
- listener 与动态值写入复用通用 callback/event/value 底座；多 wearer、实际 owner、敌我与队伍目标均按实例归属。
- `RemoveSelfModifier` 的目标来自 opcode 的“当前 modifier owner”语义。IR evidence 明确记录这是 opcode 派生语义且 raw 无显式 `TargetType`，没有伪装成 TBGD 原始目标字段。

## 本轮复核阻断修复

- postfix 一元 opcode 14 已按结构化表达式投影为 `negate`，规则求值器执行取负；验证逐条核对真实装备来源中的同类节点，不按光锥 ID 选样。
- 新增通用有效属性读取入口。正式角色单位保留基础值、静态百分比和静态固定值三池，战斗中动态贡献再按 `base × (1 + static% + dynamic%) + static_flat + dynamic_flat` 归并；伤害、行动条、状态概率及相关公式不再对最终面板二次乘算。
- 正式 ScenarioStateBuilder 现在把 provider 注册和 OnStart 效果产生的 mutation、settlement、event、RNG 一并暴露在构建结果中；公开 mutation 可以从启动前状态重放到最终状态，并通过来源审计。
- 正式场景的时间线初始化 mutation 也有独立 `scenario_setup` settlement 与来源策略；总摘要直接依赖正式场景矩阵的整体 `ok`，不能再由“角色进入战斗”掩盖启动链失败。
- callback group、callback 与 predicate 子任务改为事务式执行；前置任务成功而后续任务失败时，状态、mutation、event、RNG 和“已生效”settlement 全部回滚，只保留 process-only blocked 记录。
- 技能类型、攻击类型等必要上下文缺失时条件直接 blocked；显式 callback 目标解析失败时不再回退到装备者本人。
- `AliveOrRevivable` 在内核尚无可复活状态时保持 blocked 并归入 S8；没有把它降格成单纯“存活”。普通敌方全体与状态回调统一使用同一不可选判断，显式 `WithUnSelectable` 目标族才会包含不可选单位。
- 属性节点按实际消费语义拆分。S7 只接纳攻击、防御、速度、暴击和效果命中/抵抗；能量恢复、治疗、护盾、仇恨、追加攻击、持续伤害和额外击破等尚无对应结算消费的属性完整移交 S8。
- 事件矩阵从真实 action、damage、toughness、break、HP、defeat、status lifecycle 与正式 battle setup 生产链取得事件。每个 S7 callback 来源均逐条闭合到 RuleBook 和原始行；每个事件 family 至少有一个非 blocked 的真实生产事件派发代表，不再把手工事件或 blocked 结果算作成功。
- 显式概率但缺少状态类别来源的回调不会被推测成 debuff：若既无状态表类型也无明确 DOT、属性升降、控制或护盾 behavior flag，则连同完整来源归入 S8。当前 `OnBeforeBeingBreak` 样本因此诚实 blocked。
- 目标参与资格与实际战斗阵营均已下沉为共享类型化判定：召唤单位按来源中的 `team_side` 归属，不按 `side=summon` 猜测。正式 target、condition 和 callback group 统一识别四种已准入的不可选标记，统一排除 defeated、removed、未在场或来源未准入的召唤单位，并按单位身份稳定排序。验证同时放入双方在场召唤物、真实 removed 单位并反转插入顺序，三条消费链结果保持一致。
- 命中监听拆成独立生产窗口：整次攻击者命中序列、每个受击目标的攻击/命中序列和逐段命中分别产生不同 runtime event。回调名不写入生产事件 payload，而由来源闭合的 status event family 在 RuleBook 中绑定。双段真实 action 验证逐项固定前后顺序与 `1/1/1/2/2/1/1/1` 窗口次数。
- `UnitState` 属性池现在在公开构造和 JSON 解码边界强制属性唯一、规范排序、受支持的面板字段以及 `base × (1 + static%) + flat` 重算一致。重复属性、调换顺序、仅篡改最终面板，以及同类 JSON 篡改六项负例均直接失败；runtime 不再依赖“取第一个池”的遍历顺序。

## 实时来源与分区

当前完整内容指纹：

```text
algorithm=sha256-path-and-full-content-v1
file_count=24
byte_count=3034164
sha256=39b5d5d55a5d4d7e9a3739a5de098944b5851593de0f2311ffa661fe384a346a
```

实时扫描结果：

```text
published_light_cones=162
equipment_ability_files=14
equipment_graphs=162
raw_family_nodes=4472
s7_nodes=986
s8_nodes=3470
non_gameplay_nodes=16
unknown_gameplay_nodes=0
family_rows=287
s7_family_rows=66
status_callbacks=521
status_callback_tasks=1221
```

图级准入结果：

```text
pure_s7_executable_graphs=18
mixed_or_s8_blocked_graphs=144
coverage_gap_count=0
```

分区并集覆盖全部 gameplay 节点、交集为空；16 个 non-gameplay 节点均保存结构化理由。S8 的伤害、治疗、护盾、资源、行动、复杂目标与 RNG 分支仍整体 blocked，并完整留在继承账本中。

## 行为证据

- 19 个实际 S7 条件 family 形成 84 个运行时 case，覆盖 true、false、缺结构/未准入 blocked。
- 13 个结构化动态任务 family 直接验证成功写入、真实来源和缺上下文 blocked。
- 6 个生命周期 case 覆盖 add、Replace refresh、stack、`RemoveModifier`、`RemoveSelfModifier`、expiry。
- 每个生命周期样本均通过 mutation/settlement 来源审计和 replay equality。
- 正式 ScenarioStateBuilder 链验证单位创建后注册 provider、OnStart 状态建立、事件分发、公开 setup 账本重放、来源审计、快照恢复和重复构建不重复注册。
- 有效属性矩阵逐条关联真实 `StackProperty` 来源及其消费语义，直接验证攻击、防御、速度/行动条、暴击、效果命中/抵抗以及真实减防一元公式进入实际战斗消费侧；`100 + 20% + 10 flat + 20% dynamic = 150` 有独立池化负例。
- 部分 callback 成功后失败、缺攻击上下文、显式未知目标、普通/含不可选全体差异均有状态不变负例。
- 目标矩阵额外覆盖 `unselectable`、`target_unselectable`、`is_unselectable`、`selectable=false`，以及友方在场 summon、敌方在场 summon、defeated、实际存在于状态中的 removed、离场 summon 和反向插入顺序；敌方全体、亮方全体、暗方全体、同队全体与同队其他成员在 target、condition、callback 三条链路中的结果完全一致。
- 双段 action 的生产事件顺序固定为：整次命中前、目标受击前、目标整次命中前、第一段前/后、第二段前/后、目标整次命中后、目标受击后、整次命中后；每个事件均继续进入 dispatch、settlement、source audit 和 replay。
- 属性池负例在模型与 codec 两层各覆盖重复属性、非规范顺序和最终面板矛盾；正确池仍验证 `100 × (1 + 20% + 20%) + 10 = 150`，排列不再改变结果。
- unsupported selected branch 验证整批 state unchanged；没有装备专用 runtime handler。

当前 raw 已发布光锥没有独立 `Refresh` opcode 正例，因此本阶段没有合成该正例；刷新证据明确标注为来源声明的 `Replace` 行为。

## 聚焦验证结果

主验证串行低优先级运行：

```text
ok=true
ready_for_review=true
all structure predicates=true
artifact_byte_count=4555395
focused_rulebook_build_count=2
full_canonical_ir_serialized=false
transition_dump_written=false
```

产物目录：

```text
/tmp/hsr_p8_s7_summon_allegiance_fix
```

其中包含 family partition/coverage、condition、event timing、formal scenario attribution、target/multi-wearer、lifecycle audit/replay、structured dynamic task 和 unsupported atomic 矩阵。默认未写完整 CanonicalIR 或全量 transition dump。

本轮三项阻断修复后直接回归：

```text
P7-S9 phase machine: ok=true, rows=7
P7-S3 atomic commit: ok=true, cases=9
P7-S7 target contract: ok=true, rows=6, negative_cases=10
P2-S4 status lifecycle: ok=true
P5-S4 ValueResolver admission: ok=true, rows=7, blocked_negative_cases=6
compileall: passed
git diff --check: passed
```

P2-S4 与 P5-S4 均串行低优先级运行；P7 三项 fixture 在其后串行运行。S7 主验证自身仅写 11 份聚焦矩阵，共 4,555,395 字节，不序列化完整 CanonicalIR 或 transition dump。

召唤阵营修复另有一个纯内存小探针：在两个相反插入顺序中同时放入友方召唤物、敌方召唤物和 removed 单位，逐一比较 target、condition、callback 的 `AllEnemy`、`AllLightTeam`、`AllTeamMember` 结果，全部一致。随后串行重跑 P7-S7 target contract，结果仍为 `ok=true, rows=6, negative_cases=10`。

S6 回归已迁移到当前事实：S6 provider 生命周期 fixture 仍只验证 provider 边界，正式 ScenarioStateBuilder 正例则复用 S7 的真实 modifier/event 闭包；报告不再固定宣称 S7 未开始或全部图均 partial。当前 18 个 executable 与 144 个 blocked 图形成无损分区。

未运行 P2/P5/P7 聚合、P8-S8 全结算、`validate_v0_209` 或任何无关重验证。

## 当前边界

- 最小可用战斗纵切新增 18 个纯 S7 光锥图：可完成动态 provider 注册、状态建立、条件判断与 listener 触发。
- 144 个包含 S8 分支或缺少必要概率分类来源的图仍严格阻止正式战斗，没有部分执行。
- 距离完整光锥复刻仍缺 P8-S8 的伤害、治疗、护盾、资源、行动、复杂目标与 RNG 结算族；遗器、套装和最终构筑轨仍按后续阶段处理。
