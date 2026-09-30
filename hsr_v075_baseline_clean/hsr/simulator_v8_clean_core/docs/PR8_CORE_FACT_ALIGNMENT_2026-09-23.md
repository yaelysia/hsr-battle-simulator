# PR #8 事实与核心对账：2026-09-23

状态：第一轮有界审计摘要；不是完整内核验收，不是已批准施工计划。

## 基线与实际操作

- 当前业务 master / 本地 HEAD：`2d60a4305206bc11b67edf445a55478d90c96257`。
- PR #8 evidence HEAD：`8daa6a8abb9a15e423ecf987356dcc0a936565ba`，仍为 Draft evidence 分支，不以该分支的旧 runtime 代替当前内核。
- TBGD pin：`14c1d18f91a8101d610e6c523447a7517de3fae1`。
- R6 修复 merge：`f8e8a053ef591e1aeeb99956d46acd8390676c6f`；当前业务基线在其后 4 个提交。
- 当前任务列表：PR11 A2、P4、P5、P6 已完成；其他所列任务已取消；本轮未看到执行中的任务。
- 既有 `.gitignore`、CODEX_HANDOFF、P9 计划、工作流说明、执行卡索引及其他未跟踪文件均未覆盖。
- 本轮只新增本审计记录；未改生产代码，未跑新测试，未提交/推送/创建 PR，未启动执行器，未读取聊天或以 checkpoint 代替事实正文。

以下 K 路径均相对 `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/`；R0–R9 和 March 均指 PR #8 精确 evidence HEAD 的主记录。

## 判定口径与覆盖

“已对齐”仅针对表中具体字段、调用边、静态分区或既有运行切片；不是整个角色/机制的 native 数值正确性或当前 HEAD 全量 PASS。C（有实现）、D（静态对齐）、测试文件存在、Decimal 计算都不能自动成为 E（实际运行）。

本轮盘点 19 份事实记录，打开 11 份的相关正文，包括用户列出的九份主记录。部分长响应截断，另八份未独立读取；没有完成全文逐 claim 普查。下表 22 项是本轮有界检查项，不是全部事实分母：已对齐 10，不一致 2，明确缺失 2，待判 8。“待判”不能自动改成“未实现”。

## 优先不一致项

### F-HEAL-01：治疗公式缺省推断越过事实权威边界

状态：open；验证：当前精确基线的静态 producer/consumer 核对，未实际运行复现。

事实依据：`docs/tbgd_evidence/shared/healing_modifier_lifecycle_core_v1.md`。Gallagher 的样本有 ModifyValue，但缺 FormulaType / HealPercentage；记录未恢复该缺省的 native 固定治疗公式。存在数值输入不等于默认公式已被源证明。

当前代码：

- `K/tbgd/lowering.py::_standard_heal_payload`（21617–21681）：缺省 FormulaType 配合可解析 ModifyValue 可进入 flat；缺省且 percentage-only 时补造 `HealByTargetMaxHP`，并标注 `tbgd_schema_default_for_percentage_only_heal`。
- `K/systems/effect.py::_fixed_payload_is_executable`（471–490）：没有独立治疗公式权威校验。
- `K/systems/effect.py::_formula_type_blocked`（2549 起）：允许 heal 的 None / 空公式。
- `_resolve_formula_amount` 可按 flat 或 target.max_hp 运算，`_execute_fixed_unit_delta` 可继续生成 HP mutation。

结论是来源权威/准入不一致，不是已证明 Gallagher 的 native 最终治疗值错误或应等于另一个数字。缺省+固定值、缺省+仅百分比、缺省+两个字段、空/错误公式和旧标准化 payload 是需要运行验证的反例。显式公式及 canonical/internal Heal 的合法固定值合同必须保留；不能为封堵 raw HealHP 的默认推断而粗暴拒绝所有内部 fixture。

关闭边界：分开源事实、明确授权的 local convention、未知；无权威或已准入规则时保持 blocked。仅改 provenance 标签却继续默认执行，不足以关闭。正式动作拒绝必须维持状态、资源、队列、RNG、回调与结算的零提交，不能只看最终 HP。

### F-SHIELD-01：比例护盾的 ShieldValue 没有进入消费/拒绝路径

状态：open；验证：当前精确基线的静态数据流核对，未实际运行复现。

事实依据：`docs/tbgd_evidence/characters/march_7th_preservation_skill02_shield.md`，以及 R0 `battle_execution_language_core_v1.md`。March 普通 Skill02 的 index0 → MDF_ShieldPercentage → InitShield.ShieldPercentage，index3 → MDF_ShieldValue → InitShield.ShieldValue 是两条不同源输入；Level11 对应 .589 与 802.75。InitShield 位于 OnStack，不是 OnCreate。

当前代码：

