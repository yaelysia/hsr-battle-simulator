# 技能后置监听的行动事实传递

执行：dsh / DeepSeek；约束与集中验收：Codex。基线 `58a6376`；当前状态只在
[交接文档](../../CODEX_HANDOFF.md)维护。

## 本批成果

让正式技能的后置监听消费本次已准入行动的真实上下文，接通希儿实际普攻及其后续合法行动。
沿同一事实的生产、派发、监听、Retarget/嵌套消费集中修复；单体、扩散、全体及不同执行者之间
保持目标表与调用身份隔离，不按角色逐项交回。

交付一条正式构筑、来源波次、外部 advance/submit 的自然路线，以及必要的共享边界检查。
完整希儿增强版自动追击、特殊追加行动、任意构筑及所有技能分支不作为本批完成声明。

## 已核对的事实

- Codex 使用希儿 `avatar:1102` E0/Lv1/P0、空装备、未选额外行迹，搭配娜塔莎 E0/Lv80/P6，
  进入来源波次 `400020800` wave0。正式出生成功，合法选择为增强版普攻 `avatar_skill:1110201`
  和战技 `avatar_skill:1110202`；不能按旧技能编号 `110201` 提交。
- 对 `enemy:stage:400020800:wave:0:pos:0` 提交合法普攻后，结果为
  `status_callback_group_atomic_precheck_failed` / `action_target_fact_missing`。
  实际监听者为 `MAvatar_Advanced_Seele_00_Skill02_AutoInsertListen.OnListenAfterAttack`。
- 真实来源 `Config/ConfigAbility/Avatar/Advanced/Avatar_Advanced_Seele_00_Ability.json`，
  `$.AbilityList[7].Modifiers.MAvatar_Advanced_Seele_00_Skill02_AutoInsertListen._CallbackList[1]`
  在成功分支用 `ParamEntityAttackTargetList.SortByHP` 执行 Retarget。
- `core/executor.py` 已持有接受行动产生的 `action_target_fact`；正式 action.window 事件会绑定
  预期调用作用域。其后逐目标生成的 `action.after_attack` 仅带普通 payload，当前未携带该事实。
- 目标解析只接受正式生产、调用身份绑定的 `AdmittedActionTargetFact`；现有防伪造、跨执行及
  跨步骤检查必须保留。不能从 payload 的 actor/target 列表重新制造事实。
- 瓦尔特增强版来源另有 `OnListenAfterSkillUse → RemoveSelfModifier`。它是同域复查入口，
  不能仅凭 V2 的旧阻断说明认定与希儿同根，也不能预先宣称本批将关闭其全部阻断。

探针输入与命令在当前工作区可复用：`/tmp/seele-post-attack-probe.json`、
`PYTHONPATH=hsr_v075_baseline_clean .venv/bin/python -B /tmp/probe_seele_post_attack.py`；
日志 `/tmp/seele-post-attack-probe.log`。上述构筑、来源与合法动作说明足以重新建立输入，
正式回归和示例不要依赖临时文件。该探针不注入状态，也未修改生产代码。

## 生产权威与完整调用链

`ActionTargetSelectionSystem.resolve_impact` 接受正式动作与目标，产生行动事实；
`CombatExecutor` 持有执行身份并发布事件；`EventDispatchSystem` 规范化与派发；
`StatusCallbackSystem` 执行真实监听；`TargetSystem / EntityRelationResolver` 消费目标表；
后续 Retarget、嵌套任务图及 settlement/source audit 继续使用各自的正式身份。

直接入口：`systems/action_event_contract.py`、`core/executor.py`、`systems/event_dispatch.py`、
`systems/status_callbacks.py`、`systems/unit_relation.py`、`systems/target.py`。
先沿实际调用者确认丢失位置，再改最小共享边界；不为每个角色加补丁。

## 一次性约束

