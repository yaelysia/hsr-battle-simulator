# P9-S2 行迹、星魂与最终构筑机制绑定验收报告

## 状态与结论

- 状态：`accepted`。
- 基线：`cd8e62a`。
- P9-S2 已通过独立生产代码、来源闭包、负例、正式场景边界和资源验收。
- 本阶段只完成最终构筑选择与内容来源绑定；动态图仍为只读 blocked 引用，执行语义由 P9-S4 至 P9-S17 负责。

## 生产结果

- 当前 79 张角色卡、3,950 个当前形态行迹节点、474 个星魂槽完成类型化构筑绑定。
- S0 当前发现 907 个原始选择器，其中 901 个属于战斗构筑：337 个行迹选择、564 个星魂选择；6 个表现用途选择器未进入战斗构筑。
- 901 个战斗构筑选择器全部形成唯一、来源闭合的关系，gap 为 0；关系可回到 S0 投影、S1 来源图、能力定义或来源根、当前角色内容节点和原始字段位置。
- 默认行迹、显式升级、星魂前缀、技能等级、静态/资源贡献、直接 ability 和条件分支均由 `CharacterBuildAssembler` 统一解析一次。
- 动态结果采用“来源图根 + 构筑选择 specialization”，不复制效果 payload；同一来源根的无条件内容与条件分支不会拆成两次执行。
- 未闭合动态图保留面板和审计账本，但阻止 battle admission；assembly blocked 时所有正式结果通道为空。
- 正式场景只消费装配结果；旧行迹 flags 与星魂启动路径仅保留在显式 `kernel_fixture`。

## 验证结果

最终聚焦入口：

```text
python3 -B -m simulator_v8_clean_core.tools.validate_p9_s2_trace_eidolon_build_binding
```

- 10/10 结构化通过谓词全部为 true，附加 7 项分支和治理检查全部通过。
- 316 个构筑变体完成装配检查，覆盖默认/全行迹与 E0/E6 组合。
- 真实正反分支、双分支、Inverse、空分支无伪根、直接根与 specialization 合并均已观察。
- 12 项负例通过：重复、默认重选、等级冲突、跨角色、来源/归属篡改、旧字段、可变输入和 fingerprint 篡改均 fail-closed。
- 内部墙钟 19.901 秒；`/usr/bin/time` 墙钟 20.20 秒；峰值 RSS 421,100 KiB。
- evidence 2,290,475 bytes；验证器 900 个非空行；完整 lowering 0 次。
- `compileall` 与 `git diff --check` 通过。

前三次聚焦运行未通过，原因均为新验证器 oracle 偏差：误纳入 6 个表现用途选择器、未按当前增强形态选择内容、能力定义匹配缺来源路径约束，以及 TargetAlias 上下文按错误作用域归组。生产关系集合在这些运行中始终为 901/0；修正 oracle 后相同生产链通过，未放宽生产契约。

曾定向尝试旧 P8-S2 `fixture-only`。它继续阻断于既有正式构筑清单缺来源指纹，属于已经陈旧的历史验证入口；本阶段没有为其补兼容链。P9-S2 主验证直接调用正式出生规划并证明未准入构筑被拒绝，因此不以该旧脚本冒充现行 direct。

证据：

- `/tmp/hsr_v8_p9_s2_final_review_20260802_d/summary.json`
- `/tmp/hsr_v8_p9_s2_final_review_20260802_d/content_binding_evidence.json`

## 代码审查

- 未发现角色名、技能名、固定角色 ID、固定文件映射或观测答案驱动生产逻辑。
- 构筑绑定只保存类型化身份、数值贡献、图引用和来源，不保存第二套 task/effect payload。
- Canonical IR 与 RuleBook 同时检查全局重复、角色归属、当前行迹/星魂身份、S1 来源图、能力定义和机制槽来源闭包。
- 选择器在装配时对已选和未选状态都求值；空分支不创建动态图根，有内容的 false 分支和 Inverse 均保留。
- runtime 不读取 raw TBGD，也不再依据正式构筑的旧 flags/rank 重算。

## 未覆盖范围

- 动态 ability、状态、事件、目标、数值和行动语义尚未执行；对应 P9-S4 至 P9-S17。
- 当前多数正式角色构筑仍会因动态图未准入而阻止出生，这是诚实的下游机制缺口，不是 S2 来源绑定遗漏。
- 未运行 P1-P8 聚合、完整 Canonical lowering、P4/P6 重验证或 `validate_v0_209`。

开工前已有的 `simulator_v8_clean_core/ARCHITECTURE_BOUNDARY_CONTRACT.md` 修改及两个未跟踪 UI 文件未触碰、暂存或清理。
