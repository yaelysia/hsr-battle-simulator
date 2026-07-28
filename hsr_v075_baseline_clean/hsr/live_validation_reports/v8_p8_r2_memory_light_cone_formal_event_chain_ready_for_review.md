# P8-R2 记忆光锥正式事件链 `ready_for_review`

## 状态

执行线程状态：`ready_for_review`

验收线程状态：`accepted`（2026-07-28）

本轮基于检查点 `419e476`，按原执行卡与最终差量卡施工，差量卡优先。
P8-R2 Checklist 已由验收线程勾选，代码与报告随本次验收检查点提交。

## 本轮审查阻断收口

### 1. 死亡回响正式前置链

Equip36 现在由一个明确 fixture 边界之后的连续正式战斗链证明：

1. 两个正式 servant spawn 完成后、首个动作开始前，一次性把被击败忆灵
   `HP=1`，并设置“己方忆灵先行动、敌方忆灵随后行动”的初始行动值；
   同时清除旧 turn marker。该 fixture 是本链唯一的非交易状态边界。
2. 己方忆灵通过 `DecisionSystem -> ActionCommand -> submit` 行动。
3. `MEquip_23049_Listen/OnBeforeSkillUse` 执行
   `AddModifier:MEquip_23049_Sub`。
4. 动作前装备者没有 `MEquip_23049_Sub`，动作后状态存在。
5. 状态写入产生 `2` 个 mutation，均有绑定 settlement，来源为
   `Config/ConfigAbility/Equip/Equip36.json`。
6. 首个动作的最终 snapshot 与第二次
   `DecisionSystem.advance_to_decision` 的输入 snapshot 完全相同；两者之间
   没有 HP、行动值或 turn marker 的直接写入。
7. 正常 scheduler transition 自然选出敌方忆灵；该内部 transition 的
   settlement、来源审计、replay、前后 snapshot 连续性均通过。
8. 敌方忆灵通过同一正式入口完成致死动作。
9. `OnDeathrattle` 的 `ModifySPNew` 执行真实效果：装备者能量
   `0.0 -> 8.0`，产生 `1` 个 mutation 和 `1` 条
   `resource_delta` settlement。

注意：该 Canonical IR 中 `ModifySPNew` 修改的是角色能量，不是团队战技点。
最终 transition 的 source audit、settlement trace 和 replay 均通过。

本次共执行 `3` 次正式动作：

- 一次普通忆灵动作，同时证明 `SetDynamicValueByCopying` 与
  `SetModifierDynamicValue`。
- 一次己方忆灵前置动作，获得死亡回响所需状态。
- 一次敌方忆灵正式致死动作。

致死交易只包含一个规范死亡事件：

- event id：
  `event:mutation_backed:mutation:831e90b7c7f735f8:unit_defeated`
- lifecycle mutation id：`mutation:831e90b7c7f735f8`
- event、defeat record、目标实体和 lifecycle mutation 身份一致。

三类死亡监听对同一规范事件完成裁决：

- `OnDeathrattle`：`executed`
- `OnListenCharacterDie`：`true_scope_no_match`，生产 scope 原因为
  `scope_kill_credit_owner_mismatch`
- `OnTriggerDeath`：`true_scope_no_match`，当前场景没有激活对应 modifier

### 2. 同事件身份冲突 fail-closed

executor 先统一解析显式或自动事件身份，再对每个同身份重复项无条件比较。
普通重复事件只允许：

- `event_type`、来源、目标、窗口、`process_only` 和完整 payload
  全部相同。

payload 补全只允许来自 dispatcher 返回的显式 provenance，目前只有两个
逐字段白名单：

- 类型化目标补入与真实 `target_id` 相同的 `param_entity_id`。
- dispatcher 递归派发回调子事件时补入固定
  `mutation_event_depth=1`。

两条受控路径都会先固化补全前的自动身份；任何其他字段变化均 blocked。

轻量负例覆盖：

- 显式身份事件与自动生成相同身份事件发生来源冲突。
- 两个自动身份事件只在 `process_only` 上不同。
- 同一身份 payload 注入 `callback_events`。
- 同一身份 payload 注入伪造 `param_entity_id`。
- 既有 `event_type`、来源、目标、payload 和 `process_only` 冲突。

所有负例均保持 state unchanged，提交的 mutation、event、RNG 数均为 `0`。
完全相同重复项和 dispatcher 受控 `param_entity_id` 规范化正例各保留一个事件。

### 3. 窄投影身份冲突

生产 lowering 与 R2 窄投影共用严格身份合并：

- 完全一致且来源一致的重复 IR 合并为一项。
- 内容不同或来源不同的同身份 IR 抛出
  `ir_identity_conflict`。
- 冲突在 RuleBook 构建前阻断，负例明确记录
  `rulebook_constructed=false`。

严格合并同时暴露并移除了旧的重复 callback task lowering 生产路径；
正式 callback lowering 现在只有一个来源。

### 4. 报告归属

