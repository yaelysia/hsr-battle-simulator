# v8 加强版希儿行迹启动能力检查点 v0_276

## 本阶段做到哪里

- 接通加强版希儿行迹 `11102101` 的 `trace_ability_hook`。
- 角色卡构建层从 `AvatarSkillTreeConfig` 读取 `AbilityName=Avatar_Advanced_Seele_SkillTree01`、`PointTriggerKey=PointB1` 和 `ParamList`。
- 角色卡构建层从 `Config/ConfigCharacter/Avatar/Advanced/Avatar_Advanced_Seele_00_Config.json` 的 `DynamicValues.Floats[*].ReadInfo` 读取 `SkillTreeParam` 参数绑定。
- lowering 后半段在 standalone ability graph、OnStart AddModifier effect、动态值绑定都可执行时，把该 trace slot admission 为 executable。
- scenario build 在该 trace node 启用时，通过通用 `StatusSystem.apply_add_modifier` 给单位挂载 `MAvatar_Seele_00_SkillTree01`。
- 击杀事件 `unit.defeated` 继续走通用 `EventDispatchSystem` / `StatusCallbackSystem`，触发 `OnTriggerDeath` 后挂载 `MAvatar_Advanced_Seele_00_SkillTree01_KillDamageRatio`。

## 来源链路

- trace node 来源：
  - `ExcelOutput/AvatarSkillTreeConfig.json`
  - `PointID=11102101`
  - `EnhancedID=1`
  - `PointTriggerKey=PointB1`
  - `ParamList=[0.5, 3, 3]`
- 参数绑定来源：
  - `Config/ConfigCharacter/Avatar/Advanced/Avatar_Advanced_Seele_00_Config.json`
  - `ReadInfo.Type=SkillTreeParam`
  - `ReadInfo.TriggerKey=PointB1`
  - `MDF_DamageRatio -> ParamList[0] = 0.5`
  - `MDF_MaxLayer -> ParamList[1] = 3`
  - `MDF_LiftTime -> ParamList[2] = 3`
- ability graph 来源：
  - `Config/ConfigAbility/Avatar/Advanced/Avatar_Advanced_Seele_00_Ability.json`
  - `Avatar_Advanced_Seele_SkillTree01`
  - 顶层 `OnStart -> AddModifier`

## 负例

- 普通版 trace `1102101` 仍保持 blocked，不在本阶段 admission。
- 启用普通版 trace 不会挂载 `MAvatar_Seele_00_LowHP_AggroDown`。
- 缺 graph、缺 OnStart AddModifier、缺动态值 hash 绑定、参数越界时仍 blocked，不产生 startup status mutation。

## 没做什么

- 没有按角色名、技能名、固定 action id 或观测值在 runtime 特判。
- 没有让 runtime 读取 raw TBGD、TextMap、技能文本、旧 v7 或旧 model pack。
- 没有接普通版希儿低血量仇恨降低行迹。
- 没有新增伤害公式或面板装配规则。
- 没有把 trace ability hook 全量标为 executable；只有满足结构化 admission 的增强行迹启动 AddModifier 被接通。

## 距离最小可用战斗纵切还缺什么

- 继续补角色卡机制槽位 admission，尤其是更多 trace ability hook、星魂、状态监听和行动插队。
- 需要稳定的队伍、敌人、路线输入样例，覆盖 UI 点选路线和核心 replay。
- 敌方动作选择或敌方路线输入仍需明确。
- 面板来源仍缺光锥、遗器、套装、晋阶和更多行迹影响。

## 距离完整复刻还缺哪些大模块

- 大量角色卡人工解释、来源审计和负例验证。
- 光锥、遗器、套装机制。
- 敌方动作序列 admission、波次系统、召唤物、assistant、特殊战斗模式。
- OnCustomEvent、OnWaveMonster 等 hook 的真实事件源。
- engine convention 项继续等待真实 TBGD admission。

## 验证

已通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_276 --output-dir /tmp/hsr_v8_audit_v0_276
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_265 --output-dir /tmp/hsr_v8_audit_v0_265_after_v0_276
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_270 --output-dir /tmp/hsr_v8_audit_v0_270_after_v0_276
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_271 --output-dir /tmp/hsr_v8_audit_v0_271_after_v0_276
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_272 --output-dir /tmp/hsr_v8_audit_v0_272_after_v0_276
git diff --check
```

结果：

- `compileall`: pass
- `validate_v0_276`: `ok=true`
- `validate_v0_265`: `ok=true`
- `validate_v0_270`: `ok=true`
- `validate_v0_271`: `ok=true`
- `validate_v0_272`: `ok=true`
- `git diff --check`: pass
