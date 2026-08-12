# P9-S8A-R1 控制流来源分母完整性验收报告

## 结论

P9-S8A-R1 已通过验收。S8A 的 compiler 侧控制流来源分母已从旧的 family 列表口径修订为
“发生项 scope + 明确物化角色 + shared template 递归树”的完整责任集合；本阶段没有修改
Canonical IR、RuleBook 或 runtime。

## 完成事实

- 完整来源 occurrence：9,432。
- 角色 scope occurrence：9,052；shared template occurrence：380。
- 跨领域、实际携带执行子图的混合 occurrence：429。
- 命名 template 参数子图：31；对应 fetch：5，调用名称集合完全闭合。
- 分支：5,248；child 来源：8,293，均可反查唯一父分支和规范 raw 路径。
- 目录状态：`issue_count=0`，blocked 为 0。
- 覆盖状态：1,361 条已完成 compiler 责任，8,071 条携带精确后续阶段义务。

旧 S8A 的 8,651 条记录只证明旧分母内部一致，不再作为完整来源前置。R1 没有按固定数量、
固定 family 白名单或验证器已支持集合反推生产分母。

## 五面验收

1. **来源范围**：独立遍历完整 scope 与 shared template 原始树，得到的 9,432 个身份与生产目录
   集合完全相等；普通无子图 gameplay task 未被误提升，终端表现分支未被 family 分类重新提升。
2. **生产不变量**：目录构造直接拒绝分母遗漏、多父物化、参数名不闭合、未知同级字段和伪造来源；
   不是由验证器在事后容忍错误目录。
3. **正式调用者**：变更仅限来源分类、compiler 目录模型与其聚焦验证；没有新增 runtime consumer，
   没有改变状态、mutation、event、RNG、settlement 或 replay。
4. **gap 归属**：8,071 条下游义务均有精确阶段 owner；它们表示 S8B-S16 的执行责任，不是 R1
   来源缺口，也没有被标记为 executable。
5. **验证独立性**：验收分母独立读取 raw 结构，未从生产目录反推；完整性总门显式要求非空、
   集合相等、来源反查和 blocked 为零。

## 验证结果

- 主结果：`ok=true`。
- 墙钟：5.856627 秒。
- 峰值 RSS：335,212 KiB。
- 完整 Canonical IR build：0。
- 目录构建：1；scope 构建：1。
- evidence：约 6 KiB。
- `compileall`：通过。
- `git diff --check`：通过。

主入口共运行四次：第一次在谓词前暴露生产与独立分母选择口径不一致；第二次暴露 89 条来源
路径表示不一致；第三次业务通过；第四次是在加强命名子图顺序和 fetch 集合相等门后完成最终取证。
前两次问题本可在主入口前通过集合差量和 child 来源反查发现，因此计为流程预检遗漏，而非合理的
主入口调试。后续阶段已新增不落盘的这两项预检，禁止把它们扩成新的长期验证器。

## 后续边界

S8A 聚焦验证在本检查点后转为 `historical_evidence`，不得在 S8B1-S8B6 中继续扩写。下一阶段
只允许执行 `P9-S8B1_TASK_GRAPH_IR_MATERIALIZATION.md`，以 R1 目录作为唯一来源输入；不得提前
建立 runtime 执行器或迁移 ability/status consumer。