- `K/tbgd/lowering.py::_standard_shield_payload`（21685–21713）保存两个字段，但比例公式下只把 percentage 放入 amount。
- `K/systems/effect.py::_execute_fixed_unit_delta`（678–837）只有 heal 分支处理额外 flat_addition；shield 分支仅缩放单一 amount，再交给 ShieldSystem。
- `K/systems/shield.py::ShieldSystem.apply_effect`（59–230）接收单一 float amount，直接据此设置实例 capacity/remaining，没有补用 ShieldValue。
- 当前已检查的 systems 路径没有 ShieldValue 消费分支；第二个已声明输入既未被消费，也没有因其语义/绑定未支持而被拒绝。

结论是源输入覆盖/运行消费不一致。不能直接宣布 native 修复必然为 DEF×比例+固定值：主记录保留 generic ShieldByCasterDefence、快照和运算次序边界。本轮证明的是漏掉一个输入，而不是恢复完整 native evaluator。

需要运行验证：同一 basis/percentage 下仅改变 ShieldValue；第二个操作数缺绑定/不可解析；合法单操作数护盾对照。结果应由显式已准入合同处理两个操作数，或诚实拒绝未支持的复合公式，而不能静默忽略字段后声称完整执行。InitShield/StackShield/ModifyShield 的实例策略不是本 finding 自动授权重写的范围。

## 三类分拣与待判矩阵

| ID | 分类 | 本轮成立的边界 | 不得外推 |
|---|---|---|---|
| C01 | 已对齐 | R6 rank proof 当前仍含 raw_path/rank/value；历史修复已合并。 | 不是当前 HEAD 的新运行。 |
| C02 | 已对齐 | Stage103201 重复怪物共用模板，但 entry/position/unit_id 独立；历史三槽 plan/to_unit 通过。 | 不是整场战斗或完整构筑通过。 |
| C03 | 已对齐 | Stage202212020 后续波次历史 9 mutations、replay_ok=true。 | 起点有 cleared-wave/inert-ally fixture，不证明攻击击杀全过程。 |
| C04 | 已对齐 | R6 缺来源证明/错误 request 的历史负例保留严格拒绝。 | 不证明任意 evidence 文本篡改都可检测。 |
| C05 | 已对齐 | 已读 DirectDamageFormula 入口要求 scaling basis 解析成功。 | 不签署所有 basis producer 或最终伤害公式。 |
| C06 | 已对齐 | 当前映射保留 Attacker_CriticalDamage、Defender_DefenceAddedRatio、Defender_AllDamageTypeTakenRatio 的不同目的侧。 | 不把字段名直接解释成 native DEF-ignore 代数。 |
| C07 | 已对齐 | GLOABNLLLEL 字面 family 仍保留；共用结构处理不等于改写原始身份。 | 不证明 native primitive 或随机算法。 |
| C08 | 已对齐 | AddRatio-only / FixedAddRatio-only 资源请求当前被 blocked，而非直接作为 max_energy 比例。 | 多字段并存组合未审计；整个资源经济未验收。 |
| C09 | 已对齐（既有 D 的有界分区） | R5/R8 的静态属性与 LC/Set 动态分区；相关 assembler 在 f8e8a053… 到当前比较中未改。 | startup/status 后续有修改，不签署选定 B2/B3 真实执行或完整回归。 |
| C10 | 已对齐（既有 D 的源投影） | R7 TargetInfo 源投影、怪物候选约束与外部控制分开；相应 producer 在比较中未改。 | 不签署后续修改过的完整 action_selection/Decision 运行链。 |
| F-HEAL-01 | 不一致 | 缺省治疗公式被推断/准入；见上文。 | 静态发现，不是 native 数值已证伪。 |
| F-SHIELD-01 | 不一致 | 比例护盾漏掉另一源操作数的消费/拒绝；见上文。 | 不擅造 native 运算顺序。 |
| N01 | 未实现 | 普通 CreateServant 正式调用边缺失；当前 Python 命中只在 source scope/lowering，EffectRegistry/正式分派未接通。 | 已有定义/helper 不等于零实现；G02–G06 不能全部判错。 |
| N02 | 未实现 | MazeBuff → CharacterSkill/SkillMaze 的规范化外部适配器未建立；只有 downstream canonical-effect setup。 | 不是构筑应自动获得秘技却失败。 |
| U01 | 待判：source gap | Asta 等普通 StanceValue 注入来源未闭合。 | 不用 ShowStanceList / StanceDamageDisplay 补 0/10/30。 |
| U02 | 待判：native gap | 完整伤害/治疗/护盾 evaluator、clamp、rounding、缺省尚未全恢复。 | local convention 与源事实分开，不一律判成错误。 |
| U03 | 待判：source role | SPNeed requirement/cap、SPBase/AddRatio 与 raw-SP/BP 的完整关系未全闭合。 | C08 正确拒绝不等于已实现全部资源机制。 |
| U04 | 待判：native/validation gap | Replace、ReplaceByCaster、快照、回调总顺序与通用计时。 | 单个角色 hook 不自动成为全局规则。 |
| U05 | 待判：validation gap | R5 指定 tuple 的正式构筑/运行缺匹配 E。 | Decimal 面板不是实际运行；也不能据缺 E 说未实现。 |
| U06 | 待判：validation gap | R8 指定装备/遗器/秘技的真实 callback 效果缺匹配 E。 | provider 注册、条件比较真或 validator 文件存在不是执行证据。 |
| U07 | 待判：gate-stopped | R9 G01 下游 owner/build/stat/registry/action 未继续裁决。 | 不把 helper fixture 当真实 Aglaea caller。 |
| U08 | 待判：审计覆盖 | 八份专项未独立读取，长记录亦未全文逐项普查。 | 不计算全量覆盖率或整体 PASS。 |

