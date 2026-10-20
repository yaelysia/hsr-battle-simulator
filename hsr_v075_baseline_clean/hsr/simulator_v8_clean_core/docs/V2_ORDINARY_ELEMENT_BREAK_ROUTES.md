# V2 剩余五元素普通击破自然路线

执行：dsh / DeepSeek；范围、约束与集中验收：Codex。基线为 `fc2e6ff`，当前状态只在
[交接文档](../../CODEX_HANDOFF.md)维护。

## 一次交付的成果

补齐火、雷、冰、量子、虚数五条普通单韧性自然路线。每条均从正式构筑与来源波次入场，
经合法技能完成：首次击破 → 元素后续效果 → 自然恢复 → 同一目标再次击破 → 后续合法行动。
优先合并修复这五条路线暴露的共享接线问题，整批交回，不按元素逐项等待验收。

无需为了结束脚本强行击杀目标；可以保存可继续操作的会话，明确战斗未完。

## 交付范围与证据

五条路线使用正式构筑与来源波次，固定外部命令；战斗在交付链完成后允许未结束。集成入口为
[test_ordinary_element_break_natural_routes.py](../tests/test_ordinary_element_break_natural_routes.py)，
场景与固定命令位于 `examples/cli/`。

| 元素 | 角色/构筑 | 关卡/敌人 | 自然操作结果 | 剩余依赖 |
| --- | --- | --- | --- | --- |
| Fire | 艾丝妲 avatar:1009 E0/Lv1/P0 空装备；娜塔莎 avatar:1105 E0/Lv80/P6 空装备 | stage 201011361 wave0，两只 Lv32 8001020（Fire/Wind，单层韧性 30，HP 340.32） | 6 条固定命令：普攻首破 → `MCommon_Element_Burn` tick → 自然恢复 → 同目标二次击破 → 治疗后置；CLI exit 3，战斗未完 | 无 |
| Thunder | 阿兰 avatar:1008 E0/Lv1/P0 空装备；娜塔莎 1105 E0/Lv80/P6 | stage 202110311 wave0，8001050（Fire/Thunder，韧性 30，HP 340.32）+ 8001040 | 6 条：普攻首破 → `MCommon_Element_Electric` tick → 恢复 → 二次击破 → 治疗后置；CLI exit 3 | 无 |
| Ice | 三月七 avatar:1001 E0/Lv1/P0；娜塔莎 1105 E0/Lv40/P2（计划角色佩拉 1106） | stage 202232051 wave0，单只 Lv32 8001010（Physical/Ice，韧性 30，HP 340.32） | 7 条：首破 → 冻结回合 `control_skip`（含冻结 ByBreakDamage 与 expire，该回合不恢复）→ 解冻后下一自然回合恢复 → 二次击破 → 后续行动 | 佩拉普攻 `avatar_skill:110601` 任务图未准入（hit_random_sequence / projectile source shape） |
| Quantum | 玲可 avatar:1110 E0/Lv1/P0；娜塔莎 1105 E0/Lv80/P6（计划角色希儿 1102） | stage 400020800 wave0，两只 Lv28 8011020（Physical/Quantum，韧性 30，HP 482.03） | 6 条：首破 → Entangle 计数 1→2（真实命中）→ 到期一次结算 → 恢复 → 二次击破（共享修复后新生命周期起始 stacks=1）→ 后续行动；CLI run exit 3，独立 replay 13 步 0 错误 | 希儿增强版 after_attack 缺 `AdmittedActionTargetFact`；青雀构筑未准入；雪衣任务图 ByAnd 阻断 |
| Imaginary | 同谐主 avatar:8005 E0/Lv1/P0；娜塔莎 1105 E0/Lv80/P6（计划角色瓦尔特 1004） | stage 1022231 wave0，两只 Lv32 1022020（Ice/Wind/Imaginary，单层韧性 60，HP 1446.38） | 15 条（含 1 条 `timeline:select_tied_actor` 同速选择）：两发普攻首破 → 禁锢减速 -10% 与延后 0.3×full_AV → 到期恢复 → 二次击破 → 后续合法行动（敌方）；CLI exit 3 | 瓦尔特增强版监听缺口；1305 SetDynamicValueByStatusCount；1304 dynamic_hash_unbound；1213 任务图；1313/1404/1506 构筑准入；1203 condition fact 生产者；怪物 2011010 被动图 / 3001020 projectile / 1012030 敌动作 |

