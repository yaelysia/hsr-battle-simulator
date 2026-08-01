# P8-S19 查询、审计、Snapshot、Replay 与紧凑状态验收报告

状态：`accepted`

## 验收结论

P8-S19 当前源码通过独立验收。装备目录与构筑查询、来源反查、正式构筑 manifest、重装配回放和紧凑语义状态已经形成同一条只读契约；没有新增装备机制、前端规则或完整目录/账本的状态复制。

最终业务主验证 17/17 谓词通过：

- 光锥、遗器模板、套装和词条合法性查询均为类型化只读结果；缺失和受控重复定义结构化 blocked，不取第一项。
- 构筑提交只接受角色、装备实例和词条 roll 选择；最终面板、套装激活、命途激活和效果结果字段全部拒绝。
- manifest 保存严格构筑输入、角色结果指纹、装备结果指纹、来源集合指纹、Canonical IR 指纹和引擎规则版本；不复制完整装配结果。
- replay 在应用 mutation 前重新装配并核对结果、provider 和版本身份。来源、IR、引擎、结果账本或 provider 任一篡改均 blocked，状态不变。
- compact state 删除完整 manifest、构筑输入、贡献账本和来源材料，只保留 manifest、构筑结果和 provider 的稳定身份以及当前动态状态。
- 静态贡献按“贡献项 -> 来源账本 -> 定义卡 -> TBGD”反查；动态 provider mutation 按正式 settlement、机制引用、套装档位和 TBGD 来源反查。
- P7 动作查询/提交模块未修改；UI 报告仅将正式构筑回放切换到 build-locked verifier，kernel fixture 继续使用通用 reducer。

## 代码审查

验收期间主动收紧了三处实现：

1. 删除查询层按字符串重拼遗器贡献身份的实现，改为消费装配器已经生成的类型化来源账本。
2. manifest 从保存完整 `CharacterBuildAssemblyResult` 收缩为保存选择和结果指纹，单角色样例由约 296 KB 降为约 5 KB。
3. provider 注册由生产结果原生生成可审计 transition；回放只允许空注册表到重装配所得完整 provider 集合的初始注册，战中修改或伪造身份继续 fail-closed。

未发现固定角色、光锥、遗器、套装 ID，未发现装备专属事件循环、第二套面板计算或 source trace 驱动 runtime。

## 验证结果

最终主入口：

```text
ok=true
checks=17/17
wall=15.984s
peak_rss=450692 KiB
rulebook_build_count=1
complete_tbgd_lowering_count=0
artifact_count=2
artifact_bytes=16353
```

聚焦产物：

- `/tmp/hsr_v8_p8_s19_query_audit_snapshot_replay/validation_summary_p8_s19_query_audit_snapshot_replay.json`
- `/tmp/hsr_v8_p8_s19_query_audit_snapshot_replay/p8_s19_query_audit_replay_matrix.json`

直接回归：

- `validate_p7_s18_compact_semantic_state`：通过，5 行为矩阵全部通过。
- 首次 direct 未进入投影，原因是旧 fixture 仍在 flags 重复保存生命周期；删除三个陈旧字段后通过，未放宽内核。
- 全包 `compileall` 与 `git diff --check`：通过。

## 运行审计

本阶段发生三类前置/诊断失败，均如实保留：

- 第一次在 manifest 创建前发现窄 IR 没有复制 full-lowering 顶层来源元数据。生产实现改为汇总 IR 内真实 `IRSource` 指纹，没有由验证器伪造元数据。
- 第二次在 provider transition 构造时发现系统命令漏传现有必填动作等级，单行修复后先用无 TBGD 微型切片验证。
- 第三次完整运行暴露一个真实回放保护冲突和两个验收器误判：合法初始 provider 注册被当作身份篡改；受控歧义页面被误要求 resolved；所有名为 `source` 的语义字段被误判为 provenance。生产边界与验收谓词分别按职责修正。

全部运行合计仍低于一分钟，最高峰值约 441 MiB，没有完整 lowering、完整 snapshot/catalog/transition dump 或阶段聚合。

## 未运行与边界

- 未运行 P1-P8 聚合、S8/S17 ability transition、S18 主验证、完整 TBGD lowering 或 `validate_v0_209`。
- 未制作 UI 布局或完整构筑编辑器。
- 未新增或回修装备 gameplay 机制。
- compact state 是搜索节点身份，不是独立恢复包；精确恢复继续使用完整 snapshot manifest。
- 下一阶段只能消费本阶段公开查询、提交和 replay API，不得复制清单重装配或来源反查逻辑。
