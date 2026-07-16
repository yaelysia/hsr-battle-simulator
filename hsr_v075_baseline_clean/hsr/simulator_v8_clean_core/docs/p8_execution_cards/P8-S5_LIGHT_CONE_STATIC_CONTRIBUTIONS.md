# P8-S5 光锥静态属性贡献执行卡

## 执行配置

- 对应问题：P8-I06、P8-I07 静态部分。
- 硬前置：P8-S4 已验收并有独立 commit；不得在 S4 未提交工作区实施。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`xhigh`。
- 推荐模式：普通聚焦模式，光锥轨独立 worktree。
- 选择理由：改动集中于共享贡献账本和装备装配器，范围有限但双计、命途失配和来源归属需要严谨代码审查；不适合低推理批量生成。

## 当前事实与阶段结果

S3 已保存每个叠影档位的有序静态属性及真实来源；S4 负责光锥实例成长、基础生命/攻击/防御和命途激活决策。S4 当前装配结果会记录被选叠影的静态属性索引，但本阶段开始前必须确认这些属性尚未进入正式静态贡献账本，也没有被 character assembler 或 scenario 重复消费。

本阶段完成后：光锥基础三维始终按合法实例贡献；叠影行的静态被动属性只在命途激活为 active 时进入统一账本。两类贡献拥有不同贡献身份、计算通道、来源和激活证据。无静态属性是合法空集合；有静态属性却无法类型化或绑定数值时，正式装配必须 blocked，不能静默漏项。

本阶段不执行条件、modifier、callback 或动态 ability；这些仍属于 S6-S8。

## 本阶段只做

- 将被选叠影行的每个静态属性项目转换为一个 `StaticStatContribution`，保持原项目顺序和独立来源。
- 复用 S2 的基础、百分比、固定值、资源四类贡献通道；不得创建光锥专用面板算法。
- 以 S4 的激活决策控制被动静态属性；命途失配时基础三维保留，被动静态项为零。
- 在 `EquipmentAssemblyResult` 和 source ledger 中保留实例、光锥定义、叠影等级、属性项目和激活决策的关联。
- 对 S3 目录按结构选出三类真实来源：无静态属性、只有静态属性、静态属性与动态能力并存。
- 原子迁移受影响的 S1/S2/S4 fixture 和 JSON codec，不保留旧静态属性副本。

## 本阶段不做

- 不 lower 或执行光锥能力图。
- 不把条件属性按常驻属性提前装配。
- 不实现遗器、套装或最终跨来源面板顺序。
- 不为 UI 保存第二份“已经求和”的可信规则结果。
- 不以固定光锥 ID、名称或描述文本选择主验证样例。

## 设计与失败不变量

1. 每个 raw 静态属性项目最多产生一个 ledger term；相同属性类型的多个项目不得覆盖或预聚合。
2. 基础生命/攻击/防御来自成长档位；被动生命/攻击/防御百分比等来自叠影属性，来源和通道不可互换。
3. 命途失配只令被动 activation inactive，不得删除基础贡献，也不得生成动态 blocker。
4. 属性类型未知、数值不是规范十进制、来源与所选叠影不一致或项目重复消费时，装配 blocked 且不返回可进入战斗的贡献集合。
5. `StaticProperty` 与后续 ability 中表达的动态效果不得因为数值相同被合并；本阶段只消费明确静态列表。
6. 输入、结果和嵌套 ledger 递归不可变，fingerprint 必须覆盖新增贡献及激活证据。

## 目标与证据映射

| 目标 | 必须成立 | 证据 |
|---|---|---|
| 三类来源均被识别 | 三个结构集合非空，且按字段/能力关系选样 | `source_class_matrix.json` |
| 同命途静态被动生效 | 当前叠影每一项恰好一个贡献，数值由 S3 Decimal 字符串重算 | `static_contribution_matrix.json` |
| 异命途只禁被动 | 基础三维不变，被动贡献和动态机制均为空 | path mismatch case |
| 无静态属性合法 | assembly 可成功且不是 gap | empty-static case |
| 双计被拒绝 | 重复 term、错误项目身份或旧路径再次消费均 blocked | negative matrix |
| 来源闭合 | term -> 实例 -> 叠影属性项 -> raw row/JSON path | source walkback sample |
| 动态能力未提前执行 | transition、status、callback 数量均未改变 | runtime unchanged probe |