计划角色与实际角色不同均因正式准入阻断，未跳过被动、删任务或伪造绑定；示例文件已按实际角色
改名（`pela_ice_break_natural` → `march7th_ice_break_natural`，`seele_quantum_break_natural` →
`lynx_quantum_break_natural`，`welt_imaginary_break_natural` → `trailblazer_imaginary_break_natural`）。
五行表“剩余依赖”是该元素继续扩展的阻断，不影响本批普通单韧性自然链的验收。

### 共享修复：状态作用域动态值清理

- 缺陷：status 作用域动态值在状态移除/过期后残留于 `dynamic_value_store`；break 状态
  `instance_id` 由来源哈希确定，二次生命周期复用同一 id 时会读到上一生命周期的计数
  （量子纠缠二次击破 stacks/dv 串值）。
- 修复：`systems/dynamic_values.py` 新增 `remove_status_instance_entries`（同时清理 references
  的 `operation_ledger`）；`systems/status.py` 在 remove/expire plan 同一事务追加
  `status_dynamic_value_cleanup` mutation + settlement record。
- 组件回归：`tests/test_status_dynamic_value_cleanup.py`（5 passed，含多目标移除、驱散两个调用者
  的原子合并，以及保留条目/索引/ledger/结算关联的差分审计篡改回归）。
- 多目标移除：`apply_remove_modifier` 与 `apply_dispel_status` 原先对每个目标都从同一原始 state
  规划整仓写入；现改为在候选状态上逐目标规划，同一原子返回中的多次清理合并为可顺序提交的
  mutation 序列，两个调用者均已覆盖。〔`systems/status.py`〕
- 差分审计：`core/source_audit.py` 现对 `global_flags.dynamic_value_store` 清理 mutation 校验精确
  差分——只允许删除 metadata 指定 `status_instance_id` 的 status 作用域条目及其 operation ledger
  行，保留条目、索引和结算关联必须完全一致；防止合法移除来源借机携带其它改动。
- 影响验证：五路线集成模块 5 passed；wind + `test_ordinary_break_recovery.py` 3 passed。

### 验证证据与成本

- 五路线模块 1 次运行：`5 passed in 335.81s`（墙钟 5:19，峰值 RSS 703,132 KB）。
- 受影响既有检查同一次调用：`test_ordinary_wind_break_natural_route.py` +
  `test_ordinary_break_recovery.py`，`3 passed in 144.52s`（墙钟 2:17，RSS 862,692 KB）。
- 量子归档 1 次生成：`/tmp/hsr-v2-quantum-postfix.json.gz`（CLI run exit 3，41.70s，
  RSS 501,172 KB，归档 225,072 B）；独立 replay exit 0，`{"ok": true, "step_count": 13,
  "errors": []}`，49.46s，RSS 498,424 KB；归档未提交。
- 集中验收 P2 修复后复验：Codex 两处边界复现
  `/tmp/test_v2_cleanup_review.py` `2 passed`（0.50s）；量子+虚数定向 1 次
  `2 passed in 225.34s`（墙钟 3:35，RSS 876,008 KB）；组件清理回归 1 次 `5 passed`（0.78s）。
  其余三条自然路线未受影响，按验收要求复用既有证据。
- 探索性编译/逐角色准入探查属过程成本，不计入验收必需运行；本批验收必需重任务为模块 1、
  受影响检查 1、CLI run 1、replay 1，以及 P2 复验的边界回归 1、量子+虚数定向 1。
  全程串行并复用编译缓存。

## 已核对事实与入口

- 普通击破已有 `BreakSystem`、状态回调、生命周期、调度恢复与来源审计；不另写元素结算器。
- 物理已有自然交战路线；风已有完整自然多轮检查
  [test_ordinary_wind_break_natural_route.py](../tests/test_ordinary_wind_break_natural_route.py)，
  可复用其公开操作、原生记录检查与缓存使用方式。
- 固定 `AvatarSkillConfig` 的 Lv1 普攻声明如下；这些是选角起点，不等于完整角色已验收。
  默认采用 E0、空装备、未选额外行迹的正式构筑；等级、晋阶按生存与目标血量需要合法配置。

| 元素 | 优先角色 | 普攻来源 | ShowStanceList 主目标 |
| --- | --- | --- | --- |
| Fire | 艾丝妲 `1009` | `100901` | 30 |
| Thunder | 阿兰 `1008` | `100801` | 30 |
| Ice | 佩拉 `1106` | `110601` | 30 |
| Quantum | 希儿 `1102` | `110201` | 30 |
| Imaginary | 瓦尔特 `1004` | `100401` | 30 |

先核对候选角色的正式构筑启动与必要被动。若某候选有无关复杂依赖，可换同元素合法角色，
注明原因；不能跳过被动、删任务或伪造自有绑定来让启动通过。辅助角色优先复用娜塔莎。

