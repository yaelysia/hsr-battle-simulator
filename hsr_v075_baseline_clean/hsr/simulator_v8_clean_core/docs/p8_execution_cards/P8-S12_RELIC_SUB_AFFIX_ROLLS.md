# P8-S12 副词条 roll、精度与可实现性执行卡

## 执行配置

- 对应问题：P8-I10。
- 硬前置：P8-S11 已验收并形成遗器轨检查点。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`max`。
- 推荐模式：Goal 模式，目标严格限定为本卡。
- 选择理由：副词条同时涉及精确算术、组合约束、生成历史存在性和 TBGD 未完整表达的 engine convention，是遗器合法性中最容易出现“数值看着对但实例不可能”的阶段。

## 当前事实与阶段结果

S9 应保存副词条分组、基础值、步进值和步进上限；S10 实例输入已有副词条 roll 形状；S11 已确定主词条 property。当前 release 表不一定完整声明初始词条数量和每三级新增/强化的全部规则，因此开始时必须分别审计 TBGD 数值事实与需要版本化的游戏基础规则，不能混为一个来源。

完成后，每条副词条由真实 affix、累计出现/强化次数 `count` 和累计步进 `step` 唯一计算完整精度值；整件遗器满足 group、最多四种 property、同 property 去重、主副排斥、整数范围、稀有度/等级 roll 预算和至少一条合法生成历史。系统不模拟随机掉落，但拒绝不可能存在的成品。任何非法项使整件实例 blocked、零贡献、零套装计数。

## 本阶段只做

- 定义明确的 `count/step` 累计语义和 Decimal 公式，并从 SubAffixGroup 解析真实定义。
- 校验 count 为正整数、step 为整数且位于该定义/累计 roll 可达范围。
- 强制同件最多四种副词条，同 affix 和同 property 都不可重复；主副同 property 不可共存。
- 根据 rarity、强化等级和每三级节点验证副词条数量与总 roll 是否存在至少一个合法生成历史。
- 将 TBGD 数值来源和版本化 engine rule 分开记录；engine rule 包含版本、语义依据和适用范围。
- 提供只读 display projection 验证舍入，但显示值绝不回流 fingerprint 或装配。
- 产生类型化副词条计算结果，暂不进入最终贡献账本。

## 本阶段不做

- 不随机生成词条、不模拟掉落概率、强化材料或权重。
- 不实现遗器评分、角色推荐或自动配装。
- 不接受最终浮点值替代 count/step。
- 不枚举所有可能遗器组合；使用约束求解/闭式存在性判断和 property tests。
- 不应用到最终面板或套装能力。

## Engine rule 决策

执行线程必须先输出来源审计：哪些约束由当前 TBGD 直接表达，哪些没有。对于缺失的初始词条/强化节点规则，只允许新增一个通用、版本化、可审计的 engine convention 模型：

- 不写在 UI、fixture 或具体遗器分支中。
- 不伪装成 `IRSource` 的 TBGD row；来源类型明确为 engine convention。
- 规则版本进入构筑/result fingerprint 和 replay manifest。
- 若规则存在版本争议或无法确定，停止并询问用户，不自行选择攻略说法。

## 设计与失败不变量

1. 规则值由 affix 定义和 count/step 重算；用户提交的 final value 没有可信入口。
2. fixed HP 与 HP ratio 是不同 property，可共存；相同 property 的不同 affix ID 仍视为重复。
3. display 舍入相同的两个内部值仍保持不同 Decimal 值和 fingerprint。
4. 可实现性验证的是“存在合法历史”，不要求恢复唯一掉落顺序，也不能只检查最终 roll 总数。
5. rarity/level 决定可用强化节点；未来数据变化通过规则版本或定义驱动，不散落 if/else。
6. 任何一条非法导致整件遗器 blocked；不能丢掉非法副词条后继续装配。
7. 验证 oracle 独立实现最小枚举/约束检查，不调用生产 feasibility helper。

