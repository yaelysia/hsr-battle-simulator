# P9-S1 共享来源、动作阶段与能力入口来源图执行卡

## 执行配置

- 对应问题：P9-I02；机制包 M01。
- 硬前置：P9-S0 已验收并形成检查点。
- 推荐：5.6 Sol / `max` / Goal 模式。
- 理由：需要对全角色动作、阶段、被动和共享能力做唯一来源关联，来源猜错会污染全部下游执行。

## 当前事实与阶段结果

当前盘点有 17 条目标记录、19 个动作/入口绑定缺口；共享 `Avatar_Common_Ability` 尚未作为
独立来源正式接入。旧绑定可能把可提交动作、强化阶段、被动入口和演出 ability 混在一起。

完成后，角色卡拥有唯一、类型化的能力来源图：共享定义只 lower 一次；每个动作阶段、
standalone ability、被动入口和角色拥有的 battle-event ability 都关联真实记录。缺失或多义
来源结构化 blocked，不按名称相似度猜测。

## 详细目标

1. 接入共享角色能力并建立共享 graph 身份，角色卡只引用，不复制节点。
2. 建立 skill/action/phase/entry/standalone/passive 的类型化关系，保留来源路径和具体记录身份。
3. 区分可由推演器提交的动作、动作内部阶段、被动触发、强化替换和 presentation ability。
4. 对当前全部绑定缺口重新从 S0 窄来源计算；可闭合项必须唯一关联，真缺源项进入 source gap ledger。
5. 保留最高等级、技能等级和多阶段关系，不按文件顺序或首个候选决定。
6. Canonical IR / RuleBook 提供稳定窄查询，重复身份、跨角色候选和错误 kind fail-closed。

## 本阶段不做

- 不执行能力 task、condition、target 或 event。
- 不绑定行迹和星魂；留给 S2。
- 不用技能描述、TextMap、旧 v7 或观察结果补 missing phase。
- 不为每个角色生成复制的共享 graph。

## 架构与负例

- 同名多个 ability 记录、phase 缺失、entry 与 passive 冲突、跨角色候选必须 blocked。
- 共享来源的同一节点被多个角色引用时身份相同，不能复制后获得不同 fingerprint。
- presentation ability 不能因被技能文件引用就升级为 gameplay。
- generic limit 截断角色或 graph 后不能报告 complete。
- 来源容器修改不能改变已构建 IR/fingerprint。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 共享来源唯一 | 共享 graph 只构建一次，多角色只引用 | source graph matrix |
| 动作语义分层 | action/phase/passive/entry 类型不混淆 | binding-kind matrix |
| 当前缺口诚实 | 每个旧缺口变为唯一绑定或 source gap | binding resolution ledger |
| 查询 fail-closed | 缺失、重复、跨类型和跨角色候选均 blocked | RuleBook negatives |
| 确定性 | 输入顺序不改变身份、序列化和 fingerprint | permutation probe |

## 结构化通过谓词

```text
shared_character_ability_lowered_once=true
action_phase_entry_passive_kinds_distinct=true
current_binding_candidates_fully_classified=true
unique_source_bindings_resolved=true
ambiguous_or_missing_binding_blocked=true
presentation_ability_not_promoted=true
rulebook_source_graph_query_fail_closed=true
source_graph_deterministic=true
full_lowering_count=0
```

## Gap 与停止条件

- raw 无所需 ability：`source_gap_blocked`，保留引用方和完整检索证据。
- raw 有唯一记录但 lowering 未关联：本阶段 `lowering_gap`，必须修复。
- 需要按角色 ID 或相似名称才能选择：停止，不能形成 executable。
- 发现新动作 kind 会改变 action definition 架构：停止交规划线程修订。

## 拟改范围

- `tbgd/character_cards.py`、S0 窄目录模块、`tbgd/lowering.py`。
- `rules/ir.py`、`rules/rulebook.py` 的来源图和类型化查询。
- 必要的角色数据卡 action binding 模型；不改 runtime executor。
- 主验证 `tools/validate_p9_s1_ability_source_graph.py` 和报告。

## 验证与资源

- 一次构建 S0 窄目录，一次建立来源图；不生成 task/effect 全图。
- catalog 触发理由：角色来源图和 Canonical IR 定义目录改变；只输出 binding matrix 和少量样本。
- direct 最多 1 项，仅在修改现有数据卡 codec/query 时运行最小契约。
- 预算：8 分钟、1 GiB、5 MiB、900 行；完整 Canonical IR/RuleBook 0 次。

## 唯一执行清单

- [ ] 共享角色能力只 lower 一次并可由角色卡引用。
- [ ] action、phase、entry、passive 和 standalone 关系类型化。
- [ ] 当前全部绑定缺口唯一闭合或诚实 source-gap。
- [ ] 查询、冲突、顺序变化和伪来源负例 fail-closed。
- [ ] 无角色/技能/固定 ID 绑定逻辑或兼容双轨。
- [ ] 主验证、必要 direct 和资源审计通过并提交 `ready_for_review`。
