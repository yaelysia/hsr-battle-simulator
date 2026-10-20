# v8 当前交接

更新：2026-10-20。只维护当前状态、已验收基线、阻断和下一步；更新时替换对应条目。

## 当前状态

- 主线：`simulator_v8_clean_core`；实现固定交给 dsh / DeepSeek，Codex 负责范围、约束与验收。
- 最近已验收提交：`fc2e6ff`（I12 逐任务参数绑定与交接瘦身）；前基线为 `b4b8227`。
- TBGD 固定指针：`14c1d18f91a8101d610e6c523447a7517de3fae1`；本批未新增依赖或环境。
- 当前基线已提交；V2 五元素自然路线与共享清理修复均已验收通过，尚未提交。

## 当前任务：V2 剩余五元素普通击破自然路线

**状态：本批验收通过，待提交。** 五条自然路线通过；共享动态值清理的多目标事务合并、
差分审计及晚期失败不泄漏 mutation 均已复验。

- 执行说明、五行结果表与验证成本见
  [V2_ORDINARY_ELEMENT_BREAK_ROUTES.md](simulator_v8_clean_core/docs/V2_ORDINARY_ELEMENT_BREAK_ROUTES.md)。
- 集成入口：`simulator_v8_clean_core/tests/test_ordinary_element_break_natural_routes.py`；
  五个示例与固定命令为 `examples/cli/{asta_fire,arlan_thunder,march7th_ice,lynx_quantum,
  trailblazer_imaginary}_break_natural{,.commands}.json`。
- 共享修复：状态移除/过期同一事务清理 status 作用域动态值（避免二次生命周期复用来源哈希
  `instance_id` 时串值）；`apply_remove_modifier`/`apply_dispel_status` 改为在候选状态上逐目标
  规划并原子合并整仓写入；`source_audit` 校验清理 mutation 的精确差分、保留条目/索引/ledger
  与结算关联。永久回归见 `tests/test_status_dynamic_value_cleanup.py`，覆盖两个移除调用者、
  清理范围与结算篡改。
- Codex 最终复验：原始复现、相关组件与第二目标失败检查共 16 项通过；量子自然路线
  1 项通过。此前五路线通过及量子独立 replay 13 步、0 错误的证据继续复用。
- 计划的佩拉/希儿/瓦尔特均被正式准入阻断，按同元素合法角色交付（三月七/玲可/同谐主），
  示例文件名已同步；各元素剩余依赖见执行说明五行表，不阻断本批普通单韧性路线验收。

## 已验收基线

| 范围 | 可用行为与边界 |
| --- | --- |
| V2 五元素普通击破 | 火/雷/冰/量子/虚数的首次击破、元素后续效果、自然恢复、同目标二次击破及后续合法行动通过；限定正式构筑、来源波次、普通单韧性和存活施加者，场景与边界见当前任务说明。 |
| I12 逐任务绑定 | 倍率、基准、等级及削韧来源逐任务绑定；继承传播与物化分开，冲突拒绝，常数时间查找。29 项验收通过；继承链包含明确标注的组件输入，不代表完整角色整图。边界见 [I12 契约](simulator_v8_clean_core/docs/I12_STANDALONE_DAMAGE_BINDING.md)。 |
| I11 真实来源子图 | Phainon 当前回合所有者 Buff 寿命延长、爻光新增状态实例寿命修改、遐蝶限定 InfectModifier 状态复制；生命周期事实与属性审计通过。 |
| I11 完整内容限制 | 爻光 A6 正式构筑启动尚未验证；遐蝶完整忆灵/死龙与整场未验；Phainon 完整 Ultra 仍有其它未准入任务。 |
| V2 风属性普通击破 | 丹恒＋娜塔莎自然完成首次击破、风化、恢复、二次击破和后续行动，并完成回放；仅普通单韧性，配置与固定命令为 `examples/cli/danheng_wind_break_natural{,.commands}.json`。 |
| 已有共享链与路线 | 普通伤害/治疗/护盾、双方外控、任务图与 RNG、限定两波及归档恢复、普通公共环境 full_stage、普通多层韧性，以及阿兰/娜塔莎/希露瓦、三月七、佩拉、阿格莱雅等已记录的限定路线继续复用。 |

