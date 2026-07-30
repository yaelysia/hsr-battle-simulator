# P8-S10 六槽遗器实例与构筑合法性执行卡

## 执行配置

- 对应问题：P8-I08 实例部分。
- 硬前置：P8-S9 已验收并形成遗器轨检查点。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`xhigh`。
- 推荐模式：普通聚焦模式，遗器轨独立 worktree。
- 选择理由：实例、槽位、队伍占用和失败原子性属于架构边界，工作量有限但不能靠批量数据处理替代设计审查。

## 当前事实与阶段结果

S1 已有弱 `RelicInstanceInput` 形状，S9 建立真实模板和六槽定义；此前装配器应明确拒绝非空遗器。开始前必须审查所有实例构造、构筑 fingerprint、队伍级唯一性检查和 S4 的 `relics_not_admitted` blocker，原子替换该临时边界。

完成后，正式构筑可为空、部分装备或装满六件。每件实例必须引用唯一模板、显式自身身份、与模板一致的槽位和合法强化等级；同一角色不能重复槽位，同一物理实例不能在队伍内重复装备。非法输入使装配结果 blocked，零属性、零套装计数、零动态机制；缺少某槽位则是合法空位。

本阶段只验证实例骨架、槽位、等级、模式和身份，不判断词条数值合法性；含词条的正式 battle admission 仍由 S11/S12 承接。

## 本阶段只做

- 规范 `RelicInstanceInput`：实例 ID、模板 key、槽位、强化等级、主词条 key、副词条 roll 输入，递归冻结和稳定 fingerprint。
- 建立来源驱动的六槽枚举与 template-slot 精确校验。
- 校验模板发布/模式 admission、强化等级边界、单构筑槽位唯一和实例 identity 唯一。
- 提供队伍范围占用校验，保证同一 `instance_id + fingerprint` 不能被多个角色复用；身份相同但 payload 不同也必须拒绝冲突。
- 区分 absent slot、invalid instance、unknown template 和 deferred affix validation。
- 从装配器移除 S4 的“只要有遗器就拒绝”临时逻辑，替换为类型化实例 admission；仍不产出遗器贡献。

## 本阶段不做

- 不验证主词条所属池和数值，不验证副词条 roll 历史。
- 不统计套装、不应用属性、不启动套装能力。
- 不接受客户端提交的最终遗器属性或 `set_active`。
- 不根据列表位置推断槽位，不为兼容旧 payload 提供无标记 fallback。

## 设计与失败不变量

1. 空构筑和缺槽合法；错误槽位、重复槽位或未知模板非法，语义不可混淆。
2. 模板的 slot 是唯一事实来源，调用者提交的 slot 只能用于一致性校验。
3. `CUSTOM` 只保留在 S9 来源目录中，正式玩家构筑一律拒绝；不实现定向生成、映射或 BASIC fallback。未知模式同样 fail-closed。
4. 非法实例不得进入任何 downstream ledger、set counter 或 dynamic selection。
5. 队伍实例唯一性在正式 scenario/build admission 前执行，不能只检查单角色。
6. instance/build fingerprint 覆盖所有结构选择，不包含名称、评分或 UI 展示字段。
7. S11/S12 尚未验证的 affix 输入必须明确标记为 pending/blocked battle admission，不能冒充完整合法实例。

## 目标与证据映射

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 0-6 槽合法 | 空、单件、部分、完整六槽均 assembly-valid | positive slot matrix |
| 错槽/重复拒绝 | template-slot mismatch、同槽两件均 blocked | negative slot matrix |
| 等级与模式正确 | +0/最大合法，越界、unknown 和全部 CUSTOM 均明确拒绝 | level/mode matrix |
| 队伍实例唯一 | 两角色复用同实例或冲突 payload 被拒绝 | team occupancy matrix |
| 失败无贡献 | blocked 结果无 relic contributions/set thresholds/mechanisms | assembly invariant |
| fingerprint 稳定 | 顺序规范化、payload 变化可检测、外部修改无影响 | codec/fingerprint matrix |
| 临时 blocker 退役 | 非空但结构合法的遗器不再因 S4 通用 blocker 失败 | migration probe |

