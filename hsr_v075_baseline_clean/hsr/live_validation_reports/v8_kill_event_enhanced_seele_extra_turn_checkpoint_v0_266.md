# v8 v0_266 - 通用击杀事件、加强版希儿与额外回合回正

## 结果

`v0_266` 已把希儿示例卡切到加强版来源，并把击杀收益收敛到通用 `unit.defeated` 事件链路：

- 希儿卡默认使用 `AvatarConfigEnhanced.json`，技能组为 `1110201 / 1110202 / 1110203 / 1110204 / 1110206 / 1110207`。
- 旧版 `11020x` 只作为增强版覆盖证据保留，不作为希儿主示例卡的可执行动作入口。
- 通用击杀事件继续按具体伤害来源归因，不只按 actor 归因。
- 通用击杀回能从同一个 `unit.defeated` 事件产生，走 `ResourceSystem`，并带 `ResourceRuleIR(engine_convention)` source audit。
- 希儿再现只监听通用击杀事件：普攻、战技、终结技造成击杀都能写入再现动态值，再由后续技能结束窗口入队额外回合。
- 额外回合内再次击杀不再触发再现，仍保持队列为空。
- 额外回合不再硬禁终结技；终结技与额外回合同级，按入队顺序执行；追击/反击优先级仍高于二者。
- 加强版 50% 自动战技来源接入：`OnListenAfterAttack -> Retarget -> TurnInsertAction(SkillType=ControlSkill02)`，满足条件时自动入队战技，`IgnoreBPDec` 使其不耗战技点、不回能。
- 加强版再现 buff 的持续时间参数已进入角色卡参数槽位：`1110204 ParamList[1] = 3`，并与 Advanced AddModifier 的动态 lifetime evidence 一起保留。

## 本次修复点

- 角色卡构建层优先读取增强版 Avatar 配置，`AvatarConfigEnhanced.json` 覆盖普通 `AvatarConfig.json`。
- Queue intent admission 补 `SkillType` 型 `TurnInsertAction`，可解析到角色 action set 的战技/普攻/终结技。
- `OnListenCharacterDie` 作为击杀监听按 owner-local 处理，不再落到泛化 global listener。
- `action.after_attack` 通过统一 dispatcher 发布，支持加强版希儿 50% 自动战技监听。
- `TurnInsertAction.IgnoreBPDec` 进入 queue source trace，并在 scheduler/executor 中跳过战技点消耗与回能。
- `TurnInsertAction.PreCheck(SameTagInsertUnusedCount)` 进入 queue admission；已有使用标记时不再入队。
- 角色卡新增通用 `skill_param_slot`，用于保存非伤害公式参数证据，例如加强版希儿天赋持续时间。
- `extra_turn_ultimate_action_not_allowed` 硬禁路径已移除。

## 仍未做

- 50% 自动战技的“回合开始重置次数”还未做完整 turn-begin 还原链路；当前已支持有使用标记时阻止再次入队。
- 本阶段不做遗器、光锥、完整星魂、敌方 AI、波次系统。

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_257 --output-dir /tmp/hsr_v8_regression_v0_257
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_263 --output-dir /tmp/hsr_v8_regression_v0_263
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_264 --output-dir /tmp/hsr_v8_regression_v0_264
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_265 --output-dir /tmp/hsr_v8_regression_v0_265
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_266 --output-dir /tmp/hsr_v8_v0_266
git diff --check
```
