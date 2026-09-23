# PR11-A2-RUNTIME-RESUME / Revision 35 收尾执行报告

状态：本地实现与规定验证通过，待最终 committed HEAD 的 GitHub required checks 和独立
`FULL_AUDIT`。分支仍为原 PR #11 的
`plan/p9-a2-action-window-status-transport-20260907`；启动时远端 HEAD 已精确核验为
`a092a270191ffeba340fe4f28ac22376f3a87af0`，本地接管 HEAD 为
`de100243225a10a56270c04db52d55752bea81d4`，且两者及
`5b222a2fb05970b5d23fd053ffd9beb453e4dfac` 均为当前工作祖先。

## Revision 35 实现

1. `task_graph_materializer.py` 仅在 D2/D3 全部闭合时，把已有 RandomConfig weighted
   selection 接到共享 branch dispatch；runtime deferred guard、全局 domain 白名单和 RNG
   caller 未修改。
2. formal slice ledger 同步退休已由 typed weighted dispatch 承接的 control disposition。
   同源 own-effect 仍保留 deferred reference/coverage，不作为 effect 执行；额外域、错 role、
   process-only、异源/额外引用和 blocked source 继续 fail closed。
3. 新 bridge test 从 `_build_graph` 进入真实 `TaskGraphExecutor`，并保留 S8C2 的 hook、choice、
   ordinal、branch、RNG identity 和 atomic rollback 守卫。真实 source 静态门另行证明 nested
   weighted 分母非空，未用 fixture 冒充 Direct。
4. Direct validator 区分 committed event 与 failed-plan process-only diagnostics，并直接记录
   formal root 的 projection 泄漏、weighted hook、普通 dispatch 的 event/type/order。

## 真实 Direct 证据

正式路径依次命中 `action.window.after_attack`、真实 status instance
`status:8ba7488b830b45d3`、status root、typed nested graph、AbilityTaskSystem weighted hook；
selection `task_graph_weighted_selection:bb82cae3e9069058108923a92c47e6a6ba7ed887cab5c789fc4e432ea328bd63`
返回 `ability_task_weighted_selection_caller_deferred_to_pr9`，无 RNGEvent。formal root 返回
该错误且 projection_count=0。整动作 state unchanged、mutation=0、committed event=0、RNG=0。

之后普通 `OnListenAfterAttack` 在
`event:1:action_after_attack:validation:enemy` 因 `action_target_fact_missing` fail closed；它没有
expected window scope，且在 weighted deferred 之后发生，未被当作正式 window 授权或主终点。
Direct 最终 `ok=true`，wall 55.35s，peak RSS 863976 KiB，均在 120s/1.5GiB 门内。

## 本轮实际验证

解释器为既有 `.venv/bin/python`，未安装依赖或创建环境。所有命令从仓库根以
`PYTHONPATH=.../hsr_v075_baseline_clean` 和 `-m hsr.simulator_v8_clean_core...` 入口运行。

| 验证 | 结果 |
|---|---|
| scoped `py_compile` 与 import-only | exit 0 |
| bridge + S8C2 executor | 23 passed |
| P3/P5 materializer 保护回归 | 42 passed |
| 真实 source `direct_static_context` | 5 passed |
| 固定 A2 pytest 集（formal build、SkillParam、attack target、metadata、P6、direct static、bridge） | 84 passed |
| A1 Fast / A2 Fast | exit 0，`ok=true` |
| P8-S2 `--fixture-only` / P7-S7 / S5C2 / S8B5C | exit 0，均 `ok=true` |
| S8C1C source-closure `--fast` | exit 0，8 cases，`ok=true` |
| A2 `--direct` | exit 0，`ok=true` |

计划点名的 `tests/test_p9_a2_target_contract_regressions.py` 经工作区文件清单和 Git 历史核对均
不存在，未把缺文件记为通过。相应 sealed target/fact 负例实际位于已提交并在本轮运行的
`test_p9_a2_action_attack_target_context.py`（包含 issued fact、跨 invocation/step、subject、
state、空 subject 等回归）；因此未新增重复测试文件。

最终 committed HEAD 仍须复跑同一门并由 GitHub Actions 精确核验；以下旧 Revision 26 内容
仅供追溯，不代表当前状态。

---

## 历史记录：Revision 26（仅追溯，不是当前状态）

状态：`needs_replan`，不是 `ready_for_review`。2026-09-22 本轮执行在 C01 的真实
owner 构筑准入处触发批准计划 C01 §6 / C04 §6 的停止条件。C02、C03、C04 未完成。

## 现场与改动

- 直接读取批准文件 `pr-workflow/PR11-A2-RUNTIME-RESUME-REPLAN-26.md` 成功。
- `git ls-remote origin refs/heads/plan/p9-a2-action-window-status-transport-20260907`
  返回 `a092a270191ffeba340fe4f28ac22376f3a87af0`；第一次受限网络连接失败，获准的
  只读网络重试成功。当前已经在同名任务分支，无需切换。
