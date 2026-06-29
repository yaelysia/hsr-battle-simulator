# v0_289 目标表达式序列、过滤与重定向安全纵切

## 本阶段完成

- `TargetSystem.resolve_target_expression` 从仅支持简单 `TargetAlias` 扩展为可解析安全子集：
  - `TargetSequence`
  - `TargetConcat`
  - `TargetFilter`
  - `Retarget`
- 新增上下文型目标别名：
  - `SkillTargetEntityList`
  - `ParamEntityList`
  - `TeamFormation`
  - `AllDarkTeam`
- `TargetFilter` 只复用现有 `RuleEvaluator` 已支持的条件谓词；unsupported 条件 blocked。
- `Retarget` 只接确定性目标来源、固定正数 `MaxNumber`、已 admission 条件；随机、排序、fetch 继续 blocked。
- `EffectExecutionContext`、`StatusSystem.apply_add_modifier` 透传 `event_payload`，让状态回调和 effect 能使用事件 payload 解析目标列表。
- `AddModifier` lowering 和 runtime coverage 认可 `target_expression_coverage_status=executable`，但仍要求真实 `target_expression_id` 来源。
- 新增 `validate_v0_289`，验证 resolver、AddModifier runtime mutation、blocked 负例和静态红线。

## 数据库事实进入 IR 的结果

`validate_v0_289` 本轮构建结果：

- `target_expression_count=243671`
- `executable=198012`
- `blocked=45659`

新增可执行 composite 统计：

- `TargetSequence=128`
- `Retarget=823`
- `TargetAlias=197061`

仍 blocked 的目标表达式继续保留 source trace 和 blocked reason，尤其是：

- `TargetFetch*`
- `TargetSort*`
- 随机 retarget
- 召唤物/servant/唯一实体/特殊玩法目标
- unsupported filter condition

## 正例与负例

正例选择策略：

- 按 `TargetExpressionIR.expression_kind`、`alias`、`coverage_status` 选择。
- runtime mutation 正例只选 `EffectIR(opcode=AddModifier)`。
- runtime mutation 正例只选主线 `Config/ConfigAbility/Avatar`、`Config/ConfigAbility/Monster`、`Config/ConfigAbility/Equip` 来源。
- 不按固定角色名、怪物名、技能 ID、文件名或观测值选择。

本轮实际正例：

- `SkillTargetEntityList` 可从当前 action target resolution 解析目标列表。
- `ParamEntityList` 可从事件 payload 的参数实体列表解析目标列表。
- `TeamFormation` 可解析为施放者同阵营存活单位，按稳定顺序返回。
- `TargetSequence` resolver 正例通过，并带完整 resolution steps。
- `Retarget` resolver 正例通过，并带完整 resolution steps。
- AddModifier runtime 正例通过目标表达式解析后产生 `status_details` mutation，状态来源可反查到 `target_expression`。

负例覆盖：

- `TargetSort*` / `TargetFetch*` 仍 blocked，不产生 mutation。
- unsupported `TargetFilter` condition blocked。
- 缺 `Retarget.TargetType` blocked。
- `ParamEntityList` 缺事件 payload blocked。
- blocked/audit-only/discovered-only 不产生 mutation。

## 当前支持边界

本阶段补的是“安全目标表达式解析”，不是完整目标选择系统：

- 已支持：简单别名、明确群体、上下文目标列表、序列合并、确定性过滤、确定性 retarget。
- 未支持：排序、随机、fetch、相邻目标、召唤物目标、servant 目标、唯一实体查询、特殊玩法目标。
- `Retarget` 在本阶段只影响当前 effect/callback 的目标解析，不改写整次 action 的主 target resolution。
- Runtime 仍只读取 Canonical IR / RuleBook，不读取 raw TBGD、TextMap、旧 v7 或旧 model pack。

## 验证结果

在 `hsr_v075_baseline_clean/hsr` 下已通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_289 --output-dir /tmp/hsr_v8_target_expression_v0_289
```

`validate_v0_289` 输出 `ok=True`，核心断言包括：

- `TargetSequence`、`Retarget` 已进入 IR。
- `SkillTargetEntityList`、`ParamEntityList`、`TeamFormation` 均有 executable 样例。
- `TargetSequence` resolver 正例通过。
- `Retarget` resolver 正例通过。
- AddModifier runtime 正例产生状态 mutation。
- 状态详情能反查到 target expression 来源。
- unsupported filter、缺 payload、sort/fetch 都 blocked。
- static checks 通过。

## 距离最小可用战斗纵切还缺什么

- 目标表达式底座已经能支撑更多怪物技能附带状态和部分状态监听 callback。
- 下一步建议补状态系统主体：stack/refresh/chance，再补 duration/tick/expire。
- 之后再把 DoT tick、控制、抵抗、免疫、驱散按状态生命周期接入。

## 距离完整复刻还缺什么

- 完整目标表达式系统：排序、随机、fetch、唯一实体、相邻目标、召唤物和 servant 目标。
- 完整状态系统：叠层、刷新、概率、失败分支、持续时间、tick、DoT、控制、抵抗、免疫、驱散。
- 全角色数据卡、光锥、内外圈遗器与套装机制。
- 全怪物技能、被动、阶段切换、召唤、波次和关卡倍率。
- 完整敌方行动推演、波次和关卡环境。
