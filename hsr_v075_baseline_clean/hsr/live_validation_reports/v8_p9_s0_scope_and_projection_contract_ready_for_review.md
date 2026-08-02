# P9-S0 scope and projection contract ready for review

执行线程状态：`ready_for_review`。验收线程状态：`accepted`（2026-08-02）。

基线：`8d8f746fd03ea23d3fbabadc9f97c0e250154544`

日期：`2026-08-02`

## 验收结论

P9-S0 通过验收。验收线程检查了生产代码、来源选择与指纹链、完整对象范围传播、目录引用
闭包、类型化投影和验证器独立 oracle，并复现确认以下绕过均已在构造边界拒绝：解析文档与
原始字节脱钩、候选清单与来源协同伪造、record/projection 来源证据分离、同对象范围顺序依赖，
以及内部 IR 子类跳过校验后修改目录语义。

最终权威 summary 的 14 项业务检查和全部资源检查均为 true；验收线程另行执行的合并式内存
探针通过，`compileall` 与 `git diff --check` 通过。当前 213 条 decode-required 和 unit-topology
`external_content_dependency` 是 S0 明确保留给后续责任阶段的结构化事实，不阻断本阶段通过，
也不表示对应 gameplay 机制已经实现。

## 生产改动

1. **递归不可变与严格构造边界**
   - S0 新 IR 复用 `immutable_json.freeze_json/thaw_json`，所有 nested payload、source evidence、
     counters 和 summary 均在构造时复制并冻结，序列化结果与对象脱离。
   - digest、枚举、coverage、有限数值、唯一身份、引用闭合和 complete 状态在构造边界 fail-closed。
   - `simulator_v8_clean_core/ir_types.py` 保持基线行为，没有第二套全局 freeze/thaw，也没有改变
     `IRSource.to_json()`。

2. **raw snapshot 绑定真实字节与 inventory manifest**
   - `documents` 为 `init=False`，只从冻结后的 `source_bytes` 在 snapshot 构造边界解析；调用者不能
     在原字节和 fingerprint 不变时注入伪造解析树。完整构建的 80 份 ability 各解析一次。
   - candidate manifest 只由三张 inventory 原始字节派生，并闭合发布基表、命途、增强版本、config
     path/row 与 source evidence。enhanced 只覆盖 `JsonPath`、config row 和版本，不补造命途或发布状态。
   - raw `AvatarID` 仅接受非 `bool` 的整数并无损规范化为内部非空十进制字符串；`bool`、`float`、
     object 和空值均拒绝。candidate 内部仍严格使用 `str`。
   - manifest 与 fingerprint 都按规范路径顺序计算，等价输入映射顺序不影响候选或 fingerprint；同步
     伪造 candidate、source、evidence 和重算 fingerprint 仍被 snapshot 构造器拒绝。

3. **完整对象分支先裁决再物化**
   - 同一对象的 `Event`、`$type` 和结构入口在生成记录前统一计算 terminal scope，明确终止范围支配
     同对象全部标记及后代，不再依赖字段遍历顺序。
   - `_CL Event + AddModifier` 与反向 `OnAfterAttack + TriggerEffect` 都不能被内部 opcode 重新准入；
     相互冲突的 terminal scope 结构化进入 `scope_decision_required`，不猜测优先级。
   - `OnBreakExtendAnim` 携带真实 gameplay effect 的正例仍保持 gameplay。

4. **catalog 来源链和语义身份闭合**
   - record identity 绑定 source path、occurrence kind、JSON path 和 family；record evidence 的精确 schema
     与顶层 source、父链、nominal semantic、parent branch 和 inherited terminal identity 全部互证。
   - projection source 必须与所属 scope record 的完整 source 相等，伪造 `json_path` 或 avatar evidence
     会在构造器中拒绝，不能仅靠 `catalog_id` 变化掩盖内部矛盾。
   - `catalog_id` 哈希规范序列化后的完整 sources、records、families、projections、dependencies、filters、
     fingerprint、status/reason 和 issues。合法语义变化会改变 ID，同内容重排保持相同 ID。