- 初始及结束本地 HEAD 均为 `3492f4ae27404c37999391ad00ca5d8a1e6ff31d`。
  `git merge-base --is-ancestor` 分别验证批准基线和
  `5b222a2fb05970b5d23fd053ffd9beb453e4dfac` 均为 HEAD 祖先。
- TBGD 工作树及主仓库 gitlink 均为 `14c1d18f91a8101d610e6c523447a7517de3fae1`，未更新。
- 本轮仅修改 `scenarios/build_state.py`，新增
  `tests/test_p9_a2_formal_build_param_projection.py` 和本报告；前两路径相对 core。
  原任务 WIP、`.gitignore`、工作流协议用户改动、UI 和其他 untracked 均保留。
- 未提交、未推送、未更新 PR/工作流账本；原 PR #11 保持原样。局部修改待重规划后接续。

生产局部修复：`_formal_character_activation` 校验 unit/build/assembly 身份及准入，
按 `(action_id, effective_level)` 查询唯一 canonical definition，核对定义身份和来源；
拒绝非法等级、歧义定义、矛盾 action 和 trigger 等级；仅空 trigger 不进入部分索引。
完整 action/level/definition/source 账本保留。新增测试真实经过 assembler、build admission、
formal birth planning 和 activation；未将 fixture 当作真实 owner 准入证据。

## 真实 owner 准入：计划与代码事实冲突

复用 `_a2p0_build_focused_direct_ir`、lowerer 的真实 snapshot/scope/source graph，按
focused status 来源唯一推导出 owner `1006`，没有按此 ID 选择样例。
调用 `build_character_card_ir(avatar_ids=...)`，显式提供真实 source graph 和 scope。
正式输入：等级 1、晋阶 0、星魂 0、无主动额外行迹、空装备。

临时诊断：`/tmp/pr11_r26_owner_probe.py`；完整输出：
`/tmp/pr11_r26_owner_probe.json` 和 `/tmp/pr11_r26_owner_probe.log`。
复现命令（仓库根目录，已有环境）：

```sh
PYTHONPATH=hsr_v075_baseline_clean nice -n 10 .venv/bin/python /tmp/pr11_r26_owner_probe.py
```

诊断的局部视图边界明确如下，未充当 C04 最终 RuleBook preflight：

- builder 的 selector gaps 返回其他 owner 项；只在同 owner 视图中过滤其他 owner，
  保留本 owner 全部 7 条 selector relations，owner selector gaps 实测为 0。
- 完整 source graph 直接装入单卡 CanonicalIR 会因其他 owner 卡缺失被拒绝。
  临时诊断将 catalog 的 `fingerprint_kind` 声明为 `partial` 后重新调用生产 card builder；
  原 snapshot/scope/source fingerprint、所有 source/definition/graph/binding/gap 均保留，
  未篡改 catalog ID、未跳过 CanonicalIR 一致性检查。这只是局部诊断视图，不宣称全目录闭合。
- 提供 1 profile、1 card、1 eligibility、50 trace nodes、6 eidolon slots；沿 card action_set
  保留 57 个 canonical definitions，所需 `(action_id, level)` 缺失集合为空。
  builder 返回的机制槽、公式及 bounce 数据作为超集保留，没有删除 owner 依赖。
- 生产 assembler 默认选中 5 个一级基础行迹；所有 6 个 effective skill levels 成功解析。
  canonical 非空 trigger 为 Skill01/Skill02/Skill03/SkillP01/SkillMaze，另有 1 个空 trigger。
  此处只记录 canonical 分区；真实 owner 因未获准入，未调用 activation 放行。

实际结果：

```text
assembly_status = assembled
equipment_assembly_result.battle_admission_status = admitted
battle_admission_status = blocked
blocked_reasons = []
unadmitted_mechanism_diagnostics = 1
reason = character_dynamic_graph_runtime_semantics_pending_p9_s4_s17
validate_character_build_admission = (
  character_build_has_unadmitted_mechanisms,
  character_build_not_admitted_for_battle,
)
```

输入 fingerprint：`64c7e1e5037b681ae8c57c9c411af4e4a814d5290f02755218871eeca3f15ee1`。
结果 fingerprint：`01b202da11d9506fd176b35aedb2b4cb1b7c8103165747caaed5590513913801`。
面板已解析为 HP 142.56、ATK 87.12、DEF 62.7、SPD 107、能量上限 110。

