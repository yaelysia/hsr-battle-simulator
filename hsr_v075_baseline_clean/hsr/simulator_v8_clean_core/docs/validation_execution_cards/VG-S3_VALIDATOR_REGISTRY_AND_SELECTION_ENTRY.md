# VG-S3 验证登记表与选择入口执行卡

## 执行配置

- 代码基线：`d29b34b`。
- 前置阶段：`VG-S0`、`VG-S1`、`VG-S2` 已通过验收。
- 推荐模型：GPT-5.6 Terra。
- 推荐推理等级：`xhigh`。
- 推荐模式：普通模式，单卡执行。
- 执行归属：新的代码执行线程。
- 验证命令工作目录：`hsr_v075_baseline_clean/hsr/`。
- 最终状态上限：`ready_for_review`。
- 禁止执行线程修改本卡 checklist、提交 Git 或开始 `VG-S4`。
- 工作区现有无关 UI 草稿不属于本卡，禁止修改、删除或提交。

## 1. 项目背景

本项目的目标不是做一组互不相关的战斗算例，而是建立一个可审计、可扩展、
可供外部推演器操作的《崩坏：星穹铁道》战斗内核。正式规则链固定为：

```text
turnbasedgamedata-main
  -> compiler/lowering
  -> Canonical IR
  -> data cards / build assembly
  -> Combat Core
  -> snapshot / settlement / replay
```

过去各阶段为了证明当时的实现，积累了大量独立验证器。它们有四种本质不同的
用途：

1. 用小型 fixture 检查一个当前内核契约。
2. 扫描完整来源目录，证明来源覆盖或目录闭合。
3. 在里程碑时聚合多个阶段结果。
4. 保存已经被后续架构替代的历史证据。

目前这些用途主要依靠文件名、旧计划和人工记忆区分。执行线程无法可靠知道哪些
验证属于当前改动，于是经常采取“尽量全跑”的方式。这会重复构建完整
Canonical IR 和 RuleBook，也会让已过时的历史缺口反过来要求当前生产代码兼容。

`VG-S0` 已确认：

- 当前验证目录规模较大，完整 lowering 被大量脚本重复调用。
- P7-S2、P7-S3、P8-R1 runtime-only 等内核契约可以在不读取完整 TBGD 的情况下
  低成本验证。
- `validate_p7_current_tree_shared_regressions.py` 虽然复用一次 RuleBook，但仍把
  已关闭的旧缺口作为通过条件，不能继续充当当前统一入口。
- `validate_v0_209.py` 同时执行 discovery、完整 lowering、coverage、fidelity、
  RuleBook、scenario 和 transition，并默认写大产物，不能用于普通局部回归。

`VG-S1` 和 `VG-S2` 已经关闭 committed state 的外部可写绕过，并建立第一个
touched-domain 完整性协议。现在需要先建立验证选择边界，防止后续每个领域改造
再次被旧验证和重复目录构建拖慢。

## 2. 当前代码事实

本卡目标必须以当前代码为准，不得只复制历史计划中的分类。

### 2.1 登记粒度必须是运行模式

一个 Python 文件不一定只代表一种验证成本：

- `validate_p8_s2_character_build_base_panel.py`
  - `--fixture-only` 是小型内存契约；
  - `--character-card-source-only` 读取角色来源目录；
  - 默认模式会构建完整 Canonical IR / RuleBook。
- `validate_p8_r1_summon_runtime_halo_lifecycle.py`
  - `--runtime-only` 是轻量 runtime 契约；
  - `--source-catalog-only` 是来源目录审计；
  - 默认模式会合并两者。
- `validate_p8_s8_light_cone_remaining_gameplay_closure.py`
  - 提供多个聚焦模式；
  - `--catalog-startup-only` 仍属于光锥完整目录启动审计。

因此 registry 的最小身份必须是：

```text
验证器模块 + 明确运行模式
```

禁止只按文件登记后，把该文件的所有模式视为同一资源等级。

### 2.2 direct 不等于“不构造任何 RuleBook”

P7-S3、VG-S2、P8-S1 等验证会构造小型 Canonical IR / RuleBook fixture，但不读取
完整 TBGD。它们仍可归类为 direct。registry 必须区分：

- 不需要 RuleBook；
- 只需要小型 fixture RuleBook；
- 需要来源 inventory；
- 需要完整 lowering 后的 RuleBook。

