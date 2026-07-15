# P8-S2 正式角色构筑输入与基础面板 ready_for_review

## 状态

- 执行线程状态：`ready_for_review`
- 验收线程状态：`accepted`
- 代码基线：`d5ab366 feat(v8): establish P8 equipment type contract`
- Checklist：已由验收线程勾选 P8-S2
- Git：随本次 P8-S2 验收检查点提交
- 后续阶段：未开始 P8-S3
- 本阶段没有 lower 光锥或遗器，也没有实现装备合法性、装备数值或装备效果

本报告是代码、验证与缺口的证据索引，不是独立完成证明。验收线程已复核当前源码、真实来源矩阵、模板锚点与独立篡改负例，P8-S2 通过验收。

## 本阶段产物

### 类型化角色成长来源

- `AvatarPromotionTierIR` 逐档保存晋阶号、等级上限、生命 / 攻击 / 防御的基础值与每级成长、速度、基础暴击率、基础暴击伤害、基础仇恨值和真实 `IRSource`。
- 角色成长 JSON 使用 `Decimal` 解析；进入贡献账本前不转为 `float`。旧 `base_stats_by_promotion` 宽泛字典及其唯一消费点已删除，没有保留双来源兼容层。
- 缺少 `Promotion` 字段只允许投影为带明确 evidence 的零阶语义。重复、冲突、缺档、不连续、等级上限不递增或损坏档位都会 blocked，不按文件顺序覆盖。
- `SPNeed` 缺失不会默认为 0。只有角色能力文件中存在结构化特殊资源节点时才归类为 `special_resource`；当前对应来源为 `RPG.GameCore.SetSummonerEnergyBarState`，仍因尚未 lower 而 blocked。若找不到这种来源则归类为 `source_missing`，不能凭角色身份猜测特殊资源。

### 正式构筑、贡献账本与装配结果

- `CharacterBuildInput` 只包含构筑身份、角色卡身份、等级、晋阶、星魂等级、已解锁行迹节点和 S1 装备选择结构；不包含最终面板、行迹禁用列表、角色行迹等级、当前生命 / 能量或行动值。
- 所有行迹节点都保留节点等级、最高等级、默认解锁、要求晋阶、要求角色等级、前置节点、技能等级引用、能力引用和额外效果引用。默认解锁直接来自节点定义并自动生效；显式重选同一默认等级会被拒绝，更高等级会原子替换默认低等级；不满足任一解锁条件、重复节点、未知节点、跨角色节点和同一逻辑行迹的冲突等级也都会被拒绝。
- 技能等级和额外效果各自拥有独立机制槽。技能等级通过 `CharacterSkillLevelResolution` 形成类型化静态通道，保存技能、动作、基础等级、星魂加级、最终有效等级、角色卡动作记录来源、唯一动作定义身份及其真实来源；缺失、重复、非 executable、来源损坏或两条来源不属于同一 raw row 时都会阻止战斗。额外效果等当前不能执行的子来源会产生未准入诊断，未绑定来源也不能静默跳过。
- `IRRawRowIdentity` 只抽取来源路径、raw 类型、raw ID、ID 字段、结构化 `row_index` 和等级作为原始记录身份；角色卡 builder 与动作定义 builder 各自附加的说明性 evidence 不参与相等判断。
- `StaticStatContribution` 统一保存贡献池、精确十进制值、计算过程、类型化来源引用和真实 `IRSource`。固定归并顺序为基础池、百分比、固定值、资源池；生命、攻击、防御、速度、能量上限属于基础池，基础暴击率、暴击伤害和仇恨值属于资源池。
- `CharacterBuildAssemblyResult` 区分 `assembled | blocked` 和 `admitted | blocked`，保存最终基础面板、完整贡献账本、类型化有效技能等级、已准入动态机制、未准入诊断、输入 fingerprint 与结果 fingerprint。
- 新增构筑模型、账本、动态引用和结果均为递归不可变；外部列表后续修改不会改变 JSON 或 fingerprint。反序列化拒绝额外旧字段、损坏 fingerprint、错误嵌套类型与重复身份。
- blocked 装配不暴露正式面板、贡献或动态机制；已装配但战斗 blocked 必须具有未准入机制诊断。正式准入会重新从当前 RuleBook 装配并逐字段比较结果，伪造来源、值或机制通道不能进入战斗。

### 晋阶边界与精确数值

