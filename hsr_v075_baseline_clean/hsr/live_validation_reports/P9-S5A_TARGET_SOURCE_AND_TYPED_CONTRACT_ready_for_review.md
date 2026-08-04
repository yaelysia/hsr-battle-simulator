# P9-S5A 目标来源与类型化契约 — ready_for_review

状态：`ready_for_review`。未勾总计划、未提交 Git、未进入 S5B-S5D。

## 生产改动

- `tbgd.target_source` 复用一次完整 S0 snapshot，并在 Canonical IR materialization 前建立逐记录目标来源视图。记录状态、责任、表达式状态和真实来源身份互相闭合；partial snapshot 显式保留完整性标记。随机目标先尊重逐记录 scope，只有 gameplay 记录委派到 S5D。
- 全局 `TargetAliasConfig` 与 `TargetOperationConfig` 使用拒绝重复键的 JSON 读取。名称在 alias/operation 间多义时，两个真实定义都保留为带来源的 `blocked`，并经引用图向上游依赖传播；不再抛弃整个目录，也不回退 Python 白名单。
- 正式 lowering 只为 raw 中真实存在的目标字段生成表达式。`RemoveSelfModifier` 与 `AttachEntityDeparted` 的隐式归属保留在原任务 payload 语义中，不再生成 `.implicit:*` JSON 路径或合成 `ModifierOwnerEntity` 节点。
- `TargetExpressionNodeIR` v2、`TargetExpressionIR` 与 `ConditionIR` 收紧构造/codec 边界：直接子节点、predicate 及 condition 内嵌目标均须闭合到精确字段或数组位置；跨文件、父节点冒充和 `.Fake` 子路径均在构造期拒绝。condition 内嵌 target 节点 JSON round-trip 后仍恢复为 `TargetExpressionNodeIR`。
- `ConditionIR` 现在拒绝把任何自身已知为 blocked 的嵌套目标标记为 executable；正式 lowering 使用同一阻断原因 fail-closed。`TargetExpressionIR` 也要求外层 blocked 原因精确等于节点自身原因，不能以通用“尚未准入”覆盖递归召唤者、相邻忽略召唤物、离场单位或存活状态查询。
- 原始目标关系参数完整进入节点：召唤者递归标记、相邻计数选项、Retarget 的 `IncludeLimbo`。当前 runtime 不支持这些特殊关系时，表达式和直接节点解析均 fail-closed 为带来源的 S5B deferred，而不是丢字段后执行。
- Retarget 直接复用 predicate candidate evaluator，不再临时构造不存在于 raw 的 `TargetFilter`。未填写 `MaxNumber` 以空 typed payload 保留既有默认语义；显式但 runtime 不支持的数值表达式在 lowering/构造期即变为 blocked，不再留给 runtime 才失败。lowering 对 `ByRandom`、排序方向和目标字段只接受原始正确类型，不再以 `bool()`/`str()` 强转；Take/严格索引拒绝 unsupported 数值，First/Last 和各 Fetch tag 拒绝无效的附带字段，非空 Query 存活范围保留并明确 S5B deferred。
- 语言定义引用列表、目标结果、metadata 与 RNG events 均在构造边界冻结并校验；`.ok` 已删除，状态回调条件上下文及其余真实结果消费者改用 `resolved`，未改变动作、RNG、事件或状态语义。`status_callbacks.py` 是该残留调用链所必需的最小额外生产改动。

## 验证

- 聚焦 `compileall` 与秒级构造负例：通过。新增负例证明：可执行或 blocked 的条件都不能改写 S5B deferred 目标的 blocker、正式 lowering 会以递归召唤者的精确原因阻断该条件、Retarget 拒绝 unsupported `MaxNumber`、外层表达式不能改写节点 blocker；既有跨文件/伪造来源、原始错误类型、Query 存活范围、不可变性和名称闭包负例仍通过。
- 唯一主入口 `validate_p9_s5a_target_source_and_typed_contract`：通过。它拦截 `TBGDLowering.build`，完整 Canonical IR 构建次数为 0；逐条反查 16,113 个来源 record、14,280 个目标节点和 424 个 predicate。`source_ownership.json` 内的 `blocked_gap_ledger` 按 phase、原因和 owner 聚合完整 blocked 集合，并由 `blocked_gap_ledger_complete=true` 反查总数；每个原因＋归属桶保留 canonical 顺序下的 `source_path`、`record_identity` 与 `json_path` 代表来源。
- 正式 lowering 验证以 raw 形状动态求最小来源集合，不固定角色、文件或 ID：本次一份真实能力来源覆盖回调、两类无显式目标任务与 `IncludeLimbo`，并反查 83 条能力表达式、189 条正式全局定义、573 个节点和 21 个 predicate；合成隐式目标数为 0。该来源还产生 26 条真实状态回调条件，其中一条含目标条件通过正式 `_condition_context` 直达解析；全目录独立验证了递归召唤者 1、忽略召唤物相邻计算 1、`IncludeLimbo` 72，以及存活状态查询 2 的 raw 字段、IR 字段和 S5B blocker 闭合。
- `git diff --check`：通过。

最终主运行资源：4.32 秒，峰值 RSS 265,968 KiB（约 260 MiB），evidence 131,247 bytes；验证器 650 非空行。均低于 5 分钟、768 MiB、2 MiB、650 行预算。

临时 evidence：

- `/tmp/hsr_v8_p9_s5a_target_source_and_typed_contract.5La2T9/summary.json`
- `/tmp/hsr_v8_p9_s5a_target_source_and_typed_contract.5La2T9/source_ownership.json`
- `/tmp/hsr_v8_p9_s5a_target_source_and_typed_contract.5La2T9/source_closure.json`
- `/tmp/hsr_v8_p9_s5a_target_source_and_typed_contract.5La2T9/formal_lowering_closure.json`
- `/tmp/hsr_v8_p9_s5a_target_source_and_typed_contract.5La2T9/node_contract.json`
- `/tmp/hsr_v8_p9_s5a_target_source_and_typed_contract.5La2T9/negative_cases.json`
- `/tmp/hsr_v8_p9_s5a_target_source_and_typed_contract.5La2T9/migration_slice.json`

## 真实 gap

- 完整来源视图仍有 103 条 record 因 source scope 未准入而 `blocked`，未产生 mutation。
- S5A 责任范围有 639 条 blocked 表达式；全局目标语言定义有 168 条 blocked 定义。两组均已在 `source_ownership.json` 的 `blocked_gap_ledger` 中按真实 blocker 和 owner 完整列账，并为每个桶保留可直接抽查的代表来源，而非仅保留旧的 103/4/7 摘要。
- 4 条 input projection 目标保持委派给 S5C；7 条 gameplay `RandomSelectInTargetList` 保持委派给 S5D。non-gameplay 同 family 记录已退役，不会被错误委派。
- S5B 的已识别真实缺口保持 deferred：S5A 中 72 条 `IncludeLimbo` Retarget；全局定义中各 1 条递归召唤者、相邻忽略召唤物，以及 2 条按存活状态查询目标。它们未被降格为普通目标关系，也未进入 S5B 实施。