禁止用单个 `requires_rulebook=true/false` 丢失这一区别。

### 2.3 CLI 参数不等于真实语义依赖

P8-R1 的 `--runtime-only` 当前仍要求传入 `--tbgd-root`，但该模式本身不读取来源
目录。registry 必须分别记录：

- 当前 CLI 为渲染命令所需的参数；
- 验证语义实际会读取或构建的资源。

禁止仅因 argparse 要求一个路径，就把 runtime-only 错标为 catalog；也禁止
伪装成现有脚本已经不需要该参数。

### 2.4 历史分类不等于删除

P1、P2、P3 聚合、P7 shared aggregate 和 `validate_v0_209` 仍有历史审计价值。
本阶段只把它们移出当前 direct 选择，不删除文件、不重写其中的历史口径，也不
声称它们的全部有效谓词已经迁移。

## 3. 阶段最终结果

VG-S3 完成后，仓库必须具备以下能力：

1. 用机器可读、递归不可变的 registry 描述一批代表性验证运行模式。
2. 每个登记项都明确回答：
   - 它证明什么；
   - 它属于当前契约、目录审计还是历史证据；
   - 它触达哪些领域；
   - 什么改动才应触发它；
   - 它需要何种来源、RuleBook 和输出资源；
   - 它应使用哪个真实 CLI 模式。
3. 一个统一选择 CLI 能根据显式验证 ID 或显式 trigger 生成确定性的 dry-run
   计划。
4. 普通 direct 选择绝不会夹带 catalog、full、historical、superseded 或
   invalid 项。
5. 未登记、未知、缺少必要输入或存在身份歧义时 fail-closed。
6. dry-run 不导入验证器、不读取 TBGD、不构建 RuleBook、不创建验证输出目录、
   不启动子进程。
7. catalog 项可以被显式描述，并在用户明确请求重验证计划时进入 dry-run
   计划；本阶段不执行它们。
8. registry 能表达哪些项目未来可能共享构建，但不能宣称当前已经实现共享
   lowering、共享 RuleBook 或缓存。

本阶段不改变任何战斗规则、Canonical IR、数据卡、scenario、runtime、snapshot、
replay 或 UI 行为。

## 4. 详细目标

### 4.1 建立类型化 registry 契约

新增独立于战斗生产模块的验证治理模型。模型名称由执行层按现有代码风格决定，
但必须完整表达以下概念：

- 唯一、稳定的 validator entry ID。
- Python 模块路径。
- 模式身份和固定 argv 片段。
- 生命周期分类：
  - `active_contract`
  - `catalog_audit`
  - `historical_evidence`
  - `superseded`
  - `invalid`
- 验证层级：
  - `direct`
  - `catalog`
  - `full`
- 覆盖领域。
- 显式触发条件。
- 当前 CLI 所需输入。
- 真实语义资源需求。
- RuleBook 构建种类。
- 输出目录和紧凑 summary 契约。
- 替代关系或“尚无完整替代”的明确状态。
- 当前是否允许进入普通选择。
- 分类理由和已知限制。

registry 必须满足：

- 所有集合稳定排序并递归不可变。
- 规范 JSON 输出确定。
- fingerprint 由规范 JSON 计算。
- 外部字典、列表或子类容器修改不能改变已构造 registry。
- 未知字段、错误枚举、错误类型和相互矛盾的组合在构造边界被拒绝。
- registry 加载和查询不得导入其登记的 validator 模块。
- 命令以结构化 module/argv 表示，禁止保存 shell 命令字符串。

### 4.2 以“模块 + 模式”建立唯一身份

同一文件的不同运行模式必须是不同 entry。至少验证以下身份冲突会被拒绝：

- 两个 entry 使用同一个 entry ID。
- 两个 entry 使用同一模块和同一模式身份。
- 两个 entry 最终渲染为不可区分的命令，却声称是不同验证。
- 一个模式同时声明 direct 和 full。
- 一个 direct 模式声明会完整读取 TBGD 并构建完整 RuleBook。

同一模块的 fixture、source-only、catalog-startup 等不同模式可以并存，但每个
模式的分类、资源和触发条件必须独立。

### 4.3 分离生命周期分类、验证层级和资源成本

这三个维度不能合并成一个字符串：