- 等级成长按 `base + add * (level - 1)` 使用 `Decimal` 计算。
- 晋阶发生在上一档等级上限：同一等级的晋阶前与晋阶后状态都合法，但使用不同来源档位；低于上一档上限的已晋阶状态 blocked。
- 面板分别保存最大生命、攻击、防御、速度、最大能量、基础暴击率、基础暴击伤害、基础仇恨值和额外资源，不保存当前生命或当前能量。
- 只有在创建 `UnitState` 时将最终十进制面板值转换一次为运行时数值。

### scenario 与旧路径原子迁移

- `UnitSpec.build_mode` 改为必填，且只能是 `assembled_character_build` 或显式 `kernel_fixture`；loader 不再默认选择 kernel fixture。
- 正式角色构筑强制 `panel=None`，并要求独立的 `CharacterInitialConditionInput`。S2 只准入显式满生命、零能量；缺初始条件直接拒绝。
- 正式身份校验要求 `UnitSpec.entity_ref`、角色卡、角色构筑和内嵌空装备构筑属于同一角色，外层等级 / 星魂与构筑镜像一致；非空光锥、遗器或任一身份不一致均 blocked。
- 正式静态行迹只由构筑装配器计算一次。旧 panel flags 行迹调整和旧星魂启动只保留给 `kernel_fixture`；正式路径仅消费装配结果中已准入的通用图引用。
- 正式动作等级由装配结果中的有效技能等级决定。scenario route 的 `action_level` 只是显式镜像；动作不属于角色卡、没有装配后的有效等级或镜像值不一致都会在身份解析阶段被拒绝。`ActionAvailabilitySystem` 在正式模式下读取同一等级映射及动作定义绑定，不再使用角色卡默认等级；映射缺失、身份集合损坏、来源损坏或与 RuleBook 不一致时拒绝查询。`kernel_fixture` 仍保留原默认等级行为。
- 任一已选行迹或星魂机制未准入时仍可生成只读面板，但战斗准入为 blocked；诊断记录不能替代阻止战斗。
- 正式时间线只能使用 `runtime_initialize`，且不能携带 `action_values` 或 `explicit_overrides`；Loader 与直接构造后的 IdentityResolver 都会拒绝这两类注入。

### UI 边界

- UI 报告展示 `build_mode`、正式构筑、初始条件和装配结果摘要。
- JSON 编辑器遇到正式模式不会写回旧 panel 字段。本阶段没有扩张为完整构筑编辑器。

### 指定重回归暴露的迁移与共享内核修复

- P4-S8 保留原矩阵行 ID，但 `trace_static_stat_assembly_runtime` 已改为读取正式 `CharacterBuildAssemblyResult` 的精确贡献账本，不再依赖 kernel fixture 的旧 panel flags；`eidolon_skill_level_assembly_runtime` 改为读取 `CharacterSkillLevelResolution`、prefix-closed 星魂槽和类型化 bonus 来源。
- `UnitSpawnSystem` 现在要求 summon、servant 和 wave 的请求来源、entry 来源、出生模板来源、计划来源及单位 source flags 形成完整证明链；缺任一证明时，出生计划 blocked、零 mutation、state unchanged。
- 来源证明只使用稳定的 `source_path + raw_type + raw_id` 身份，说明性 evidence 不参与单位数值生成。波次等级允许 Stage 与 HardLevelProfile 组成结构化复合来源，但任一叶来源损坏或缺失都会 blocked。

## 约束与证据映射

| 约束 | 生产代码证据 | 失败条件 |
|---|---|---|
| 完整基础面板来源 | `AvatarPromotionTierIR`、`_avatar_promotion_tiers`、`_base_contributions` | 任一成长字段缺失 / 非精确数值、能量来源缺失或晋阶档损坏时 blocked |
| 行迹来源闭环 | `CharacterTraceNodeIR`、`_trace_nodes_and_slots`、`_selected_trace_nodes` | 任一解锁晋阶 / 角色等级 / 前置节点要求或效果来源被静默忽略时失败；条件未满足、同等级默认节点重选、重复、未知、跨角色或冲突等级拒绝；更高等级必须替换默认低等级 |
| 有效技能等级闭环 | `IRRawRowIdentity`、`CharacterSkillLevelResolution`、`_resolve_effective_skill_levels`、`RuleBook.action_definition_candidates` | 缺技能归属、缺真实等级来源、重复 / 冲突等级，或最终动作定义缺失、重复、非 executable、raw row 来源不一致时拒绝 |
| 正式动作查询等级 | `_formal_character_activation`、`ActionAvailabilitySystem._ally_choices` | 正式模式读取卡片默认等级、等级映射 / 来源 / 动作定义绑定缺失或损坏、与 RuleBook 不一致时拒绝 |
| 星魂子来源闭环 | `_eidolon_mechanism_slots`、`_eidolon_mechanisms` | 能力、技能等级和额外效果未独立准入，或任一未处理子来源未阻止战斗时失败 |
| 正式装配结果 | `CharacterBuildAssemblyResult`、`assemble_character_build` | blocked 结果泄漏正式通道、battle blocked 无诊断、账本无法重算面板均拒绝 |
| 来源与不可变性 | `build_types.py`、构筑模型 `from_json` | 空 / 错来源、可变嵌套、重复贡献、损坏 fingerprint、额外旧字段均拒绝 |
| 严格战斗准入 | `validate_character_build_admission`、`_formal_character_activation` | 结果与 RuleBook 重建不一致、动态图缺失 / 类型错误 / 来源错误或存在未准入诊断时拒绝 |
| scenario 身份与初始条件 | `ScenarioLoader`、`IdentityResolver`、`ScenarioStateBuilder` | 非显式模式、正式 panel、缺初始条件、角色 / 等级 / 星魂 / 装备身份不一致时拒绝 |
| 旧路径只供 fixture | `build_state.py` 的 formal / kernel 分支 | 正式路径出现旧 trace panel adjustment、旧 eidolon activation 或非准入 startup 时验证失败 |