## R6 的真实 E 与复核边界

本轮实际读取 GitHub Actions run `34570966064` 的 job `103172770943` metadata 及原始日志。checkout/tested HEAD 为 `70eabfe4a94ec458eacdd4bf324d9a8889743c49`；结果 `12 passed in 21.24s`，exit 0。

日志确认 Stage103201 三槽、来源负例/request 负例、后续波次 9 mutations/replay。目录检查为 59,940 templates、899,100 formal consumer source identities、missing evidence 0；不是 59,940 场完整战斗。上传日志记录 artifact `10187755334` 与 digest `98b11f4d9c2ae70645da1827863bf50ddd5a72eb59fb217ed978d944e7dc21ef`；本轮未把再次下载 ZIP 的校验冒充已做。

旧 run 不改写为当前 master 的新运行，其 E 不转借给 R5/R7/R8/R9。

## 阅读覆盖与后续优先级

已打开相关正文：R0 battle_execution_language；R1 ordinary_damage；R2 weakness_toughness_break；R3 healing_modifier_lifecycle；R4 resource_economy；R5 battle_start_build；R6 encounter_spawn；R7 action_targeting；R8 battle_start_effect_activation；R9 owned_servant_runtime_admission；March Skill02 shield。

未独立读取的八份：aglaea_servant_11402_reference_chain、light_cone_20000_arrows、monster_1002011_reference_chain、stage_config_wave_source、global_shared_reverse_scan、ordinary_rng_callback_reference_chains、timeline_one_more_and_speed_boundary、嵌套目录的 march_7th_preservation_source_chain。它们不能因本轮未读而被归为“没做”。

修复优先顺序：F-HEAL-01 → F-SHIELD-01 → N01。前两项保持独立有界验收，不扩成重写所有公式；已关闭 R6 不重做。RandomConfig 正式 caller/RNG ledger 不因 PR11 A2 完成而自动算完成，也不因本轮未审而被另行猜测。

本轮没有创建执行任务。新任务接口要求当前 PLAN 会话 URL，当前上下文没有该值；未复用旧线程 URL，也未绕过协调器写任务状态。

## 不可变来源

所有 evidence 链接固定到 PR #8 指定 HEAD：

- [R3 治疗主记录](https://github.com/yaelysia/hsr-battle-simulator/blob/8daa6a8abb9a15e423ecf987356dcc0a936565ba/docs/tbgd_evidence/shared/healing_modifier_lifecycle_core_v1.md)
- [March 护盾主记录](https://github.com/yaelysia/hsr-battle-simulator/blob/8daa6a8abb9a15e423ecf987356dcc0a936565ba/docs/tbgd_evidence/characters/march_7th_preservation_skill02_shield.md)
- [R6 出生/波次主记录](https://github.com/yaelysia/hsr-battle-simulator/blob/8daa6a8abb9a15e423ecf987356dcc0a936565ba/docs/tbgd_evidence/shared/encounter_spawn_phase_termination_v1.md)
- [R8 启动效果主记录](https://github.com/yaelysia/hsr-battle-simulator/blob/8daa6a8abb9a15e423ecf987356dcc0a936565ba/docs/tbgd_evidence/shared/battle_start_effect_activation_v1.md)
- [R9 召唤物主记录](https://github.com/yaelysia/hsr-battle-simulator/blob/8daa6a8abb9a15e423ecf987356dcc0a936565ba/docs/tbgd_evidence/shared/owned_servant_runtime_admission_v1.md)
- [当前治疗 lowering](https://github.com/yaelysia/hsr-battle-simulator/blob/2d60a4305206bc11b67edf445a55478d90c96257/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py#L21617-L21681)
- [当前护盾 lowering](https://github.com/yaelysia/hsr-battle-simulator/blob/2d60a4305206bc11b67edf445a55478d90c96257/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py#L21685-L21713)
- [当前 Effect 数值消费](https://github.com/yaelysia/hsr-battle-simulator/blob/2d60a4305206bc11b67edf445a55478d90c96257/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/effect.py#L678-L837)
- [当前公式 gate](https://github.com/yaelysia/hsr-battle-simulator/blob/2d60a4305206bc11b67edf445a55478d90c96257/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/effect.py#L2549-L2629)
- [历史 R6 实际运行](https://github.com/yaelysia/hsr-battle-simulator/actions/runs/34570966064)