- 生命周期分类回答“它现在是否仍是权威证据”。
- 验证层级回答“它应在 direct、catalog 还是 full 时运行”。
- 资源描述回答“它实际需要读取和构建什么”。

例如：

- P8-S2 fixture 是 `active_contract + direct + small_fixture_rulebook`。
- P8-S2 source-only 是 `catalog_audit + catalog + source_inventory`。
- P1 聚合是 `historical_evidence + full`。

registry 自检必须拒绝明显矛盾：

- historical/superseded/invalid 被标成普通 direct 默认项。
- catalog/full 项被标成 direct 默认项。
- 不读取 TBGD 的项目声称需要完整 lowering。
- 需要来源目录的项目没有声明 TBGD 输入。
- 声称产生紧凑 summary 的项目没有 summary 相对路径。
- replacement 指向不存在的 entry 或形成循环。

### 4.4 建立显式、确定性的选择请求

选择器只能使用调用者显式提供的信息，不读取 Git diff 自动猜测改动。

必须支持：

- 按一个或多个精确 entry ID 选择。
- 按一个或多个已登记 trigger 选择当前 direct 契约。
- 用 domain 进一步收窄已有选择。
- 指定输出根目录和必要的外部输入，以渲染可执行 argv。
- 只查看、描述某个 historical/catalog 项，不把它混入 direct。

选择语义必须固定：

1. 空选择请求被拒绝，禁止默认“全跑”。
2. 精确 ID 和 trigger 必须来自 registry；未知值直接 blocked。
3. trigger 选择只考虑 `active_contract + direct`。
4. domain 只允许收窄，不得单独作为“把该领域所有历史验证都选上”的入口。
5. direct 请求中出现 catalog/full/historical/superseded/invalid 精确 ID 时，整个
   请求 blocked，不得静默忽略后继续。
6. catalog dry-run 只能按精确 ID 请求，并要求显式 heavy-plan 确认；不能由普通
   trigger 自动带出。
7. 同一 entry 被多个条件命中时只出现一次。
8. 输入顺序变化不影响最终选择顺序、fingerprint 和 argv。
9. 依赖关系只能表达“解释本结果确实必需的验证依赖”，禁止把所有相关旧阶段
   都注册为依赖。

### 4.5 建立纯 dry-run CLI

新增统一 CLI，至少提供：

- 列出登记项及关键分类。
- 描述单个 entry。
- 根据显式请求执行 selection dry-run。
- 输出人可读摘要和机器可读 JSON。

`--dry-run` 是本阶段唯一允许的选择执行模式。它必须：

- 不调用任何 `run_validation`。
- 不 import 登记的 validator 模块。
- 不启动 subprocess。
- 不读取 TBGD 文件。
- 不构造 Canonical IR 或 RuleBook。
- 不创建每个 validator 的输出目录。
- 不写完整 registry 以外的大产物。
- 只在调用者显式要求机器可读输出文件时写一个紧凑 selection manifest。

manifest 至少包含：

- registry schema version 和 fingerprint。
- 规范化后的 selection request。
- selected entries。
- excluded entries及结构化原因。
- blocked issues。
- 每个选择项的分类、领域、trigger、资源需求和 argv。
- 未提供的必要 CLI 输入。
- 构建需求分组。
- `execution_performed=false`。
- `tbgd_read_count=0`。
- `lowering_build_count=0`。
- `rulebook_build_count=0`。
- selection fingerprint。

CLI 不得提供一个看似可用但能绕过 dry-run 的隐藏默认执行路径。

### 4.6 只表达共享构建需求，不提前实现共享构建

本阶段需要把构建需求分成至少以下类别：

```text
none
small_fixture_rulebook
source_inventory
full_lowering_rulebook
```

selection manifest 可把具有相同真实需求的项目放进同一“候选构建组”，供 VG-S6
后续设计共享执行。但本阶段必须明确：

- 分组不等于已经共享构建。
- 当前独立 validator 仍不能自动接收同一个 RuleBook。
- 不创建 lowering cache。
- 不序列化完整 Canonical IR 作为跨进程缓存。
- 不读取 `/tmp` 旧产物冒充当前构建。
- 不宣称完整 RuleBook 构建次数已经从多次降为一次。

manifest 中若出现共享组，必须同时输出当前 adapter 状态。尚不能共享时应诚实写
`not_implemented` 或等价结构化状态。

### 4.7 首批 registry 清单

