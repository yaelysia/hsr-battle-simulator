# v8 怪物技能附带状态纵切检查点 v0_284

## 本阶段完成

- 接通怪物技能 `AddModifier` 给动作目标附带状态的通用 runtime 链路。
- `AbilityTargetEntity` 现在可解析为本次动作主目标，并在 `status_details.source_trace` 中记录 `target_resolution`。
- `AllEnemy`、`AllTeamMember`、`AllLightTeam`、`AllTeammate` 这类可由当前战斗阵营明确枚举的群体目标，支持按目标集合逐个走现有 status lifecycle。
- `AddModifier` 的群体目标 admission 只打开状态系统；治疗、护盾、资源变化、动态值等 effect 仍沿用原单目标 admission，避免顺带打开未审计能力。
- 新增严格附带状态边界：本轮新增的动作目标/群体目标状态如果缺动态值绑定、duration blocked、存在未 admission 的事件监听、chance/stack/refresh 未支持，则 blocked/process-only，不产生 mutation。

## 验证样例

- 单体附带状态样例按结构化谓词选中：`monster_skill:200402107`，云骑骁卫・彦卿（完整），`AbilityTargetEntity -> MMonster_W2_Yanqing_00_Skill02_Mark`。
- 群体附带状态样例按结构化谓词选中：`monster_skill:100402203`，杰帕德（完整），`AllTeamMember -> MAvatar_Gepard_00_RL_ShieldIcon`。
- 选择过程不依赖固定 MonsterID、SkillID、文件名或观测数值；验证中记录实际选中对象只用于审计。

## 未完成内容

- 带事件监听/回调的目标附带状态仍 blocked；后续应接状态监听 admission，不在本阶段半接。
- DoT tick、控制效果、锁定目标后续行为、护盾数值语义、状态特殊清理语义未在本阶段展开。
- 相邻目标、召唤物目标、不可选目标、特殊队伍别名仍未 admission。
- 本阶段不做敌方 AI 自动选目标，不做波次、关卡倍率、召唤物、特殊模式。

## 距离最小敌方行动纵切

- 已有固定序列候选、手动目标选择、怪物技能伤害/削韧、技能附带状态。
- 还缺：更多目标别名 admission、常见控制/DoT 状态的运行语义、怪物技能中的条件分支覆盖、敌方动作序列与状态生命周期的组合回归。

## 距离完整复刻

- 仍需系统性补齐怪物状态监听、阶段切换、召唤/部件、多行动/插队、关卡等级倍率、波次环境、光锥/遗器及敌我完整装配。

## 验证命令

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_284 --output-dir /tmp/hsr_v8_monster_attached_status_v0_284
```

结果：`ok=True`。
