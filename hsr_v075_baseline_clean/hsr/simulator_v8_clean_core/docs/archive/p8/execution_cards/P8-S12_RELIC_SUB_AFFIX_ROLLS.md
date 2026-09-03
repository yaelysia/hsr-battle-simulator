# P8-S12 副词条最终值、精度与约束执行卡

## 执行配置

- 对应问题：P8-I10。
- 硬前置：P8-S11 已验收并形成遗器轨检查点。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`max`。
- 推荐模式：Goal 模式，目标严格限定为本卡。
- 选择理由：副词条同时涉及精确算术、分组关联、属性去重和主副排斥，是遗器最终战斗输入中最容易出现“数值能算但引用关系错误”的阶段。

## 当前事实与阶段结果

S9 应保存副词条分组、基础值、步进值和单次 roll 的步进上限；S10 实例输入已有副词条 roll 形状；S11 已确定主词条 property。本项目接收已经完成的自定义遗器作为战斗构筑输入，不模拟遗器掉落、初始词条生成或强化过程。

完成后，每条副词条由真实 affix、累计次数 `count` 和累计步进 `step` 唯一计算完整精度值；整件遗器满足正确分组、最多四种 property、同 property 去重、主副排斥和单项整数范围。系统不检查初始词条数量、每三级新增或强化、整件总 roll 预算及生成历史。任何非法项使整件实例 blocked、零贡献、零套装计数。

S12 只完成遗器词条 admission，不代表完整遗器效果已经装配。合法遗器可以形成
`assembly_status=assembled` 的只读 selection，但在 S13 套装统计和 S14 静态贡献完成前，
`battle_admission_status` 必须继续为 `blocked`，并为每件 selection 保留一条类型化后续
blocker。空遗器构筑不受该 blocker 影响。

## 本阶段只做

- 定义明确的 `count/step` 累计语义和 Decimal 公式，并从 SubAffixGroup 解析真实定义。
- 校验 count 为正整数、step 为整数，且单条副词条满足 `0 <= step <= count * StepNum`。
- 强制同件最多四种副词条，同 affix 和同 property 都不可重复；主副同 property 不可共存。
- 强制副词条引用模板声明的真实分组；不同稀有度只通过模板的分组引用选择对应定义，不解析固定 ID。
- 内核只保存完整精度值；验证 UI 侧的只读显示投影不会改变模型、fingerprint 或装配结果。
- 产生类型化副词条计算结果，暂不进入最终贡献账本。
- 将旧的“副词条未验证” blocker 原子迁移为 S13/S14 后续装配 blocker；不得提前准入战斗。

## 本阶段不做

- 不随机生成词条、不模拟掉落概率、强化材料或权重。
- 不验证初始副词条数量、每三级新增/强化节点、整件总 roll 数或任何养成历史。
- 不实现遗器评分、角色推荐或自动配装。
- 不接受最终浮点值替代 count/step。
- 不应用到最终面板或套装能力。

## 战斗输入边界

遗器实例是供战斗模拟使用的已完成构筑，不是背包或养成系统记录。只要每条副词条来自模板允许的真实定义、单条 `count/step` 可计算且整件属性组合不冲突，就允许装配。四条均处于各自上界也不因缺少可还原的强化历史而拒绝；这属于用户自定义战斗输入，不是掉落合法性声明。

## 设计与失败不变量

1. 规则值由 affix 定义和 count/step 重算；用户提交的 final value 没有可信入口。
2. fixed HP 与 HP ratio 是不同 property，可共存；相同 property 的不同 affix ID 仍视为重复。
3. 即使 UI 将两个值显示成相同文本，内核仍保持不同 Decimal 值和 fingerprint；内核不定义舍入策略。
4. 单条累计步进上界只由该 affix 的 `StepNum` 和 count 决定，不从遗器等级推导整件 roll 预算。
5. 任何一条非法导致整件遗器 blocked；不能丢掉非法副词条后继续装配。
6. 验证 oracle 独立重读 raw 并计算数值与单条边界，不调用生产计算 helper。
7. 合法 selection 与后续装配 blocker 一一对应；未产生遗器贡献时不得标记 battle admitted。

## 目标与证据映射

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 单词条精确计算 | 各实际 group 的 low/mid/high step 与独立 Decimal oracle 一致 | numeric oracle matrix |
| property 唯一与主副排斥 | 同 affix、同 property、主副同 property、第五条均拒绝 | duplicate matrix |
| 单项 roll 边界 | count 为正且累计 step 不超过 `count * StepNum` | per-affix boundary matrix |
| 分组关联正确 | 副词条必须来自模板声明的真实副词条组 | group admission matrix |
| 显示不污染规则 | 外部显示投影不改变内部值，内核不携带舍入规则 | precision matrix |
| 整件原子失败 | 任一非法项导致无结果、无贡献、无套装计数 | assembly invariant |
| 后续阶段隔离 | 合法 selection 已装配但战斗仍被 S13/S14 blocker 阻断 | battle admission matrix |
| 确定性 | 输入顺序规范化但重复输入先拒绝，fingerprint 稳定 | permutation/duplicate tests |