首批只登记下表列出的运行模式。数量是本卡定义的初始覆盖边界，不是对整个
验证目录“已经治理完成”的宣称。

| Entry ID | 模块与模式 | 生命周期分类 | 层级 | 真实构建需求 |
|---|---|---|---|---|
| `vg.s1.committed_state_immutability.direct` | `validate_vg_s1_committed_state_immutability` | `active_contract` | `direct` | `none` |
| `vg.s2.committed_integrity_lifecycle.direct` | `validate_vg_s2_committed_integrity_lifecycle` | `active_contract` | `direct` | `small_fixture_rulebook` |
| `p7.s2.mutation_reducer_contract.direct` | `validate_p7_s2_mutation_reducer_contract` | `active_contract` | `direct` | `none` |
| `p7.s3.selected_graph_atomic_commit.direct` | `validate_p7_s3_selected_graph_atomic_commit` | `active_contract` | `direct` | `small_fixture_rulebook` |
| `p7.s15.rng_identity_replay.direct` | `validate_p7_s15_rng_identity_replay` | `active_contract` | `direct` | `none` |
| `p8.s1.equipment_type_contract.direct` | `validate_p8_s1_equipment_type_contract` | `active_contract` | `direct` | `small_fixture_rulebook` |
| `p8.s2.character_build.fixture` | P8-S2 `--fixture-only` | `active_contract` | `direct` | `small_fixture_rulebook` |
| `p8.s2.character_card_source.catalog` | P8-S2 `--character-card-source-only` | `catalog_audit` | `catalog` | `source_inventory` |
| `p8.s2.character_build.complete_catalog` | P8-S2 默认完整模式 | `catalog_audit` | `full` | `full_lowering_rulebook` |
| `p8.r1.summon_halo.runtime` | P8-R1 `--runtime-only` | `active_contract` | `direct` | `small_fixture_rulebook` |
| `p8.r1.summon_halo.source_catalog` | P8-R1 `--source-catalog-only` | `catalog_audit` | `catalog` | `source_inventory` |
| `p8.s8.light_cone.catalog_startup` | P8-S8 `--catalog-startup-only` | `catalog_audit` | `catalog` | `full_lowering_rulebook` |
| `p7.current_tree.shared_aggregate.history` | `validate_p7_current_tree_shared_regressions` | `historical_evidence` | `full` | `full_lowering_rulebook` |
| `p1.phase1.aggregate.history` | `validate_p1_9_phase1_aggregate` | `historical_evidence` | `full` | `full_lowering_rulebook` |
| `p2.status.aggregate.history` | `validate_p2_status_system_complete` | `historical_evidence` | `full` | `full_lowering_rulebook` |
| `p3.summon.aggregate.history` | `validate_p3_summon_assistant_servant_complete` | `historical_evidence` | `full` | `full_lowering_rulebook` |
| `v0.209.full_pipeline.history` | `validate_v0_209` | `historical_evidence` | `full` | `full_lowering_rulebook` |

每个 entry 的 domain、trigger、CLI 输入、summary 路径和分类理由必须根据当前文件
实际入口填写。不得从表中推断未核实的参数。

特别要求：

- P8-S1 必须记录现有 `--s0-summary` 验证产物输入，不能假装它不存在。
- P8-R1 runtime-only 必须区分“CLI 仍要求 tbgd-root”和“模式语义不读取 TBGD”。
- P8-S8 本阶段只登记 catalog-startup，不顺便登记其全部内部模式。
- P7 shared aggregate 必须记录旧 P2/P3 gap 门导致它不能成为当前 contract。
- P1/P2/P3 聚合和 v0.209 不得被赋予 current replacement，除非执行层能证明其
  全部仍有效谓词已有完整承接。本阶段预期为“尚无完整替代”。

### 4.8 文档和报告同步

实现完成时修改：

- `docs/AGENT_WORKFLOW_AND_VALIDATION.md`
  - 写明 registry/selection CLI 的真实命令入口；
  - 写明 direct、catalog、full、historical 的选择规则；
  - 写明普通执行卡只能引用 registry 中的 entry ID；
  - 写明未登记项必须先分类，不能直接加入默认回归。
- 新增 VG-S3 `ready_for_review` 报告。

报告必须区分：

