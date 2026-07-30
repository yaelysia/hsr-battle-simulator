# P8-S11 主词条合法池与精确数值执行卡

## 执行配置

- 对应问题：P8-I09。
- 硬前置：P8-S10 已验收并形成遗器轨检查点。
- 推荐模型：5.6 Terra；若 Decimal/属性通道模型需要共享重构，升级 5.6 Sol。
- 推荐推理等级：`xhigh`。
- 推荐模式：Goal 模式，目标严格限定为本卡。
- 选择理由：需要覆盖全定义和大量合法/非法组合，但核心是纯数据关联与精确计算，适合长时间 property/oracle 验证。

## 当前事实与阶段结果

S9 应保存模板的 `MainAffixGroup`、六部位全局允许属性和主词条定义；S10 实例引用一个主词条 key，但尚未证明该 key 对模板/部位合法，也未计算强化等级数值。

完成后，每个 admitted 遗器实例的主词条必须同时满足三层关系：模板自身主词条分组包含该定义、模板真实部位允许该属性、定义的稀有度/分组与模板一致。数值由该定义的基础值与每级成长按实例强化等级用 Decimal 计算，保留完整精度和逐字段来源。调用者不得提交最终数值；非法或来源不完整时装配 blocked、零贡献。

## 本阶段只做

- 建立 template -> main group -> affix definition 与 slot -> allowed property 的交叉 admission。
- 计算 `base_value + level_add * level` 或 raw 明确公式；公式必须由独立 raw oracle 逐字段核对，不从显示答案反推。
- 只处理 S10 已准入的 BASIC 模板。CUSTOM 继续仅保留在定义目录，UNKNOWN 继续
  fail-closed；S11 不为二者建立主词条执行支线。
- 为六个部位动态生成合法/跨槽非法矩阵；固定头/手和可选躯干/脚/球/绳都覆盖。
- 保留 template、slot、group、affix ID、property、level、精确值和 raw JSON path。
- 将验证通过的主词条计算结果放入装配中间结果，但暂不进入最终静态贡献账本。

## 本阶段不做

- 不实现主词条掉落概率或随机生成。
- 不处理副词条、套装统计或最终面板。
- 不接受 UI 四舍五入值、文本百分比或用户提交最终值。
- 不把计划中的文字池复制成 runtime if/else；该表只作独立语义对照。

## 数值与合法性不变量

1. 合法性是模板分组和部位池的交集，任一缺失均 blocked。
2. 头/手固定属性来自 source discovery，不写死为特殊分支；未来数据变化会体现在矩阵中。
3. 数值解析从 JSON token 直接进入 Decimal；内部规范字符串不丢尾数，display projection 与规则值分离。
4. +0、中间等级、最大等级均与独立 raw oracle 一致；越界等级在 S10/S11 双边防御。
5. 相同 property 的不同 affix/group 定义不能静默覆盖；RuleBook 歧义必须 blocked。
6. 结果 fingerprint 覆盖计算依据和精确值；外部修改 raw snapshot 或输入容器不改变已建模型。
7. blocked 主词条不得产生中间值、静态贡献或套装 admission 副作用。

## 目标与证据映射

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 六槽合法池真实 | 从三层关系动态交叉，六槽集合非空 | slot/property matrix |
| 模板约束生效 | 全局槽位合法但不属于 BASIC 模板 group 的组合被拒绝 | group negatives |
| 精确等级数值 | +0/中间/最大与独立 Decimal raw oracle 相同 | numeric oracle matrix |
| 跨槽拒绝 | 头非固定生命、手非固定攻击及各可选槽错误组合均失败 | cross-slot matrix |
| 来源完整 | 结果可回到模板、部位记录、group 和 affix 数值字段 | source walkback |
| 调用者不能伪造 | 提交 final value、float、显示值或错 fingerprint 被拒绝 | input negative matrix |
| 失败无贡献 | blocked 结果没有 value/contribution/set count | assembly invariant |

## 拟改文件与关键符号

