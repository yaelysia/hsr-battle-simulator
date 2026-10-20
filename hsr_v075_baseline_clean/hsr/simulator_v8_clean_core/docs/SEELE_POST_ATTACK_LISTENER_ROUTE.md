# 希儿增强版普攻后置监听路线与行动事实链路

2026-10-20。基线 `58a6376`；任务约束见
[POST_ACTION_LISTENER_FACT_CLOSURE.md](POST_ACTION_LISTENER_FACT_CLOSURE.md)，当前进度只在
[交接文档](../../CODEX_HANDOFF.md)维护。

## 新增可用行为

- 正式构筑希儿增强版 `avatar:1102` E0/Lv1/P0、空装备、未选额外行迹，进入来源波次
  `400020800` wave0；来自公开决策的增强版普攻 `avatar_skill:1110201` 从修复前的
  `status_callback_group_atomic_precheck_failed` / `action_target_fact_missing` 变为成功。
- 同一会话提交后仍可从公开决策继续；示例第四次提交又是希儿普攻。
- 不声明：完整增强版自动追击、`TurnInsertAction` 插入行动自然路线、战技等其它技能分支、
  任意构筑或所有角色后置监听。

## 真实来源与动作

来源 `Config/ConfigAbility/Avatar/Advanced/Avatar_Advanced_Seele_00_Ability.json`：

- `$.AbilityList[7]` = `Avatar_Advanced_Seele_00_PassiveSkill_1`；其 `OnStart[1]` 在入场时为
  希儿添加 `MAvatar_Advanced_Seele_00_Skill02InsertReady_ShowBuff`（本次路线中真实存在）。
- `$.AbilityList[7].Modifiers.MAvatar_Advanced_Seele_00_Skill02_AutoInsertListen._CallbackList[1]`
  （`OnListenAfterAttack`）：
  - `PredicateTaskList`：`ByAnd(ByTargetTeam ParamEntity TeamLight, ByIsContainModifier Caster
    InsertReady_ShowBuff)`；
  - 成功分支 `Retarget`：`TargetType = ParamEntityAttackTargetList.SortByHP`，
    `Predicate = ByAnd(ByCompareHPRatio ParamEntity <= 动态值, ByTargetTeam ParamEntity TeamDark)`，
    `IncludeLimbo=true`，`MaxNumber=1`；
  - 子任务：`AddModifier MAvatar_Advanced_Seele_00_Skill02InsertMuteSp`、
    `TurnInsertAction(SkillType=ControlSkill02, AutoCast)`。

编译后正式身份（当前场景范围）：

- callback：`status_callback:...:MAvatar_Advanced_Seele_00_Skill02_AutoInsertListen:13:OnListenAfterAttack`
  （`global_listener`、`mainline_avatar_ability`、`executable`）；
- Retarget task：`..._CallbackList[1].CallbackConfig[0].formal_branch[0].child[0]:Retarget`，
  来源路径 `..._CallbackList[1].CallbackConfig[0].SuccessTaskList[0]`；
- 目标表达式 `...:Retarget:self`：节点 `Retarget` → 目标 `TargetAlias`
  `ParamEntityAttackTargetList.SortByHP`。

## 断点与共享修复

断点（修复前实测）：`action.after_attack` 只带普通 payload；监听侧
`systems/status_callbacks.py` 的 `_resolve_retarget_targets` 从
`trigger_event.admitted_action_target_fact` 取事实得到 `None`，`TargetMapAttackTargetList`
变换返回 `action_target_fact_missing`，回调组整笔回滚且不提交先行伤害。

修复位置（共享边界，无角色/ID 分支）：

- `systems/action_event_contract.py`：新增 `derived_post_action_listener_event`。只接受已签发、
  未绑定的事实，且必须与本次 `ActionCommand`、动作事件 id 和 impact 指纹一致；用通知自身的
  事件 id/window 与独立 step 签发 `ActionWindowExpectedScope` 后再 `bind_invocation`。
- `core/executor.py`：逐命中目标生成 `action.after_attack` 后，由实际执行边界调用上述函数；
  每个通知携带自己的事实与作用域，不新增派发，不改变事件别名、顺序和去重。

调用链：`ActionTargetSelectionSystem.resolve_impact`（事实生产）→ `CombatExecutor.execute`
（执行身份与派生通知绑定）→ `EventDispatchSystem`（`OnListenAfterAttack → action.after_attack`）
→ `StatusCallbackSystem._execute_formal_callback` / `_resolve_formal_status_targets` →
`_resolve_retarget_targets`（把事实与作用域放入 `TargetEvaluationContext`）→ `TargetSystem`
点别名链 `ParamEntityAttackTargetList.SortByHP` → `TargetMapAttackTargetList` 消费目标表。