- 已登记并经过 registry 自检的 entry。
- 已证明的 dry-run 行为。
- 仅完成需求分组、尚未实现共享构建的 catalog 项。
- 未登记的其余 validator。
- 未运行的 direct/catalog/full 验证。
- deferred 和 `not_proven`。

## 5. 本阶段只做

- 新增验证 registry 的类型化模型与首批静态登记数据。
- 新增纯选择逻辑和 dry-run CLI。
- 新增 registry/selection 聚焦验证器。
- 静态核对首批入口的 argparse 模式、summary 路径和构建调用。
- 更新验证工作流文档。
- 新增紧凑 `ready_for_review` 报告。

允许对首批 validator 做静态读取，但原则上不修改它们。若发现现有 CLI 无法被
结构化表达，应在报告中记录阻断并回到规划线程，不得顺手重写 validator。

## 6. 本阶段明确不做

- 不改 `core/`、`systems/`、`rules/`、`tbgd/`、`scenarios/`、`equipment/`、
  `builds/` 或 UI。
- 不改任何战斗规则、状态完整性、事件 closure 或 replay 语义。
- 不执行 registry 中的 validator。
- 不新增 direct runner 或通用 subprocess executor。
- 不实现完整 lowering、RuleBook 或 source inventory 缓存。
- 不让不同进程复用序列化后的完整 Canonical IR。
- 不重写、删除或批量迁移现有 validator。
- 不登记全部验证目录。
- 不按 Git diff、文件名或 import graph 自动猜测验证依赖。
- 不把 domain 当成默认“选出所有相关脚本”的入口。
- 不修复 P7 shared aggregate 中的旧 gap 口径。
- 不修改 P8 checklist 或其他阶段 checklist。
- 不运行 P1-P8 聚合、P8-S8 catalog、`validate_v0_209` 或完整 TBGD lowering。
- 不新增第三方依赖。
- 不提交 Git。
- 不开始 VG-S4。

## 7. 架构与质量红线

### 7.1 registry 只属于工具治理层

Combat Core、Canonical IR、数据卡、构筑装配器和 scenario 不得 import registry。
registry 不能进入 battle snapshot、settlement、replay 或 runtime fingerprint。

### 7.2 不能把验证结论变成生产规则

registry 中的 domain、trigger、分类和资源信息只用于选择验证。它们不能决定：

- 哪个战斗动作可执行；
- 哪个状态、光环或召唤物生效；
- 哪条 Canonical IR 节点可 lowering；
- 哪个来源被认为真实；
- runtime 如何结算。

### 7.3 不允许 shell 注入面

命令必须由 Python module、固定 argv 和类型化外部输入组成，最终输出 argv 数组。
禁止：

- `shell=True`；
- 保存整段 shell 命令；
- 解释管道、重定向、命令替换或通配符；
- 把用户提供的任意字符串当作 module 名或 flag 名。

### 7.4 不允许 registry 自证

聚焦验证不能仅遍历生产 registry 后断言“每项都有字段”。必须有独立预期矩阵，
核对本卡定义的首批 ID、分类、模式和关键资源边界。负例必须通过公开构造/选择
边界注入，而不是复制生产校验函数。

### 7.5 不允许为通过旧验证修改生产代码

若静态核对发现旧脚本和当前语义不一致：

- 先分类为 historical、superseded 或 invalid。
- 记录仍有价值但未迁移的谓词。
- 不要求当前生产恢复旧 gap。
- 不在 S3 修复该 validator。

## 8. 目标与证据映射

| 目标 | 通过条件 | 主要证据 |
|---|---|---|
| 登记粒度正确 | 同文件不同模式是独立 entry，重复模式身份被拒绝 | registry matrix、重复身份负例 |
| 首批覆盖完整 | 本卡列出的全部 entry 都存在且关键分类与实际 CLI 一致 | 独立 expected inventory |
| 分类可用 | 生命周期、层级、资源需求彼此独立且无矛盾 | classification matrix |
| direct 安全 | direct trigger/ID 选择只产生 active direct 项 | selection matrix |
| 历史隔离 | P1/P2/P3/P7 aggregate/v0.209 只能描述，不能进入 direct | historical negative matrix |
| 模式成本诚实 | P8-S2、P8-R1、P8-S8 的模式资源分别登记 | mode/resource matrix |
| dry-run 纯净 | 零 import validator、零 subprocess、零 TBGD、零 RuleBook、零执行输出目录 | side-effect probe |
| 选择确定 | 输入顺序变化不改变选择、argv 和 fingerprint | permutation oracle |
| 选择闭合 | 未知、空请求、缺输入、冲突分类均 blocked | request negative matrix |
| 命令安全 | 只输出 argv，不解释 shell | command rendering negatives |
| 共享边界诚实 | 只生成候选构建组，不宣称缓存或复用已经实现 | build requirement matrix |
| 文档可执行 | 工作流包含唯一真实命令入口和选择规则 | docs static check |
| 生产零变化 | 战斗模块和运行行为均未修改 | Git scope audit |

