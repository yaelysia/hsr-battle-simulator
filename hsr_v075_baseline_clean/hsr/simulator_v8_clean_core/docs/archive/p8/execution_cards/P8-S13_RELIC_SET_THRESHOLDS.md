# P8-S13 外圈、内圈与套装档位激活执行卡

## 执行配置

- 对应问题：P8-I11。
- 硬前置：P8-S12 已验收，只有完整通过实例、主词条和副词条校验的遗器才可计数。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`xhigh`。
- 推荐模式：普通聚焦模式，遗器轨独立 worktree。
- 选择理由：这是纯装配语义但组合边界多，必须人工审查“累积阈值、2+2、内外圈隔离和非法件不计数”，不需要长时间机制扩面。

## 当前事实与阶段结果

S9 已定义 set/domain/threshold，S10-S12 已使实例完全合法，但当前没有从六槽构筑统计激活档位。完成后，装配器仅对 admitted 实例按 set identity 与 domain 计数，并读取数据定义中的所有阈值。达到高阈值时保留所有已满足低阈值；外圈 4、2+2、2+1+1、散件和内圈 2/1+1/部分装备均正确。输出同时包含激活、未满足档位和每档来源实例，不应用静态属性或启动 ability。

## 本阶段只做

- 仅统计完成 S10-S12 admission 的实例；blocked/unknown/CUSTOM 未准入实例不计数。
- 按 S9 的 set identity、domain 和数据驱动 `RequireNum` 计算所有满足档位。
- 实现阈值累积语义，高档激活不覆盖低档。
- 输出每个档位的 activation decision、满足数量、贡献实例、缺少数量和真实定义来源。
- 覆盖空/部分/完整、外圈 4/2+2/2+1+1/散件、内圈 2/1+1 和受控替换。
- 使构筑/装配 fingerprint 覆盖档位激活结果与来源实例选择。

## 本阶段不做

- 不应用 `PropertyList`，不绑定或启动 `AbilityName`。
- 不将当前阈值写死为 2/4，不假设只能有一个四件套加一个二件套。
- 不允许 UI 提交 set count 或 active flag。
- 不为非法槽位、重复实例或无效 affix 提供“只是不计数但继续战斗”的容错。

## 激活不变量

1. set count 只来自实例，不信任输入计数；同一实例只能计一次。
2. domain 由 S9 定义决定，outer 与 planar 永不互补；SetID 数值无语义。
3. 每个 threshold 独立产生 activation record；达到 4 时同套 2/4 都存在。
4. 两套各两件分别激活各自二件档，不合成任一四件档。
5. 无法完整验证的实例使正式 equipment assembly blocked，而不是从统计中悄悄删掉。
6. 激活只是一项装配决定，不执行 effect；重复装配确定性一致。
7. 删除/替换实例只影响相关 set/threshold，其他档位身份和来源稳定。

## 目标与证据映射

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 数据驱动档位 | 当前所有 threshold 从 S9 读取，非 2/4 fixture 也可通用计算 | threshold definition probe |
| 外圈组合正确 | 4、2+2、2+1+1、散件分别得到预期激活集合 | outer matrix |
| 内圈组合正确 | 同套 2 激活、1+1 不激活、部分装备正确 | planar matrix |
| 累积阈值 | 四件同套保留二件与四件两条独立记录 | cumulative case |
| 域隔离 | 重编号、同 ID 形似和跨域组合不能互补 | domain negatives |
| 非法件无计数 | blocked 实例导致 assembly blocked，零激活结果 | admission invariant |
| 来源与确定性 | 每档回到定义和实例集合，顺序变化结果相同 | source/permutation matrix |

## 拟改文件与关键符号

- `equipment/models.py`：必要时补充类型化 set activation decision/result。
- `builds/equipment_assembler.py` 或独立纯 `builds/relic_set_assembler.py`：档位统计。
- `tools/validate_p8_s13_relic_set_thresholds.py` 和阶段报告。
- S10-S12 装配 fixture 原子迁移；不修改 runtime 或 ability lowering。

