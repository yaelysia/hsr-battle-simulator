# P8-S18 统一最终面板与战斗出生顺序执行卡

## 执行配置

- 对应问题：P8-I03、P8-I14。
- 硬前置：P8-S8 与 P8-S17 均已独立验收并提交；两个轨道已合并到同一集成基线，光锥/遗器聚焦回归全绿。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`max`。
- 推荐模式：普通聚焦模式，使用新的集成 worktree；从本阶段起禁止双轨并行。
- 选择理由：本阶段统一两个分支对共享装配、出生和 timeline 的修改，设计取舍需要人工可见；Goal 模式容易顺手改 S19/S20 接口。

## 当前事实与阶段结果

S2 已建立角色 source-backed 基础面板与统一贡献账本；S4-S8 建立光锥基础/静态/动态机制；S9-S17 建立六件遗器、词条、套装静态/动态机制。开始前必须先审查两轨合并冲突和共享符号的最终调用链，确认没有两个 equipment assembler、两个 provider registry、两个 property mapper 或重复 ledger term。

完成后，角色自身、光锥基础、行迹、光锥静态被动、遗器主副词条和套装静态属性通过一套确定性公式形成正式最终面板；动态装备机制在静态面板和资源完成后注册，再按 P7 阶段机派发入场事件，最后按入场结算后的最终速度初始化 timeline。runtime 只接收规范出生输入和机制引用，不读取构筑或 raw。缺任一已选 gameplay 机制时可保留只读 assembly，但不得生成可开战 UnitState。

## 本阶段只做

- 合并两个轨道的共享类型和调用链，删除重复/临时路径，建立唯一 equipment assembly -> character assembly -> birth plan 流程。
- 统一 HP/ATK/DEF：角色基础与光锥基础先合为 base，乘全部 ratio 后加 flat。
- 统一速度：角色基础速度乘速度 ratio 后加 flat speed；光锥/遗器不能误作第二个基础速度。
- 其他属性按类型化聚合规则合并，基础资源、ratio、flat、resource 仍保留逐项 ledger。
- 以规范顺序执行：静态求值 -> 初始 HP/资源规则 -> provider 注册 -> OnStart/OnEnterBattle -> 验证最终状态 -> timeline initialize。
- 确保正式 scenario 禁止 panel、初始行动值和 equipment activation override；fixture 模式仍显式隔离。
- 审查 summons/servants 读取 owner 属性的真实时机；默认不继承装备，只有来源明确的 owner-binding 才生效。

## 本阶段不做

- 不实现查询/UI/replay compact contract（S19）。
- 不建立希儿固定构筑（S20），不修改任何具体角色/装备规则。
- 不允许战斗中换装或由 runtime 重算 build。
- 不重写所有出生体系；只对 playable-character 正式构筑边界做必要通用扩展。
- 不为旧未标记 panel fixture 增加兼容 fallback。

## 统一公式与顺序不变量

1. `final = base_total * (1 + ratio_total) + flat_total`；`base_total` 的成员由 property 类型明确声明，不能按贡献到达顺序决定。
2. 光锥基础攻击属于 base attack；遗器固定攻击属于 flat attack；二者位置不可互换。
3. ledger term 保持来源粒度，聚合结果可由规范排序后的 term 独立重算。
4. 输入顺序、字典顺序和两轨合并顺序不能改变 fingerprint、面板或 provider 集合。
5. OnEnterBattle 条件读取完整静态面板；若入场效果改变速度，timeline 读取入场提交后的最终速度。
6. startup 不能重复应用静态 term；静态贡献不是 runtime mutation。
7. 任一 selected graph blocked 时，不创建正式 UnitState、事件注册或 timeline；state unchanged。
8. 初始 HP、能量和行动值由正式规则生成，UI/preset 只能提供允许配置的原始构筑选择。

## 目标与证据映射

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 两轨唯一集成 | 无重复 assembler/provider/property mapper/ledger producer | CodeGraph + architecture matrix |
| HP/ATK/DEF 公式正确 | base/ratio/flat 多来源与独立 Decimal oracle 相同 | panel oracle matrix |
| 速度与 timeline 正确 | ratio/flat 顺序、入场变化和 timeline AV 与独立 oracle 一致 | speed/order matrix |
| 输入顺序无关 | contribution/build permutations 产生相同 panel/fingerprint | permutation tests |
| 局部改动隔离 | 移光锥、变叠影、替遗器、破档位只影响相应 term/mechanism | delta matrix |
| 正式边界 fail-closed | panel/action value/activation override、blocked graph 均拒绝出生 | scenario negatives |
| summon 归属诚实 | 无来源不继承，有 owner binding 才读取对应属性 | summon relation matrix |
| 来源重算闭合 | 最终属性逐 term 重算并可回到内容卡/raw | ledger walkback |

