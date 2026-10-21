# PR #8 已确认战斗事实：本地实施记录

> 历史归档（2026-10-21 整理）：下文状态、任务顺序和验收要求仅反映记录当时。
> 当前工作以[交接](../../../CODEX_HANDOFF.md)和[执行约定](../../../simulator_v8_clean_core/docs/AGENT_WORKFLOW_AND_VALIDATION.md)为准；归档不代表本轮重新验收。

基线：业务 HEAD `2d60a4305206bc11b67edf445a55478d90c96257`；研究 PR #8
`a987d2607f135799a9427c9341ebdf002a1b2c90`；TBGD
`14c1d18f91a8101d610e6c523447a7517de3fae1`。本轮不改 submodule 指针、不执行 MCP
协调流程、不提交/推送，不实现养成或 UI。工作区原有文档与其他未提交改动保留。

## 规则来源授权

用户明确确认 PR #8 事实可以直接使用，即使对应公式/数值未出现在 TBGD。
公开研究、解释模型和 raw 输入分别保留真实来源；不再把缺少 native evaluator 当成阻断。
PR #8 自身标明未知的时序、采样、组合和覆盖边界仍不凭空补齐。

## 实施结果

| 已确认事实 | 正式代码变化 |
|---|---|
| 治疗与护盾的比例项加固定项后再应用增益 | lowering 保留两个操作数；EffectRegistry 统一求值，坏值/缺动态绑定拒绝；护盾不再漏 ShieldValue |
| 固定治疗不需要伪造 raw 默认枚举 | 仅 ModifyValue 的缺省公式输入编译为有来源标注的固定治疗合同；未声明公式的百分比输入不猜为目标 MaxHP；内部 Heal 合同保留 |
| 提供治疗量、实际回复、溢出不同 | mutation 的 formula_details 原生记录 base/offered/realized/overheal |
| 明确可累加护盾有容量上限 | StackValue/MaxStack 编译到 amount/max_capacity；同源同施加者累加后截顶；满上限及零 cap 合法 no-op；拒绝未知的低于当前剩余量的新 cap |
| 固定能量恢复不受 ERR 放大 | FixedAddValue、FixedAddMaxSPRatio 不乘 ERR；普通增量保留 ERR，set 真正赋值；多公式字段不再静默选择第一项 |
| 终结技消耗、容量、回能不同 | ActionDefinitionIR 独立保留 SPNeed，缺失不猜；动作/队列可用性按成本检查；正式资源计划先扣费再独立回能，多余能量保留；删除队尾清空并设为 SPBase 的旧路径 |
| 能量每次产生时读取适用 ERR | executor 在 SP、能量扣费、基础回能各步骤执行前，使用前序监听完成后的最新状态规划；不会让旧 mutation.before 覆盖中途回能；规则版本为 v7 |
| 独立减伤相乘 | 同状态实例的属性贡献先按既有属性合同相加，再与独立实例/输入连乘；保留逐项来源 |
| 动态防御百分比作用于基础属性池 | direct 与 non-direct 共用 effective_unit_stat；静态百分比、固定值不再被动态比例重复放大 |
| 控制抵抗与通用效果抵抗分离 | StackStatusResistance 的 OnStack/STAT_CTRL 经状态安装进入正式属性消费，仅控制申请读取；callback 核对同一 producer，不重复加值；正式移除会清理 |
| 共享类别免疫来自实际防护状态 | 两张全局映射编译成 11 条规则实体，已安装实例的 BehaviorFlag 与申请类别匹配才生效；来源、移除后失效均可审计；未知覆盖/消费顺序拒绝执行 |
| 不同来源普通盾不能相加 | 多个适用于当前伤害的盾实例共同存在时拒绝未知消耗路径，保留实例且无 HP/盾 mutation；正式 direct、DoT、additional、break、super-break、true 路径都传播失败 |
| 施加者与操作来源独立 | 事务补事件接收独立 actor_id，并按 mutation 身份保持事件来源；初始化召唤调用者传递 owner |
| 移除/驱散需保留动作目标事实 | 转发 admitted_action_target_fact/expected_action_window_scope，修复正式清理路径的缺参异常 |

公式来源：PR #8 的 `public_mechanics_healing_shield_reconciliation_v1.md`、
`general_healing_shield_hp_resolution_v1.md`、`general_damage_formula_and_input_layers_v1.md`、
`general_energy_skill_point_economy_v1.md`、`general_effect_application_hit_resistance_immunity_v1.md`。
编译后的治疗/护盾/能量 payload 保留固定研究链接，不以该审计链接选择运行行为。