5. **窄视图、fingerprint 与独立 oracle**
   - family 过滤在昂贵 IR 物化前生效，同时保留 parent 与 inherited-terminal 的最小祖先闭包；不存在的
     family 结构化 fail-closed，所有 parent/projection/source 引用闭合。
   - source fingerprint 使用无歧义 framing，覆盖三张 inventory 原始字节、规范 selection mapping、
     source filter、完整性状态及选中 ability 原始字节。
   - 验证器从同一份 immutable raw snapshot 独立重建 inventory 选择和 `$type`/Event/结构入口闭包，
     不以固定角色数、文件数、投影数或 hash 作为通过条件；oracle 自行执行严格 raw `AvatarID` 类型检查。

6. **严格类型化投影与非战斗隔离**
   - 当前正式 projection kind 对 scope、opcode 和 payload 使用严格 schema；空、未知、错误类型和非有限
     数值不能伪装为 lowered IR。
   - `SetEnergyBarState` / `SetSummonerEnergyBarState` 的已知战斗字段按字段类型保存原始表达式，包括
     `CurrentState`、`Active`、`BarType` 和 `CD`，不提前解释 S12 runtime 语义。仅客户端表现字段退役。
   - 当前观测为 379 个资源状态、4 个目标保持和 52 个环境依赖投影，共 435 个；已知资源状态没有留作
     S0 deferred。非战斗记录不进入 gameplay admission，full lowering 调用为 0，未新增 runtime 行为。
   - 当前完整来源没有 unit-topology producer，catalog/summary 以 `external_content_dependency` 机器状态记录，
     没有用 synthetic producer 冒充端到端证据。

7. **已验证内部模型使用精确类型边界**
   - catalog 的 sources、scope records、projections、families、external dependencies 和 issues 仅接受
     精确内部类型；覆写 `__post_init__` 的 projection 子类会在读取 payload 或生成 identity 前被拒绝。
   - snapshot 仅接受精确 inventory manifest 和 `CharacterAbilitySourceIR`，DocumentProjection 同样复制容器
     并逐项要求精确内部类型；candidate fingerprint 路径不接受 `_SourceCandidate` 子类。
   - S0 新 IR 的嵌套 source helper 在读取字段前要求精确 `IRSource`。fingerprint、classifier、scope build
     和 family view 等复用入口也拒绝 snapshot/source/catalog 子类，普通 raw Mapping/list 仍复制、校验、冻结。

## 权威入口

最终命令：

```text
PYTHONPYCACHEPREFIX=/tmp/hsr_p9_s0_round5_authority_pycache \
  /usr/bin/time -v \
  -o /tmp/hsr_v8_p9_s0_scope_and_projection_round5_final_time_v.txt \
  timeout 480s nice -n 10 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s0_scope_and_projection_contract \
  --tbgd-root ../../turnbasedgamedata-main \
  --output-dir /tmp/hsr_v8_p9_s0_scope_and_projection_round5_final
```

整个 S0 执行线程累计公开主入口 7 次；每次原因和结果如下：

| 次数 | 原因 | 结果 |
|---:|---|---|
| 1 | 首轮诊断 | 定位首版实现问题；旧 evidence 不作为当前结论 |
| 2 | 首轮最终入口 | 生成首版 evidence，随后被第一轮代码审查否决 |
| 3 | 第一轮差量最终入口 | 生产 catalog green，但旧 limited-catalog 谓词令 summary false |
| 4 | 第二轮授权最终入口 | summary green，随后第三轮独立构造探针发现四项绕过 |
| 5 | 第三轮授权最终入口 | `0.09 s` 早退；错误地要求 raw `AvatarID: str`，未生成可用 summary |
| 6 | raw 标量修复后的授权最终入口 | 退出码 0，随后第四轮审查发现内部模型子类绕过 |
| 7 | 本轮唯一授权最终入口 | 退出码 0，`ok=true`、`business_ok=true`，catalog complete 且 issues 为空 |

