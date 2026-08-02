# P9-S3 混淆战斗族与缺失来源裁决执行卡

## 执行配置

- 对应问题：P9-I04；机制包 M17。
- 硬前置：P9-S2 已验收并形成检查点。
- 推荐：5.6 Sol / `max` / Goal 模式。
- 理由：语义判断错误会生成长期错误规则；需要结合字段形状、上下游、同构来源和完整引用图审计。

## 当前事实与阶段结果

当前目标范围发现 6 个混淆战斗族、110 次出现：两族高度像动态值定义/写入，一族位于队列
计数 precheck，三族语义仍不足。大黑塔真实追加攻击分支还引用当前来源中未发现的 ability。

完成后，当前 decode-required 集合的每一族和每个缺失引用都得到机器可读裁决：可靠解码后
类型化 lower 并移交 S4-S17；确实缺失或无法唯一证明时保留 `source_gap_blocked`。S3 不执行
下游战斗效果，不允许为了清零 unknown 猜测语义。

## 详细目标

1. 从 S0/S1 当前指纹重新发现 decode-required 家族和 unresolved ability 引用，不固定六族数量。
2. 对每族汇总字段集合、父任务、目标/数值/条件形状、涉及 graph 和前后相邻节点。
3. 在当前 TBGD 内搜索同字段结构、schema 元数据、未混淆等价形状和引用生产/消费关系。
4. 每项裁决为 `decoded_to_package`、`source_gap_blocked` 或有完整分支证明的 `non_gameplay`。
5. 已解码项建立正式 IR 类型/字段来源和下游责任包，不在 S3 写 runtime handler。
6. 对缺失 ability 做全来源候选检索、引用闭包和版本/文件截断排查，排除扫描缺口后才能声明 source gap。

## 本阶段不做

- 不使用旧 v7、外部文本、攻略或观测结果作为规则来源；它们最多提供检索假设。
- 不把混淆字段名直接映射为某个已知 opcode 而缺少结构证据。
- 不执行动态值、队列、状态、伤害或形态语义。
- 不因单一当前样例少而写角色专属实现。

## 架构与负例

- 同字段形状但父上下文、目标或操作语义冲突时必须多义 blocked。
- 只靠相邻 task 顺序、文本效果或名称相似不能达到 decoded。
- source gap 检索必须覆盖目标主文件、共享来源、全局/局部模板和被引用 ability 目录。
- 已解码 IR 的未知字段、额外字段和伪 source trace 必须拒绝。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 当前集合完整 | 与 S0 decode-required 和 S1 unresolved 引用一致 | discovery reconciliation |
| 裁决可辩护 | 每项有字段、上下游和候选排除链 | resolution dossiers |
| 解码不越权 | 只建立 typed lowering 和责任包 | IR matrix |
| 缺源真实 | 排除路径/扫描/候选歧义后才标 source gap | source search ledger |
| 未知 fail-closed | 未裁决项零 executable/mutation | negatives |

## 结构化通过谓词

```text
decode_required_set_current=true
all_decode_items_have_structured_resolution=true
decoded_items_have_typed_ir_and_package_owner=true
undecoded_items_remain_blocked=true
missing_ability_search_closure_complete=true
source_gap_not_caused_by_scan_or_lowering=true
text_or_observation_used_as_rule_source=false
obfuscated_specific_runtime_handlers=0
```

## Gap 与停止条件

- 任一项仍只能靠猜测解释：保留 source gap；阶段可以提交机制裁决，但不能声称该角色完整。
- 发现当前 TBGD 版本截断或来源包不完整：停止，交用户决定是否更换数据源。
- 解码需要新增跨包基础概念：只记录设计要求，交下游卡或规划线程修订。
- 验证器以固定六族作为未来通过条件：阶段阻断；必须按当前指纹动态发现。

## 拟改范围

- S0 范围模块、S1 来源图、`rules/ir.py` 的最小 decoded 类型。
- 必要的 `tbgd/expression_lowering.py` / `tbgd/character_cards.py` 字段投影。
- 小型 source-resolution ledger；不改 `systems/` runtime。
- 主验证 `tools/validate_p9_s3_obfuscated_source_resolution.py` 和报告。

## 验证与资源

- 主入口读取当前 decode 集合涉及文件及引用索引；不得完整 lower 全角色 task 图。
- 只输出每族聚合形状、候选结论和少量 raw path，不写 raw payload 全量 dump。
- 无 runtime direct；若扩展 IR codec，最多 1 个 round-trip direct。
- 预算：8 分钟、1 GiB、5 MiB、900 行。

## 唯一执行清单

- [x] 当前 decode-required 与 missing ability 集合完整重算。
- [x] 每项有结构化、可复核的来源裁决。
- [x] 已解码项只建立 typed IR 和下游责任归属。
- [x] 未解码/真缺源保持 blocked，零猜测执行。
- [x] 无混淆族或角色专属 runtime handler。
- [x] 主验证、必要 codec direct 和资源审计通过并提交 `ready_for_review`。
