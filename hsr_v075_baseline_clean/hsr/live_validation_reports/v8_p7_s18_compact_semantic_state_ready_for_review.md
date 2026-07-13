# P7-S18 推演器紧凑语义状态待验收报告

状态：`ready_for_review=true`。本报告仅作为统一验收证据索引，不宣告阶段完成，不修改 P7 checklist。

## 本阶段结果

- 新增只读 `CompactStateQuery` / `CompactSemanticState`。投影直接读取 `BattleState` 权威字段，不调用或 hash 完整 snapshot；提交仍必须经过正式 core API。
- 紧凑 payload 包含单位完整可变状态、战技点、global flags 的语义部分、队列、RNG state、event index 与 wave index。status detail、shield instance、timeline、decision、RNG ledger、wave runtime、summon relation、dynamic value 等未来结算依赖均被纳入。
- `source_trace`、evidence、coverage、settlement、provenance 等审计展开字段递归排除；`source_id`、owner、entry/action/decision identity 等具有运行时身份意义的字段保留。审计详情通过 `audit_details(state)` 按需取得完整权威 snapshot，source-audit 能力未关闭。
- compact key 的审计裁剪建立在“行为不读取审计详情”之上。验证会对同 key 的审计变体分别执行 timeline、summon、wave、action query 和真实 queue drain plan，并要求结构化行为投影完全相同；因此相同 key 不再只表示 payload 相同，而有定向行为等价证据。
- payload 使用递归不可变 JSON 存储；`payload_copy()` 只返回脱离内部状态的副本。`from_json()` 会重新计算并校验 SHA-256 semantic key，篡改 payload/key 不能静默通过。

## 结构化验证证据

主验证：

```text
python3 -m simulator_v8_clean_core.tools.validate_p7_s18_compact_semantic_state --output-dir /tmp/p7_review_s18
```

结果：`ok=true`、`ready_for_review=true`、`rows=5`。

实际覆盖：

- 同一语义、不同 source/audit 展开得到相同 key，同时完整 snapshot 确实不同且仍可按需读取。
- 相同 key 的状态在 timeline、summon、wave、action availability 及 queue drain 五类生产查询上的结果投影一致；queue policy source 全量与清空两个变体均可执行。
- HP、status、shield、queue window、timeline、RNG state、RNG ledger、wave、summon relation、decision phase/identity、dynamic value、attached ability 共 13 类变化分别改变 key；S16 新增的能力注册状态不会被错误合并。
- JSON round trip、key 重算、内部不可变、外部副本隔离和查询 state unchanged。
- 可重复预算夹具：完整 snapshot `52091` bytes，compact payload `2916` bytes，比例 `0.055979`，节省 `49175` bytes。该预算包含真实形态的嵌套 provenance 展开，用来证明 source graph 未被逐节点复制；它不是性能基准承诺。

输出：

- `/tmp/p7_review_s18/validation_summary_p7_s18_compact_semantic_state.json`
- `/tmp/p7_review_s18/p7_s18_compact_semantic_state_matrix.json`
- `/tmp/p7_review_s18/p7_s18_compact_semantic_state_evidence.json`

## 直接回归

- P7-S2 Mutation reducer/replay：`ok=true`、14/14 cases、9 conflict negatives。
- P7-S4 runtime rule/audit separation：`ok=true`、11 ownership rows。
- `validate_v0_286` snapshot/source trace 验证：通过。
- `compileall`、`git diff --check`：通过。

## 明确未做

- 未实现搜索、剪枝、目标函数或缓存策略。
- 未把 compact view 变成第二套可修改状态，也未改变 snapshot/replay 格式。
- 未修改 P7 checklist，未提交 Git 检查点。