## 拟改文件与关键符号

- `builds/equipment_assembler.py`：扩展 `assemble_equipment_build` 的静态被动装配，保持基础贡献与被动贡献分离。
- `build_types.py`、`equipment/models.py`：只在现有通用贡献或装配结果确实缺字段时做最小类型扩展。
- `builds/character_assembler.py`：仅消费规范装备静态贡献，不重新解释光锥属性。
- `equipment/__init__.py`、`builds/__init__.py`：原子导出迁移。
- `tools/validate_p8_s5_light_cone_static_contributions.py`：新增主验证。
- 受影响的 S1、S2、S4 fixture：迁移构造参数和 fingerprint oracle。
- `live_validation_reports/v8_p8_s5_light_cone_static_contributions_ready_for_review.md`：新增报告。

开始修改前必须用 CodeGraph 检查上述符号调用者；若 S4 验收后文件结构变化，按职责而非文件名迁移，并在报告说明。

## 结构化验收谓词

```text
real_source_classes_non_empty=true
base_and_passive_channels_separate=true
path_match_static_properties_applied_once=true
path_mismatch_base_stats_retained=true
path_mismatch_passive_stats_absent=true
empty_static_property_set_is_valid=true
unknown_static_property_blocks_assembly=true
duplicate_static_source_rejected=true
all_static_terms_source_backed=true
dynamic_ability_executed=false
input_order_deterministic=true
runtime_behavior_changed=false
```

任一谓词缺失、空 checks 被视为通过、或只由报告手写结论支撑，均不得验收。

## Gap 与停止条件

- S3 真实静态属性存在但未进入贡献账本：`implementation_missing`，本阶段必须修复。
- raw 有属性但 S3 未投影：`lowering_gap`，必须回修通用 S3 lowering；不能称 source gap。
- IR 完整但验证没选到：`validation_gap`，先修结构谓词。
- 当前类别真实为空只允许对“某种样例类别”报告数据事实；不得伪造 fixture 冒充真实来源。
- 发现某静态项目实际依赖条件或事件时，不能常驻装配；将其归入 S6-S8 并保留 battle admission blocker。若无法可靠分类，停止并交回规划线程。

## 验证命令与资源

工作目录统一为 `hsr_v075_baseline_clean`。先运行主验证，再按调用链运行回归，全部串行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p8_s5_light_cone_static_contributions --tbgd-root ../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s5_light_cone_static_contributions
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p8_s4_light_cone_instance_assembly --tbgd-root ../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s5_s4_regression
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p8_s2_character_build_base_panel --fixture-only --output-dir /tmp/hsr_v8_p8_s5_s2_fixture_regression
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s5_pycache python3 -m compileall -q hsr/simulator_v8_clean_core
git diff --check
```

只有修改到 P5 value binding 时才追加 `validate_p5_s1_value_binding_contract`。不得运行完整 ability transition、P1-P7 聚合或 `validate_v0_209`。主验证最多构建一次 focused RuleBook，只输出 summary、三类矩阵、负例和少量来源样本。

## Ready-for-review 产物

- 实现 diff 与调用者迁移清单。
- 当前 source fingerprint、三类真实来源数量和样例选择谓词。
- 结构化 summary、source matrix、negative matrix、source walkback。
- 所有命令的退出状态、产物大小和 RuleBook 构建次数。
- 未运行验证及理由、剩余 blocker；不得写 `done`。

## 唯一执行清单（仅验收线程可勾）

- [ ] 三类真实来源已按结构识别，无固定 ID 主选择器。
- [ ] 基础三维与被动静态贡献已分离，命途匹配/失配行为正确。
- [ ] 每项贡献只消费一次并可反查真实来源。
- [ ] 缺失、未知、重复和伪来源负例均 fail-closed。
- [ ] 动态能力未提前执行，S2/S4 直接回归通过。
- [ ] 代码结构、不可变性、fingerprint 和资源预算经人工复核通过。
- [ ] `ready_for_review` evidence 完整，阶段无未关闭 blocker。
