# 自动插入行动完整执行链

> 历史归档（2026-10-21 整理）：下文状态、任务顺序和验收要求仅反映记录当时。
> 当前工作以[交接](../../../../CODEX_HANDOFF.md)和[执行约定](../../AGENT_WORKFLOW_AND_VALIDATION.md)为准；归档不代表本轮重新验收。

执行：dsh / DeepSeek；约束与集中验收：Codex。工作基线 `a2afebf`；当前状态见
[交接](../../../../CODEX_HANDOFF.md)。本批完成下述整条链后集中交回。

## 可观察成果

沿正式构筑、来源波次与公开 `advance/submit`，使希儿增强版监听的真实条件满足后：

```text
普通行动把敌人打至阈值以内且仍存活
→ 真实后置监听 Retarget 选中目标
→ 正式 TurnInsertAction 入队
→ 插入开始回调
→ 希儿对所选目标自动执行战技
→ 结束回调及临时状态清理
→ 外部仍能查询并提交后续合法行动
```

交付包括成功、取消与执行失败的共享边界。不能仅以队列创建成功、单个条件接通或手工调用
伤害叶子代替整链。已有条件为假的路线继续复用。

## 已核对的来源与边界

- 基线已接通 `action.after_attack` 的行动事实及希儿条件为假的自然路线，配置为
  `examples/cli/seele_post_attack_listener_natural{,.commands}.json`。
- Codex 已用希儿 E0/Lv1/P0、娜塔莎 E0/Lv20/P1、空装备及同一来源波次复现真分支阻断。
  新配置为 `examples/cli/seele_automatic_insert_natural{,.commands}.json`：前七次提交成功，
  第八次希儿普攻前目标剩余 `243.53527588697298 / 482.02732907999996` HP；本次攻击跨过
  阈值后回调以 `task_graph_control_requires_domains:timeline_queue` 阻断，整笔回滚，队列为空。
  该输入在当前基线预期阻断，供本批实现前后对比；完成后补自动战技后的公开行动命令。
- 断点在 `tbgd/task_graph_materializer.py::_node_status`：`TurnInsertAction` 有
  `action_abort_continuation` / `OnInsertAbort` 分支，其 `timeline_queue` 归属尚未承接。
  不是目标事实再次丢失。实测该次探针 62.50 s、峰值 548016 KiB；临时过程日志为
  `/tmp/seele-insert-action-next-batch-20.log`，永久复现不依赖该文件。
- 真分支来源：`Config/ConfigAbility/Avatar/Advanced/Avatar_Advanced_Seele_00_Ability.json`，
  `AbilityList[7].Modifiers.MAvatar_Advanced_Seele_00_Skill02_AutoInsertListen._CallbackList[1]`。
  Retarget 按正式动态阈值、`IncludeLimbo`、排序和 `MaxNumber` 选择目标，添加临时状态并发布
  `TurnInsertAction(SkillType=ControlSkill02, AutoCast, AutoCastTargetType=ParamEntity)`。
- 同一任务声明 `CustomTag`、`IgnoreBPDec`、`AbortBehaviorFlags`、`PreCheck` 与 `OnInsertAbort`。
  编译已有 QueueIntent/Window/Resolution，不能将这些声明丢掉后另补角色专用执行器。
- 全局状态 `MAvatar_Advanced_Seele_00_Skill02InsertMuteSp.OnInsertActionStart` 先用
  `ByCompareParamString` 匹配 tag，再执行技能属性修改、安装清理状态并消费 ready 状态。
  清理状态在 `OnAfterSkillUse` / `OnInsertActionFinish` 有真实任务，须核对实际派发和移除顺序。
- 现有 `event.param_string` 只有条件消费者和类型化接口声明，尚无该队列事件的正式事实供应；
  `QueueActionStartFact` 已供应 actor/targets，但没有 tag。不能直接把 payload 字符串接入消费者。
- 战技实际正文是 `Skill02_Phase01 → Skill02_Phase02`，后者含四个伤害任务及状态施加。
  本批须检查完整父动作及子任务，不将战技准入等同于已执行成功。

## 生产权威与改动范围

| 边界 | 权威与消费 |
| --- | --- |
| 来源编译 | `tbgd/lowering.py` 将任务、选技、目标、tag、资源及取消策略落实为正式 IR；不把 source_trace 当运行字段。 |
| 控制流物化 | `tbgd/task_graph_materializer.py::_node_status` 正式衔接队列节点及延迟取消分支，保留定义引用和领域归属。 |
| 监听产生队列 | `StatusCallbackSystem._execute_queue_intents`、`QueueTargetResolver` 与 `QueueSystem.enqueue`；监听 caster、触发者和 Retarget 目标分开。 |
| 选择与消费 | `QueueSystem._resolve_action_candidate`、`CombatScheduler._try_queue_drain`；按实际行动者的数据卡、构筑等级和动作集选择，再正式接受目标。 |
| 开始与条件 | `QueueSystem.action_start_event`、类型化 queue fact、派发器和条件 provider；身份来自本次待消费条目和正式定义。 |
| 行动执行 | `CombatExecutor` 与通用能力任务图执行真实战技，重新产生该行动自身的目标事实。 |
| 结束与取消 | `action_terminal_event`、`plan_terminal_resolution`、来源取消任务及状态生命周期；结算与审计观察原生变化。 |