## 拟改文件与关键符号

- `builds/character_assembler.py`、`builds/equipment_assembler.py`、`builds/models.py`：唯一装配流和最终结果。
- `build_types.py`、`equipment/models.py`：统一 property aggregation basis，删除两轨重复类型。
- `scenarios/build_state.py`、`scenarios/identity.py`、`scenarios/schema.py`：正式出生准入与 fixture 隔离。
- P6 `UnitBirthTemplateIR`/birth plan 与 P7 timeline/event startup 入口：只做必要扩展。
- `tools/validate_p8_s18_final_panel_and_birth_order.py` 和阶段报告。
- 受影响的 S2、S5/S6、S14/S15 fixture 原子迁移。

合并后先用 CodeGraph 检查 `assemble_character_build -> assemble_equipment_build -> ScenarioStateBuilder -> timeline` 完整路径和 blast radius。禁止通过保留两套路径规避冲突。

## 结构化验收谓词

```text
single_equipment_assembly_path=true
duplicate_static_producers=0
duplicate_dynamic_provider_registries=0
character_and_light_cone_base_stats_combined_before_ratio=true
flat_relic_stats_applied_after_ratio=true
speed_formula_typed_and_ordered=true
ledger_reconstructs_final_panel=true
input_permutations_identical=true
startup_after_static_panel=true
timeline_after_enter_battle_settlement=true
startup_does_not_reapply_static_terms=true
formal_panel_override_rejected=true
formal_action_value_override_rejected=true
blocked_graph_prevents_unit_birth=true
summon_equipment_inheritance_requires_source=true
runtime_reads_build_or_raw=false
```

## Gap 与停止条件

- 两轨对共享模型有语义冲突：先报告冲突和来源，不自动选“改动更多”的一方。
- property 无统一聚合语义：建立类型化 rule/basis；不能用来源名称 switch。
- P6/P7 出生顺序与装备入场事件冲突：修通用阶段机并运行直接回归，不能在 scenario 手工调整 action value。
- 任一 S8/S17 graph 在合并后重新 blocked：视为集成回归 blocker，先回到所属轨修复。
- 角色/光锥/遗器具体特判一律阻断验收。

## 验证命令与资源

生产边界先保证：最终装配与出生计划在生成 `UnitState` 前校验账本可重算、provider 完整、图已准入、覆盖项为空且身份一致；任一失败都不得产生半成品单位或时间线副作用。runtime 只能读取正式装配结果。

本阶段固定只运行一个业务主验证：

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v -o /tmp/hsr_v8_p8_s18_time_v.txt timeout --signal=TERM 10m ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p8_s18_final_panel_and_birth_order --tbgd-root ../../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s18_final_panel_and_birth_order
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s18_pycache python3 -m compileall -q simulator_v8_clean_core
git diff --check
```

- 主验证只构建一次受控装备 RuleBook并贯穿面板、provider、出生和时间线证据；S8/S17 的已验收报告只校验结构与指纹，不重跑其 aggregate。
- 已验收的 S2、P6、P7 契约直接继承。仅在实际修改共享最终面板、出生计划、时间线或事件阶段时选择对应最小 direct，最多 2 项，不固定重跑四个旧验证。
- 完整主验证最多一次诊断运行和一次最终运行；中间修复只跑失败的 panel/birth/phase 切片。
- 单次主验证预算：墙钟 10 分钟、峰值 RSS 1 GiB；阶段累计验证预算 20 分钟；默认产物不超过 10 MiB。超限立即暂停。
- 不运行 S8/S17 全聚合、S2/P6/P7 完整验证、历史阶段聚合或 `validate_v0_209`，不写完整 RuleBook/transition。

## Ready-for-review 产物

- 两轨合并差异、重复路径清理和 CodeGraph 调用链。
- HP/ATK/DEF/speed Decimal oracle、permutation 和 delta matrix。
- startup/birth/timeline 顺序、formal override 和 blocked birth 负例。
- ledger/source walkback、summon relation、回归和资源报告。

## 唯一执行清单（仅验收线程可勾）

- [ ] S8/S17 已合并为唯一装配与 provider 路径，无重复生产者。
- [ ] HP/ATK/DEF/speed 和其他属性按类型化顺序精确聚合。
- [ ] ledger 可重算面板，输入顺序和局部构筑变化行为确定。
- [ ] 静态面板、provider、入场事件和 timeline 顺序正确且幂等。
- [ ] 正式 panel/action value/activation override 与 blocked graph 均 fail-closed。
- [ ] summon 继承来源明确，runtime 不读取 build/raw，无内容特判。
- [ ] `ready_for_review` evidence、实际触达所需的至多两项 direct 和资源审计完整。