以上均按已验证的来源、构筑和行为范围使用，不代表全角色、全装备或全部整场已通过。
详细历史证据按关键词查[归档快照](simulator_v8_clean_core/docs/archive/CODEX_HANDOFF_PRE_SLIM_2026-10-19.md)，
实际命令和检查入口以 CLI 与测试文档为准。

## 后续待办

启动相应任务时核对当前源码和正式调用者；以下条目不代替具体内容的准入与执行检查。

| 编号 | 剩余范围 |
| --- | --- |
| I1 | 排队救援的 pending 身份、limbo 队列权限、HealHP/SetHP 与跨交易审计未接通；普通致死已闭环。当前救援队列路径以 `limbo_queue_rescue_not_connected` 拒绝，消费时点见下表。 |
| I2 | 欢愉攻击者与属性源分离、其它特殊开关/倍率及完整阶段编排；已有基础链和限定爻光附伤继续复用。 |
| I3 | 特殊关卡模板、评分、副关卡及额外胜负条件；普通公共环境 full_stage 已有证据。 |
| I5 | 其它免疫通知、多个保护竞争、零基础概率及强制控制覆盖顺序；单保护的限定回调已通。 |
| I7 | 共享同步 TriggerBreak、RedStance 虚韧性及其它非普通强制形态；普通多层不重复实现。 |
| I8 | 确实影响战斗顺序的动态/嵌套并行屏障、超出父动作目标范围等；当前固定根并行范围继续复用。 |
| I9 | OnSnapshotCreate 正式事件生产者；出生事件与普通 snapshot 导出不能代替。 |
| I10 | battle_event/servant 双 mute 退场之外的 ForceKill 形态。 |
| I11 余项 | 其它/组合 StatusTypeMask、寿命 Set/减少、其它 InfectModifier 变体及尚未接通的精准实例操作。 |
| V1 | 工作台真实浏览器点击、布局、导入/下载；已有 HTTP/客户端检查不代替浏览器验收。 |
| V3 | 已准入 SummonMonster 形态自然召唤后继续战斗；特殊子卡仍按各自依赖处理。 |

## 规则待定与待归因

| 项目 | 当前处理 |
| --- | --- |
| I1 救援消费时点 | 白露/杰帕德来源确认经插入队列救回，但相对致命单击、整段攻击或完整技能的消费时点未确认；先补可区分依据，再实施该路径。 |
| I6 同类控制抵抗叠加 | 同 STAT_CTRL 多来源仍拒绝；已有资料不能区分其加算/乘算，无新直接证据不重复搜索。 |
| 施加者死亡/移除后的 DOT 属性 | 活体施加者实时属性已通；死亡后的属性保留规则待补，不擅自改成施加时锁面板。 |
| 护盾上限 | 护盾加成是否影响叠盾上限、上限降低后如何处理，仍待适用规则。 |
| 其它来源缺省及条件循环 | 部分百分比治疗公式、行动延迟操作缺省仍待依据；依赖运行状态推进的条件循环需按实际内容归因。 |

未正式编译或执行的角色、构筑、怪物阶段、特殊死亡/分摊/转换等按实际依赖归因，
不因来源齐全就标为“仅待验收”，不以目录覆盖数量估算成品完成率。

## 工作入口

- [CLI 操作与场景](simulator_v8_clean_core/CLI_MVP.md)、
  [测试入口](simulator_v8_clean_core/tests/README.md)。
- [实施与验证约定](simulator_v8_clean_core/docs/AGENT_WORKFLOW_AND_VALIDATION.md)、
  [文档索引](simulator_v8_clean_core/DOCUMENTATION_INDEX.md)。
- 长期目标见[工程完结路线](simulator_v8_clean_core/P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md#0-工程完结路线)；
  旧检查点、规则依据和逐轮记录见[历史快照](simulator_v8_clean_core/docs/archive/CODEX_HANDOFF_PRE_SLIM_2026-10-19.md)。
