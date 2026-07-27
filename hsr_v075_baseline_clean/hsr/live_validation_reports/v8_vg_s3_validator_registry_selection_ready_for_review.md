# VG-S3 Validator Registry 与选择入口

状态：`ready_for_review`

本报告只记录
`VG-S3_VALIDATOR_REGISTRY_AND_SELECTION_ENTRY.md` 的实现与执行证据，不代表
`accepted`、不勾执行卡 checklist、不提交 Git，也不进入 VG-S4。

## 基线与范围

- 实际基线：`d29b34bc3f72b3ff605a5fca70a6c82442a1adad`。
- 工作目录：`hsr_v075_baseline_clean/hsr/`。
- 只新增 registry、selection、dry-run CLI、聚焦验证器和本报告。
- 只修改 `docs/AGENT_WORKFLOW_AND_VALIDATION.md`。
- 未修改战斗生产代码、现有 validator 或 UI。
- registry schema：`vg-s3.validator-registry.v2`。
- registry fingerprint：
  `3cc1badb534bfb423aafb7acc2c68e615f80cd959ee318651fabc6b66fb22d97`。

## 本轮验收阻断修复

### 1. 资源维度与真实调用链

资源模型不再把“读取来源”和“构造 RuleBook”绑定成互斥分类，而是分别记录：

- `reads_tbgd`
- `full_lowering_required`
- `rulebook_build_kind`
- `source_identity`
- `builder_identity`
- `artifact_identity`
- 可选的 `shared_build_key`

对多模式入口执行了静态 AST 调用链核对，关键观察如下：

| Entry ID | 真实调用观察 | Registry 事实 |
|---|---|---|
| `p8.s2.character_build.fixture` | `RuleBook=10`、`TBGDLowering=0` | small fixture |
| `p8.s2.character_card_source.catalog` | `RuleBook=2`、角色卡 builder=1、动作定义 builder=1、`TBGDLowering=0` | 读取角色来源并构造 focused source RuleBook |
| `p8.s2.character_build.complete_catalog` | `RuleBook=1`、`TBGDLowering=1` | full lowering |
| `p8.r1.summon_halo.runtime` | `RuleBook=1`、光锥 catalog builder=0 | small fixture |
| `p8.r1.summon_halo.source_catalog` | `RuleBook=0`、光锥 catalog builder=1 | 读取光锥来源，不构造 RuleBook |
| `p8.s8.light_cone.catalog_startup` | focused bundle=1、`RuleBook=1`、`TBGDLowering=2` | 读取来源、focused RuleBook、完整 lowering |

这里的数字来自对现有 validator 入口及其本地调用路径的独立静态遍历，不来自
registry 自身。

### 2. 候选构建分组

候选组不再按粗粒度 `build_requirement` 合并：

- 没有构建需求的 entry 可进入无构建组。
- 只有显式使用同一个 `shared_build_key`，且来源、构建器、产物和资源维度完全
  相同，才可进入同一候选构建组。
- 未证明可共享的构建默认按 entry 分组。
- 所有候选组仍是 `grouping_only=true`、
  `adapter_status=not_implemented`、`shared_build_executed=false`。

独立双来源 dry-run 同时选择 P8-S2 角色来源与 P8-R1 光锥来源，结果为两个组：

| Entry | source | builder | artifact | RuleBook |
|---|---|---|---|---|
| P8-S2 source | `tbgd.character_card_tables` | `build_character_card_ir+build_character_action_definition_ir` | `character_card_ir+focused_character_rulebooks` | `focused_source` |
| P8-R1 source | `tbgd.light_cone_catalog_and_ability_files` | `build_light_cone_catalog` | `light_cone_catalog+source_hash_matrix` | `none` |

### 3. 真实 dry-run 副作用探针