## 9. 必须成立的结构化谓词

聚焦 summary 至少输出以下谓词，并且全部为 `true`：

```text
registry_entry_identity_is_module_plus_mode=true
registry_entries_are_unique=true
registry_is_recursively_immutable=true
registry_json_and_fingerprint_are_deterministic=true
registry_load_imports_no_validator_modules=true
first_batch_inventory_matches_independent_oracle=true
lifecycle_tier_and_resource_dimensions_are_separate=true
mode_specific_resource_classification_is_correct=true
direct_selection_contains_only_active_direct_entries=true
catalog_requires_exact_explicit_heavy_plan=true
historical_entries_are_not_current_selectable=true
empty_unknown_and_ambiguous_requests_fail_closed=true
domain_only_request_cannot_expand_to_all_validators=true
missing_required_cli_inputs_are_reported=true
dry_run_executes_no_validation=true
dry_run_spawns_no_subprocess=true
dry_run_reads_no_tbgd=true
dry_run_builds_no_rulebook=true
dry_run_creates_no_validator_output_directories=true
selection_order_and_fingerprint_are_deterministic=true
rendered_commands_are_structured_argv=true
shared_build_requirement_is_only_a_plan=true
full_lowering_build_count=0
production_behavior_changed=false
```

布尔谓词不得用字符串 `"true"` 冒充。计数必须使用数值。

## 10. 必须覆盖的负例

聚焦验证至少覆盖：

1. 重复 entry ID。
2. 重复模块 + 模式身份。
3. 未知生命周期分类。
4. 未知验证层级。
5. 未知 domain 或 trigger。
6. active direct 同时声明完整 lowering。
7. historical 被标成普通 selectable。
8. catalog/full 被标成 direct 默认项。
9. 来源目录需求缺少 TBGD 语义输入。
10. dangling replacement。
11. replacement cycle。
12. 空 selection request。
13. 未登记 entry ID。
14. 未登记 trigger。
15. domain-only 请求。
16. direct 请求精确包含 catalog 项。
17. direct 请求精确包含 historical 项。
18. catalog 请求未给显式 heavy-plan 确认。
19. 必需 CLI 输入缺失。
20. 两个选择项渲染到同一输出目录。
21. 输出路径试图逃离调用者指定的 output root。
22. 用户输入试图改变 module 或插入新 flag。
23. shell 字符串或 `shell=True` 等价命令表示。
24. 输入顺序变化导致结果顺序或 fingerprint 变化。
25. dry-run 触发 validator import。
26. dry-run 调用 `run_validation` 或 subprocess。
27. dry-run 读取 TBGD 或构造 RuleBook。
28. 候选构建组被标成“已经共享构建”。
29. historical gap 被写入 current contract predicate。
30. registry 原始容器修改后已构造对象发生变化。

所有 blocked 请求必须：

- 输出结构化原因。
- 不产生“部分可执行计划”。
- 不创建 validator 输出目录。
- 不导入或执行已选中的其他项目。

## 11. 拟修改文件

主要新增：

- `simulator_v8_clean_core/tools/validation_registry.py`
  - 类型化 registry 模型；
  - 首批 entry；
  - schema 自检、规范 JSON 和 fingerprint。
- `simulator_v8_clean_core/tools/validation_selection.py`
  - 纯 selection request；
  - direct/catalog 选择规则；
  - 构建需求分组；
  - 结构化 manifest。
- `simulator_v8_clean_core/tools/select_validations.py`
  - list、describe 和 `--dry-run` CLI；
  - 只负责输入解析和输出，不实现 validator runner。
- `simulator_v8_clean_core/tools/validate_vg_s3_validator_registry_selection.py`
  - 独立首批 oracle；
  - 正负例和 side-effect probe。