最小来源是 pinned TBGD 的
`Config/ConfigAbility/Avatar/Advanced/Avatar_Advanced_Silwolf_00_Ability.json`，
`$.AbilityList[7].OnStart[1]`。其 `BySkillPointActivated(PointB1)` 在未解锁时走真实
`FailedTaskList`，通过 `SetDynamicValue` 设置 `MDF_Silwolf_00_AddModifier_LifeTime`。
成功和失败分支都非空，不能把“未解锁”视为整个动态根不存在；也不能额外启用行迹追求绿灯。
来源及 ID 仅用于此处证据定位，没有进入运行分支。

生产链已核实：

```text
source selector relation
  -> _selector_dynamic_root_draft（核 card/graph/source/definition 身份）
  -> _assemble_character_dynamic_roots（真实 FailedTaskList 非空，建立 root）
  -> _CharacterDynamicRootDraft.materialize（固定 pending_p9_s4_s17）
  -> assemble_character_build（每个 dynamic root 进入 unadmitted diagnostics）
  -> validate_character_build_admission（拒绝）
  -> formal birth/activation 不得放行
```

根因不依赖缺少 runtime events/tasks：`_CharacterDynamicRootDraft.materialize` 无条件产生
上述 blocked reason；`CharacterDynamicGraphRef.to_json` 固定输出
`runtime_admission_status=blocked`，`from_json` 拒绝 admitted。因而即使继续补齐 action slice、
callback 和目标运输，也不能通过当前正式构筑准入。这排除了仅由同 owner 裁剪、缺定义、漏 slot、
漏 selector 引用或启动方式导致的失败。

最小待裁决范围：为真实构筑动态根建立正式 runtime 准入和执行消费边界，至少涉及当前只读的
`builds/character_assembler.py` / `builds/models.py` 及其 consumer；需要确定如何证明该来源根
已被正式执行链完整承接。不得仅删除诊断、改 admitted 标志或用另一套参数装配绕过准入。
这超出本包只修参数投影与运输的授权，不在本轮擅自实施。H1 的 weighted deferred 可达性仍未证明。

## 本轮验证

解释器为已有 `.venv/bin/python`（pytest 9.1.1）；未创建环境、安装依赖或修改锁文件。
以下命令均串行低优先级执行；没有将其他命令静默记作通过。

| 命令 / 检查 | 退出码与结果 |
|---|---|
| 实际 dirty Python + core/tests 新增 Python 的 scoped compile；新测试 import-only | 0，20 文件编译通过，import 通过 |
| 计划指定五个 pytest 文件：formal projection、status SkillParam、attack target、metadata sync、P6 damage admission | 0，44 passed；其中本轮 projection 12 项 |
| `python tools/validate_p8_s2_character_build_base_panel.py --fixture-only --output-dir /tmp/PR11-A2-RUNTIME-RESUME-r26/p8s2` | 1，脚本相对导入失败 |
| 同一 P8 模块使用 `PYTHONPATH=... python -m hsr.simulator_v8_clean_core.tools.validate_p8_s2_character_build_base_panel`，参数相同 | 1，实际进入 fixture 后失败：`route[0]: formal character action 'avatar_skill:fixture_skill' has no admitted effective skill level`；未豁免、未判为已证明的历史失败 |
| `python tools/validate_p9_formal_action_graph_admission_authority.py --fast` | 1，脚本相对导入失败 |
| 同一 A1 模块用 `PYTHONPATH=... python -m ...validate_p9_formal_action_graph_admission_authority --fast` | 0，`ok=true`；输出 `/tmp/pr11_r26_a1_fast.json` |
| `python tools/validate_p9_a2_action_window_status_nested_ability_transport.py --fast` | 0，`ok=true`；保留七通道和已有 deferred/原子断言，非真实 Direct 证据 |
| 临时同 owner 构筑诊断 | 0，成功取得上述 blocked 正式结果；不是准入成功 |
| `git diff --check` | 0 |
| `git diff --check 5b222a2fb05970b5d23fd053ffd9beb453e4dfac...HEAD` | 0 |

未运行：P7-S7、S8B5 完整入口、最终同 RuleBook 共用 preflight、A2 Direct、final committed HEAD
hosted required checks、FULL_AUDIT。原因是已触发明确的计划范围冲突，停止后续卡；不是这些检查
通过，也不是环境 blocker。C01 两个 Direct 入口尚未迁移；C02 三 consumer 和 C03 seal/scope
仍是继承 WIP，专项旧例通过不能证明新成功条件已完成。

## DELIVERY_CHECK

- scope：通过。本轮仅上述三个批准路径；无关 dirty 原样保留，没有提交或改写远端。
- validation：不通过。44 项和 Fast 通过，但 P8 fixture 失败，完整 Direct/CI/audit 未完成。
- plan_reality：需要重规划。正式 owner 构筑确实需要未实现的动态根准入；C01 §6 / C04 §6
  明确要求此类独立领域机制返规划，禁止假准入和扩大 assembler/动态根语义。
