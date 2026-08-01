# P8 装备、光锥与遗器体系最终检查点

状态：`accepted`

## 最终结论

P8-S0 至 P8-S21、R1 和 R2 已在当前源码完成最终聚合验收。当前来源指纹下，光锥、普通玩家遗器、主副词条、套装档位和装备 gameplay 能力形成同一条类型化定义、构筑装配、正式出生、runtime provider、settlement、来源审计与 replay 链。

最终聚合的 23 项顶层谓词全部符合预期：所有定义与 gameplay gap、unknown 均为 0；内部定义聚合和 gameplay 聚合同时为 `ok=true`，没有用外层摘要掩盖内部失败。

## 当前覆盖

- 162 张已发布光锥全部完成定义、成长、叠影、静态贡献、动态机制图与正式 provider 准入。
- 720 个普通玩家遗器模板、117 个主词条、48 个副词条、58 套遗器和 90 个套装档位全部闭合。
- 当前 raw gameplay family 共 6042 行，其中 S7 类 1551 行、S8 类 4491 行；光锥与套装图 gap、unknown、partial graph 均为 0。
- 17 行 non-gameplay 和 5 行不可达保留来源均有 raw reachability 与结构化分类，没有从目录分母静默删除。
- 6 个 `CUSTOM` 模板保留真实目录身份与来源，但正式玩家构筑逐项拒绝；项目不实现定向生成遗器流程。
- 光锥和遗器领域指纹分别覆盖完整主来源集合中的 24/24 与 21/24 个相关文件，不再错误要求两个领域摘要哈希相等。

## 集成证据

- 六类来源反查全部 resolved：光锥静态、光锥动态、主词条、副词条、套装静态、套装动态。
- 六类关键回归全部通过：命途失配只关闭被动、正式 4+2、结构化 2+2、非法副词条原子阻断、缺失机制图原子阻断、六种陈旧或篡改 replay 拒绝。
- S20 希儿样例在同一 RuleBook 中重新消费正式 manifest；六件成品遗器、目标面板、三个装备 provider、速度档位、暴击门槛、量子弱点分支、四类反例和 replay 全部通过。
- 聚合前后生产代码指纹一致；S21 没有修改 runtime、lowering、assembler 或规则模型。

## 最终资源

权威 final 位于 `/tmp/hsr_v8_p8_s21_current_source_aggregate_round3/`：

```text
ok=true
predicates=23/23
wall=22.501028s
peak_rss=392708 KiB
light_cone_catalog_builds=1
relic_catalog_builds=1
focused_rulebooks=1
full_lowering_builds=0
artifact_count=3
artifact_bytes=28309
```

全包 `compileall` 与 `git diff --check` 通过。未运行 P1-P7 聚合、历史 P8 阶段主验证、`validate_v0_209`、完整 Canonical IR/RuleBook dump 或 UI 构建。

## 验证器审查记录

S21 共经历三轮独立 final，每轮只运行一次，累计仍远低于 45 分钟预算：

1. 第一轮约 22.03 秒，把光锥全集误套入遗器阶段 IR 分区器，误报 17 行 gameplay gap。改为 raw reachability 分类账后关闭该验证器缺陷，未修改生产代码。
2. 第二轮约 22.36 秒外层显示绿色，但代码审查发现领域指纹被错误要求相等，且外层漏接两个内部 `ok=false`。该证据作废。
3. 第三轮加入领域指纹覆盖和内部一致性硬门，23/23 通过；这是唯一权威最终证据。

聚合器 909 行非空 Python，低于 S16-S21 的 1000 行治理目标；证据不包含完整 IR、RuleBook 或 transition。

## 明确不做

- 不模拟遗器刷取、掉落、初始词条、每三级强化、定向生成、背包或养成操作，只接收可用于战斗的合法成品构筑。
- 不实现自动配装、词条评分、攻略推荐或 UI 布局。
- 不把希儿样例写成内核默认，也不以它替代全目录覆盖。
- 不在装备阶段伪造希儿普攻、战技和终结技动作图；角色完整动作内容由后续角色卡阶段闭合。