- `live_validation_reports/v8_vg_s3_validator_registry_selection_ready_for_review.md`

允许最小修改：

- `simulator_v8_clean_core/docs/AGENT_WORKFLOW_AND_VALIDATION.md`

原则上不修改现有 validator。若实际代码风格更适合在 `tools/validation/` 下建立
小包，可以调整文件组织，但职责和范围不能改变，也不能引入生产层依赖。

## 12. 实施顺序

执行线程必须按以下顺序推进，不得先写报告或先跑历史验证：

1. 只读核对基线、工作区和本卡首批入口。
2. 固化首批独立事实矩阵，发现本卡与实际代码冲突时立即暂停并反馈。
3. 实现类型化 registry 和自检。
4. 实现纯 selection 与 deterministic manifest。
5. 实现 list/describe/dry-run CLI。
6. 实现聚焦验证的正例、负例和 side-effect probe。
7. 更新工作流文档。
8. 串行运行本卡规定的轻量验证。
9. 编写 `ready_for_review` 报告并做 Git scope audit。

如果在第 2 步发现某个首批 entry 的真实模式或资源需求与本卡不同，可以修正
“事实字段”，但不得自行扩大首批目录、增加执行 runner、改变 dry-run 边界或
进入 VG-S4。

## 13. 验证策略

### 13.1 必跑 fast

```bash
PYTHONPYCACHEPREFIX=/tmp/hsr_v8_vg_s3_pycache \
  python3 -m compileall -q simulator_v8_clean_core

PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_vg_s3_validator_registry_selection \
  --output-dir /tmp/hsr_v8_vg_s3_validator_registry_selection

git diff --check
```

### 13.2 必跑 CLI dry-run

至少证明：

- list 和 describe 能读取 registry。
- 按精确 direct ID 选择能生成紧凑 manifest。
- 按 direct trigger 选择不会带出 catalog/history。
- 对 P8-S2 fixture 的 dry-run 保留 `--fixture-only`。
- 对 P8-R1 runtime 的 dry-run 保留 `--runtime-only`，并诚实显示 CLI 参数与真实
  TBGD 读取需求的差异。
- 对 P8-S8 catalog 的显式 heavy dry-run 只生成计划，不执行。
- 对 P7 shared aggregate 的 direct 请求结构化失败。

具体命令以实现后的 CLI `--help` 为准，并必须写入工作流文档和报告。

### 13.3 不需要运行的 direct 回归

本阶段没有修改战斗生产代码，也不执行 registry，因此不需要为了验收重新运行
VG-S1、VG-S2、P7-S2、P7-S3、P7-S15、P8-S1、P8-S2 fixture 或 P8-R1 runtime。

聚焦验证应通过静态入口核对和 side-effect probe 证明命令登记正确。验收线程若
发现 registry 与真实 CLI 不一致，可以定向运行单个轻量入口，但这不是执行线程
的默认必跑项。

### 13.4 明确不运行

- 任何 registry entry 的实际验证。
- P1、P2、P3 或 P7 shared aggregate。
- P8-S2 source/default 模式。
- P8-R1 source-catalog/default 模式。
- P8-S8 catalog-startup 或完整模式。
- `validate_v0_209`。
- 完整 TBGD discovery/lowering。
- 完整 Canonical IR、RuleBook、coverage、fidelity 或 transition dump。
- P1-P8 任意阶段聚合。

## 14. 资源限制

- 所有验证串行运行。
- 不启动并行 worker。
- 不读取 `turnbasedgamedata-main`。
- 完整 lowering build count 必须为 0。
- 完整 RuleBook build count 必须为 0。
- 聚焦验证只允许小型内存 registry fixture。
- 默认产物只包含 summary、entry matrix、selection matrix 和负例矩阵。
- 不复制全部 validator 源码或完整 registry 到多份报告。
- 所有临时产物写入 `/tmp`。
- 不生成 `.pyc`、`__pycache__` 或仓库内验证输出。
- 报告必须记录聚焦验证耗时、输出总字节数和实际资源边界，但单次观察不能写成
  跨机器固定性能门槛。

## 15. Gap、deferred 与 not-proven

### 15.1 本阶段允许保留