聚焦验证器安装 validator import/call、RuleBook 构造、`TBGDLowering.build`、
subprocess、文件读写和输出目录哨兵，再通过真实 CLI `main` 执行 dry-run。
计数来自哨兵实际观察，不再初始化后直接当作结论。下表只描述被测 dry-run；
聚焦验证器随后另行启动只读 Git 命令完成范围审计。

| 指标 | 实测 |
|---|---:|
| validator import | 0 |
| validation call | 0 |
| production import | 0 |
| subprocess | 0 |
| file read | 0 |
| file write | 0 |
| TBGD read | 0 |
| RuleBook build | 0 |
| full lowering build | 0 |
| validator output directory | 0 |
| parallel worker | 0 |

36 个负例均核对精确结构化错误码；blocked selection 要求实际错误码集合严格等于
单个预期错误码，同时核对 `selected_entries=0` 和空构建组，避免额外 blocker
夹带与部分计划泄漏。

summary 路径证据只接受两种精确形式：`write_json` 路径参数中的完整文件名字面量，
或 VG-S2 由唯一局部赋值和 dict comprehension 可追踪得到的完整路径。两个互不
关联的字符串即使可手工拼成同名路径，也会被负例拒绝。

### 4. 不可变边界与可读性

registry、request、selected plan、candidate build group 和 manifest 在构造时均复制
并冻结外部容器。`MissingInput` 与 `ExcludedEntry` 也逐字段执行严格类型校验；
列表等可变对象不能冒充字符串进入已构造结果。对应两个负例均精确返回
`invalid_type`。

当前四个工具文件合计 4,082 行、138,262 字节；聚焦验证器为 1,871 行、
61,539 字节。四文件最长代码行 94 字符。当前实现通过具名 helper、紧凑独立
oracle 和精确错误码复用消除逐项展开与超长压缩断言；体积数字只作审查信息，
不作为通过谓词或阈值规避依据。

### 5. 生产代码范围谓词

`production_behavior_changed` 不再由工具导入边界反推。聚焦验证器实际执行
`git diff HEAD` 与未跟踪非忽略文件审计，共观察 11 个 changed path；其中
`simulator_v8_clean_core` 下、`tools/` 之外的 Python 生产路径为 0。因此：

- `git_scope_audit.audit_available=true`
- `git_scope_audit.ok=true`
- `git_scope_audit.production_paths=[]`
- `production_behavior_changed=false`

新工具的禁止导入检查仍作为独立 static boundary 保留，不再冒充 Git 写集合证据。

## 首批登记与选择结果

- 首批 entry：17。
- `active_contract + direct`：8。
- `catalog_audit`：4。
- `historical_evidence + full`：5。
- entry oracle：17/17。
- selection 正例：11。
- 精确原因负例：36/36。
- 执行卡要求的 24 个聚焦谓词全部成立，其中
  `full_lowering_build_count=0`、`production_behavior_changed=false`。

selection 只接受显式 entry ID 或已登记 trigger；domain 只能收窄。空请求、未知
请求、domain-only、direct 混入 catalog/history、缺输入、路径逃逸、输出冲突和
命令结构覆盖均整体 blocked。manifest 只包含结构化 `module` 与 `argv`，不包含
shell 命令。

## 串行验证证据

按执行卡顺序串行运行：

```bash
PYTHONPYCACHEPREFIX=/tmp/hsr_v8_vg_s3_pycache \
  python3 -m compileall -q simulator_v8_clean_core

PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_vg_s3_validator_registry_selection \
  --output-dir /tmp/hsr_v8_vg_s3_validator_registry_selection

git diff --check
```

结果：

- `compileall`：exit 0。
- VG-S3 聚焦验证：exit 0，`ok=true`、`entry_count=17`、
  `negative_case_count=36`、`full_lowering_build_count=0`。
- `git diff --check`：exit 0。

随后串行执行：