## 目标与证据映射

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 单词条精确计算 | 各实际 group 的 low/mid/high step 与独立 Decimal oracle 一致 | numeric oracle matrix |
| property 唯一与主副排斥 | 同 affix、同 property、主副同 property、第五条均拒绝 | duplicate matrix |
| roll 历史可实现 | 不同 rarity/level 的合法边界通过，不可能预算失败 | feasibility property tests |
| engine rule 诚实 | TBGD 与 convention 分账，版本进入 fingerprint | source ledger + stale-version negative |
| 显示不污染规则 | round-trip/display 舍入不改变内部值 | precision matrix |
| 整件原子失败 | 任一非法项导致无结果、无贡献、无套装计数 | assembly invariant |
| 确定性 | 输入顺序规范化但重复输入先拒绝，fingerprint 稳定 | permutation/duplicate tests |

## 拟改文件与关键符号

- `equipment/models.py`：正式化 `RelicSubAffixRollInput`、计算结果、engine rule version 引用。
- `builds/relic_affix_calculator.py` 或现有纯计算模块：Decimal 计算和 feasibility 判断。
- `builds/equipment_assembler.py`：整件遗器原子 admission。
- 可新增 `rules/engine_conventions.py`：仅当当前项目没有合适通用位置，保存版本化基础规则，不引用具体遗器 ID。
- `tools/validate_p8_s12_relic_sub_affix_rolls.py` 和阶段报告。
- S10/S11 fixtures 与 codecs 原子迁移。

任何 engine convention 新增前必须搜索工作区是否已有同一规则，避免双来源。若会改变公开构筑 schema，不做旧接口兼容，迁移当前调用者。

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
rarity_level_roll_budget_enforced=true
legal_generation_history_exists=true
impossible_history_rejected=true
engine_rule_versioned_and_separate_from_tbgd=true
display_rounding_does_not_change_internal_value=true
user_final_float_rejected=true
invalid_sub_affix_blocks_whole_relic=true
```

## Gap 与停止条件

- raw 数值字段存在但 S9 未投影：`lowering_gap`，回修定义。
- 静态表没有完整生成历史规则：不是任意值许可；建立版本化 convention 前先给出来源审计并确认语义。
- 外部资料冲突或规则版本不确定：必须停止询问用户，不能自行选一个实现。
- property test 发现生产算法接受 oracle 判定不可能的实例：`implementation_missing`，不得缩窄测试分布掩盖。

## 验证门与资源预算

副词条计算与整件 admission 必须直接拒绝重复 property、主副冲突、非法 count/step、
超预算和不存在合法生成历史的输入；验证器不得先丢弃非法项再检查剩余结果。

必跑且只有一个业务主入口：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s12_pycache python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v -o /tmp/hsr_v8_p8_s12_time_v.txt timeout --signal=TERM 5m ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p8_s12_relic_sub_affix_rolls --tbgd-root ../../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s12_relic_sub_affix_rolls
git diff --check
```

副词条表只读取一次。独立 oracle 使用固定 seed、边界等价类和受限 property case；
默认不得枚举全组合或保存全部生成样本。S10/S11 检查点默认继承；只有修改共用实例、
主词条排斥或 engine convention 接口时，追加对应小型 direct，不重跑前序主验证。

单次主验证不超过 5 分钟、768 MiB RSS；本阶段累计验证不超过 10 分钟，默认总产物
不超过 3 MiB。summary 必须记录 seed、case 数和最小失败样本。禁止 RuleBook、
套装、runtime、阶段聚合和重复 TBGD 扫描。

## Ready-for-review 产物

- TBGD 数值字段与 engine convention 来源分账。
- low/mid/high Decimal oracle、property 去重和主副排斥矩阵。
- rarity/level 可实现性 property tests、固定 seed 和最小失败样本。
- precision/display/fingerprint、整件原子失败证据。
- 所有 schema 调用者迁移与资源统计。

## 唯一执行清单（仅验收线程可勾）

- [ ] 每条副词条由真实 affix + count + step 精确重算，不接受最终值。
- [ ] 最多四项、同 property 去重、主副排斥和整数边界完整实施。
- [ ] rarity/level roll 预算与合法生成历史经独立 property oracle 证明。
- [ ] engine convention 与 TBGD 分账、版本化并进入 fingerprint/replay 边界。
- [ ] 显示舍入不回流，非法一项使整件零贡献、零套装计数。
- [ ] S10/S11 回归、代码通用性和资源预算通过。
- [ ] `ready_for_review` evidence 完整，阶段无副词条 blocker。