## 验证证据

### 当前代码的 fixture 契约验证

```text
PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
python3 -m simulator_v8_clean_core.tools.validate_p8_s2_character_build_base_panel \
  --fixture-only \
  --output-dir /tmp/hsr_v8_p8_s2_raw_row_fixture
```

结果：`ok=true`，33 项检查全部为真。除精确 Decimal 成长、晋阶边界、账本重算、JSON round-trip 和递归不变量外，还直接覆盖：

- 能量上限只能进入基础池，暴击率只能进入资源池；交叉放置会被正式结果模型拒绝。
- 固定单等级技能和默认行迹都会生成带真实来源的类型化有效等级；显式重选同一默认等级被拒绝，更高等级会替换默认低等级，同时选择默认与升级节点会被拒绝。
- 晋阶、角色等级和前置节点三类行迹解锁条件分别有原始模型负例；任一未满足都会在装配前 blocked。
- 缺失、重复和非 executable 动作定义分别重走完整装配链，并产生只读面板加战斗阻断；有效技能等级保存准确的动作定义身份与来源。
- 无关来源文件 / raw ID、错误 `row_index` 和错误来源等级分别重走完整装配链，三者均保留只读面板并阻止战斗；公开 `CharacterSkillLevelResolution` 构造器也拒绝伪造的 raw-row 绑定。
- 同一星魂的技能加级进入有效技能等级静态通道；额外效果未准入时，不能因为技能加级已处理就让战斗 admitted。
- 正式 scenario 只接受与装配结果一致的动作有效等级；实际动作查询在卡片默认等级为 2、装配等级为 1 的 fixture 中选择 1，并拒绝缺失映射及损坏的动作定义绑定。
- `action_values` 与 `explicit_overrides` 分别注入 `runtime_initialize` 时，Loader 和 IdentityResolver 均拒绝。

资源记录：TBGD 文件读取 0、lowering 构建 0、小型 fixture RuleBook 构建 11、无大型产物。

### 当前真实来源的轻量投影与独立 oracle

```text
PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
python3 -m simulator_v8_clean_core.tools.validate_p8_s2_character_build_base_panel \
  --character-card-source-only \
  --output-dir /tmp/hsr_v8_p8_s2_raw_row_source
```

结果：`ok=true`，25 项检查全部为真。该模式调用一次 focused `build_character_card_ir` 和一次角色动作定义 focused builder，不执行完整 TBGD lowering，不构建完整 CanonicalIR，不扫描能力目录，也不写大产物；为建立 focused RuleBook，只构造角色构筑所需的最小 CanonicalIR。当前观察值只作为数据库清单，不是生产通过条件：

