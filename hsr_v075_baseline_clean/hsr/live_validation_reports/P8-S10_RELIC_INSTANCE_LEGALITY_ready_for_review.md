# P8-S10 遗器实例合法性 ready_for_review

## 状态

- 阶段：`P8-S10`
- 结论：`ready_for_review`
- 基线检查点：`086e4b17d7c60edcb00f139784afde7b38aa7250`
- Checklist：未勾选
- Git 提交：未创建
- 后续阶段：未进入 `P8-S11`

## 生产改动

1. `equipment/models.py`
   - 将 `RelicInstanceInput.selected_slot_type` 原子替换为类型化
     `slot_key: EquipmentDefinitionKey`。
   - 实例结构覆盖实例 ID、模板、槽位、强化等级、主词条 key 和副词条
     roll；容器递归冻结并按结构 key 规范排序。
   - 新增稳定 `instance_fingerprint`，严格 JSON exact-field codec 会拒绝损坏
     fingerprint、旧无标记 payload 和 UI 扩展字段。
   - 构筑 fingerprint 覆盖所有结构选择并排除 `identity_labels`。
   - 新增 `RelicAssemblySelection` 与
     `relic_affix_validation_deferred_to_s11_s12` 类型化 blocker；装配结果 codec、
     fingerprint 和不变量同步覆盖遗器选择。
   - 正式 `RelicAssemblySelection` 不变量只接受 `BASIC` 模板；`CUSTOM` 不可进入
     正式选择结果。

2. `builds/equipment_assembler.py`
   - 删除 S4 的 `p8_s4_relic_instances_not_admitted` 通用 blocker。
   - 使用 RuleBook 精确解析模板和模板声明的 slot；正式玩家构筑只允许
     `BASIC`。S9 目录继续保留来源中的 `CUSTOM` 定义，但任何 `CUSTOM` 实例都由
     S10 装配边界以
     `relic_template_mode_not_admitted:CUSTOM` 精确拒绝，不生成、不映射为普通模板。
   - 校验发布状态、unknown 模式、`0..max_level`、template-slot 一致性、
     单构筑实例身份和槽位唯一性。
   - unknown、blocked、未发布、错槽、越级、重复槽位、重复实例和冲突 payload
     均在生产装配边界 fail-closed；blocked 结果的 selection、贡献、机制、
     blocker 和 ledger 正式通道全部为空。
   - 结构合法的非空遗器可 `assembled`，但在 S11/S12 完成词条合法性前保持
     `battle_admission_status=blocked`，且不产生遗器属性、套装或动态机制。
   - 队伍唯一性统一覆盖光锥与遗器；同 ID 同 fingerprint 报复用，同 ID 不同
     fingerprint 报身份冲突。

3. `scenarios/identity.py`
   - 移除 S4 身份层的全遗器拒绝。
   - 队伍占用检查仍在正式角色装配和任何 `UnitState` 创建之前执行；合法骨架由
     正式角色装备准入继续检查，并因 deferred affix blocker 在状态构建前拒绝。

4. 导出与调用点迁移
   - `equipment/__init__.py` 导出 `RelicAssemblySelection` 和
     `RelicAffixValidationStatus`。
   - `tools/validate_p8_s1_equipment_type_contract.py` 的两个直接
     `RelicInstanceInput` 构造点改用 S9 slot definition key，并更新 blocked
     结果空通道断言。
   - CodeGraph 与字面调用点复核显示：基线内没有需要迁移的 S2/S4
     `RelicInstanceInput` 直接构造点；新增构造仅位于本阶段验证器。
   - `EquipmentBuildInput.from_json` 递归使用新 codec；不提供旧
     `selected_slot_type` 兼容层。
   - 既有 `EquipmentAssemblyResult` 构造点通过默认空 `relic_selections`
     保持现行光锥语义；角色装配器继续消费正式装备结果，无新增 runtime
     遗器规则。
   - `validate_equipment_instance_uniqueness` 的既有 S4 光锥调用保持有效，
     scenario 身份调用扩展到遗器，本阶段验证器新增团队正负例调用。

5. 验收差量
   - `CUSTOM` 由原正例改为拒绝负例，并同时核对精确诊断以及遗器选择、静态贡献、
     动态机制、激活结果、准入 blocker、来源账本六类正式通道为空。
   - UNKNOWN 合成模板不再复用真实 `RelicConfig` 行的 TBGD 来源；改用
     `source_kind=validation_fixture`、路径
     `validation/p8_s10/fixtures/RelicConfig.UNKNOWN.json`、自洽 fixture identity
     和基于路径及完整 payload 计算的独立 fingerprint。
   - UNKNOWN 同时核对 RuleBook 和正式装配边界的规范诊断
     `equipment_definition_not_lowered`、fixture 诊断来源以及所有正式通道为空，
     不以单独检查 `assembly_status=blocked` 代替失败路径验证。
   - 验证汇总删除虚假的 `selected_character_count`；保留
     `team_occupancy_case_count=3`，其含义仅为三个队伍占用案例，不代表选择了三个
     角色。

