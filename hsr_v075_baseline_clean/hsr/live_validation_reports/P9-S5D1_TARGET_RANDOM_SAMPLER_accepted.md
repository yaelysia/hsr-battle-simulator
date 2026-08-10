# P9-S5D1 目标随机抽样基础契约验收报告

状态：`accepted`

## 阶段结论

S5D1 已通过验收。目标随机计划、结果和 sampler 成为 `Retarget.ByRandom` 与
`TargetShuffle` 的唯一随机权威；动作弹射和 `RandomSelectInTargetList` 未提前实施，留给 S5D2。

## 生产结果

- 新增严格、递归不可变的目标随机计划和结果，构造边界拒绝重复候选、非法数量、未知模式、
  缺来源以及可变嵌套污染。
- `single`、`sample_without_replacement`、`shuffle` 共用一个 draw 构造器；空池、单元素、
  数量截断和无放回语义分开处理。
- choice identity 同时绑定来源、求值上下文、调用身份、原始候选池、remaining pool、draw index
  和总 draw 数。过期 choice 即使仍指向现有成员也不能命中新 request。
- 显式 ledger 未完成时不返回任何部分 RNG event；完成后一次返回有序事件链。
- replay 按原事件的 deterministic/explicit 模式重新执行计划并逐字核对事件，不能用另一模式
  伪装重放。
- 随机 Retarget 先完成真实候选、predicate 和 lifecycle 解析，再随机排序和按上限截取；
  `TargetShuffle` 返回完整排列。

## 五面验收

1. 来源范围：当前三类真实来源均非空；表达式随机节点全部可由 sampler 接纳，随机任务仍保持
   `s5d_random_target_task` 委派状态。
2. 生产不变量：blocked 结果无选择和事件；结果事件递归不可变；零/单候选不制造 RNG。
3. 正式调用者：CodeGraph 显示生产调用者仅为 `TargetSystem` 的 Retarget/Shuffle 两条路径；
   未新增私有 ledger，弹射旧路径未被误称迁移完成。
4. Gap 归属：D1 负责的表达式随机实现 gap 为零；随机任务与弹射归 S5D2，能力控制流归 S8。
5. 验证真实性：真实来源只证明来源闭合，validation fixture 只证明上下文运输和运行时语义；
   两类证据未互相冒充。

验收中主动发现并修复两项问题：确定性事件最初被错误地用显式模式 replay；来源报告最初会
给随机任务引用错误的代表来源。两项均在打勾前修正。

## 验证结果

最终唯一主入口：

```text
python3 -B -m simulator_v8_clean_core.tools.validate_p9_s5d1_target_random_sampler
```

- 35/35 检查通过，`ok=true`。
- 墙钟 4.376 秒，峰值 RSS 267,660 KiB。
- evidence 189,500 bytes；summary 1,934 bytes。
- 完整 Canonical IR 构建 0；目标来源窄投影 1 次。
- 验证器 479 非空行，低于 520 行预算。
- `compileall` 与 `git diff --check` 通过。
- 未修改共享 RNG 实现，因此未运行非触达 RNG direct。

最终证据：`/tmp/p9_s5d1_final_20260806/`。

## 检查点状态

当前沙箱不能写 `.git/index`，因此尚不能建立 Git 检查点。S5D1 的 accepted 状态由本报告、
已勾执行卡和未漂移工作区共同记录；恢复 Git 写权限后应补交范围干净的检查点。