先沿这些正式调用者检查全链，按共享缺口集中修复。只改实际需要的边界，复用已存在的动作、
任务图、队列与 mutation；不另建调度框架。

## 一次性实现约束

1. **入队与取消分支分开**：入队只产生正式条目，`OnInsertAbort` 必须保留为实际取消时消费的
   正式延迟分支；不能作为普通子序列在成功入队或成功正文后立即执行。物化准入需要正式
   QueueIntent/Window/Resolution 及取消分支的实际承接，不能将整个 `timeline_queue` 加入
   `_ALREADY_CLOSED_DOMAINS`、删除控制分支或把整个任务标成 process_only 来绕过阻断。
2. **动作与主体**：监听者、触发这次攻击的单位、插入行动者、被攻击目标互不替代。至少关注
   “娜塔莎攻击敌人、希儿插入战技”的路径；按实际行动者的正式动作集和有效等级解析战技，
   不按旧技能 ID、触发者等级或候选首项选技。
3. **目标与作用域**：沿真实 Retarget 选择传递目标，消费时重新检查合法性；不能用当前回合
   所有者、上一命中或手写列表替代。插入战技经自己的接受边界生成新执行身份和目标事实，
   不复用触发攻击的已绑定凭证，也不把 queue 通知冒充 action.window。
4. **tag 与瞬时条件**：CustomTag 必须由正式队列定义/条目生产为类型化事实，并与当前条目、
   事件、行动者及调用作用域一致。缺事实、普通 payload 冒充、另一条目凭证均拒绝；真实但
   不匹配的 tag 才按正常条件假处理。不得从日志、source_trace 或同名状态猜出字符串。
5. **任务与资源**：真实开始回调中的 `ModifySkillPropertyByType` 等战斗叶子若未接通，一并
   补齐所需通用表达。资源按已采纳策略与正式声明执行，核对 `IgnoreBPDec`、技能属性修改、
   战技点和回能；临时修改不能泄漏到之后的手动技能。缺省值先核对既有正式依据，不能无据
   填零，也不能把未执行的任务标为完成。
6. **生命周期与顺序**：开始通知在正文前执行且只执行一次；成功正文后才发 finish。符合
   正式条件的游戏内取消走取消任务，不执行正文或成功 finish；缺来源、缺公式、校验错误
   属实现阻断，不能伪装成正常取消后静默丢掉队列。保留当前事件族归属、排序与去重。
7. **两笔事务分清**：产生队列的行动中，伤害、临时状态与入队遵守原有原子边界；队列消费
   失败时，不能泄漏 dequeue、开始状态修改、正文伤害或 RNG。也不能回滚此前已经成功提交
   的普通攻击。合法取消允许提交正式取消清理；晚期 finish 失败仍回滚本次消费的全部变化。
8. **恢复与再次触发**：按正式 insert_action 生命周期恢复被中断的时机，不多走一次普通
   TurnStart/TurnEnd、不额外重置 AV 或扣寿命。ready、mute、clean、CD 及取消标记按来源消费
   和清理，不能残留免耗效果或递归无限入队。重复触发及 `SameTagInsertUnusedCount` 只使用
   已准入定义，不能根据一个样例自行扩大为永久限次或任意去重。
9. **原生证据**：入队、选择、开始、正文、结束/取消与清理均可从 mutation、settlement 和
   实际来源反查；不补写成功答案，不用审计结果驱动 runtime。目标与资源记录须和实际一致。
10. **集中收口**：同域叶子、目标、资源、取消与恢复缺口一起修完再交回。注册事件根的
   `TriggerAbility` 行动事实是独立后续项；仅当实际路线依赖时接入必要边界，不盲目全局透传。
   瓦尔特其它缺口、limbo 救援和其它插入类型不扩入本批。无新依赖/环境、不动 submodule，
   不自行提交或推送。

## 固定验收与执行次序

1. 先复用上述已复现的八次公开提交，保存首次达到真实阈值的输入、命令及实际阻断。允许调整正式
   构筑、队伍和来源波次以避免直接击杀；不注入 HP、状态、队列、时间线或替换正式回调。
2. 用真实来源子图集中处理条件、选技、资源和清理；组件输入明确标注。复用
   `test_queue_terminal_callbacks.py`、`test_p9_a2_action_attack_target_context.py` 及已有队列检查。
   另同步 `test_sustain_resource_reconciled_rules.py` 的旧 lookup fixture 为当前正式结构，
   不给生产代码增加旧输入兼容。
3. 保留最小必要检查：不同触发者/行动者与准确目标；本次 tag 的真假与缺失/错用事实；
   开始前取消及清理；正文或结束晚失败不泄漏本次消费。可合并组件场景，不逐项重跑整场。
4. 一次自然集成跑通“真分支→自动战技实际伤害→清理→后续公开行动”，明确比较战技点、
   回能、目标和事件顺序；继续复用上批条件为假的例子，不重复编译全目录。
5. 队列事件与消费序列有变化，用该次自然运行归档做一次独立 replay；复用已有产物，不再
   生成第二场。重任务串行加锁并记录耗时/峰值，不默认全量回归。

交付一个可复跑示例/固定命令与必要回归；CLI/测试入口简记，交接覆盖更新当前状态。
已经完成的探查和源链证据合并记录，不逐个 blocker 或单个修复点交回。
