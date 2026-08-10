# P9-S5C2 动作选择查询、提交与执行上下文验收报告

状态：`accepted`  
日期：2026-08-06  
下一阶段：`P9-S5D_RANDOM_TARGET_AND_AGGREGATE.md`

## 验收结论

P9-S5C2 通过五面验收。动作主目标选择现由 S5C1 类型化契约、committed state 和统一
`ActionTargetSelectionSystem` 共同产生；外部只提交选择，scheduler 负责授权，executor 只消费
已签发的不可变上下文。选择关系与实际作用范围已经分离，旧自由 target policy 不再参与生产行为。

本结论不表示真实角色动作已全部端到端可执行。真实 explicit/automatic 样例只证明来源语义；
Decision -> scheduler -> executor -> settlement/replay 连续性由明确标记的 validation fixture 证明。
动态目标、随机抽样、shuffle 和 bounce 后续命中继续精确归 P9-S5D。

## 五面结果

1. 来源范围：10,799 条动作目标契约全部进入字段分母，8,610 条 lowered、2,189 条 blocked；
   10,216 个真实 `TargetInfo` 同级字段沿用 S5C1 已验收闭包，全部 gameplay 字段已有唯一消费者。
2. 生产不变量：query、selection、context、decision authorization 和 action authorization 均严格绑定
   actor/action/level/state/contract/candidate；陈旧、重复、越界、伪 seal 和 metadata 注入均原子拒绝。
3. 正式调用者：normal、summon、enemy fixed/external、queue、manual ultimate、scheduler、executor
   和 UI runner 已迁移。公开请求不会取候选首项，也不会从画面当前单位推断提交 actor。
4. gap 归属：S5C1 blocked 不发布候选；动态目标与 bounce 仅在独立 impact 边界阻断并交给 S5D；
   client target lock 保持 projection-only，standalone ability 与 timeline tie 有明确代码豁免。
5. 验证真实性：真实来源语义、通用上下文运输和未证明的真实 gameplay 端到端结果分栏记录；
   总门含假值控制，完整 Canonical IR 构建次数为 0。

## 验收发现与修正

五面代码审查在主验证之外一次性发现并修正三项问题：

- UI 曾使用行动条当前单位作为提交 actor，队列插入动作可能错绑，行动序并列也没有单一 actor。
  现改为每个 `ActionChoice` 自带并提交 actor；多行动者 UI 路线编辑未接通时明确阻断。
- 手动终结技曾在入队前不验证动作所有权，只能等出队时失败。现于首次 mutation 前核对
  `insert_window` admission；无权动作保持 state 和 queue 不变。
- 同一决策若出现重复 actor/action/level，旧逻辑会采用首项。现仅唯一匹配可提交，重复身份在
  decision 边界 fail-closed。

这些问题没有形成多轮整改：完成闭合地图后实施一次，首次完整五面审查集中发现，单次修正后
最终门通过。相应通用规则已写回 `AGENTS.md`、工作流文档和 P9 执行卡协议。

## 最终证据

- 主入口：`validate_p9_s5c2_action_selection_query_submit_context`
- 结果：6/6 顶层谓词通过，`ok=true`
- 产物：`/tmp/p9_s5c2_final_20260806/`
- 墙钟：7.225 秒
- 峰值 RSS：444,520 KiB
- evidence：22,604 bytes
- 构建：动作目标目录 1 次、角色动作窄切片 1 次、transport fixture 1 个、完整 Canonical IR 0 次
- `compileall`：通过
- UI choice actor 差量探针：通过
- 重复 decision choice 差量探针：通过
- `git diff --check`：通过

验证器共 700 个非空行，达到但未超过预算；本阶段验收后冻结为 `historical_evidence`，S5D 不得
继续扩写或重跑本入口，只复用生产契约并做自己的随机目标聚合门。

## 检查点状态

Checklist 已标记验收。由于当前沙箱不能写 `.git/index`，本报告生成时尚未创建 Git 检查点；
提交范围必须排除既有无关的架构文档修改和 UI 草稿。