- 首批清单以外的 validator 仍未登记。
- catalog/full entry 仅完成分类与 dry-run 计划。
- 完整 lowering/RuleBook 共享执行 adapter 尚未实现。
- source inventory 和完整 RuleBook 缓存尚未实现。
- 旧 validator 中仍有效谓词尚未逐项迁移。
- Git diff 到 trigger 的自动映射尚未实现，并且当前没有计划自动实现。
- P8-R1 runtime-only 仍保留现有 CLI 的 tbgd-root 参数。
- P8-S1 仍需要现有 S0 summary 验证产物输入。

### 15.2 必须记为 not-proven

- 未运行的所有 direct validator。
- 未运行的所有 catalog/full validator。
- 候选构建组是否真的可以共享同一个生产 RuleBook。
- 未登记验证器的当前有效性。
- 历史聚合中每个旧谓词是否已有新承接。
- VG-S6 的峰值内存、IO、恢复和缓存收益。

### 15.3 不允许用 gap 豁免

以下任一项未成立，本阶段不得提交 `ready_for_review`：

- 首批 entry 缺失。
- 模式级身份没有建立。
- direct 能带出 catalog/history。
- dry-run 会执行、导入 validator、读取 TBGD 或构建 RuleBook。
- 未知请求会降级成默认全跑。
- historical gap 仍可成为 current predicate。
- registry 声称共享构建已经实现。

## 16. 交付物与报告要求

执行线程最终只提交：

- registry、selection 和 CLI 实现。
- 聚焦验证器。
- 工作流文档更新。
- `/tmp` 下的轻量 evidence。
- `v8_vg_s3_validator_registry_selection_ready_for_review.md`。
- 状态 `ready_for_review`。

报告至少说明：

- 实际基线和工作区范围。
- 首批 entry 清单及实际分类。
- P8 多模式登记结果。
- direct/catalog/history 选择矩阵。
- dry-run side-effect 计数。
- 构建需求分组及其未实现状态。
- 正负例结果。
- 实际运行命令。
- 明确未运行的验证。
- deferred、gap 和 `not_proven`。
- Git scope audit。

执行线程不得：

- 把本卡 checklist 改为完成。
- 宣称 VG-S3 `done`、`accepted` 或整个验证治理已完成。
- 提交 Git。
- 开始 VG-S4。

## 17. 唯一执行清单（仅验收线程可勾）

- [x] registry 以“模块 + 运行模式”为登记单位，同文件不同成本模式已拆开。
- [x] 首批 17 个 entry 已全部登记，并与当前 argparse、summary 和构建事实一致。
- [x] entry 的生命周期分类、验证层级、domain、trigger、CLI 输入和真实资源需求均为类型化字段。
- [x] registry 构造边界已拒绝重复身份、未知类型、矛盾资源、dangling/cyclic replacement。
- [x] registry 递归不可变，规范 JSON 和 fingerprint 确定且不受外部容器修改影响。
- [x] registry 加载、list、describe 和 selection 不会导入登记 validator。
- [x] 空请求、未知 ID/trigger/domain、缺输入和歧义请求均 fail-closed。
- [x] direct 选择只包含 `active_contract + direct`，不会夹带 catalog、full 或历史项。
- [x] catalog 只能按精确 ID 和显式 heavy-plan 确认进入 dry-run。
- [x] domain 只能收窄已有请求，不能单独扩大为领域全量验证。
- [x] dry-run 只输出紧凑 manifest，零 validation、零 subprocess、零 TBGD、零 RuleBook。
- [x] 命令只以 module/argv 渲染，不存在 shell 字符串或用户控制 flag/module 的入口。
- [x] 构建需求已分组，但 manifest 和报告均未伪称共享 lowering/RuleBook 已实现。
- [x] P7 shared、P1/P2/P3 aggregate 和 v0.209 已隔离为历史证据，旧 gap 不再是 current predicate。
- [x] 聚焦验证使用独立首批 oracle，并覆盖本卡要求的结构、选择和 side-effect 负例。
- [x] `AGENT_WORKFLOW_AND_VALIDATION.md` 已写入真实 CLI 入口和后续执行卡引用规则。
- [x] 必跑 fast 与 CLI dry-run 全部通过，完整 lowering/RuleBook build count 均为 0。
- [x] 未修改战斗生产代码、旧 validator、P8 checklist 或无关 UI，未运行 catalog/full/历史聚合。
- [x] `ready_for_review` 报告完整区分已证明、deferred、gap 与 not-proven。