1. `list`
2. `describe p8.r1.summon_halo.runtime --json`
3. 精确 VG-S1 direct dry-run
4. `lifecycle_contract_changed` trigger dry-run
5. P8-S2 fixture dry-run
6. P8-R1 runtime dry-run
7. P8-S8 catalog heavy dry-run
8. P8-S2 source + P8-R1 source 双 entry catalog dry-run
9. P7 shared historical 的 direct 负例

前八项均按预期 exit 0；第九项按契约 exit 2，并精确返回
`direct_entry_not_current_selectable`，且 `selected=0`。

所有 CLI 命令只生成调用者显式请求的七个 manifest。七个 validator output root
均不存在，未执行任何登记项。

## 资源与产物

- 聚焦验证内部观察耗时：`0.5406128710001212s`；仅为本机单次观察，不是性能
  门槛。
- 四个聚焦 evidence 总字节数：19,872。
- 七个 CLI manifest 总字节数：27,099。
- 聚焦 evidence：
  - `/tmp/hsr_v8_vg_s3_validator_registry_selection/validation_summary_vg_s3_validator_registry_selection.json`
  - `/tmp/hsr_v8_vg_s3_validator_registry_selection/vg_s3_registry_entry_matrix.json`
  - `/tmp/hsr_v8_vg_s3_validator_registry_selection/vg_s3_selection_matrix.json`
  - `/tmp/hsr_v8_vg_s3_validator_registry_selection/vg_s3_negative_matrix.json`
- 双来源分组 evidence：
  `/tmp/hsr_v8_vg_s3_cli_source_pair.json`。
- 本轮没有生成仓库内验证输出，也没有为新增 VG-S3 模块生成 `.pyc` 或
  `__pycache__`；工作区原有的受忽略 Python 缓存未修改、未纳入本卡。

## 明确未运行

- 未运行任何 registry entry。
- 未运行任何 direct validator。
- 未运行任何 catalog/full validator。
- 未读取 `turnbasedgamedata-main`。
- 未构建完整 Canonical IR 或生产 RuleBook。
- 未运行 P7 shared、P1/P2/P3 aggregate 或 v0.209。

## Deferred、gap 与 not-proven

允许保留：

- 首批 17 项以外的 validator 尚未登记。
- catalog/full 只完成分类和 dry-run 计划。
- 共享 source inventory、lowering、RuleBook adapter 与缓存尚未实现。
- P8-R1 runtime-only 仍保留现有 CLI 的 `tbgd-root` 参数。
- P8-S1 仍要求现有 S0 summary 验证产物输入。

`not_proven`：

- 所有未运行 direct validator 的当前运行结果。
- 所有未运行 catalog/full validator 的当前运行结果。
- 未显式声明相同 `shared_build_key` 的候选是否可安全共享构建。
- 未登记 validator 的当前有效性。
- 历史聚合中每个旧谓词是否已有完整新承接。
- VG-S6 的峰值内存、IO、恢复和缓存收益。

当前没有用 gap 豁免本卡必须成立的 registry、selection 或 dry-run 谓词。

## Git scope audit

本卡写集合：

- `simulator_v8_clean_core/tools/validation_registry.py`
- `simulator_v8_clean_core/tools/validation_selection.py`
- `simulator_v8_clean_core/tools/select_validations.py`
- `simulator_v8_clean_core/tools/validate_vg_s3_validator_registry_selection.py`
- `simulator_v8_clean_core/docs/AGENT_WORKFLOW_AND_VALIDATION.md`
- `live_validation_reports/v8_vg_s3_validator_registry_selection_ready_for_review.md`

开始实施前已存在并保留的无关工作区状态：

- `CODEX_HANDOFF.md`
- `simulator_v8_clean_core/VALIDATION_GOVERNANCE_AND_STATE_INTEGRITY_PLAN.md`
- 本执行卡文件
- `../../hsr_battle_sim_ui_v10_toughness_fixed.html`
- `simulator_v8_ui/UI_V2_WORKBENCH_TASK_PLAN.md`

未修改执行卡 checklist，未提交 Git，未进入后续阶段。