1. **事实来自接受行动**：复用现有类型化事实、执行身份和作用域契约。派生后置通知若需绑定
   自己的事件/步骤身份，由实际生产边界完成；不能复用旧的已绑定窗口凭证、放宽校验，或把
   通知冒充另一个技能步骤借用权限。普通 payload、日志、回合所有者和审计 trace 不是生产权威。
2. **主体与目标表分清**：监听者 owner/caster、实际技能执行者、当前命中目标、主目标互不替代。
   AttackTargetList、SkillTargetList、SkillSubTargetList 继续遵守各自来源契约；不能把单次命中
   列表当完整行动表，也不能用声明主目标替代扩散/全体影响组。关注“甲监听乙攻击丙”的路径。
3. **传递不断链**：派发、规范化、回调作用域包装、Retarget 和确实需要该上下文的嵌套消费
   必须保留正确事实。子调用与并行子动作使用自身的执行作用域，不能借父动作或上一事件的凭证。
   没有接受行动身份的独立伤害不凭空获得技能行动权限。
4. **事件粒度不变**：保留 OnAfterAttack、OnListenAfterAttack、OnAfterSkillUse、
   OnListenAfterSkillUse 的既有归属、顺序和去重语义；不为运输事实新增一次派发或扩大事件别名。
   不改变本次任务以外的触发条件、伤害、回能、队列及命中次数。
5. **拒绝边界保留**：缺失、伪造、跨执行/跨步骤的事实仍拒绝；动态目标模式按现有每种目标表
   的准入处理，不能因静态路径接通就放开未证明的命中表。先验能力校验不能被合法空目标绕过。
   IncludeLimbo、存活过滤、排序和数量继续按正式目标表达式执行，不以清空目标或跳过监听掩盖错误。
6. **原子性与审计**：失败整笔不泄漏状态、mutation、RNG；后置监听晚期失败也不能提交先行
   伤害。成功的参数/目标与 mutation、settlement 来源一致。瞬时事实不从 JSON 注入或归档恢复；
   必要回放从正式输入重新生产事实，不序列化内部能力凭证。
7. **范围与工程**：原始来源与合法条件推动修复，不默认删除增强版监听、不切换回旧角色来源，
   不按角色名/ID/文件名写 runtime 分支。同域共享问题一并关闭；独立队列或角色机制缺口明确
   保留，不混作本批成果。无新依赖/环境、不动 submodule、不擅改兼容方向、不提交或推送。

## 固定验收与成本

- 先保存上述合法普攻失败的正式输入与原因；修复后同输入成功，后续还能从公开决策提交合法
  行动。保留真实增强版启动与监听，不能替换成手写最终目标列表或只绕过一个回调。
- 真实希儿监听中的目标表消费至少执行一次；可用来源子图组件证明 Retarget 的选择及条件
  为假时零副作用，明确组件身份。完整自然路线与来源子图分别报告。
- 核对不同执行者/目标、静态影响组与三种目标表、作用域包装/Retarget 的同一调用链；复用已有
  检查，缺失处只补能暴露本次错误的最小用例，不穷举组合。
- 已有边界入口：`tests/test_p9_a2_action_attack_target_context.py`、
  `tests/test_parallel_skill_targets.py`、`tests/test_registered_event_nested_ability.py`。
  选择实际受影响部分；不用为每个调用者重编目录或重跑整场。
- 瓦尔特 OnListenAfterSkillUse 复查必须先定位实际事实链；同根一起修，不同根明确记录。
  不能以其单独仍有准入缺口否定已关闭的共享链，也不能把它当已关闭的完整角色路线。
- 一条希儿自然路线合并验证修复结果；选用缓存/场景范围编译，重任务串行并记录耗时与峰值。
  无默认全目录编译或全量回归；事件序列/归档路径实际变化时再用该路线补一次回放。

交回时写清新增可用行为、真实来源与动作、共享修复位置、必要验证和剩余具体依赖。
CLI/测试入口补简短说明，交接覆盖更新当前条目；不再追加逐轮过程或新增历史快照。
