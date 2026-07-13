# P7-S3 选中执行图原子提交待验收报告

状态：`ready_for_review=true`。本报告只提交统一验收所需的证据索引，不宣告阶段完成，不修改 P7 checklist。

## 本阶段结果

- 新增 `core.atomic_commit.finalize_selected_execution_graph`，把子系统的 immutable candidate 计算与正式 successor 发布分离。
- 只有选中执行节点全部 `complete`、整批 Mutation 从原始 `before` 归约成功、且归约结果与 candidate 严格一致时，才发布 `after` 和 committed mutations。
- `blocked / unsupported / partial / error`、Mutation 前置冲突、candidate/Mutation 不一致均保持正式 `after == before`、`transaction.mutations == ()`、`successor_eligible == false`。
- 未提交图中的 Mutation 记录被规范化为 `process_only + planned_only` 诊断记录；来源、路径、Mutation ID 和冲突详情仍保留，但不会冒充已提交事实。
- executor 与 scheduler transition 组合均接入同一提交门；diagnostic 子 transition 会阻止父 transition 发布候选状态。
- transition contract 已收紧：diagnostic transition 也必须正式状态不变且 committed mutation 为零。

## 结构化验证证据

主验证命令：

```text
python3 -m simulator_v8_clean_core.tools.validate_p7_s3_selected_graph_atomic_commit --output-dir /tmp/hsr_v8_p7_s3_selected_graph_atomic_commit
```

结果：`ok=true`、`ready_for_review=true`、`cases=9`。

覆盖的结构化反例与正例：

- 完整多节点图一次提交并严格 replay。
- 多 task 中途 unsupported：零提交、状态不变。
- 状态激活后续节点 partial：零提交、状态不变。
- callback 中途 error：零提交、状态不变。
- reducer before 冲突：结构化冲突、零提交、状态不变。
- candidate 与 Mutation 图不一致：拒绝发布。
- 未进入的条件分支不进入 node results，不阻断已选完整分支。
- executor 真实 partial action 与 scheduler diagnostic child 均通过原子边界和 transition contract。

输出文件：

- `/tmp/hsr_v8_p7_s3_selected_graph_atomic_commit/validation_summary_p7_s3_selected_graph_atomic_commit.json`
- `/tmp/hsr_v8_p7_s3_selected_graph_atomic_commit/p7_s3_atomic_commit_matrix.json`
- `/tmp/hsr_v8_p7_s3_selected_graph_atomic_commit/p7_s3_atomic_commit_cases.json`

## 直接回归与资源控制

- P7-S1：`ok=true`，四类 runtime transition contract 有效，非法 unclassified payload 被 contract 拒绝。
- P7-S2：`ok=true`，`cases=14/14`、`conflicts=9`。
- 定向 `compileall`：通过。
- `git diff --check`：通过。
- 未运行 P1-5 队列大产物验证、全量 TBGD discovery/lowering 或无调用链关系的重验证；本阶段验证只写 summary、matrix 和必要抽样 evidence。

## 明确未做

- 未实现 P7-S4 的规则输入与审计信息隔离。
- 未实现 P7-S5 及后续战斗语义阶段。
- 未修改 P7 计划 checklist，未提交 Git 检查点。