- `equipment/models.py`：类型化主词条计算结果/依据；避免重复 S9 定义。
- `builds/equipment_assembler.py` 或独立纯函数模块 `builds/relic_affix_calculator.py`：主词条 admission 和 Decimal 计算。
- `rules/rulebook.py`：只补按 group/identity 的窄查询，不提供模糊首项 fallback。
- `tools/validate_p8_s11_relic_main_affix.py` 和阶段报告。
- 使用 S11 自己的最小 BASIC 构筑样本；不扩写或复制 S10 验证器，不修改
  runtime/ScenarioStateBuilder。只有共享生产 schema 确实变化时才运行对应小型 direct。

是否新建 calculator 由当前代码复杂度决定；同一公式不得在验证、assembler 和 UI 复制。验证 oracle 必须独立重读 raw，不调用生产计算函数。

## 结构化验收谓词

```text
six_real_slot_pools_non_empty=true
main_affix_requires_slot_and_template_group=true
fixed_head_hand_are_source_derived=true
cross_slot_main_affixes_rejected=true
template_group_restriction_enforced=true
level_zero_mid_max_match_independent_oracle=true
numeric_values_never_pass_through_float=true
display_projection_not_rule_input=true
user_final_value_rejected=true
ambiguous_affix_definition_blocked=true
all_results_source_backed=true
blocked_main_affix_contributes_nothing=true
```

## Gap 与停止条件

- raw 有合法关系但 S9 没投影：`lowering_gap`，回修 S9 类型化定义。
- S9 定义完整但装配未校验/计算：`implementation_missing`，本阶段修。
- CUSTOM 或 UNKNOWN 出现在正式主词条装配路径：属于 S10 admission 回退，必须阻断，
  不得借 BASIC 池放行。
- 独立 oracle 与生产值不一致时停止，先定位 Decimal 读取、公式或等级语义，不能改期望值迎合实现。

## 验证门与资源预算

主词条计算器和装配器必须在创建计算结果前完成模板分组、部位池、稀有度、等级和
数值有限性校验；非法输入不得留下中间值。

必跑且只有一个业务主入口：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s11_pycache python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v -o /tmp/hsr_v8_p8_s11_time_v.txt timeout --signal=TERM 5m ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p8_s11_relic_main_affix --tbgd-root ../../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s11_relic_main_affix
git diff --check
```

主入口只加载模板、部位和主词条表一次；全定义合法性和 Decimal 边界 oracle 在同一
进程完成。S10 检查点默认继承，不重跑 S10 完整验证。只有修改实例 admission 或共用
Decimal/属性类型时，追加一个对应的小型 direct。

单次主验证不超过 5 分钟、768 MiB RSS；本阶段累计验证不超过 10 分钟，默认总产物
不超过 3 MiB。业务验证只允许一个公开 CLI mode，不增设重复的 slice/direct/probe
完成门；新增验证代码不超过 900 行非空 Python，预计超限时暂停并修订证据设计，不得
通过拆文件规避。禁止完整 RuleBook、副词条、套装、战斗、跨阶段聚合和重复 raw 解析。

## Ready-for-review 产物

- 六槽合法池、模板 group 交叉、跨槽和特殊模式矩阵。
- +0/中间/最大独立 Decimal oracle 与来源反查。
- 伪 final value、float、歧义、缺字段和 blocked 无贡献负例。
- 代码/fixture 迁移、资源统计和未运行范围。

## 唯一执行清单（仅验收线程可勾）

- [x] 六部位主词条合法池由真实三层关系动态生成。
- [x] 模板 group 与部位池均强制校验，跨槽和特殊模板错误 fail-closed。
- [x] +0、中间和最大强化值与独立 Decimal oracle 一致。
- [x] UI/用户最终值、float、显示舍入和模糊定义不能进入规则。
- [x] 每个结果来源完整，blocked 不产生值或贡献。
- [x] S10 已验收契约未被实际改动，或已通过对应最小 direct；代码通用性和资源预算通过。
- [x] `ready_for_review` evidence 完整，阶段无主词条 blocker。