- 5246 条 raw 行迹与 5246 个类型化节点身份、等级、默认状态和子来源逐条一致。
- 3918 条技能等级节点均有 executable 类型化等级槽；106 条额外效果节点均有 blocked 子槽。标准能量角色涉及 523 个默认技能节点，其中 461 个属于当前主卡、50 个是旧版本镜像、12 个属于辅助单位；三类均保留来源并明确分类。当前主卡节点解析有效等级，旧镜像不重复参与；辅助单位节点仍作为默认来源进入选择，但在 owned combatant build 尚未实现时产生诊断并阻止战斗，不能静默排除。
- 5246 条行迹中，4408 条含晋阶要求、306 条含角色等级要求、868 条含前置节点要求；三类字段逐条与 raw 表一致。结构化选择的真实低进度和缺前置负例都会 blocked，不依赖固定角色或节点 ID。
- focused RuleBook 保留 6784 个角色动作定义。所有 admitted 有效技能等级都准确绑定唯一 executable 动作定义及来源；从内存原始 IR 快照移除一个真实动作定义后重新装配，会保留面板但阻止战斗。
- 6101 条进入当前角色卡 action set 的动作记录逐条与动作定义比较稳定 raw-row 身份，6101 条全部对应；验证不比较两个 builder 各自不同的完整 evidence。
- 91 个具备常规能量来源的角色逐一装配：84 个得到 `assembled + admitted`，7 个得到带来源诊断的只读面板并阻止战斗。阻断来源分别是辅助单位技能等级尚无 owned combatant build，以及 1 个多等级主技能缺少唯一结构化等级来源；两类都没有猜测默认等级。
- 真实数据同时验证了默认技能等级自动生效、显式重选同一默认等级被拒绝，以及更高等级替换默认低等级。
- 644 个晋阶档的全部数值字段逐条与 raw 行独立对照。面板 oracle 直接从 raw JSON 字段计算，不读取生产 IR 的投影数值；能量上限还会重读精确 raw 来源，并核对 raw、基础池贡献账本和最终面板三处一致。
- raw 星魂中 35 条“能力 + 额外效果”混合来源全部保留；当前卡使用的 28 条分拆成独立子槽，被增强版替换的 7 条旧镜像仍保留在卡来源 evidence 中。
- 缺常规能量字段的当前 profile 只因能力文件中实际发现 4 个 `SetSummonerEnergyBarState` 节点才归类为 `special_resource`；验证器独立重读精确来源文件并核对全部 JSON 路径，否则会保留为 `source_missing`。

资源记录：完整 lowering 0、完整 CanonicalIR 0、focused 角色卡 CanonicalIR 1、focused 角色动作定义构建 1、小型 focused RuleBook 2、角色动作来源表读取 4、能力目录扫描 0、精确特殊资源来源文件读取 1、精确能量上限来源文件读取 3、无大型产物。

### 直接回归与静态检查

```text
PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
python3 -m simulator_v8_clean_core.tools.validate_p8_s1_equipment_type_contract \
  --s0-summary /tmp/hsr_v8_p8_s0_equipment_source_inventory/validation_summary_p8_s0_equipment_source_inventory.json \
  --output-dir /tmp/hsr_v8_p8_s2_p6_source_proof_s1
```

结果：`ok=true`；TBGD 来源读取和 lowering 构建均为 0，无大型产物。这里只把各 `checks` 子矩阵作为 S1 类型契约回归；顶层 `p8_s2_or_later_started=false` 等字段描述的是 S1 阶段自身范围，不作为当前工作树未开始 S2 的证据。

```text
PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
python3 -m simulator_v8_clean_core.tools.validate_p7_s10_timeline_control_semantics \
  --output-dir /tmp/hsr_v8_p8_s2_p7_s10_regression
```

结果：`ok=true`，6 行时间线语义检查通过。

```text
ionice -c 2 -n 7 nice -n 10 \
env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
python3 -m simulator_v8_clean_core.tools.validate_p4_s8_trace_eidolon_level_resource_hooks \
  --output-dir /tmp/hsr_v8_p8_s2_p4_s8_migrated
```

结果：`ok=true`，9 行矩阵全部通过。正式行迹贡献账本与正式星魂技能等级装配两行均为 `executable`；完整 lowering 1 次、RuleBook 1 次，只写 summary 和 matrix。

```text
ionice -c 2 -n 7 nice -n 10 \
env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
python3 -m simulator_v8_clean_core.tools.validate_p6_s2_s3_unit_spawn_birth_plan \
  --output-dir /tmp/hsr_v8_p8_s2_spawn_template_anchor_p6_final
```

最终结果：`ok=true`，15 行矩阵全部通过；29 个不完整出生计划负例和 26 个篡改负例全部 blocked、零 mutation、state unchanged，波次复合等级来源正例通过。普通召唤物、servant 和波次敌人各自包含一项“业务身份不变，计划内部全部请求来源被格式完整的无关来源一致替换”负例，三项均由 `unit_spawn_plan_request_source_mismatch` 拒绝。消费端还会从 RuleBook 取得可信 `UnitBirthTemplateIR`，按可信模板、原始请求和 owner 重新物化完整出生 payload；波次等级、面板、数据卡、时间线来源以及普通召唤物和 servant 生命周期来源的六项完整替换负例均由 `unit_spawn_plan_template_payload_mismatch` 拒绝。正式 `to_unit` 必须同时显式传入原始请求、可信模板和 owner；source 叶子必须具有合法 evidence 映射，但只改变 evidence 说明文字的三项正例仍可生成出生 mutation。第一次 P6 重跑因错误地把复合等级来源限定成单个 `IRSource` 而失败，该结果不作为证据；模板锚点本轮首次通过后又因新增递归 source 完整性校验重跑一次，只有上述 `final` 产物作为最终证据。