优先把统计实现为纯函数并由 equipment assembler 调用；不得在 UI、scenario 或 set definition 中缓存角色构筑状态。

## 结构化验收谓词

```text
only_admitted_relics_counted=true
thresholds_loaded_from_definition=true
higher_threshold_retains_lower_threshold=true
outer_four_piece_correct=true
outer_two_plus_two_correct=true
outer_partial_and_scattered_correct=true
planar_matching_pair_correct=true
planar_mismatched_pair_inactive=true
outer_planar_counts_isolated=true
duplicate_instance_not_counted=true
invalid_relic_blocks_before_counting=true
ui_set_active_input_rejected=true
activation_sources_complete=true
input_order_deterministic=true
```

## Gap 与停止条件

- S9 threshold/domain 定义缺失或歧义：上游 `lowering_gap`，回修 S9，不在统计器补默认。
- S10-S12 未完全 admitted 的实例：整个正式 assembly blocked，不能用“合法部分”统计。
- 当前数据出现重叠域、新阈值语义或一件多 set 关系：停止并重新评估类型模型，不能写特例。
- 缺当前组合正例时允许结构 fixture 验证通用阈值，但真实当前 4+2/2+2/内圈案例必须按结构选出，不能固定名称。

## 验证命令与资源

生产边界先保证：套装统计器只接受已完整准入的遗器实例；套装身份、区域、实例身份或来源不一致时必须在生成激活结果前 blocked。所有门槛从类型化定义读取，UI 计数和 active 标记不能进入生产输入。

本阶段固定只运行一个业务主验证：

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v -o /tmp/hsr_v8_p8_s13_time_v.txt timeout --signal=TERM 5m python3 -B -m simulator_v8_clean_core.tools.validate_p8_s13_relic_set_thresholds --tbgd-root ../../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s13_relic_set_thresholds
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s13_pycache python3 -m compileall -q simulator_v8_clean_core
git diff --check
```

- 主验证只构建一次聚焦遗器目录/RuleBook，使用少量 source-backed 实例覆盖外圈、内圈、4 件、2+2、散件和一个非 2/4 门槛 fixture。
- 已验收的 S10-S12 结论直接继承，不固定重跑其验证器。只有本阶段实际修改实例准入或身份契约时，才追加一个对应的最小 direct 切片。
- 完整主验证最多一次诊断运行和一次最终运行；中间修复只跑失败的统计切片。
- 单次主验证预算：墙钟 5 分钟、峰值 RSS 768 MiB；阶段累计验证预算 10 分钟；默认产物不超过 3 MiB。超限立即暂停，不提高限制。
- 不运行全 affix property tests、静态贡献、ability、战斗、历史阶段聚合或 `validate_v0_209`，也不写完整 Canonical IR、RuleBook 或 transition。

## Ready-for-review 产物

- outer/planar 全组合类别矩阵和非 2/4 通用阈值证明。
- cumulative、2+2、跨域、替换、非法件和 UI 伪 active 负例。
- 每档来源实例与定义反查、fingerprint/permutation 证据。
- 代码 diff、直接回归和资源统计。

## 唯一执行清单（仅验收线程可勾）

- [x] 只对完整 admitted 实例按真实 set/domain 计数。
- [x] 外圈 4、2+2、2+1+1、散件和内圈 2/1+1/部分组合均正确。
- [x] 高阈值保留低阈值，所有门槛从定义读取。
- [x] 域隔离、重复实例和非法件 fail-closed，无 UI active 输入。
- [x] activation 来源、fingerprint 和输入顺序确定性完整。
- [x] 未应用静态属性或启动能力；S10-S12 已验收契约未被实际改动，或已通过对应最小 direct 切片。
- [x] `ready_for_review` evidence 完整，阶段无套装统计 blocker。
