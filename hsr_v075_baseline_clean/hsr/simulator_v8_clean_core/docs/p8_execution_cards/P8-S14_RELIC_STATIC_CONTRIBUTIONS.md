# P8-S14 遗器与套装静态属性贡献执行卡

## 执行配置

- 对应问题：P8-I12。
- 硬前置：P8-S13 已验收，实例、主副词条和套装档位均可稳定装配。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`xhigh`。
- 推荐模式：普通聚焦模式，遗器轨独立 worktree。
- 选择理由：本阶段主要复用统一贡献账本，但来源项多且双计风险高，需要聚焦人工审查，不应和动态套装能力混做。

## 当前事实与阶段结果

S11/S12 产生精确主副词条计算结果，S13 产生激活套装档位；这些结果目前不应修改最终角色面板。S5 已证明光锥静态属性进入统一账本的模式，本阶段必须复用同一贡献类型和聚合通道，不建立遗器专用属性系统。

完成后，每件遗器的主词条、每条副词条、每个已激活套装档位的 `PropertyList` 都产生独立、source-backed 的静态贡献。相同属性可聚合但 ledger term 不合并，未达到门槛的档位零贡献。静态与动态并存档位只装配静态部分，ability 留给 S15。可形成遗器中间面板，但跨角色/光锥/行迹的最终顺序留给 S18。

## 本阶段只做

- 将主词条计算结果转换为一个贡献 term；每条副词条分别转换，不按实例预求和。
- 将每个已激活套装 threshold 的静态属性列表按原项目分别转换为贡献。
- 映射到 S2 共用基础/ratio/flat/resource 通道，数值保持 Decimal 规范字符串。
- 在 term 中保留实例、模板、affix/count/step 或 set threshold、activation evidence 和 raw source。
- 防止同一 row/definition 被旧 entity lowering、数据卡和正式装备装配重复消费。
- 扩展 `EquipmentAssemblyResult` 的静态贡献和 source ledger，保持递归不可变和稳定 fingerprint。

## 本阶段不做

- 不执行、注册或部分 lower 套装动态 ability。
- 不最终合并角色、行迹、光锥和遗器面板；S18 负责统一公式和出生顺序。
- 不将同属性多项压成一条来源，不接受评分/推荐权重。
- 不从套装描述补 PropertyList 中不存在的值。

## 贡献不变量

1. 一个合法 main affix 对应一个 term；一个 sub affix 对应一个 term；一个静态 set property 项对应一个 term。
2. 同属性多来源只在求值层聚合，ledger 层保持每项身份和来源。
3. 未激活 threshold、blocked relic 或未通过 affix admission 的实例不得产生任何 term。
4. 达到高 threshold 后，低/高档静态属性分别存在；来源不互相覆盖。
5. 同时含静态与动态的档位只产生静态 term 和待绑定 ability source，不产生 runtime mutation。
6. property type 无法映射通用通道时 assembly blocked；不得存为任意字符串后交给 runtime 猜。
7. 最终数值可以从 ledger 独立重算，term 顺序变化不影响结果/fingerprint 的规范排序。

## 目标与证据映射

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 六槽词条全进入账本 | 每个 main/sub 结果一一对应 term，无漏项/合并 | affix ledger matrix |
| 套装静态门槛正确 | inactive 零贡献，active 低/高档分别贡献 | threshold contribution matrix |
| 静态/动态分离 | static-only、dynamic-only、both 三类真实档位行为正确 | payload class matrix |
| 聚合精确 | 多实例同 property 的 ledger 重算与聚合相同 | Decimal reconstruction |
| 无双计 | entity/legacy/重复 source 注入均拒绝或检测 | duplicate consumption negatives |
| 来源闭合 | term -> instance/threshold -> definition -> raw field | walkback samples |
| 无提前 runtime | 零 provider、listener、status、mutation | boundary probe |

## 拟改文件与关键符号

