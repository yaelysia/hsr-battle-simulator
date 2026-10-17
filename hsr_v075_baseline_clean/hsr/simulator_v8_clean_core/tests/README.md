# 当前验证入口

从仓库根目录使用已有 uv 环境；不创建环境、不安装新依赖。
日常先选受影响文件或用例，例如改编译缓存时：

```bash
.venv/bin/python -B -m pytest hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_compile_cache.py
```

将路径替换为本次相关测试，也可加 `-k` 选择用例。省略路径的 `pytest` 会运行全部普通回归，
仅在广泛影响或版本验收需要时使用，不是每次修改后的默认命令。
以下各节是可选入口，不是必跑清单；检查已覆盖实际风险且通过即停止，选择依据见
[本地执行与验证约定](../docs/AGENT_WORKFLOW_AND_VALIDATION.md#验证选择)。
`integration` 标记表示完整来源编译或真实场景，显式选择：

```bash
.venv/bin/python -B -m pytest -m integration \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_pre_action_dot_defeat.py
```

替换路径可选择其它检查；省略路径会运行全部集成检查。
集成组件探查不等同于游戏操作整链，支持边界见各测试与 CLI 文档。

`TBGDLowering.build()` 默认复用持久化编译缓存，CLI、UI 和独立回放共用此入口。
默认目录为 `/tmp/hsr-v8-ir-cache-<uid>`，可用 `HSR_IR_CACHE_DIR` 指定持久目录。
来源 JSON（含仅供展示的 TextMap）、生产代码、Python 主/次版本、内容范围或 lowering limits
变化时自动失效；每个范围只保留一个版本，损坏缓存重新构建，并发冷编译串行发布。
需要证明 lowering 自身结果时显式使用 `build(..., use_cache=False)`，不以缓存命中冒充重新编译。
缓存只保存已验证的类型化 IR，不改变运行时准入、来源审计或归档指纹。
修改 Python 代码后先重启常驻服务以载入新代码；缓存不承担模块热重载。

共享免疫与一次性保护消费使用 `test_status_shared_immunity.py`；其中真实玲可 E2 来源小检查
从正式状态施加进入 `OnImmuneDebuff` 并移除保护，覆盖不同 caster/owner、免疫先于效果抵抗、
回调只消费一次、来源审计与失败原子回滚。单位和 incoming 异常是组件输入，不代表完整
角色实战。单纯改这条路径不需要全目录编译或重复已有战斗；相关抵抗检查为
`test_status_control_resistance.py`。
`test_status_fuxuan_immunity.py` 复用同一小范围来源装配，覆盖 typed incoming 控制条件、
同技能两目标仍免控、正式 TurnEnd 清理全队保护、来源审计及清理末叶失败回滚。
队列开始通知的时机与失败边界使用 `test_queue_terminal_callbacks.py`：正文前真实消费，
取消无开始通知，正文失败只保留 process_only 阻断诊断；不编译完整内容或运行整场。

Remodifier 查询与精准实例操作使用 `test_remodifier_status_scope.py` 和
`test_remodifier_lifetime_filter.py`：分别覆盖真实来源逐实例读取，以及 Buff＋正寿命筛选后
对 ParamModifier 延长寿命、保留原 caster、来源审计与晚期失败回滚。后者只执行所选真实
子图，候选状态为规范组件输入，不代表完整角色已验收。

多层韧性使用 `test_multilayer_toughness.py`：真实怪物卡的三条韧性、单段跨层、中间层伤害和
通知、公共模板避免重复结算、末层完整击破及自然恢复，连同来源审计与晚期失败回滚集中检查。
入射削韧动作与攻击者为明确标记的组件输入，不代表完整首领战或角色构筑已验收。
`test_monster_stance_count_source.py` 检查正式卡初始化和剩余层数条件读取。

待死亡生命周期底座使用 `test_pending_defeat_lifecycle.py`：原生致死因果的保存/恢复、进入
limbo、救回、最终死亡、完整性和原子回滚；救援 HP 是明确组件输入，正式救援队列尚未
贯通。队列生命范围字段的来源归一化使用 `test_queue_battle_state_transition.py -k queue_life_scope`。

## 按需战斗与独立回放

仅在需要整场行为证据时运行受影响路线。独立回放另按归档/恢复/确定性风险决定，不与整场
绑定；需要时直接使用已有适用归档。以下为两个可分别使用的命令：

```bash
export PYTHONPATH=hsr_v075_baseline_clean
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli run \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/serval_natasha_vs_antimatter.json \
  --commands hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/serval_natasha_vs_antimatter.commands.json \
  --output /tmp/hsr-validation-battle.json.gz
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli replay /tmp/hsr-validation-battle.json.gz
```

输出路径必须尚不存在；保留已有证据，重跑时选择新文件名。
检查战斗结果、replay 的 ok/step_count/errors，并记录耗时与产物大小。
不为同一路线额外叠加内存回放。更多路线和限制见 [CLI_MVP.md](../CLI_MVP.md)。

三人组合检查覆盖损血、定向治疗、感电命中/未命中及三人群疗，并直接生成归档：

```bash
.venv/bin/python -B -m pytest -s -m integration \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_cli_content_scope.py -k three_character
```

末尾输出 `archive: 路径`，可直接交给上述 CLI `replay` 命令验证。

额外构筑启动与娜塔莎受击星魂的定向检查：

```bash
.venv/bin/python -B -m pytest -s -m integration \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_character_build_startup.py
```

覆盖零魂/一魂/四魂启动差异、跨角色及未选来源拒绝、普通动作入口不能调用启动能力，以及
自然受击回能、低血量插入自疗、消费一次性状态与胜利。末尾归档可用于按需独立文件回放；轻量来源
准入检查随普通回归运行。这里没有手动压低血量或填入治疗结果。

装备来源、施加者过滤及真实整场的定向入口：

```bash
.venv/bin/python -B -m pytest \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_equipment_caster_removal.py
.venv/bin/python -B -m pytest -s -m integration \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_equipment_battle.py
```

普通检查覆盖复合目标来源闭合、多施加者同名状态、缺身份零提交以及事件来源与单位身份分离。
集成检查复用一个限定范围规则集，核对装备图仍保留的阻断、真实快/慢入场、速度阈值边界和
带装备阿兰整场胜利；整场生成一份归档，独立回放按实际风险选用。阈值扫值是显式边界 fixture。

多波出生、被动原子性与真实整场的定向入口：

```bash
.venv/bin/python -B -m pytest -s -m integration \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_multiwave_battle.py
```

边界 fixture 检查第二波被动与首波一致、队友不重复初始化、每怪一次出生通知、来源审计、
mutation 回放及失败整波回滚；真实三人两波路线使用正式构筑与伤害，中途保存、校验恢复后继续
获胜，输出 checkpoint 和完整归档。篡改终态拒绝恢复，调用方修改已读归档不影响恢复后的历史。
另用自然行动验证枪兵属性快照缺口不会提交先行伤害或消耗 RNG。此路线在敌人行动前清怪，
不是敌方全部动作验收；全部通过也不等于完整关卡环境已接入。checkpoint 可交给
`cli resume 路径 --commands 后续操作.json --output 新路径`，独立进程继续验证。
`test_melee_natural_turns_and_debuff_complete_two_wave_battle` 使用自然交战样例的固定操作，检查
4 次近战攻击的回能、减防来源参数、原子 mutation 回放和两波胜利。普通
`test_presentation_distance_branch.py` 检查表现分支的完整来源保留及未知/战斗内容拒绝。

`test_transient_resistance_penetration.py` 检查真实穿透字段编译、类型化回调贡献进入直接伤害、
按元素匹配及单包作用域；`test_mechanism_bar_callbacks.py` 用真实来源片段检查状态剩余时间
经回调动态值进入机制条冷却，缺绑定/缺目标/未知字段零提交。这些边界检查不是角色整场验收。
`test_ir_import_identity.py` 防止 CLI/UI 两种内部包前缀污染同一份 IR 的规则指纹。

欢愉共享链的定向入口是 `test_elation_accounting.py`、`test_elation_damage.py`、
`test_elation_source_lowering.py` 和 `test_queue_battle_state_transition.py`；
`test_independent_ability_damage.py -k unbound` 另覆盖正式能力图及状态伤害入口与来源审计。
这些检查只编译所选真实来源或使用明确标注的组件输入，不重建全目录，不代表完整角色实战。
`test_elation_source_lowering.py -k real_owner` 实际执行状态附伤及其全局预命中回调，
区分伤害身份与技能参数施加者，检查元素、等级、暴击、本击欢愉/好活覆盖、来源审计和
晚失败完整回滚；单位构筑与倍率初值为明确的组件输入。`test_registered_event_nested_ability.py`
同时检查外层保留内部事件证据且只消费一次。它们不要求重新编译完整角色目录。

关卡环境接线的定向入口为 `test_stage_environment_source.py`：真实关卡能力从正式图启动，
通过出生监听授予暴击增益，并影响共享伤害结算；它隔离模板其它依赖，不代表完整关卡验收。
`test_level_enter_battle_order.py` 检查关卡自身的入场通知只执行一次及其与单位出生的顺序。
`test_stage_enemy_scaling.py` 检查真实难度倍率与精英组倍率共同进入波次来源，
`test_character_count_dynamic_value.py` 检查真实目标表达式计数复用动态值结算、审计与回放。
`test_stage_environment_common.py` 小范围编译真实公共环境，检查模板启动顺序、关卡自身
入场回调和来源审计；战斗单位明确使用组件输入，不冒充完整角色构筑。
`test_level_target_source.py` 与 `test_empty_target_filter.py` 分别覆盖正式关卡实体目标，
以及空候选过滤、目标运算列表传递和按正式创建者映射战斗事件实体。
公开整场样例是 `examples/cli/arlan_common_stage_environment{,.commands}.json`，
通过 CLI `run` 可重现普通环境入场、双方操作和胜利，再使用 CLI `replay` 校验归档。
按实际改动选择，不是每次必跑套餐。

## 持续操作 UI

持续操作 UI 的定向入口（不触发全目录编译）：

```bash
.venv/bin/python -B -m pytest -s -m integration \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_live_battle_ui.py
node hsr_v075_baseline_clean/hsr/simulator_v8_ui/test_live_client.cjs
```

Python 检查使用内存 HTTP 请求经过实际处理器与真实内核，覆盖完整战斗、旧决策拒绝、非法目标、
查询、按需审计、下载和归档恢复后胜利；篡改归档不能替换旧会话。输出可独立回放的归档路径，
不依赖监听端口。两个轻量检查随普通回归运行。Node 检查覆盖导入、重复点击、失败保留旧画面
和解压大小边界，只验证客户端请求流程，不冒充浏览器交互或游戏机制证据。
`test_build_preview_uses_formal_trace_selection_without_replacing_battle` 单独验证构筑预览的真实
来源装配：阿兰战技 Lv1→Lv2、未知行迹拒绝及当前会话不变。客户端检查包括同一行迹等级替换、
默认选择、未知项保留和异步校验期间草稿变动；无需为这些表单检查重复执行整场战斗。
`test_equipment_forms_preserve_build_and_replay_battle` 使用真实装备目录，检查光锥应用/卸下、
单部位遗器修改、非法词条拒绝及服务端生成的指纹，并将组合构筑贯通到胜利和标准归档。
可用 `-k equipment_forms` 单独选取；目录与装配查询不创建或替换正在进行的会话。
`-k selected_character` 选择角色切换后的真实整场：阿兰位置换为希露瓦，核对正式动作归属，
获胜并输出归档。角色目录与草稿切换另有不编译技能图的普通检查；文件保存普通检查覆盖序列化
与原子替换失败，旧文件必须保持完整。Node 检查覆盖切换、加载/保存双击及请求期间继续编辑。
该真实场景还覆盖历史分支：从战技前回溯、改选普攻后再次获胜；篡改操作前缀和非法边界拒绝，
原会话保持不变，输出 `selected-character-branch.json.gz` 供独立 CLI 回放。

## 历史工具与现行依赖

`tests/` 是当前默认入口；`tools/validate_v0_*`、P1–P9 专项脚本保留来源与历史证据，
不自动成为当前任务的必跑套餐。CI 中既有阶段 workflow 仍保留其明确范围，
新增核心回归入口负责当前 pytest；是否运行历史 Direct 由改动风险和实际调用链决定。

以下工具仍向现行测试提供辅助构造，移动/删除前必须迁移调用者：

| 工具 | 当前引用 |
| --- | --- |
| validate_p9_s5c2_action_selection_query_submit_context | action_attack_target_context |
| validate_p9_a2_action_window_status_nested_ability_transport | direct_static_context |
| validate_p8_s2_character_build_base_panel | formal_build_param_projection |
| validate_p9_a2_p4_set_entity_visible_process_only_retirement | p4 来源准入回归 |
| validate_p9_a2_p5_process_only_settlement_barrier_retirement | p5 来源准入回归 |
| validate_p9_formal_action_graph_admission_authority | p6 来源准入回归 |
| validate_p9_s8c1b_action_entry_weighted_selection | s8c1b_materialization_regression |
| validate_p7_s13_shield_hp_routing | parallel_shield_absorption |

这些引用是测试辅助，不是 runtime 依赖。不要为归档而建立另一套 fixture 框架；
触及相关检查时再将真正共享的最小构造迁到测试目录。

