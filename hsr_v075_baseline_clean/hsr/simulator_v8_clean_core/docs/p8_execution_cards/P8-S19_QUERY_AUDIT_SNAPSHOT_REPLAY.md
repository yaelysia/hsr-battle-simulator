# P8-S19 查询、审计、snapshot、replay 与紧凑状态执行卡

## 执行配置

- 对应问题：P8-I15、P8-I16。
- 硬前置：P8-S18 已验收并形成统一装配/出生检查点。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`max`。
- 推荐模式：普通聚焦模式，集成 worktree 串行执行。
- 选择理由：本阶段定义 UI/推演器可见契约、回放可信边界和状态体积，需要精确控制暴露信息；不适合让 Goal 模式顺手做 UI。

## 当前事实与阶段结果

S18 提供正式装配结果和出生流程；现有 RuleBook、P7 query/submit、snapshot/replay、source audit 和 compact semantic state 已有通用基础，但尚未完整表达装备目录、构筑 manifest 和装备来源。开始前必须审查当前 API/view model 是否自行计算命途、词条、套装或面板，并列出所有外部 consumer。

完成后，UI/场景编辑器/未来推演器可以只读查询角色资格、光锥目录、遗器模板、槽位合法主词条、构筑校验和装配摘要；只能提交选择，所有规则由 assembler 返回。snapshot/replay 以不可变 manifest、build/result fingerprint 和 source/IR fingerprint 锁定构筑；compact state 只保留影响未来分支的身份与动态状态，不随完整装备目录线性增长。静态 term 和动态 mutation 均可按需反查完整 provenance。

## 本阶段只做

- 建立只读、分页/窄查询的光锥、遗器模板/套装、槽位/词条合法性和构筑验证接口。
- 建立装配摘要：状态、最终面板、逐项静态贡献、激活/未激活机制、套装档位和结构化 blocked reason。
- 明确提交 schema 只接受定义/实例/roll 选择，不接受最终面板、set active、path active 或效果结果。
- snapshot/replay 保存版本化 build manifest、build/result fingerprint、source fingerprint、Canonical IR fingerprint 和 engine-rule version。
- replay 重新装配并比较规范结果，再执行 transition；陈旧、篡改或来源不一致 fail-closed。
- compact state 保存 build identity、provider identity 和当前动态状态，不复制完整定义/ledger/raw provenance。
- 扩展 source audit query，使面板 term 与 runtime settlement/mutation 可走到实例、定义、IR 和 TBGD。

## 本阶段不做

- 不制作配置/战斗/结算 UI 布局，不在前端复刻规则。
- 不允许推演器在战斗中换装或搜索配装；构筑在开战前固定。
- 不把完整装备目录、raw source 或完整 ledger 复制进每个 BattleState。
- 不执行新的装备机制，不回修 S8/S17 内容 gap；若发现回归则阻断并退回对应阶段。

## 查询与回放不变量

1. 查询是纯函数/只读操作：不注册 provider、不触发事件、不推进 timeline、不改变 RNG ledger。
2. UI 提交的任何派生规则值都拒绝；view model 可格式化但不能成为可信输入。
3. snapshot manifest 足以重新装配同一结果，不能只存最终面板；replay 必须验证所有 fingerprint/version。
4. compact state 的大小与已安装完整装备目录规模无关；provenance 通过外部索引按需查询。
5. source audit 使用稳定 identity 连接，不从日志文本、显示名称或路径猜测。
6. query 返回 `resolved|blocked` 和候选/原因，缺失或歧义不取第一项。
7. 任何篡改 ledger、manifest、fingerprint 或 provider identity 都阻止精确回放，state unchanged。

## 目标与证据映射

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 目录/合法性查询 | 唯一类型、只读、缺失/歧义结构化 blocked | query matrix |
| UI 只提交选择 | final panel/set active/path active 等字段拒绝 | submission negatives |
| 查询纯度 | 前后 state/provider/RNG/timeline 完全相同 | purity snapshots |
| manifest round-trip | 构筑导出/导入/重装配结果完全一致 | build round-trip matrix |
| stale/tamper 拒绝 | source/IR/engine version/ledger 任一变化 replay blocked | replay negatives |
| compact 预算 | 增大目录规模不线性扩大单节点语义状态 | size budget report |
| 来源 walkback | 静态 term 和动态 mutation 各自完整反查 | audit samples |
| P7 契约不退化 | 未修改调用链继承检查点；实际修改时运行对应最小 direct | direct trigger record |

## 拟改文件与关键符号