本报告已从内核包内部迁移到仓库级：

`hsr/live_validation_reports/`

### 5. 目录启动重复角色动作修复

目录入口此前把基础 RuleBook 已有角色动作与 owned-combatant 投影动作直接拼接，
使完全相同的 `ActionDefinitionIR` 在 `(action_id, level)` 下形成多个候选。
角色装配器正确地将其判为歧义，但目录矩阵随后把 14 张记忆命途光锥误报为装备缺口。

`_focused_bundle()` 现在于 RuleBook 构建前复用生产 lowering 的
`merge_identical_ir_items`，按 `definition_id` 执行严格合并：

- 完全相同（包括来源相同）的重复动作定义合并为一项。
- 同一身份下内容或来源不同会抛出 `ir_identity_conflict`。
- 不任取第一项，也不修改角色装配器的唯一候选要求。

## 保持通过的既有结论

- 两项动态值任务继续由同一次正式忆灵动作证明。
- 基础类型监听没有继续使用忆灵出生作为错误生产者，仍诚实分类为
  `external_content_e2e_deferred`。
- `OnCustomEvent`、`OnListenModifierAdd`、
  `OnListenModifierOnStack` 保持结构化 external content deferred。
- 完整 `TBGDLowering.build()` 调用数为 `0`。
- 来源投影与来源真实 RuleBook 各构建 `1` 次。

## 最终 R2 聚焦验证

修正后的最终证据：

`/tmp/p8_r2_focused_final_continuous_fix2_20260728/validation_summary_p8_r2_memory_light_cone_formal_event_chain_closure.json`

结果：

- 退出码：`0`
- `ok=true`
- `ready_for_review=true`
- 验证器计时：`103.203s`
- 外部 wall time：`1:43.71`
- 验证器峰值：`571.824 MiB`
- `/usr/bin/time` maximum resident set size：`585548 KiB`
- summary artifact 实际文件大小：`97777 bytes`
- 正式动作：`3`
- 扫描能力文件：`15`
- 解析能力文件：`3`
- 完整 lowering：`0`

摘要内嵌的 `artifact_size_bytes=97709` 是写入该字段前的文件尺寸；最终文件
经第二次序列化后由 `stat` 核对为 `97777 bytes`。本报告使用最终落盘尺寸。

本次审查意见后的第一次聚焦运行保留在：

`/tmp/p8_r2_focused_final_continuous_20260728/`

该次运行资源达标，但业务失败，暴露出两项事实：普通动态场景仍依赖旧辅助函数
改行动顺序；dispatcher 的回调子事件还存在一条未声明的
`mutation_event_depth` 受控补全。前者已移到首动作前 fixture，后者已纳入
dispatcher provenance 和严格单字段白名单；随后才进行了上述通过运行。

## 直接契约与回归

- 同事件身份冲突直接契约：通过
  - 证据：
    `/tmp/p8_r2_direct_event_fix_20260728/direct_death_identity_contract_p8_r2.json`
- P7-S3 selected graph atomic commit：通过，`9` 个 case
- VG-S2 committed integrity lifecycle：通过，positive `14`、
  negative `25`
- P8-R1 runtime-only：通过

最终静态检查：

- `compileall`：通过
- `git diff --check`：通过
- 工作区未新增 `.pyc`、`__pycache__` 或重型验证产物

## 唯一一次目录启动

修复目录入口后仅运行：

```text
python3 -B -m simulator_v8_clean_core.tools.validate_p8_s8_light_cone_remaining_gameplay_closure \
  --tbgd-root /home/zhangjinhao/code/hsr/turnbasedgamedata-main \
  --output-dir /tmp/p8_r2_catalog_startup_final_20260728 \
  --catalog-startup-only
```

证据：

`/tmp/p8_r2_catalog_startup_final_20260728/validation_summary_p8_s8_catalog_startup.json`

结果：

- 退出码：`0`
- `ok=true`
- `formal_catalog_startup_complete=true`
- `started=162`
- `equipment_failure_count=0`
- `external_character_build_dependency_count=0`
- focused RuleBook：`1`
- owned-combatant catalog lowering：`1`
- 完整 `TBGDLowering.build()`：`0`
- full S8 matrices：未运行
- 外部 wall time：`36.34s`
- `/usr/bin/time` maximum resident set size：`905952 KiB`

该专用目录摘要保持 `ready_for_review=false`，因为它不修改 checklist 或创建 Git
提交；业务 gate 由 `ok=true` 与 `formal_catalog_startup_complete=true` 表示。
本执行线程仍只提交本报告的 `ready_for_review`。

## 明确未运行

- 未运行九族组合或未过滤 S8 聚合。
- 未运行完整 lowering。
- 未运行 full 验证。
- 本次目录差量没有重跑 R2 聚焦验证。

验收结论：P8-R2 通过。两条真实记忆光锥来源的正式事件链已经闭合，当前
162 张已发布光锥全部完成低内存正式目录启动；未恢复完整 lowering 或旧重聚合 gate。
