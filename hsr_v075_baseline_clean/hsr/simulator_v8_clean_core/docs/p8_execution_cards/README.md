# P8-S5 至 P8-S21 与 P8-R1 执行卡索引

## 1. 用途

本目录保存 P8 剩余阶段的预先规划执行卡。执行线程不再临时重写阶段目标，而是读取对应执行卡，核对当前代码事实后只实施该阶段。执行线程最多提交 `ready_for_review`，不得修改 P8 checklist、不得自称完成、不得提交 Git。

长期目标、全局红线和唯一阶段 checklist 仍以 `P8_EQUIPMENT_BUILD_LIGHT_CONE_RELIC_TASK_PLAN.md` 为准。本目录不是第二套总计划；每个文件只包含一个阶段的唯一执行清单。

## 2. 依赖图与并行边界

```text
accepted S4
   |-- light-cone track: S5 -> S6 -> S7 -> S8 -> R1 --|
   |                                                   |-> S18 -> S19 -> S20 -> S21
   |-- relic track:      S9 -> ... -> S17 -------------|
```

- S5 与 S9 只有在 S4 验收并形成代码检查点后才能开始。
- 光锥轨内部严格按 S5、S6、S7、S8 顺序执行。
- 遗器轨内部严格按 S9 至 S17 顺序执行。
- R1 是 CHAR-M1 后发现的共享 runtime 修复门。R1-RUNTIME 已于检查点 `2d1a3f9` 通过聚焦验收并合入，满足 S15 的生产代码前置条件；R1-CATALOG 因旧验证资源成本过高由用户明确延期，当前为 `deferred / not_proven`。
- 两条轨可并行，但必须从同一个已验收 S4 检查点创建不同 Git worktree；禁止在同一工作区并行修改。
- 每个阶段验收后先形成独立检查点，下一阶段再基于该检查点继续。
- S18 只有在 R1-RUNTIME 与 S17 均验收、两个检查点已合并且聚焦回归通过后才能开始。R1-CATALOG 必须在 P8 最终聚合前使用新的低内存目录入口补证。
- S19-S21 重新严格串行，不允许继续在分支上各自演进共享装配或 runtime 契约。

## 3. 执行模式定义

- `普通聚焦模式`：单独线程只做一张卡，适合边界明确、需要人工审查设计取舍的阶段；达到 `ready_for_review` 立即停止。
- `Goal 模式`：目标只允许设为当前一张卡，适合大量来源扫描、机制族闭合或长时间 property test；仍不得自动进入下一阶段、勾 checklist 或提交 Git。
- `独立 worktree`：并行轨的必选隔离方式，不是一种放宽验收的模式。分支必须记录基线 commit，不能复制未提交工作区。
- `max`：用于跨 runtime、来源图、原子提交、回放或最终集成；`xhigh` 用于数据投影、纯装配和有限共享边界；本目录不推荐 `medium` 执行任何剩余 P8 阶段。

## 4. 每张卡的统一执行协议

1. 核对依赖阶段的已验收 commit、当前工作区和 CodeGraph 索引状态。
2. 只读审查卡内“当前事实”。若实际代码已改变但不影响目标，报告差异后按当前结构实施；若目标、职责边界或验收谓词失效，停止并交回规划线程修订，不能自行改目标。
3. 先建立来源、lowering、admission、runtime、validation 五层缺口矩阵，再编码。检查脚本没选到正例不能直接写成 source gap。
4. 只修改本卡范围。发现相邻阶段问题时记录为依赖或后续项，不提前实现。
5. 必须检查代码结构、通用性、来源真实性、不可变性和失败原子性，不能只跑脚本。
6. 验证只跑本卡最小集和有直接调用链的回归；重验证串行、低优先级、输出 `/tmp`。
7. 提交 `ready_for_review` 报告，列出实际 diff、每个谓词的证据路径、未运行验证及剩余风险；执行线程不得修改卡内勾选项。
8. 验收线程独立复核代码和证据，只有通过后才更新本卡和总计划 checklist，并提交阶段检查点。

## 5. 共用状态口径

