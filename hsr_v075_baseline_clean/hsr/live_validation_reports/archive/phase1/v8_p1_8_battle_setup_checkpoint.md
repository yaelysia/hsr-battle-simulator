# v8 P1-8 BattleSetup checkpoint

日期：2026-07-02

## 结论

P1-8 最小战斗配置入口已完成。当前 v8 scenario 主入口仍是：

```text
ScenarioLoader -> ScenarioSpec -> IdentityResolver -> ScenarioStateBuilder -> BattleState + ActionCommand
```

新增 `battle_setup` canonical schema 后，旧 root-level `skill_points`、`max_skill_points`、`wave_index`、`wave_definition_ref`、`stage_ref`、`rng_state` 仍作为 legacy alias 保留；若 root alias 与 `battle_setup` 写出不同值，会 fail fast，避免同一初始条件出现两套语义。

## 已完成范围

- `BattleSetupSpec` 及子对象：resources、wave、timeline、rng、initial_statuses、initial_summons、objective。
- `PanelInput.hp_ratio` / `energy_ratio`，与 `hp` / `energy` 互斥，ratio 越界失败。
- `battle_setup.resources` 初始 SP / max SP，校验 `0 <= skill_points <= max_skill_points`。
- `battle_setup.wave` 支持 stage / wave_definition，复用 P1-2 wave runtime；下一波单位不会初始进入 `state.units`。
- `initial_statuses` 只支持 source-backed `EffectIR(opcode=AddModifier)`，并复用 `StatusSystem.apply_add_modifier()`。
- `initial_summons.kind=summoned_monster` 复用 `SummonSystem.plan_spawn_summoned_monster()` + `apply_spawn()`。
- `battle_unit_summon` / `servant` 当前保持 source-gap blocked，不创建 fake unit/runtime。
- `timeline.runtime_initialize` 只记录初始化策略；`explicit_action_values` 通过 setup mutation 写入 unit action value。
- scenario-level `rng_mode` / `rng_choices` 合并进入 route command metadata，route metadata 优先。
- root-level `rng_state` 与 `battle_setup.rng` 合成时保留“缺省 vs 显式”语义：
  `battle_setup.rng` 只写 `rng_mode/rng_choices` 时会继承 root seed；显式写出不同
  `battle_setup.rng.rng_state` 才会被视为歧义并失败。
- `objective` 写入 metadata/global flags，不参与 action availability、target、damage、status、queue、wave。
- UI runner/report 最小 roundtrip 输出 normalized scenario、setup records、blocked setup，并识别 `battle_setup.timeline.action_values`。
- 新增轻量主验证脚本 `validate_p1_8_battle_setup.py`，默认不写完整 canonical/coverage/fidelity 大产物。

## Source / admission 口径

- Scenario setup 是初始条件和 route input，不是规则来源。
- initial status 正例必须从真实 `EffectIR` 反查到 modifier/status source trace；blocked coverage 不产生 mutation。
- initial summon 正例必须从真实 `SummonMonsterIntentIR` 生成 unit spawn 和 `summon_runtime` mutation。
- servant 当前没有 P1 可执行 runtime admission，验证为 `source_gap_blocked`，不创建 servant unit。
- setup 应用顺序为 initial statuses -> initial summons -> timeline；timeline 显式
  action value 在 summon 后定稿，允许覆盖 setup 生成的召唤单位。
- static boundary 检查确认 `scenarios/` 不读取 raw TBGD、TextMap、旧 v7 或旧 model pack。

## 验证

已运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_8_battle_setup --output-dir /tmp/hsr_v8_p1_8_battle_setup
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_2_wave_system --output-dir /tmp/hsr_v8_p1_2_wave_after_p1_8
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_summon_after_p1_8
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_status_after_p1_8
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_7_rng_branch_system --output-dir /tmp/hsr_v8_p1_7_rng_after_p1_8
git diff --check
```

结果：

```text
compileall ok
v8 p1_8_battle_setup validation ok=True
v8 p1_2_wave_system validation ok=True
v8 p1_3_summon_assistant_servant validation ok=True
v8 p1_4_status_system validation ok=True
v8 p1_7_rng_branch_system validation ok=True
git diff --check ok
```

P1-8 主验证覆盖：

- legacy scenario load/build。
- new `battle_setup` load/build。
- roster resources、HP/energy ratio、SP。
- two-wave source-backed setup。
- source-backed initial AddModifier status。
- source-backed summoned monster。
- summoned monster 生成后 timeline explicit action value 覆盖。
- servant source-gap blocked。
- explicit timeline action value。
- root `rng_state` + setup `rng_mode/rng_choices` 且不重复写 setup `rng_state` 的 alias 合成。
- scenario-level RNG metadata merge/replay。
- objective metadata non-interference。
- unknown entity/effect/summon/wave/timeline unit、invalid ratio、invalid SP negative cases。
- no-rule-injection static boundary。

P1-2/P1-3/P1-4/P1-7 回归由本次触达的 wave、summon、status、rng setup 触发，已串行运行，未与 TBGD lowering 重验证并发。

## 距离最小可用战斗纵切

P1-8 后，验证战斗已经不需要手写 Python `BattleState` 来表达两波、初始状态、初始召唤、timeline、RNG 和 objective。进入 P1-9 后应做第一阶段聚合验收：把 P1-0 到 P1-8 的 action boundary、lifecycle、wave、summon、status、queue/window、target、RNG、BattleSetup、snapshot/replay、source audit 串成一个分层验证入口。

## 距离完整复刻仍缺

- 完整角色面板装配：晋阶、全量行迹、光锥、遗器和套装。
- 全角色/怪物机制解释与来源验证。
- 更完整的状态系统：复杂叠层、刷新、驱散、控制、免疫、DoT tick 等大范围正例。
- 完整 wave/stage/environment、enemy AI、召唤物/assistant/servant 行为。
- 光锥、遗器、关卡机制和外部推演器路线搜索。
