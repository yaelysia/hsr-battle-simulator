# P9-S8B5C 跨入口 Runtime 运输验收报告

## 结论

P9-S8B5C 已通过验收。正式 ability leaf 派生的任务图 continuation 现可同步穿过事件派发、
状态 callback 和属性 watcher，并把状态 `TriggerAbility` 子图 projection 原子返回外层共享执行器。

本结论只证明通用运输组件可执行。S8B5B 已验收的 8 条真实调用边和 6 个 nested phase 仍继承父
callback 的 S8C/S9/S10 blocker，因此没有宣称真实角色链已 gameplay executable。

## 完成结果

- continuation 只从当前类型化 hook request 派生；事件 payload、日志和 source trace 均未参与重建。
- ability 伤害事件、递归事件、状态 callback 及属性 watcher 运输同一 continuation 和 ability hook。
- 状态 `TriggerAbility` 只消费类型化 phase/standalone 引用，并要求唯一 `nested_only` 正式图。
- status、watcher 和 event 结果增加严格 child projection 通道；失败结果不能携带成功子图投影。
- 直接环、间接环、projection 身份冲突、callback 组失败及 watcher 后置失败均在外层事务回滚。
- 普通无 continuation 的入口保持可用，但没有 ability hook 时不能进入状态触发的角色正式子图。

## 五面验收

| 审查面 | 结果 |
|---|---|
| 来源范围 | 不改 lowering 或来源目录；继承 S8B5B 的真实调用边审计，fixture 未冒充真实内容执行 |
| 生产不变量 | 三类结果对象拒绝错误 projection；事件和 callback 组失败清空成功子图，状态与正式四通道回滚 |
| 正式调用者 | CodeGraph 核对 ability 伤害事件、事件递归、状态入口及独立 watcher callback 入口均已运输 |
| gap 归属 | 旧 topology 归 S8B6；随机、命中与 barrier 归 S8C；事件和状态准入仍归 S9/S10 |
| 验证质量 | 实际 ability leaf 发起成功链；共享执行器负责环和冲突；blocked 外层投影与成功 child projection 分开判断 |

## 验证结果

- 唯一主入口最终 8/8 谓词通过。
- 最终墙钟约 0.26 秒，峰值 RSS 33,076 KiB，summary 1,677 bytes。
- 完整 Canonical IR build 和来源扫描均为 0。
- 验证器 420 个非空行，等于修订后的 420 行硬上限；未拆文件或增加 CLI 模式绕预算。
- 全包 `compileall`、精确 fixture 构造 smoke 和 `git diff --check` 通过。
- 未运行 S8B1-S8B4 历史主入口，也未运行 catalog/full 验证。

## 运行偏差与流程反馈

首次业务运行前的代码审查发现并修复了两个不会被原夹具发现的生产问题：伤害入口参数被误放到
旧任务函数，以及 listener 已成功后 watcher 失败会在回滚前构造“错误加成功 projection”的非法结果。

验证入口有两次在业务谓词前因窄 RuleBook 误走完整构造器而失败；改为只替换无关领域初始化的最窄
状态回调夹具，并执行精确构造 smoke 后进入业务。首次业务结果的错误码和原子行为均正确，但验证器
错误要求 blocked 结果完全没有 projection；按 B5A 既有契约改为允许外层 blocked 诊断、禁止成功 child
projection 后，最终运行通过。

可复用结论已写入流程：运输卡必须追到同步 watcher/reconciler 返回边界；新增 fixture 的精确构造和
调用形状 smoke 必须出现在阶段清单；允许 blocked 诊断的结果应按身份和状态验收，不能用容器为空代替。

本验证器验收后标记为 `historical_evidence`。