- `rules/rulebook.py`：装备窄查询，不暴露内部可变对象。
- 可新增 `queries/equipment.py` 或现有 query 层：目录、合法性和装配摘要 view model。
- `scenarios/schema.py`、loader/identity：版本化 manifest 输入输出。
- `snapshot.py`、`replay.py`、P7 compact semantic state：增加稳定装备引用，不复制目录。
- source audit/settlement 查询模块：扩展装备 provenance walkback。
- `simulator_v8_ui` 只允许做 API 边界迁移和显示字段接线，不做布局或规则。
- `tools/validate_p8_s19_query_audit_snapshot_replay.py` 和阶段报告。

开始前用 CodeGraph 列出查询、snapshot/replay 和 compact state 的 consumer/producer。若 UI 当前含规则计算，移除并改为展示 core 结果；不修改视觉布局。

## 结构化验收谓词

```text
equipment_queries_typed_and_read_only=true
query_missing_and_ambiguous_fail_closed=true
query_causes_no_state_change=true
ui_submits_choices_only=true
derived_activation_inputs_rejected=true
build_manifest_round_trip_equal=true
replay_reassembles_before_transition=true
source_fingerprint_mismatch_rejected=true
ir_fingerprint_mismatch_rejected=true
engine_rule_version_mismatch_rejected=true
tampered_ledger_rejected=true
compact_state_excludes_full_catalog=true
compact_state_growth_not_linear_with_catalog=true
static_and_dynamic_sources_walk_back=true
action_query_submit_contract_unchanged=true
```

## Gap 与停止条件

- 查询为方便 UI 需要 core 暴露/接受派生规则：设计不合格，改 view model，不改 core 事实来源。
- replay 只能比较最终面板而无法重装配 manifest：`implementation_missing`，本阶段必须补齐。
- compact state 需要完整 ledger 才能决定未来分支：先区分语义状态与审计索引，不直接塞入状态。
- S8/S17 graph 在当前装配中重新 blocked：停止并退回所属阶段，不在 S19 放宽 replay/admission。
- API schema 变化不兼容旧 UI fixture时，迁移当前工作区调用者，不做旧 v7/旧 JSON 兼容。

## 验证命令与资源

生产边界先保证：查询、提交、manifest、snapshot 和 replay API 直接拒绝派生规则输入、过期身份、篡改指纹和线性复制完整目录的状态结构；失败必须保持状态不变。验证器只调用这些公开契约，不能自行重装配或比较一套简化结果。

本阶段固定只运行一个业务主验证：

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v -o /tmp/hsr_v8_p8_s19_time_v.txt timeout --signal=TERM 10m ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p8_s19_query_audit_snapshot_replay --tbgd-root ../../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s19_query_audit_snapshot_replay
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s19_pycache python3 -m compileall -q simulator_v8_clean_core
git diff --check
```

- 主验证使用一次受控 RuleBook，复用当前指纹下 S8/S17 结论，不重新跑 ability transition。compact budget 使用受控规模探针，不复制真实大对象。
- 已验收的 P7 query、replay 和 compact 契约直接继承。只有实际修改对应共享模块时才运行其最小 direct，最多 2 项，不固定重跑三个旧验证。
- 只有 UI 文件或 UI 契约调用者实际被修改时才追加 UI typecheck/build；纯 core 改动不得编译整个 UI。
- 完整主验证最多一次诊断运行和一次最终运行；中间修复只跑失败 API/replay/size 切片。
- 单次主验证预算：墙钟 10 分钟、峰值 RSS 1 GiB；阶段累计验证预算 20 分钟；默认产物不超过 10 MiB。超限立即暂停。
- 禁止全阶段聚合、完整 snapshot/catalog dump、全 ability transition 和 `validate_v0_209`。

## Ready-for-review 产物

- 查询/提交 schema、纯度矩阵和 UI 规则移除清单。
- manifest round-trip、stale/tamper/replay 负例和 compact size budget。
- 静态 term 与动态 mutation 来源反查。
- consumer 迁移、direct 触发判定、资源和未运行范围报告。

## 唯一执行清单（仅验收线程可勾）

- [ ] 装备目录、合法性和装配结果查询类型化、只读、fail-closed。
- [ ] UI/外部层只提交选择，所有派生规则输入均拒绝。
- [ ] manifest/fingerprint/version 可重新装配并锁定 snapshot/replay。
- [ ] stale、篡改和伪来源回放 state unchanged。
- [ ] compact state 不复制完整目录/ledger/raw，尺寸预算通过。
- [ ] 静态/动态来源 walkback 完整；P7 契约未被实际改动，或已通过对应最小 direct。
- [ ] `ready_for_review` evidence 完整，阶段无查询/回放 blocker。