- `executable`：真实来源已投影，装配已准入，runtime、settlement、source audit、snapshot/replay 均按阶段要求闭合。
- `non_gameplay`：有结构化证据证明只属于展示、动画或养成，不参与战斗。
- `source_gap_blocked`：raw 确实缺来源；必须同时排除 lowering、admission 和验证谓词错误。
- `lowering_gap`、`admission_gap`、`implementation_missing`、`validation_gap`：均是当前阶段应关闭的真实缺口，不能改名为 deferred 后打勾。
- 被当前已发布装备选中的 gameplay 图只支持一部分时，整个正式构筑 battle admission 必须 blocked；不能部分执行。

## 6. 共用资源边界

- 默认不运行 P1-P7 聚合和 `validate_v0_209`。
- 默认不写完整 Canonical IR、RuleBook、全量 raw ability、全 transition 或全构筑组合。
- 新验证默认只写 summary、coverage matrix、negative matrix、少量来源和 transition 样本。
- 全量来源只解析一次并复用；property test 不重复扫描 TBGD。
- S8、S17、S21 才允许各运行一次 focused 全装备聚合；S18、S20 只构建一次受控完整 RuleBook。
- 任一重验证运行时禁止并行启动 compileall 或其他验证；使用 `ionice -c3 nice -n 15`，结束后再检查资源释放。

## 7. 执行卡

| 阶段 | 执行卡 | 推荐执行配置 |
|---|---|---|
| S5 | `P8-S5_LIGHT_CONE_STATIC_CONTRIBUTIONS.md` | 5.6 Sol / xhigh / 普通聚焦 |
| S6 | `P8-S6_LIGHT_CONE_DYNAMIC_STARTUP.md` | 5.6 Sol / max / 普通聚焦 |
| S7 | `P8-S7_LIGHT_CONE_STATUS_CONDITION_LISTENER_CLOSURE.md` | 5.6 Sol / max / Goal |
| S8 | `P8-S8_LIGHT_CONE_REMAINING_GAMEPLAY_CLOSURE.md` | 5.6 Sol / max / Goal |
| R1 | `P8-R1_SUMMON_RUNTIME_HALO_LIFECYCLE_REPAIR.md` | 5.6 Sol / max / 普通聚焦 |
| S9 | `P8-S9_RELIC_DEFINITION_CARDS.md` | 5.6 Terra / xhigh / Goal |
| S10 | `P8-S10_RELIC_INSTANCE_LEGALITY.md` | 5.6 Sol / xhigh / 普通聚焦 |
| S11 | `P8-S11_RELIC_MAIN_AFFIX.md` | 5.6 Terra / xhigh / Goal |
| S12 | `P8-S12_RELIC_SUB_AFFIX_ROLLS.md` | 5.6 Sol / max / Goal |
| S13 | `P8-S13_RELIC_SET_THRESHOLDS.md` | 5.6 Sol / xhigh / 普通聚焦 |
| S14 | `P8-S14_RELIC_STATIC_CONTRIBUTIONS.md` | 5.6 Sol / xhigh / 普通聚焦 |
| S15 | `P8-S15_RELIC_SET_DYNAMIC_STARTUP.md` | 5.6 Sol / max / 普通聚焦 |
| S16 | `P8-S16_RELIC_SET_STATUS_CONDITION_LISTENER_CLOSURE.md` | 5.6 Sol / max / Goal |
| S17 | `P8-S17_RELIC_SET_REMAINING_GAMEPLAY_CLOSURE.md` | 5.6 Sol / max / Goal |
| S18 | `P8-S18_FINAL_PANEL_AND_BIRTH_ORDER.md` | 5.6 Sol / max / 普通聚焦 |
| S19 | `P8-S19_QUERY_AUDIT_SNAPSHOT_REPLAY.md` | 5.6 Sol / max / 普通聚焦 |
| S20 | `P8-S20_SEELE_COMPLETE_BUILD_SLICE.md` | 5.6 Sol / max / 普通聚焦 |
| S21 | `P8-S21_CURRENT_SOURCE_AGGREGATE.md` | 5.6 Sol / max / Goal |
