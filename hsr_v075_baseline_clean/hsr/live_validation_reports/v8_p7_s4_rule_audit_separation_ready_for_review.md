# P7-S4 规则输入与审计来源分离待验收报告

状态：`ready_for_review=true`。本报告仅作为统一验收的证据索引，不宣告阶段完成，不修改 P7 checklist。

## 本阶段结果

- P7-I16 的行为读取矩阵现有 21 行。除既有 status/action/queue/dynamic/engine-rule 路径外，新增覆盖 callback 执行顺序、servant replacement、wave definition/entry 准入和 break recovery identity。
- runtime 不再用 `IRSource.source_path/raw_id/evidence` 或状态/队列 `source_trace` 中的语义 key 决定上述行为；这些结构仍可用于 settlement/source audit 输出。
- lowering 负责一次性解析 source-scope 歧义并写入稳定 link ID。runtime 缺 link、link 歧义、缺 typed field 时 blocked，不按路径或“第一个匹配项”回退。
- 新增版本化 `engine_rule_registry`，统一承载行动值基数、终结技能量顺序和击杀能量。规则包含稳定 ID、registry version、source kind、适用范围及 typed numeric value；runtime 的击杀能量不再硬编码 `10`。
- RuleBook 对 engine rule 使用 exact-one admission；缺失、重复、版本错误、适用范围不符和缺数值都会返回结构化阻断原因。
- scheduler/action availability 对缺 timeline rule 保持 state unchanged；击杀能量规则在选中图中缺失时形成 error node，并由 S3 原子门阻止整图提交。
- status callback 的顺序由 lowering 写入必填的 `StatusCallbackIR.execution_order`，runtime 排序不再读取 `IRSource.source_path/raw_type/raw_id`。字段没有默认值，手工或未来构建路径遗漏时会在 IR 构造边界直接失败；相同结构化顺序在完整来源与全空来源下得到相同执行序列。
- servant replacement 只检查版本化 typed policy；wave runtime 只检查 definition/entry 的稳定身份、coverage 和 birth binding；break recovery 只读取 `StatusInstance.break_status_emission_id`。来源路径与 evidence 均只进入审计。

## 结构化验证证据

主验证：

```text
python3 -m simulator_v8_clean_core.tools.validate_p7_s4_rule_audit_separation --output-dir /tmp/p7_s4_repair_final8
```

当前修正后结果：`ok=true`、`ready_for_review=true`、`ownership_rows=21`。

验证实际覆盖：

- 轻量 RuleBook 中全部结构可选 action 在完整 IRSource 与裁剪 IRSource 下，state、正式 after、outcome、节点状态、Mutation 状态字段、事件和目标行为投影完全一致；同时包含 committed 与非 successor case。
- status task payload、retarget、modifier definition link、break template/element、queue resource policy、DoT formula binding、角色动态值均有 audit 裁剪等价性或缺 typed field 不回退负例。
- lowering helper 直接证明 TriggerAbility graph、状态 definition/callback/source mode、ActionDefinition skill trigger key 被投影到显式字段。
- engine registry 证明 source audit 裁剪不改变规则值；missing、wrong version、ambiguous、missing numeric value 均阻断；missing timeline rule 的 scheduler transition 为 blocked/state unchanged。
- callback 顺序反例使用互相冲突的来源路径顺序与 typed execution order；清空 `source_path/raw_type/raw_id/evidence` 后，helper、RuleBook 索引和 EventDispatch 实际 listener match 顺序均严格按 typed order 执行。
- servant policy 清空 `source_path/predicate_path/create_task_path/evidence` 后仍准入；删除 `owner_scope` 等 typed 字段则阻断。
- wave definition/entry 的四类 IRSource 字段全部置空后，payload 准入与真实 transition plan 均保持等价；缺 stage/birth 等 typed 字段仍阻断。
- break recovery 的 audit evidence 故意放入错误 emission id；实际 `recover_from_break_status` 在完整与全空审计状态下生成相同的 6 条 Mutation 并恢复 100 toughness，删除 typed emission id 后则 blocked/zero mutation。
- AST 检查自动遍历 `core/`、`rules/`、`systems/` 当前全部 58 个 Python runtime 文件，只排除职责明确的 `core/source_audit.py`；扫描 source attribute、字典 audit key、条件、排序和身份读取，`behavior_read_count=0`。新增 runtime 文件会自动进入门禁。

输出：

- `/tmp/p7_s4_repair_final8/validation_summary_p7_s4_rule_audit_separation.json`
- `/tmp/p7_s4_repair_final8/p7_s4_rule_audit_separation_matrix.json`
- `/tmp/p7_s4_repair_final8/p7_s4_rule_audit_separation_evidence.json`

## 直接回归与资源情况

- P6-S4/S5 boundary static：`ok=true`，6 行边界检查通过。
- P7-S1：`ok=true`。
- P7-S3：`ok=true`，9 case。
- 定向 `compileall`：通过。
- `git diff --check`：通过。
- P1-4 与 P2-S8 旧状态重验证曾串行尝试，但进程在约 20–30 秒后被外层执行单元无输出终止，且未生成结果目录；不能记为通过或失败。本阶段以更窄的状态字段/链接真实执行验证覆盖所触达语义，并将旧重入口未完成保留为统一验收风险。
- 未运行已知会默认写约 1.6GB 产物的 P1-5，也未写完整 CanonicalIR/transition dump。

## 明确未做

- 未完成 P7-S5 的 raw target/numeric/condition 子语言类型化。
- 未删除 source audit；只移除了其行为输入职责。
- 未修改 P7 checklist，未提交 Git 检查点。

## 统一验收反例修正补充

验收发现 `UnitSpawnSystem` 曾要求 source trace 非空并比较完整字典，导致审计裁剪改变出生准入。现已改为只使用 `birth_template_id`、`source_id`、`entry_id`、owner/summoner 和波次位置等稳定规则身份；trace 只随 plan/unit 输出用于审计，不参与 admission、request equality 或 flag consistency。

同类路径也一并收口：wave/summon spawn request 不再比较 trace；召唤 target/action admission 只看 runtime entity identity/status 与 typed admission；生命周期事件只校验结构化 payload；shield/status control/timeline priority/queue wait-retarget 只使用显式 ID、值与 policy admission。状态所属 effect 新增 `EffectIR.owner_modifier_name`，runtime 不再从 `IRSource.raw_id/source_path` 或 status trace 反查行为归属。

新增动态负例同时证明：清空 request 的两类 trace 后出生行为与单位状态不变；修改稳定 `source_id` 仍被结构化阻断。S4 AST 门禁新增 `unit_spawn.py` 行为函数扫描。本轮修正后主验证输出：

```text
ok=true
ownership_rows=21
unit_spawn_audit_trim_equivalent=true
```

本轮统一验收拒绝后最终复跑使用 `/tmp/p7_s4_repair_final8`，21 行 ownership 与全部 checks 为 true；callback helper、RuleBook 索引和 EventDispatch match 顺序均只读取必填 `execution_order`，break recovery 覆盖实际 Mutation 路径。S16/S17 使用 `/tmp/p7_s4_repair_real/` 的单次共享真实 lowering，分别证明 servant replacement 和 wave transition 在真正清空审计字段后行为不变。