生产与消费链：`battle_catalog.build_battle_rulebook` 范围编译 → `ScenarioStateBuilder` 正式
构筑/波次/出生 → `BattleSession.advance/submit` → 来源技能伤害与削韧 →
`BreakSystem.enter_if_depleted/enter_break` → 公共监听/元素状态 → 调度器自然回合与状态生命周期
→ `recover_ordinary_before_action` 或来源要求的控制恢复路径 → 后续行动、审计与归档。
修改前沿实际调用者确认各环节的生产权威，不能在测试、CLI 或 session 中补算规则。

## 实现边界与不可变条件

1. **自然输入**：敌人必须来自真实关卡波次，有对应元素弱点、普通单层韧性及足够存活时间。
   构筑、等级、关卡和合法操作用于调节路线；不注入或覆盖 HP、弱点、韧性、状态、时间线、
   队列、RNG 结果，不把中途改写 `session.state` 的夹具当自然路线。
2. **完整操作链**：通过公开合法动作与目标查询、`advance/submit` 推进双方。敌方仍由外部
   操作选择；控制跳过的回合不伪造敌方提交，不增加自动战斗策略。普通击破不能重复结算初始
   伤害、公共延迟或韧性减伤，恢复后再次击破必须生成新的正式生命周期。
3. **元素语义分别核对**：火/雷检查真实灼烧/触电的来源与自然扣血；冰检查冻结消耗行动及
   解冻后的行动时序；量子通过实际命中检查纠缠计数变化及到期的一次结算；虚数检查禁锢的
   减速、延后与到期恢复。纠缠/禁锢到期不能照搬冻结的跳过行动。复用来源与已采纳参数，
   不为凑路线硬编码系数、层数、时序或最终血量。
4. **共享权威**：发现错误修正式共享生产者/消费者，并核对其调用者；保留任务身份、施加者、
   实例身份、参数来源、mutation 与 settlement 的一致性，不能从审计日志反推 runtime 输入。
   有实际提交边界改动时，复用或补一个能证明失败不泄漏状态、mutation、RNG 的检查。
5. **范围固定**：普通单韧性、存活施加者、来源无特殊免疫的普通敌人。本批不扩展 I7 特殊
   韧性/强制击破、BigBoss/Elite 特殊分支、死亡来源 DOT 或任意构筑组合。缺口按真实依赖
   阻断，不能为样例跳过校验。可靠规则资料按现有约定采用，不重新研究已采纳结论。
6. **工程边界**：无新依赖/环境、不动 submodule、不改公共接口兼容方向；不提交、不推送。
   必要生产代码修复可跨共享文件，交付不限定为只写示例；不建新的验证平台或通用测试框架。

## 验收与成本

- 五条路线分别保存 `examples/cli/` 场景与同名 `.commands.json`，CLI 可以直接复现。
  在一个 `integration` 测试模块集中检查上述自然链和各元素差异；复用现有测试辅助方式，
  不复制五份风路线测试，也不单凭脚本成功退出认定元素生命周期正确。
- 断言应读正式事件、mutation、状态实例、参数与结算来源，检查恢复与再次击破的顺序。
  普通攻击自身的异常状态不能冒充击破状态；中途死亡导致未走到恢复不能算该路线通过。
- 使用场景范围编译与现有缓存，重任务串行，记录耗时及可取得的峰值内存。不默认全目录
  编译或全量回归；改变共享逻辑才选取实际受影响的既有检查。
- 可复用的组件入口：`test_initial_break_base.py`、`test_ordinary_frozen_turn.py`、
  `test_quantum_entanglement_count.py`；恢复与风回归分别见 `test_ordinary_break_recovery.py`、
  `test_ordinary_wind_break_natural_route.py`。按改动选择，不逐项叠加成强制套餐。
- 五条自然路线各运行一次；选量子路线保存归档并独立文件 replay 一次，复用同一编译缓存。
  其它路线不附加相同回放。新增模块可命名 `test_ordinary_element_break_natural_routes.py`，运行：

  ```bash
  .venv/bin/python -B -m pytest -o addopts='' -q -m integration \
    hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_ordinary_element_break_natural_routes.py
  ```

交回时用五行表写清角色/构筑、关卡/敌人、自然操作结果及剩余依赖，附实际命令和必要成本。
成功与阻断分别报告，组件证据与自然路线分别报告。CLI/测试入口补简短说明；交接覆盖更新
本批状态与入口，不追加逐轮修复日志或新历史快照。整批集中验收后由 Codex 提交基线。
