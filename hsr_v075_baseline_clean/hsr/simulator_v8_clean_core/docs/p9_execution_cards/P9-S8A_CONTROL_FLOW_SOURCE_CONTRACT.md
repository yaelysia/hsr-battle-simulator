# P9-S8A 控制流完整来源与类型化责任目录执行卡

## 执行配置

- 对应问题：P9-I08；机制包 M06 来源与 IR。
- 硬前置：P9-S7 已验收。
- 推荐：5.6 Sol / `max` / 普通聚焦。
- 本卡只改变 compiler 侧来源契约，不改变 runtime、RNG、settlement 或 replay。

## 背景与目标

旧 S8 使用的 `31 / 8,651` 已不是当前权威事实，而且没有区分直接来源节点与为完整分支范围
保留的祖先上下文。S8A 必须从当前完整 snapshot 和 scope catalog 实时重建分母，并对每个直接
控制流/模拟时序节点的每个同级字段作出唯一裁决：

- 进入控制结构；
- 委派给已经存在的条件、目标、数值或 ability 来源契约；
- 交给 S8B/S8C 或 S9-S16 的精确下游责任；
- 经完整分支证明为表现字段；
- 因缺来源、歧义或未知形状 fail-closed。

完成后，S8B 不再扫描项目或猜测 raw 形状，只消费 S8A 的类型化节点、引用、分支、终止依据和
下游义务。

## 权威分母

1. 输入必须是 `CharacterAbilityRawSnapshot` 与同一 snapshot 构建的完整
   `CharacterAbilityScopeProjectionCatalog`。
2. 直接节点分母由 `occurrence_kind=typed_node`、
   `semantic_kind in {combat_control_flow, simulation_sequence}` 且
   `materialization_role=selected` 的实时记录生成；不得使用固定数量、角色名、文件名或旧报告。
3. 结构容器与 `ancestor_context` 单独计数，只证明事件窗口和分支闭合，不重复生成可执行节点；
   结构容器的生产责任归 S9/S8C，不得仅凭 `semantic_kind` 混入 M06 节点分母。
4. 每条记录必须能从 `source_path + json_path` 精确反查 raw 对象，且 `$type` 与 family 一致。
5. 对象中除 `$type` 外的每个同级字段必须恰好出现于一条字段责任记录；未知字段令该节点 blocked。

## 生产模型

建立递归不可变、可稳定序列化的类型化目录：

- 控制节点：来源身份、family、控制角色、直接父子/分支引用、字段责任、覆盖状态和精确 blocker。
- 分支引用：有序分支、case/成功/失败/任务列表/命中回调等来源位置及直接 child 身份。
- template 定义与引用：作用域、名称、动态数值/字符串参数声明、真实定义位置、有序 child、
  唯一解析结果和环诊断；参数声明中的 key、读取序号、读取类型或字符串声明值均须类型化。
- 循环终止依据：来源 count 表达式、有限目标集合或条件进展义务；不得制造默认上限。
- projectile 摘要：只保留目标、命中回调、次数和 per-hit gameplay 字段；物理/视觉字段逐项归表现。
- downstream obligation：精确 owner 为 S8B、S8C 或 S9-S16，保留代表来源；不能写“后续处理”。

目录构造边界必须拒绝重复节点身份、悬空 child、父子来源不一致、同字段多重归属、template
缺失/多候选/递归环、非法数值表达式和伪造来源。blocked 节点不得伪装成 lowered。

## 明确不做

- 不创建或修改 `AbilityTaskSystem`、`StatusCallbackSystem` 的执行行为。
- 不运行循环、选择随机分支、触发 ability 或生成 projectile hit。
- 不把下游 effect blocked 解释成控制流 lowering 失败。
- 不把纯视觉飞行参数、帧数、动画、timeline 名称带入战斗内核。
- 不将完整目录默认塞入 runtime RuleBook；S8B 只 materialize 正式动作需要的节点。

## 验收门

```text
denominator_derived_from_complete_current_scope=true
direct_nodes_and_ancestor_context_separated=true
typed_nodes_and_structural_containers_separated=true
every_direct_node_reverses_to_exact_raw_object=true
every_peer_field_has_exactly_one_responsibility=true
all_control_roles_are_typed=true
template_definitions_and_references_are_source_closed=true
template_parameter_declarations_are_typed=true
loop_termination_basis_is_source_backed_or_precisely_blocked=true
projectile_gameplay_fields_separated_from_physics=true
downstream_obligations_have_exact_stage_owner=true
unknown_or_forged_shapes_fail_closed=true
runtime_behavior_changed=false
full_canonical_ir_build_count=0
```

允许某个节点因 S8B-S16 的明确义务保持 `lowered_with_obligation`；这不等于 executable。S8A 自身
不得存在未归属字段、无法反查来源、模板引用未裁决或 `implementation_missing`。

## 验证与预算

- 一次完整 snapshot 读取，一次 scope 投影，一次 S8A 目录构建；不构建完整 Canonical IR。
- 主入口一个：`validate_p9_s8a_control_flow_source_contract.py`。
- 负例只覆盖生产不变量：未知字段、来源错位、重复身份、悬空 child、模板歧义/环、伪造状态。
- 不执行 runtime direct；`compileall + 主入口 + git diff --check`。
- 预算：3 分钟、768 MiB、2 MiB evidence、验证器目标不超过 700 非空行。

## 唯一执行清单

- [x] 实时分母与直接/祖先物化角色已分离。
- [x] 每条直接节点和每个同级字段均有类型化、来源可逆的唯一责任。
- [x] 分支、模板参数与引用、循环和 projectile 来源结构已闭合。
- [x] 下游 gameplay 义务均有精确阶段 owner，未归属为零。
- [x] 生产负例、唯一主入口与资源门通过并提交 `ready_for_review`。