- `builds/equipment_assembler.py`：消费 S11-S13 规范结果并产生静态 contributions。
- `build_types.py`、`equipment/models.py`：仅补通用贡献 basis/source 所缺字段。
- `builds/character_assembler.py`：可接收装备静态账本，但不得在 S18 前自行定义最终聚合顺序。
- `tools/validate_p8_s14_relic_static_contributions.py` 和阶段报告。
- S5、S11-S13 fixture/codec 的原子迁移。

修改前用 CodeGraph 检查 `StaticStatContribution` 全部生产者和消费者，确认不存在旧遗器/实体属性重复路径。若发现双轨，应删除旧弱路径而非加去重白名单。

## 结构化验收谓词

```text
main_affix_terms_one_to_one=true
sub_affix_terms_one_to_one=true
active_set_property_terms_one_to_one=true
inactive_threshold_contributes_zero=true
high_threshold_retains_lower_terms=true
static_dynamic_payloads_separate=true
same_property_terms_not_preaggregated=true
decimal_ledger_reconstructs_totals=true
duplicate_source_consumption_rejected=true
unknown_property_type_blocks_assembly=true
all_terms_source_backed=true
dynamic_runtime_effects_started=false
input_order_deterministic=true
```

## Gap 与停止条件

- S11/S12 数值存在但无法映射通用属性类型：`admission_gap` 或共享属性模型缺口，本阶段修通用类型，不在 runtime 存裸值。
- S9 套装静态项漏投影：`lowering_gap`，回修 S9 来源模型。
- 发现实体 lowering 已消费同一 relic row：架构双计缺陷，本阶段必须原子退役旧路径。
- 动态 ability 中的条件属性不能人工转为静态 term；保留给 S15-S17。

## 验证命令与资源

生产边界先保证：贡献账本创建时逐项校验来源身份、属性类型和激活依据；重复来源、未知属性或未激活档位必须在装配结果形成前 blocked。账本是唯一计算输入，验证器不得另写一套属性归并公式。

本阶段固定只运行一个业务主验证：

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v -o /tmp/hsr_v8_p8_s14_time_v.txt timeout --signal=TERM 5m python3 -B -m simulator_v8_clean_core.tools.validate_p8_s14_relic_static_contributions --tbgd-root ../../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s14_relic_static_contributions
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s14_pycache python3 -m compileall -q simulator_v8_clean_core
git diff --check
```

- 主验证复用一份 source-backed 构筑输入，最多建立一次聚焦 RuleBook；独立 oracle 只从账本公开项重算，不复制生产映射逻辑。
- 已验收的 S5、S13 结论直接继承，不固定重跑。只有实际修改共享贡献类型或聚合器时，追加一个 S5 小型账本 direct；只有修改角色面板求值器时，追加一个 S2 fixture direct。direct 总数最多 2。
- 完整主验证最多一次诊断运行和一次最终运行；中间修复只跑失败的 term/ledger 切片。
- 单次主验证预算：墙钟 5 分钟、峰值 RSS 768 MiB；阶段累计验证预算 10 分钟；默认产物不超过 3 MiB。超限立即暂停。
- 不执行套装 ability、不构建战斗状态、不跑全 affix property tests、历史阶段聚合或 `validate_v0_209`，不写完整 RuleBook。

## Ready-for-review 产物

- main/sub/set 静态 term 一一映射和三类档位矩阵。
- Decimal 重算、inactive threshold、双计和 unknown property 负例。
- 至少一条 main、一条 sub、一条 set term 的完整来源反查。
- S5 复用性、代码调用链、资源和未运行范围报告。

## 唯一执行清单（仅验收线程可勾）

- [ ] 主词条、副词条和已激活套装静态项逐项进入统一账本。
- [ ] 未达门槛零贡献，高档保留低档，静态/动态并存不漏不提前执行。
- [ ] 相同 property 不预合并，Decimal 账本可独立重算。
- [ ] 旧路径/重复来源不双计，unknown property fail-closed。
- [ ] 每类 term 来源反查完整，结果不可变且确定性。
- [ ] S5/S13 已验收契约未被实际改动，或已通过实际触达所需的最小 direct；人工代码审查通过。
- [ ] `ready_for_review` evidence 完整，阶段无静态贡献 blocker。