第 5 次失败为 `avatar source identity incomplete:ExcelOutput/AvatarConfig.json:0`。本次修复前先运行
inventory-only 探针：三表 manifest 构造成功、候选规范排序、bool/float 拒绝；随后单 ability 协调伪造
探针在 snapshot 构造边界被 `ValueError` 拒绝。

第 7 次前的子类微探针逐项证明 catalog 六类成员、DocumentProjection、snapshot manifest/source、嵌套
`IRSource`、candidate fingerprint 及公开复用入口均拒绝 no-op `__post_init__` 子类。fake projection 的普通
dict payload 可在外部修改，但该对象从未进入 catalog。第 7 次后没有重跑权威入口。

## 当前 evidence

以下数量均为第 7 次入口从当前 raw source 动态观测，不是固定通过条件：

| 项目 | 当前观测 |
|---|---:|
| target source | 79 main + 1 shared |
| inventory read / parse | 3 / 3 |
| ability read / parse | 80 / 80 |
| materialized record | 48,547 |
| typed node / Event / structural entry | 44,700 / 2,462 / 1,385 |
| projection | 435（379 resource、4 target、52 environment） |
| decode-required | 213 |
| non-gameplay retired | 10,432 |
| full lowering 调用 | 0 |

关键负例均为 green：document/bytes 不一致、coordinated inventory forgery、manifest 非法标量、
record/projection source evidence 伪造、inherited terminal 伪造、同对象正反顺序与冲突 scope、family
祖先闭包、空/伪 projection、projection 子类、snapshot manifest 子类、catalog 完整性和机器可读
external dependency。

## 资源与路径

- 验证器内部墙钟：`11.069706 s`；预算 `480 s`。
- `/usr/bin/time` 墙钟：`11.58 s`；退出状态 `0`。
- 峰值 RSS：`336,224,256 bytes`（`328,344 KiB`）；预算 `1 GiB`。
- evidence：`1,457,873 bytes`；预算 `5 MiB`。
- 验证代码：`898` 个非空行；预算 `900`。
- 最终 summary：
  `/tmp/hsr_v8_p9_s0_scope_and_projection_round5_final/summary.json`
- evidence 目录：
  `/tmp/hsr_v8_p9_s0_scope_and_projection_round5_final/`
- 资源日志：
  `/tmp/hsr_v8_p9_s0_scope_and_projection_round5_final_time_v.txt`

`compileall`、`git diff --check` 和新增文件 whitespace 检查成功。未运行 P1-P8 聚合、完整 lowering、
`validate_v0_209`、完整 RuleBook、runtime/replay 或全角色出生。

## 修改文件

- `simulator_v8_clean_core/rules/ir.py`
- `simulator_v8_clean_core/rules/__init__.py`
- `simulator_v8_clean_core/tbgd/character_ability_scope.py`
- `simulator_v8_clean_core/tbgd/__init__.py`
- `simulator_v8_clean_core/tools/validate_p9_s0_scope_and_projection_contract.py`
- `live_validation_reports/v8_p9_s0_scope_and_projection_contract_ready_for_review.md`

`simulator_v8_clean_core/ir_types.py` 当前无差异。执行线程未修改总计划 checklist、未提交 Git、
未进入 S1；验收线程已勾选 S0 清单并建立检查点。开工前已有无关 dirty scope 保持原样。

## 遗留 gap

- 当前 213 条 decode-required 仍保留完整 raw 字段、JSON path 和父分支，不进入 gameplay。它们属于后续
  解码阶段的真实未知/混淆 family，不包含本轮已知特殊资源状态。
- 当前完整角色能力来源没有 unit-topology producer；状态为机器可读 `external_content_dependency`。
- S0 只建立 scope/catalog/projection 契约，不提供 runtime 执行语义；后续阶段仍须消费这些正式 IR。
