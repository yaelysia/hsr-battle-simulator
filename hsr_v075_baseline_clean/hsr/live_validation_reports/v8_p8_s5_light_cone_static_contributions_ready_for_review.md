# P8-S5 光锥静态贡献 — ready_for_review

状态：`ready_for_review`

基线检查点：`23062cc feat(v8): complete P8-S4 light cone assembly`

本执行线程未修改 P8 Checklist，未创建 Git 提交，未进入 P8-S6。

## 本阶段实现

- 建立共享、类型化的静态属性映射，将 raw 属性类型明确映射到贡献池、规范面板字段和计算方式；角色行迹与光锥复用同一份生产定义，不保留平行映射。
- 光锥叠影静态属性保留项目序号、精确十进制值和具体 raw 行来源；未知属性或损坏的类型化映射会 fail-closed，不能进入完整目录。
- 同命途时，所选叠影档的每个静态属性生成一条独立、来源可追溯的被动贡献；跨命途时只保留光锥基础生命、攻击、防御贡献，不夹带被动贡献或动态渠道。
- 装配选择只保存稳定贡献身份，装备结果强制校验基础贡献与被动贡献分离、贡献身份唯一，以及每条贡献与来源账本一一对应。blocked / inactive 结果不能夹带被动贡献。
- 装配结果进一步从选择中的实例、定义、叠影、技能、属性序号和叠影 raw 行路径重建预期被动贡献身份；贡献及账本即使被共同改写，也必须同时归属于当前选择的光锥，并与所选叠影的 raw id、文件、json path 和 source fingerprint 完整一致。
- 角色装配器继续只消费通用贡献账本，不重新解释光锥属性类型；来源回查同时接受所选晋阶字段和所选叠影静态属性的真实 raw 行。
- 动态能力仍保持 `lowering_gap`，本阶段没有创建能力图引用、启动能力、产生 runtime mutation 或进入 P8-S6。
- 光锥目录 schema 与规范目录 fingerprint 算法均升级为 v2；S3 验证明确拒绝继续以 v1 口径描述新增了必填类型字段的数据卡。

## 完整来源分类

生产目录一次构建得到：

- 已发布光锥：162 张。
- 叠影档位：810 个。
- 无静态属性、有唯一能力来源：260 个档位。
- 静态属性与唯一能力来源并存：550 个档位。
- 仅静态属性、无能力来源：0 个档位。
- 静态属性项目：575 条。

三类合计严格覆盖全部 810 个档位。当前空类只作为实时来源事实记录，验证没有合成正例，生产逻辑也没有写死该数量或空集结论。全部档位均存在唯一能力来源；能力缺失、歧义或错绑继续作为 S3 目录级 blocker。

## 数值、面板与来源证据

- 810 个同命途档位和 810 个跨命途档位均经过正式装备装配器。
- 575 条静态属性逐项独立核对 raw Decimal、原始顺序、类型化映射、贡献值与来源账本，差异为 0。
- 输入遍历顺序反转后重新装配全部 810 个档位，规范结果摘要保持一致。
- 740 个档位可通过当前真实、已准入的角色构筑继续核对最终面板归并，独立贡献池 oracle 差异为 0。
- 另有 70 个档位所在命途当前不存在可正式准入的角色构筑；原因是 S2 已记录的角色内容准入缺口。本阶段没有合成角色绕过该边界，但对应装备贡献、来源、命途激活和跨命途隔离仍已在全部 810 个档位上完成验证。
- source walkback 样本可从角色最终面板贡献回查到装备结果、所选叠影静态属性、具体 `EquipmentSkillConfig` 行及其来源证据。

## 负例矩阵

固定必备矩阵共 19 行，全部通过：

- 未知属性、非规范十进制、损坏的规范属性绑定。
- 外来静态来源、重复静态来源、重复贡献身份、缺少所选被动贡献。
- 伪造贡献来源、贡献与账本共同改绑到另一叠影、共同伪造 raw json path、共同伪造格式合法但不同的 source fingerprint、贡献与账本归属共同改成另一张光锥、损坏被动贡献身份。
- inactive 夹带被动贡献、角色侧重复消费、结果 fingerprint 篡改。
- 能力来源缺失、歧义和错绑。

必备行名称由验证器固定声明，不能仅靠负例总数冒充覆盖完整；三次目录破坏均复用内存文档，没有重复读取全量来源。

## 串行验证

主验证：

```text
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/zhangjinhao/code/hsr/hsr_v075_baseline_clean/hsr ionice -c 3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p8_s5_light_cone_static_contributions --tbgd-root /home/zhangjinhao/code/hsr/turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s5_light_cone_static_contributions
```

结果：`ok=true`，六个矩阵全部通过；summary 写入前的产物总计 18,831 bytes。只读取一次主来源，构建一次聚焦 RuleBook，没有写完整 CanonicalIR、完整 RuleBook 或 transition dump。

“动态能力未执行”不再由固定布尔值声明：验证器统计全部 810 个同命途与 810 个跨命途装配结果，动态机制选择总数为 0；810 个同命途结果均携带动态 blocker，810 个跨命途结果均为 inactive + admitted。正式边界探针进一步证明同命途构筑在 `ScenarioStateBuilder` 创建战斗状态前被拒绝；同一角色的空装备与跨命途装备正式场景均可构建，二者实际 setup mutation / event / RNG 产物完全一致。

直接回归：

- P8-S4 光锥实例装配：`ok=true`。
- P8-S3 光锥数据卡：`ok=true`。
- P8-S2 fixture：33/33。
- P8-S2 真实角色来源：25/25。
- P8-S1 类型契约：`ok=true`。
- 全 core `compileall`：通过，pycache 定向写入 `/tmp`。
- `git diff --check`：通过。

所有验证均串行、`nice + ionice` 限流并只写 `/tmp` 小型产物。未运行 P1-P7 聚合、`validate_v0_209`、全量 ability transition 或其他无直接调用链关系的重验证。

## 当前边界

距离下一步：P8-S6 仍需把真实装备能力记录 lower / bind 到通用能力图，并建立动态能力的准入、执行、settlement、source audit 与 replay 闭环；“存在能力来源”没有在本阶段被冒充为动态可执行。

距离完整复刻：光锥条件化与动态效果、遗器定义、六槽实例、主副词条、套装效果、最终构筑纵切和全目录机制覆盖仍属于后续阶段。