## 验收谓词

当前 16 项验收谓词为：

```text
empty_relic_build_valid
partial_relic_build_valid
six_distinct_slots_valid
slot_identity_source_driven
wrong_slot_rejected
duplicate_slot_rejected
unknown_template_rejected
level_bounds_enforced
unknown_mode_rejected
custom_mode_excluded
team_duplicate_instance_rejected
same_identity_conflicting_payload_rejected
invalid_relic_contributes_nothing
affix_validation_not_masquerading_as_complete
instance_fingerprint_stable
legacy_all_relics_blocker_absent
```

其中 15 项未受本轮差量影响，沿用第三次主验证的通过证据；被替换的
`custom_mode_excluded=true` 由本轮 level/mode 聚焦切片直接证明。UNKNOWN
fixture 的来源与精确失败路径也由同一切片及独立轻量探针补证。目录证据仍为
726 个模板、6 个来源槽位、6 个 `CUSTOM` 模板；这 6 个 `CUSTOM` 只保留在
来源目录中，正式玩家构筑全部排除。

## 验证记录

### 主验证三次运行

| 次数 | 原因与结果 | 墙钟 | 峰值 RSS | 退出码 |
|---|---|---:|---:|---:|
| 1 | 诊断运行；原 16 项谓词通过 | 0.55 s | 71,676 KiB | 0 |
| 2 | 最终运行；新增 blocked-template 负例期待了验证专用 reason，但生产 RuleBook 正确返回规范 `equipment_definition_not_lowered`，装配仍 fail-closed 且正式通道为空 | 0.51 s | 71,636 KiB | 1 |
| 3 | 用户明确授权的唯一额外运行；修正负例 reason 断言，未放宽生产契约；16/16 通过 | 0.52 s | 71,296 KiB | 0 |

本轮验收差量没有第四次运行完整主验证。上表第三次通过发生在谓词替换前；
本轮只用获准的聚焦切片证明新的 `custom_mode_excluded` 和修正后的 UNKNOWN
fixture，不把聚焦结果伪装成第四次主验证。

最终命令：

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v -o /tmp/hsr_v8_p8_s10_time_v.txt timeout --signal=TERM 5m python3 -B -m simulator_v8_clean_core.tools.validate_p8_s10_relic_instance_legality --tbgd-root ../../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s10_relic_instance_legality
```

### 本轮验收差量验证

| 验证 | 结果 | 墙钟 | 峰值 RSS |
|---|---|---:|---:|
| `compileall` | 通过；bytecode 定向到 `/tmp` | 0.95 s | 55,920 KiB |
| BASIC/CUSTOM/UNKNOWN level/mode 聚焦切片 | 通过；3/3 checks 为 `true`，S9 遗器窄目录构建 1 次，完整 lowering 0 次 | 0.54 s | 72,404 KiB |
| UNKNOWN fixture 与空正式通道轻量探针 | 通过；8/8 checks 为 `true`，TBGD 读取 0 次，完整 lowering 0 次 | 0.32 s | 64,176 KiB |

三条计量命令墙钟合计 1.81 s，本轮峰值 72,404 KiB。`git diff --check`
在报告更新后执行；未运行完整主验证、S9 主验证、scenario direct、历史阶段验证或
任何聚合。

### 此前已有 Fast 与 direct（本轮未重跑）

- `compileall`：因场景夹具补正前后各执行一次，两次均通过。
- codec direct：通过，0.30 s，64,112 KiB；TBGD 读取 0 次。
- scenario admission direct：首个夹具因空 route 被正式 loader 正确拒绝；仅补入
  最小合法 kernel 敌方动作后通过，最终 0.30 s、64,136 KiB、TBGD 读取 0 次。
  正例身份无错误，状态构建直接返回
  `character_build_not_admitted_for_battle; equipment_build_not_admitted_for_battle`；
  未返回 `BattleState`。
- `git diff --check`：通过。
- 未运行 S9、历史阶段完整验证器或任何聚合。

三次主验证与两个 direct 的 `/usr/bin/time` 墙钟合计 2.18 s；全程最高峰值
71,676 KiB，均低于 5 分钟 / 768 MiB 单次上限。保留的三次主验证与两个 direct
产物合计 1,087,972 bytes，低于 3 MiB 上限。

## Deferred

- S11/S12：主词条所属池与数值、副词条所属池、数量、roll 历史及升级合法性。
- 后续阶段：套装计数、套装档位选择、遗器静态属性贡献和动态机制。
- 本阶段没有计算 affix、套装、属性贡献或机制，没有把 deferred 写成 executable，
  也没有构建战斗状态。

## 工作区隔离

以下既有未跟踪文件未读取、未修改，也未纳入本阶段：

- `hsr_battle_sim_ui_v10_toughness_fixed.html`
- `hsr_v075_baseline_clean/hsr/simulator_v8_ui/UI_V2_WORKBENCH_TASK_PLAN.md`