```text
PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
python3 -m simulator_v8_clean_core.tools.validate_p7_s4_rule_audit_separation \
  --output-dir /tmp/hsr_v8_p8_s2_spawn_template_anchor_p7_s4_final
```

结果：`ok=true`，21 个 ownership 行通过；缺来源证明会 blocked，仅改变 evidence 注释不会改变单位行为投影。

```text
PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s2_pycache \
python3 -m compileall -q \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core \
  hsr_v075_baseline_clean/hsr/simulator_v8_ui

git diff --check
```

两项通过；`ir_types` 中 2 个数据类、`rules.ir` 中 62 个数据类、`builds.models` 中 9 个数据类，以及两个 raw-row 身份 helper 的运行时 `get_type_hints()` 全部可解析。

### 未运行与资源风险

- `validate_v0_204` 曾被错误启动，造成内存和磁盘 I/O 峰值，随后由用户手动终止；它没有通过，不能作为本阶段证据。
- 未运行 P4-S2 / P4-S11 直接验证：两者都会调用完整 `TBGDLowering.build()`。本轮已在 S2 fixture 中通过公开 `ActionAvailabilitySystem.view()` 覆盖正式动作等级消费链，不再为同一阻断点重复触发全量 lowering。
- 未运行 `validate_v0_205`、`validate_v0_206`、P4 / P6 阶段聚合、P1-P7 聚合、`validate_v0_209` 或其他全量 lowering / RuleBook 重验证。
- 本阶段按验收要求串行执行了 P4-S8 一次、P6-S2/S3 五次完整 lowering；后续 P6 分别用于修复复合来源误判、请求来源锚点、可信模板来源锚点，以及在最终递归 source 完整性校验落地后重跑。六次均低 CPU/IO 优先级运行，上一进程结束后才启动下一项，且均未写完整 IR / RuleBook / transition dump；失败或中间产物不作为最终证据。
- loader / identity / timeline 的 S2 相关谓词已进入 focused 验证，时间线另有 P7-S10 直接回归；剩余旧聚合风险留给验收线程按资源条件决定，不以少跑验证冒充已覆盖。
- 所有当前补强后的验证产物均为小型 summary / matrix，没有写完整 CanonicalIR、完整 RuleBook 或 transition dump。

## 当前 gap 与阶段边界

- 当前真实数据库中缺常规能量上限的角色归类为 `implementation_missing`：特殊资源尚未实现，面板与正式战斗均 blocked。
- 当前 3918 条行迹技能等级节点已进入通用有效等级链路。91 个常规能量角色中 84 个的默认或选定等级可以解析并通过装配层战斗准入；7 个保留只读面板并 blocked，其中包含 owned combatant build 尚未实现的辅助单位技能等级，以及 1 个没有唯一结构化等级来源的多等级主技能。两类都明确归类为 `implementation_missing`，不用固定技能 ID、身份特判或猜测默认等级补齐。
- 106 条行迹额外效果节点仍完整投影为 `implementation_missing`；只有实际选中或默认生效的未准入子来源才产生诊断并阻止正式战斗。旧版本镜像和辅助单位技能节点不会冒充当前主角色来源，但仍保留在 CanonicalIR 和 source-only 分类清单中。
- 星魂能力、技能等级和额外效果已按子来源拆分；任一子来源未准入时，已实现部分也不能让整个星魂冒充 admitted。
- S2 只允许空装备构筑；光锥、遗器、槽位、词条、套装和装备机制均留给 P8-S3 及后续阶段。

距离最小可用战斗纵切：S2 已闭合正式构筑面板、有效技能等级和 fail-closed 战斗准入；当前有 84 个常规能量角色在装配层具备真实 `assembled + admitted` 正例，但这只证明构筑与动作等级边界可进入正式路径，不代表这些角色的全部技能、行迹和星魂机制已经复刻。距离完整复刻仍缺剩余行迹 / 星魂子来源执行、辅助战斗单位构筑、特殊资源、全部光锥 / 遗器 lowering、装备数值与合法性、套装和装备动态机制以及 P8 最终端到端聚合。