## 来源子图组件证据

对真实编译子图做一次过程探针（临时脚本，不提交）：

- `TargetMapAttackTargetList` 实际消费本次已准入行动的目标表，解析为
  `('enemy:stage:400020800:wave:0:pos:0',)`，无阻断；
- 同一 Retarget 解析成功但目标为空集：满血目标的 `ByCompareHPRatio <= 动态值` 为假，
  监听零副作用（希儿状态集合前后相同，无 `InsertMuteSp`，无队列插入）；
- 条件为真的分支（`InsertMuteSp` + `TurnInsertAction`）本次未走到，属剩余依赖。

稳定回归不依赖该临时探针：公开路线示例与新增契约用例共同覆盖。

## 自然路线与验证

`examples/cli/seele_post_attack_listener_natural{,.commands}.json`：希儿 E0/Lv1/P0、娜塔莎
E0/Lv80/P6、空装备、来源波次 `400020800` wave0；四次公开提交依次为希儿普攻、娜塔莎普攻、
敌方行动、希儿普攻，结束时战斗未结束（CLI 退出码 3）。修复前的失败输入即同一场景的首条命令。

2026-10-20 实测（含本次代码的首次重新编译）：CLI `run` 耗时 51.24 s、峰值 535840 KiB；
同一归档 `cli replay` 在独立进程通过，9 步、0 错误（耗时 57.55 s、峰值 504676 KiB）。
定向测试：
`test_p9_a2_action_attack_target_context.py` 20 项通过（含新增
`test_derived_post_action_notice_binds_its_own_target_fact`），
`test_parallel_skill_targets.py`、`test_registered_event_nested_ability.py` 通过；
`test_arlan_action_graph_mvp.py`、`test_status_count_callbacks.py`、`test_action_pre_windows.py`
44 项通过；`test_sustain_resource_reconciled_rules.py` 除既有的 `by_task` fixture 失配
（I12 前的旧 lookup 形状，与本次改动无关）外 66 项通过。集成路线
`test_seele_post_attack_listener_natural.py` 1 项通过（显式 `-m integration`，单次约 51 s），
重跑公开示例的 4 次提交并确认后续决策仍可就绪。

## 拒绝边界保留

- 缺失、伪造（非 issuer 签发）、已绑定、跨执行者、跨事件和跨步骤的事实继续拒绝；新用例覆盖
  已绑定事实和另一执行者命令。
- 普通 payload、日志、回合所有者与审计 trace 不参与事实生产；动态与弹射目标继续按各自
  `unavailable_reason` 拒绝，既有用例保持不变。
- 后置通知仍逐命中目标派发一次，未改触发条件、伤害、回能、队列或命中次数。
- IncludeLimbo、存活过滤、排序和数量仍按正式目标表达式执行，不以清空目标掩盖错误。

## 瓦尔特 OnListenAfterSkillUse 复查

结论：**不同根**，不并入本批成果，也不声称其阻断已关闭。

- 来源：`Avatar_Advanced_Welt_00_Ability.json` 的
  `GlobalModifiers.MAvatar_Welt_00_Rank01_HitMark` 与 `..._SkillTree02_HitMark` 上的
  `OnListenAfterSkillUse → RemoveSelfModifier`（移除标记持有者自身）。
- 运行时在正式 `action.window.after_skill_use` 窗口派发；该窗口在基线已携带绑定事实
  （`core/executor.py` 的 `_action_window_dispatch_event`），经
  `dispatch_action_window_listeners` → `execute_action_window_formal_root` →
  `_execute_formal_callback` 中 `OnListenAfterSkillUse` 全局监听的事实检查。
- 独立缺口（与事实链正交）：E0/Lv1 战技在 availability 被 `RandomSelectInTargetList` 等
  未准入项挡住；普攻在能力任务图报 `target_alias_unresolved`；解锁行迹 `11004102` 需要
  额外效果 `10000005` 的结构化来源（`trace_extra_effect_has_no_structured_effect_source`）。

## 剩余具体依赖

1. `TurnInsertAction` 条件为真时的插入行动自然路线未验证（本次目标满血，条件为假）。
2. 注册事件根（`execute_registered_event_formal_root`）的 `TriggerAbility` 嵌套能力仍不接收
   行动事实；本批监听子图不含该节点，属独立边界，需要单独的作用域契约。
3. 瓦尔特的动作任务图与行迹额外效果缺口见上。