## 拟改文件与关键符号

- `equipment/models.py`：正式化 `RelicSubAffixRollInput`、计算结果和来源依据。
- `builds/relic_affix_calculator.py` 或现有纯计算模块：Decimal 计算以及单条 count/step 边界判断。
- `builds/equipment_assembler.py`：整件遗器原子 admission。
- `tools/validate_p8_s12_relic_sub_affix_rolls.py` 和阶段报告。
- S10/S11 fixtures 与 codecs 原子迁移。

禁止为本阶段新增掉落、强化节点、养成历史或 engine convention 模型。若会改变公开构筑 schema，不做旧接口兼容，迁移当前调用者。

## 结构化验收谓词

```text
sub_affix_values_derived_from_affix_count_step=true
count_and_step_integer_bounds_enforced=true
low_mid_high_steps_match_independent_oracle=true
maximum_four_unique_properties_enforced=true
same_affix_rejected=true
same_property_rejected=true
main_sub_same_property_rejected=true
distinct_flat_and_ratio_properties_can_coexist=true
sub_affix_group_membership_enforced=true
per_affix_cumulative_step_bound_enforced=true
aggregate_upgrade_history_not_modeled=true
external_display_projection_does_not_change_internal_value=true
user_final_float_rejected=true
invalid_sub_affix_blocks_whole_relic=true
validated_relics_remain_battle_blocked_until_static_assembly=true
future_blocker_matches_each_relic_selection=true
```

## Gap 与停止条件

- raw 数值字段存在但 S9 未投影：`lowering_gap`，回修定义。
- 静态表没有初始词条或强化历史规则：属于明确排除的养成范围，不是 gap，也不得新增 convention。
- property test 发现生产算法接受超出单项 count/step 边界的实例：`implementation_missing`，不得缩窄测试分布掩盖。

## 验证门与资源预算

副词条计算与整件 admission 必须直接拒绝错误分组、重复 property、主副冲突和非法
count/step；验证器不得先丢弃非法项再检查剩余结果。

必跑且只有一个业务主入口：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s12_pycache python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v -o /tmp/hsr_v8_p8_s12_time_v.txt timeout --signal=TERM 5m ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p8_s12_relic_sub_affix_rolls --tbgd-root ../../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s12_relic_sub_affix_rolls
git diff --check
```

副词条表只读取一次。独立 oracle 使用边界等价类和受限 property case；默认不得枚举
全组合或保存全部样本。S10/S11 检查点默认继承；只有修改共用实例模型或
主词条排斥接口时，追加对应小型 direct，不重跑前序主验证。

本阶段允许复用一次现有、实测受控的 relic domain catalog 构建，再在 RuleBook
构建前选择词条所需定义；不得仅为验证另建一套只有 `tools/` 消费者的 production
lowering。报告必须诚实记录完整领域目录的构建规模。若该领域构建超过 2 秒或
128 MiB，则暂停并重新设计真正的生产共享窄投影，不能先完整 CanonicalIR 再过滤。

单次主验证不超过 5 分钟、768 MiB RSS；本阶段累计验证不超过 10 分钟，默认总产物
不超过 3 MiB。summary 必须记录 case 数和最小失败样本。禁止完整 RuleBook、
套装效果执行、runtime、阶段聚合和重复 TBGD 扫描。

## Ready-for-review 产物

- low/mid/high Decimal oracle、property 去重和主副排斥矩阵。
- 分组准入、单项 count/step 边界和整件原子失败矩阵。
- exact-value/fingerprint、外部显示投影隔离和整件原子失败证据。
- 所有 schema 调用者迁移与资源统计。

## 唯一执行清单（仅验收线程可勾）

- [x] 每条副词条由真实 affix + count + step 精确重算，不接受最终值。
- [x] 最多四项、同 property 去重、主副排斥和整数边界完整实施。
- [x] 模板副词条分组与单项 count/step 边界经独立 raw oracle 证明。
- [x] 未引入初始词条、强化节点、总 roll 预算或养成历史规则。
- [x] 内核不定义显示舍入且外部投影不回流；非法一项使整件零贡献、零套装计数。
- [x] 合法遗器仅形成只读 selection，并由一对一后续 blocker 阻止零效果进入战斗。
- [x] S10/S11 回归、代码通用性和资源预算通过。
- [x] `ready_for_review` evidence 完整，阶段无副词条 blocker。