## 验证范围

本地实际结果：规则注册 v7 下当前核心 tests 目录 **245 passed，19 subtests passed**（77.72 秒）；
18 个触达生产模块编译检查通过；`git diff --check` 通过；TBGD submodule 无差异。
既有 P7-S14 概率验证的 13 项检查通过。

- 新增八份定向测试：`test_sustain_resource_reconciled_rules.py`、
  `test_damage_formula_reconciled_rules.py`、`test_capped_shield.py`、
  `test_status_control_resistance.py`、`test_status_shared_immunity.py`、
  `test_action_definition_sp_need.py`、`test_ultimate_action_energy_gate.py`、
  `test_ultimate_energy_execution.py`。
- 真实 March InitShield 单文件来源经过 lowering → EffectRegistry → MutationReducer → replay。
- 真实罗刹类别抵抗来源经过 lowering → StatusSystem 安装 → 同一 OnStack 叶子消费 → 正式移除。
- 全部 11 条真实免疫映射逐项覆盖；真实 Endurance 防护安装/移除改变 Freeze 申请结果；
  真实 Lynx 一次保护由于消费顺序未闭合保持零 mutation/RNG 拒绝。
- 完整角色动作定义编译集合为 6784 条，其中 Ultra 1800 条、带明确 SPNeed 的 Ultra 1620 条；
  缺失的 180 条不从容量回填。娜塔莎一级终结技保留成本 90 与基础回能 5。
- 合成容量 200、成本 100、当前能量 140、ERR 25%、基础回能 5 的正式资源 producer 产生
  140→40→46.25 两条 mutation；中间插入真实固定回能效果 +10 后重规划得到 56.25。
  动态绑定失败时连同已计划的扣费与回能整事务零提交；这不是完整终结技任务图验收。
- 事务正负对照使用真实 EffectRegistry 与 CombatExecutor.commit_eventful_transition；缺绑定时
  已计划的 HP/SP/队列/RNG 都不提交。另有公共 ActionCommand 拒绝门检查。
- 四个直接相关 raw 文件共 23 个任务：HealHP 9、ModifySPNew 11、InitShield 2、StackShield 1。
  16 处标准化结果变化，无新增 blocked；1 个 StackShield 从缺 amount 改为已表达 amount/cap。
  这是局部静态编译分母，不是角色可执行率。临时详情在 `/tmp/hsr_pr8_lowering_catalog.json`。

统一可重跑命令（使用原有环境，无新依赖）：

```bash
PYTHONPATH=hsr_v075_baseline_clean .venv/bin/python -m pytest -q -p no:cacheprovider hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests
git diff --check
```

## 明确保留的边界

- 未完成所有 PR #8 事实及全项目；本记录不宣布完整角色、全怪物或整场战斗完成。
- 已准入 ActionCommand 的完整任务图内公式失败回滚尚缺本轮专门证据；上述事务层测试不冒充它。
- 终结技成本链只读复核未发现新增问题；完整 Ultra ActionCommand 的 prepare/listener 调度仍缺
  专门端到端用例。队列子动作失败会按既有策略终止队列条目，不能把动作能量回滚说成所有队列
  状态都保持不变；合成事务测试的完整快照断言只适用于其明确构造的提交边界。
- 类别抵抗只接单一 STAT_CTRL 来源；重叠类别聚合、一次保护消费与强制控制覆盖顺序未确认。
  静态共享免疫已接入，有 OnImmune* 消费 callback 的路径仍拒绝执行。
- 普通多来源护盾的完整消耗/退出顺序、变化属性下的护盾采样与降 cap 处理未闭合；
  已阻止多适用盾叠加吸收的错误结果，汇总值只作来源实例记账。
- 终结技成本与回能已分离；资源相对于其它 callback 的精确时机保留并标注原引擎资源窗口约定。
  特殊多档消耗、容量构造和无 SPNeed 的终结技不从公开反例反推成角色专用答案。
- 复杂静态 DEF、hit 减防与无视防御混合仍保留原 engine convention，审计明确标记，未宣称 PR #8 证明。
- AddRatio 的 action SPBase 运输及整动作能量去重、召唤物完整创建链、击破跨阈值记账、
  未完成控制流和其他研究记录的剩余覆盖，不因本轮局部修复被标为完成。
