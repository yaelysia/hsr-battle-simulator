# P9-S7 动作、事件与结算上下文条件族验收报告

状态：`accepted`

## 结论

P9-S7 通过验收。当前来源中的 48 条 transient-context 条件记录、17 个 family 已全部进入严格
lowering 和统一三态 evaluator，阶段内部 lowering/evaluator gap 为零。运行时通过七类领域
transient fact 契约读取瞬时事实；缺生产者、错事实类型、错调用身份、错窗口或不完整动作准入身份
均 fail-closed。

本结论不等于真实角色机制已经端到端执行。当前只有两条动作事实具备 source-backed 组件投影，
真实 gameplay end-to-end 计数仍为 0：普通动作目标条件等待 P9-S9 的 callback/context 运输；动态
目标条件同时等待 P9-S8 和 P9-S9。其余 46 条记录分别精确归属 P9-S9、S10、S11、S12、S13 或
S16。48 条记录均保留可反查来源和后续义务。

## 五面验收

1. 来源范围：责任目录来源指纹为
   `349d9dd2ade62d32e17b25a49400c8043dfdf0cea73250aa0ee4bc23fcedb998`；48 条记录和 17 个
   family 全部可逆回到 raw 行，真实同级字段、值域、集合基数和嵌套目标形状均完成独立对账。
2. 生产不变量：transient request/result 递归冻结并绑定事实种类、领域 authority、invocation、window
   和来源身份；普通 event payload 不能升级为正式事实。lowering 拒绝未知同级字段、多标签未证明
   语义、非严格布尔和空字符串。
3. 正式调用者：动作目标查询、已准入 ability predicate 和 action trigger window 已显式传递 typed
   provider；状态 callback 的真实运输未伪造，精确留给 P9-S9。
4. Gap 归属：2 条记录为来源已具备但运输未证明，46 条为领域 producer 未证明；没有“以后处理”
   混合桶，也没有 fixture 被标成 gameplay executable。
5. 验证独立性：来源 family/字段分母、raw shape 和生产 registry 分开核对；true/false/blocked 组件
   fixture 与 source-backed 组件证据分栏。总门显式要求非空，不依赖 `all([])`。

## 验证结果

- 唯一主入口：22/22，通过；只运行 1 次。
- 墙钟：7.492 秒；外部计时 8.31 秒。
- 峰值 RSS：446,340 KiB。
- evidence：166,649 bytes；完整 Canonical IR build：0。
- 组件矩阵：18 组 true/false/blocked；动作来源组件：2；真实 gameplay end-to-end：0。
- 验证器：735 个非空行，低于 900 行硬上限。超过 630 行软复核点后完成了范围复核；保留单一来源
  分母、单一主入口和可读独立 oracle，没有压行或拆分模式规避预算。
- `compileall` 与 `git diff --check` 通过。
- direct：0。S5C2、S6A、S6B 均为冻结历史证据，本阶段主入口已经覆盖实际触达的现行契约。

主 evidence 位于 `/tmp/p9_s7_final_20260811/`。本阶段验证器验收后归类为
`historical_evidence`，后续阶段不得持续扩写或默认重跑。

## 流程复盘

主验证前的五面审查发现，初版验证器曾手工构造目标解析结果并称为“正式动作入口”。该证据在运行
主入口前已改为 source-backed 组件口径，并将未完成运输写入义务账本；最终主验证因此一次通过，
没有形成“跑主入口、逐项补丁、反复重跑”的循环。

本阶段沉淀三条跨阶段规则：来源值域必须包含集合基数；瞬时事实只能由领域生产者通过 typed
provider/capability 运输；工程阶段编号只能存在于计划和 gap ledger，不能成为 runtime 语义。

