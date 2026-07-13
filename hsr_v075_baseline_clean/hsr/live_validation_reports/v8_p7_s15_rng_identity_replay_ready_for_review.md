# P7-S15 随机决策身份与重放待验收报告

状态：`ready_for_review=true`。本报告仅作为统一验收证据索引，不宣告阶段完成，不修改 P7 checklist。

## 本阶段结果

- `RNGRequest` 新增结构化 `identity`；identity 至少包含 decision scope/index，并按来源携带 action/task/phase/hit/target/status/target-expression/derived-event 维度。缺完整 identity 的请求在解析前 blocked。
- `choice_key_for_identity` 对规范化 identity 生成稳定 key。direct crit 和 random target 均纳入 actor、action definition/level、task、phase、hit/decision index、target-expression path 等维度；不同动作来源和同目标多段不再共用 key。
- 外部显式选择只接受精确 `choice_key` 或对应 `event_id`；`rng_type`、`default`、旧 `target_random_choices` 不再作为主路径 fallback。
- 新增 `RNGChoiceLedgerValidation`：检查提供项与消费项的精确集合、重复提供、重复消费/identity collision、缺项、多余项和无 identity 事件。
- executor 从动作初始目标解析开始汇总 RNG event，并在 selected graph 原子提交前验证 ledger；不完整 ledger 作为 blocked execution node，原计划 Mutation 不会提交。settlement 保存 ledger 行，供推演器和 replay 审计。
- 同一输入与 deterministic seed 继续得到相同 roll、outcome 和事件 JSON；显式 ledger 的每项只对应一个逻辑事件。
- direct damage 的 crit `event_id` 与 `choice_key` 现在都从同一完整 identity 派生，包含 task、phase、hit 和 target；不再由 action/target 的短字符串生成事件号。

## 结构化验证证据

主验证：

```text
python3 -m simulator_v8_clean_core.tools.validate_p7_s15_rng_identity_replay --output-dir /tmp/p7_review_s15
```

结果：`ok=true`、`ready_for_review=true`、`rows=14`。

实际覆盖：同目标多段、多目标、status identity、random-target identity、缺选择、多余选择、重复提供 key、重复消费 identity、错误/rng_type/default key、deterministic replay、identity 缺失。新增反例通过真实 `DirectDamageFormula` 入口生成同动作同目标第 1/2 段暴击，确认 event id 与 choice key 均不同，并能分别用 event id 强制 crit/noncrit。

输出：

- `/tmp/p7_review_s15/validation_summary_p7_s15_rng_identity_replay.json`
- `/tmp/p7_review_s15/p7_s15_rng_identity_matrix.json`
- `/tmp/p7_review_s15/p7_s15_rng_identity_evidence.json`

## 直接回归

- P1-7 RNG branch 已迁移 typed target node 与 exact key：`ok=true`。旧 target-random compatibility 断言改为验证 broad/default key 被拒绝。
- P7-S7 target selection/impact：`ok=true`、6 rows/10 negative cases。
- P7-S8 decision query-submit：`ok=true`、6 rows。
- P7-S12 damage/toughness：`ok=true`、11 rows。
- P7-S14 status admission：`ok=true`、12 rows。
- `compileall`、`git diff --check`：通过。
- 未运行 `validate_v0_209`：S15 主矩阵与 P1-7 已直接覆盖 identity、crit、target、ledger 和 replay；该脚本会全量构建/写出大产物，按资源约束不作为普通回归。

## 明确未做

- 未实现搜索/枚举策略，未引入真实随机。
- 未保留宽泛 key 作为“exact”兼容，也未让未消费选择静默存在。
- 未修改 P7 checklist，未提交 Git 检查点。