## 拟改文件与关键符号

- `equipment/models.py`：正式化 `RelicInstanceInput`、slot/mode admission 结果与 JSON codec。
- `builds/equipment_assembler.py`：遗器实例结构校验和 fail-closed 结果。
- `builds/models.py`、scenario/build admission：队伍实例占用边界；不得让 runtime 理解遗器。
- `tools/validate_p8_s10_relic_instance_legality.py` 和阶段报告。
- 原子迁移 S1/S2/S4 fixture 与构造调用者。

开始前必须用 CodeGraph 列出 `RelicInstanceInput` 和实例唯一性校验的所有调用者。若改变公开 JSON schema，不做旧 v8 兼容；迁移工作区调用点并在报告列出。

## 结构化验收谓词

```text
empty_relic_build_valid=true
partial_relic_build_valid=true
six_distinct_slots_valid=true
slot_identity_source_driven=true
wrong_slot_rejected=true
duplicate_slot_rejected=true
unknown_template_rejected=true
level_bounds_enforced=true
unknown_mode_rejected=true
custom_mode_excluded=true
team_duplicate_instance_rejected=true
same_identity_conflicting_payload_rejected=true
invalid_relic_contributes_nothing=true
affix_validation_not_masquerading_as_complete=true
instance_fingerprint_stable=true
legacy_all_relics_blocker_absent=true
```

## Gap 与停止条件

- S9 定义缺 template/slot/mode：上游 `lowering_gap`，停止 S10 并回修 S9，不能在实例层猜。
- 词条合法性尚未验证：明确 `deferred_to_s11_s12`，但实例结构可以 assembled；正式 battle admission 必须保持 blocked。
- 队伍级上下文当前没有合理装配入口：属于架构 gap，必须在 build/scenario admission 建立通用占用校验，不得用全局可变 registry。
- 发现旧调用依赖无 slot 或手填属性，直接迁移 fixture；不要默认兼容。

## 验证门与资源预算

实例 schema、装备装配边界和队伍占用检查必须直接拒绝错槽、重复身份、冲突 payload
和非法等级；不得依赖后续属性计算发现结构错误。

必跑且只有一个业务主入口：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s10_pycache python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v -o /tmp/hsr_v8_p8_s10_time_v.txt timeout --signal=TERM 5m python3 -B -m simulator_v8_clean_core.tools.validate_p8_s10_relic_instance_legality --tbgd-root ../../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s10_relic_instance_legality
git diff --check
```

主入口共享一次 S9 目录窄投影，使用 2-4 个角色和少量模板等价类。S9 检查点默认
继承，不重跑 S9 目录验证。只有修改正式 scenario/队伍占用边界时，追加一个小型
scenario admission direct；只有修改 S1 共用实例 codec 时，追加一个无 TBGD 的
codec direct。direct 总数最多两个。

单次主验证不超过 5 分钟、768 MiB RSS；本阶段累计验证不超过 10 分钟，默认总产物
不超过 3 MiB。禁止计算 affix、构建战斗状态、运行全遗器组合、前序阶段完整验证器
或任何阶段聚合。

## Ready-for-review 产物

- 0-6 槽正例、slot/level/mode/identity 负例和 team occupancy 矩阵。
- schema 迁移与所有调用者清单。
- fingerprint/immutability 证据和 blocked 无贡献不变量。
- S11/S12 deferred admission 的机器可读诊断，不得写成已完成。

## 唯一执行清单（仅验收线程可勾）

- [x] 空、部分、完整六槽实例结构均可合法装配。
- [x] 错槽、重复槽、未知模板、等级、模式和队伍重复实例均 fail-closed。
- [x] 非法实例不贡献属性、不计套装、不生成动态机制。
- [x] S4 临时全拒绝逻辑已原子退役，S11/S12 未验证项仍阻断正式战斗。
- [x] schema、不可变性、fingerprint 和调用者迁移完整。
- [x] 无 UI 顺序、名称、SetID 或全局可变 registry 硬编码。
- [x] `ready_for_review` evidence 完整，阶段无实例骨架 blocker。
