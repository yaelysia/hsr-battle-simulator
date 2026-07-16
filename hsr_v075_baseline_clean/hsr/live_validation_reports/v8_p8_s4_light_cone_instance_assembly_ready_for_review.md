# P8-S4 光锥实例、成长与命途激活决策 — ready_for_review

状态：`ready_for_review`

基线检查点：`34bcb90 feat(v8): complete P8-S3 light cone data cards`

本执行线程未修改 P8 Checklist，未创建 Git 提交，未进入 P8-S5。

## 本阶段实现

- 建立光锥实例 fingerprint、稳定选择引用、双来源命途比较依据、激活决策、战斗准入 blocker 和装备装配结果契约；JSON 解析 fail-closed，解析后递归不可变。
- 角色卡 lowering 生成真实角色装备资格，并通过 CanonicalIR / RuleBook 校验角色卡、角色 profile、命途和来源的一致性。
- 新增装备装配器，按 `Base + Add × (level - 1)` 使用精确十进制值生成生命、攻击、防御的基础项与成长项；两个操作数保留各自 raw 字段来源。
- 任意角色均可装备任意光锥。跨命途只关闭被动，基础属性仍生效；同命途被动为 active，但静态被动和动态能力尚未准入时正式战斗 blocked。
- 角色装配器传播类型化装备准入结果；正式 scenario 消费装配后的面板与来源；队伍内同一光锥实例身份重复时由 identity 边界拒绝。

## 关键结构化结论

- 空装备：`assembled + admitted`。
- 跨命途光锥：`assembled + base_applied + inactive + admitted`。
- 同命途光锥：`assembled + base_applied + active + battle_blocked`，只读面板保留。
- 当前静态被动缺口：`implementation_missing`。
- 当前动态能力缺口：`lowering_gap`。分类由 RuleBook 中是否存在同一能力原始记录的通用图事实决定；生产分类器不按装备目录路径硬编码，同名但来源不同的图不能冒充。
- 选择结果只保存实例、定义、晋阶、叠影、参数序号、属性序号和来源引用，不复制晋阶、叠影或效果 payload。

## 聚焦验证证据

主验证输出：

```text
/tmp/hsr_v8_p8_s4_light_cone_instance_assembly/
```

结果：

- S4 六个验证域全部 `ok=true`。
- 独立 raw Decimal oracle 共核对 87,642 项。
- 覆盖 2,268 个等级 / 晋阶边界、2,268 个角色最终面板合并结果和 810 个叠影档，差异为 0。
- 35 项负例全部被拒绝；验收指定的资格角色 / 档案 / 命途 / 来源错绑、未发布 / 状态不明 / 未完成投影、晋阶 / 叠影来源错绑、0 级光锥 / 0 级叠影、叠影档位缺失 / 重复、其他装备类型冒充光锥、相反激活状态、装配结果指纹篡改、blocked 夹带正式结果以及跨命途夹带被动渠道均由固定矩阵行逐项约束，不再以负例总数代替覆盖证明。
- 正式跨命途 scenario 完成 identity 与 state build；同实例重复被拒绝，同定义不同实例通过。

直接回归：

- P8-S3 光锥数据卡：`ok=true`。
- P8-S1 类型契约：`ok=true`。
- P8-S2 fixture：全部通过。
- P8-S2 character-card source：全部通过。
- targeted `compileall`：通过。
- `git diff --check`：通过。

S1 与 S3 回归摘要已升级为验证范围陈述：只说明各自是否读取、构建或断言后续阶段，不再把历史阶段边界冒充为当前项目状态。

## 资源与未运行项

- 所有命令串行、`nice + ionice` 限流，产物只写入 `/tmp` 的小型 summary / matrix。
- S4 主验证只构建一次光锥目录、一次角色卡、一次动作定义和聚焦 RuleBook；完整 TBGD lowering 次数为 0。
- 未运行 P1-P7 聚合、完整 P8-S2 lowering、`validate_v0_209` 或其他无调用链关系的重验证。

## 当前边界

距离下一步：P8-S5 仍需消费已选叠影档的静态被动属性；P8-S6 仍需将装备能力原始记录 lower / bind 到通用能力图并实现准入与执行。

距离完整复刻：遗器定义、六槽实例、主副词条、套装统计、静态 / 动态效果、最终端到端构筑与全目录覆盖仍属于后续阶段。本阶段没有将这些缺口伪装为 executable。
