# 希儿增强版自动插入行动路线（2026-10-20）

本路线沿正式来源、构筑装配、来源波次与公开 advance/submit 走通：

    普通行动把敌人打至真实阈值以内且仍存活
    → 真实后置监听 Retarget 选中该目标
    → 正式 TurnInsertAction 入队（custom_tag / insert_abort 绑定）
    → 开始回调（tag 条件、SPBase 静音、MuteSp 生命周期）
    → 希儿对所选目标自动执行战技（实际动作集与有效等级）
    → 正文后 OnAfterSkillUse / OnInsertActionFinish 清理
    → 后续公开行动仍可查询并提交

## 固定输入与命令

- 场景：examples/cli/seele_automatic_insert_natural.json
- 操作：examples/cli/seele_automatic_insert_natural.commands.json
  （八次复现提交 + 自动战技后的第九次公开行动：娜塔莎治疗战技）
- 构筑：希儿 avatar:1102 E0/Lv1/P0、娜塔莎 avatar:1105 E0/Lv32/P2，均空装备；
  来源波次 400020800 wave0；无 HP、韧性、状态、时间线或队列注入。
- 娜塔莎等级由复现输入的 Lv20/P1 调整为 Lv32/P2：复现输入中她在第三次敌方攻击后死亡，
  使仍然有效的物理击破 DOT 在采样施加者时命中“施加者死亡后的属性保留规则待补”
  （交接“规则待定”条目），与本批插入链无关且无法在批内以无据方式补齐。仅提升存活等级，
  命令、目标、波次与正式回调均未替换；第八次提交仍首次跨过真实监听阈值。

    export PYTHONPATH=hsr_v075_baseline_clean
    .venv/bin/python -B -m hsr.simulator_v8_clean_core.cli run \
      hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/seele_automatic_insert_natural.json \
      --commands hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/seele_automatic_insert_natural.commands.json \
      --output /tmp/hsr-seele-automatic-insert.json.gz

脚本结束时战斗未结束（敌方另一只仍存活），CLI 返回 3 并保存可继续会话。

## 生产权威与实现边界

| 边界 | 实现 |
| --- | --- |
| 来源编译 | tbgd/lowering.py：QueueIntentIR.custom_tag；IgnoreBPDec 仅关闭战技点扣减；ModifySkillPropertyByType 落为类型化 effect（无 Value 记为 absent_value_muted_to_zero，依据 MCommon_Windfury_SkillNoNeed 同形声明与 ...InsertMuteSp 命名）。 |
| 控制流物化 | tbgd/task_graph_materializer.py：仅当正式 QueueIntent/QueueWindow(insert_action)/QueueResolution 全部 executable、且 OnInsertAbort 子分支保留并物化时，TurnInsertAction 控制节点才物化为 sequence；对应 disposition 的 timeline_queue 域按同族退役机制退休，没有全局关闭检查。 |
| 监听产生队列 | StatusCallbackSystem._execute_queue_intents：条目保存 custom_tag 与正式 insert_abort 绑定（callback、graph/node、取消子任务、状态实例）。SameTagInsertUnusedCount 改为统计同 tag 的待消费插入条目，不再推断为永久限次状态。 |
| 选择与消费 | QueueSystem._resolve_action_candidate 在接收规则库时使用实际行动者的 combatant_action_set 与 effective_skill_levels_by_action_id 定级，并与编译期候选交叉校验。 |
| 开始与条件 | QueueActionStartFact/QueueActionTerminalFact 提供类型化 custom_tag；QueueEventConditionProvider 只消费该事实（拒绝普通 payload 字符串、他条目凭据与错位 invocation），真实但不匹配的 tag 按条件假处理。 |
| 行动执行 | CombatScheduler._try_queue_drain 走既有 CombatExecutor；重建正文命令时保留类型化插入身份（action.window 事件的 is_insert_action 与队列窗口族一致）；insert_action 与 ultimate 一样保存/恢复被中断窗口，正文不额外推进 AV、不额外开回合。 |
| 结束、取消与清理 | 仅已确认的正常取消条件（同 tag 待消费插入达上限）进入 insert_abort 分支，缺最大次数等未解析预检保持阻断；OnAfterSkillUse/OnInsertActionFinish 清理链；入队前 PreCheck 合法取消时执行正式 insert_abort 子分支（不产生条目、不执行正文）；排空期合法取消时由 StatusCallbackSystem.execute_insert_abort 沿同一来源图执行取消子任务。晚期 finish 失败按既有语义整次回滚并保留条目。 |
| 资源 | 插入战技免战技点（IgnoreBPDec），回能由开始回调的 SPBase 覆盖静音；覆盖记录在所属状态实例 status_details 上，状态移除即失效，不泄漏到后续手动技能。BPNeed 覆盖同时进入公开可用性查询、动作契约、调度预检与执行计划；SPBase 覆盖同时进入资源计划与正文 action_sp_base 回能公式。存在显式 action_sp_base 正文回能请求时，资源计划回能恒为 0，由正文公式读取有效覆盖，保持单一回能生产者；覆盖冲突或无法解析一律阻断资源准入，不回退基础值。 |

## 验证入口

- 技能属性修改的 mutation 携带 effect_source 与显式属性值求值事实，RuntimeSourceAuditor 对真实自然路线消费事务返回 ok；
- tests/test_automatic_insert_action_closure.py（7 项单元 + 3 项 integration 标记的真实场景）：
  - tag 事实真/假/缺失/冒用与派发作用域；
  - 技能属性覆盖的状态实例作用域；
  - 自然路线入队、开始、正文伤害、清理、实际等级、资源与后续公开行动；
  - 入队前合法取消执行 OnInsertAbort 分支（不重复条目、无正文）；
  - 晚期 finish 失败回滚本次消费且保留条目。
- 归档：上述 CLI 运行产物用 cli replay 独立回放。
- 复用已有队列检查：tests/test_queue_terminal_callbacks.py（before/after/abort 顺序与取消保留）。

## 本批验证结果

- tests/test_automatic_insert_action_closure.py：8 项纯组件单元通过（含显式回能单一生产者）；3 项真实场景检查已标记
  integration，默认快测不再收集（tag 事实与冒用、技能属性覆盖、资源门槛/公式、未解析预检；
  自然路线含 RuntimeSourceAuditor 审计与 action.window is_insert_action 断言、入队前取消清理、
  晚期 finish 回滚）。
- 固定命令运行：九次提交后 CLI 返回 3；希儿能量在插入行动前后不变（动作回能被静音，
  击杀回能按既有资源规则单独结算），战技点在插入行动前后不变；第九次治疗战技正常消耗 1 点。
- 归档独立回放：step_count=19，errors=[]。
- 最终一次运行（含 1 次 IR 重建与九次提交）墙钟 2:58、峰值约 1.13 GiB；重任务串行执行。
- 定向回归：队列终结回调、队列状态转移、可持续资源复核、终结技能量门/执行、
  希儿条件为假的后置监听自然路线、编译器一致性测试。

## 未纳入本批

- 其它插入类型（TurnInsertAbility/TurnInsertAssistantAbility）的取消与正文迁移；
- 瓦尔特其它缺口、limbo 救援与注册事件根 TriggerAbility 的行动事实作用域；
- 施加者死亡后的 DOT 属性保留规则（见交接“规则待定”，本路线仅通过正式构筑调整规避）。
