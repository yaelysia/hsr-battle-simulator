# P9-S19 代表角色正式战斗纵切执行卡

## 执行配置

- 对应问题：P9-I19；机制包 M18 纵切。
- 硬前置：P9-S18 已验收并形成检查点；代表 manifest 与当前源码和来源指纹一致。
- 推荐：5.6 Sol / `max` / Goal 模式。
- 理由：本阶段跨正式构筑、场景、动作查询、结算、事件、审计和 replay，必须识别组合语义
  中的真实生产缺口，不能用测试夹具绕过。

## 当前事实与阶段结果

S18 已通过当前 79 条角色的全目录静态审计，并根据未证明的机制组合动态生成代表 manifest。
目录为零 gap 只能证明所有单项有合法链路，不能证明它们在同一正式战斗中按正确顺序组合，
也不能证明构筑选择、动作窗口、状态回调、RNG、生命周期和 replay 没有跨系统偏差。

完成后，manifest 中所有 proof obligation 都由至少一条正式 battle slice 覆盖。每条纵切从
合法角色构筑和场景加载开始，经内核动作查询与提交进入原生 mutation、settlement、事件、
来源审计、快照和 replay；真实 source gap 则通过正式准入拒绝和 state unchanged 证明。
本阶段不追求“每名角色跑一场”，也不允许少量角色样例替代 S18 的 79 条目录审计。

## 详细目标

1. 只消费 S18 已验收 manifest；开工时校验来源指纹、目录指纹、义务集合和构筑身份。陈旧或
   人工修改的 manifest 必须阻断，不能在验证器里重新挑角色。
2. 每个 executable 代表使用正式 `CharacterBuildInput`、正式装配结果、正式 scenario loader
   和 `ScenarioStateBuilder`。不得手填最终面板、行动值、已计算贡献或机制结果。
3. 行迹、星魂和技能等级必须来自 manifest 指定的真实构筑选择；默认节点和显式选择只由
   装配器解析一次，runtime 不重复发现机制。
4. 通过正式 action query 获取可用动作和目标，再提交内核公布的选择。执行线程可以像外部
   推演器一样选择，但不能计算合法动作、目标范围、资源成本或效果。
5. 场景前置必须通过已有正式 setup、状态、关系、资源、queue 或 wave 入口建立。只允许
   manifest 声明的链前 fixture 类型；禁止直接替换 committed state、手工插 mutation/event
   或拼装动作计划。
6. 对每条纵切保留连续链：生产前快照、动作选择、原生 mutation、候选状态、原子提交、
   settlement、派发事件、RNG ledger、来源审计和 replay 结果。
7. 多段攻击、callback、额外行动、形态切换、独立行动实体、死亡/复活等跨窗口机制必须
   在真实 producer 时序中触发，不能把一个状态生成的裸事件放到另一个状态中执行。
8. 随机目标、随机分支和概率条件只消费统一 RNG ledger。纵切使用记录的合法选择以便 replay，
   不固定观测答案，不让表现随机进入 gameplay RNG。
9. 每项 proof obligation 必须回指覆盖它的纵切和具体来源节点；若一条纵切覆盖多个义务，
   仍需逐义务证明输入、触发窗口和结果。
10. source gap 代表只验证正式构筑或动作准入 blocked、state/mutation/event/RNG 全部不变；
    不伪造缺失来源来获得 executable 正例。

## 纵切边界

- 纵切证明“共享机制组合能通过正式产品入口工作”，不是固定伤害答案测试。
- 数值验收以来源公式、贡献和结算账本重算为准，不以内置预期最终数字驱动生产逻辑。
- 角色装备可以为空或使用已验收的合法构筑；只有 proof obligation 需要装备交互时才加入，
  避免把 P8 目录重新纳入本阶段验证成本。
- 敌我双方动作都由测试驱动像玩家一样选择；不实现敌方 AI。
- 代表数量不写死。若预计无法在本阶段预算内完成，必须在修改前把互斥义务拆成新的顺序
  执行卡，由规划线程更新总计划；不得减少义务或只保留简单案例。

## 本阶段不做

- 不修 S0-S17 的生产机制缺口；发现后退回唯一责任阶段形成新检查点。
- 不新增角色、技能或固定 ID handler；manifest 中的 ID 仅用于最终示例定位。
- 不为验证新增只有 `tools/` 消费的 core API。
- 不运行 79 名角色逐个完整战斗，不重跑全部角色装备或旧阶段聚合。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| manifest 当前 | 指纹和全部 proof obligation 与 S18 一致 | manifest admission |
| 正式构筑 | 每条 executable slice 由 assembled/admitted 构筑出生 | build ledger |
| 玩家式操作 | 动作和目标均来自内核 query，提交选择不复制规则 | query-submit trace |
| 连续执行链 | 无中途直接状态注入或手工事件 | transition continuity matrix |
| 机制覆盖 | 每项义务至少有一条正式或 blocked 纵切 | obligation coverage |
| 原子与来源 | mutation、settlement、事件和来源身份一致 | audit matrix |
| 确定重放 | RNG ledger 完整且 replay 与原结果相同 | replay samples |
| source gap 诚实 | 缺源入口 blocked 且所有正式通道为空 | blocked slices |

## 结构化通过谓词

```text
accepted_s18_manifest_current=true
all_executable_slices_use_formal_character_build=true
manual_final_panel_injection_count=0
all_actions_selected_from_core_query=true
all_targets_selected_from_core_query=true
manual_mutation_or_event_injection_count=0
transition_chain_continuous=true
representative_obligation_coverage_complete=true
all_expected_mutations_settled=true
all_events_use_formal_producers=true
all_gameplay_rng_ledgered=true
sampled_replay_equal=true
source_gap_slices_blocked_unchanged=true
character_specific_validation_api_count=0
```

## 关键负例与停止条件

- 陈旧 manifest、缺义务、重复义务身份或构筑身份错绑必须在场景构建前拒绝。
- 正式模式出现手填 panel、行动值、旧行迹 flags、直接 UnitState 或未准入机制引用必须拒绝。
- query 后更换未公布动作/目标、资源不足仍提交、错误 owner 操作独立实体必须拒绝。
- 同事件身份冲突、来源篡改、replay mutation/event/RNG 改动必须 fail-closed。
- source gap 样例若产生部分面板、机制引用、mutation 或事件，必须阻断。
- 发现任一 S0-S17 内部 gap 时停止并报告责任阶段；不能在 S19 边跑边补共享机制。
- 预计 manifest 在 25 分钟累计预算内无法覆盖时，在修改前返回 `plan_split_required`。

## 拟改范围

- 新增 `tools/validate_p9_s19_representative_formal_battle_slices.py`。
- 按需新增小型、数据驱动的正式 scenario fixture；不得复制规则或最终结果。
- 新增 S19 `ready_for_review` 报告。
- 默认不修改 compiler、IR、RuleBook、assembler、runtime；若暴露生产 gap，退回责任阶段。

## 验证与资源

- 只装配 manifest 选中的角色和直接依赖，不构建 79 角色完整 battle state。
- 共享目录或 RuleBook 最多构建一次并在同一进程复用；每条纵切只保存小型审计摘要。
- 修复验证器期间只运行失败 slice；权威主入口最多一次诊断和一次最终。
- direct 最多两项，且只在 S19 为正式入口修复验证边界时运行；不得把旧 P1-P8 套餐附加进来。
- 预算：主入口 12 分钟、累计 25 分钟、1.25 GiB、12 MiB、1,000 非空验证行。
- `compileall`、唯一 S19 主验证、必要 direct、`git diff --check`。

## 唯一执行清单

- [ ] S18 manifest 当前、完整且未经人工缩减。
- [ ] 所有 executable 代表从正式构筑和正式场景入口出生。
- [ ] 动作、目标、资源和 RNG 均通过内核查询/提交契约。
- [ ] 每个 proof obligation 获得连续正式纵切证据。
- [ ] source gap 入口通过正式 blocked 与 state unchanged 证明。
- [ ] settlement、来源审计和 replay 全部闭合。
- [ ] 主验证、必要 direct 和资源审计通过并提交 `ready_for_review`。
