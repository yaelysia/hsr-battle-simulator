# v8 Existing Mechanism Trust Audit Checkpoint v0_225

## Scope

本阶段不新增游戏机制，专门对 v0_200-v0_224 已有 runtime 路径做可信度审计和必要回正。

已实现：

- `RuntimeSourceAuditor` 升级为 mutation provenance 闸门。
- 新增 mutation source policy，覆盖：
  - `combat_executor.timeline`
  - `combat_executor.resources`
  - `damage_system`
  - `status_system`
  - `effect_system`
  - `queue_system`
  - `combat_executor.queue`
- 新增 `validate_v0_225`，生成：
  - `source_audit_full_v0_225.json`
  - `mechanism_trust_matrix_v0_225.json`
  - `sample_negative_cases_v0_225.json`
  - `sample_source_audit_trace_v0_225.json`
- `QueueSystem` mutation 补齐 queue metadata，避免未来队列机制继续使用不可审计 source。

## Fixes Found During Audit

- 修正 source audit 的语义边界：
  - 真正产生 action mutation 的 `ActionDefinitionIR` 必须 executable。
  - `ActionEventIR` 是事件/phase 来源图，当前只要求可追踪，不能误要求它承担完整 executable 语义。
  - damage mutation 必须来自 executable `DamageEmissionIR`。
  - `AbilityTaskIR` / `HitProfileIR` 作为 damage provenance 父节点要求可追踪，不能绕过 `DamageEmissionIR` 单独发射伤害。
- 修正 v0_225 验证自身的 status ledger replay：
  - 先执行真实 TBGD AddModifier 得到带状态的 before state。
  - 再执行 action transition。
  - replay 现在基于正确 before snapshot。
- 修正验证误判：
  - fixed 主线样例不存在时，Heal/Shield 标记为 blocked，而不是要求不存在的 transition。
  - RemoveModifier/RemoveSelfModifier 样例补充结构化 selection metadata。

## Audit Summary

`validation_outputs_v0_225/source_audit_full_v0_225.json`：

- `ok=true`
- checked transitions：13
- checked mutations：35
- source policy 覆盖全部当前 runtime mutation source。

`validation_outputs_v0_225/mechanism_trust_matrix_v0_225.json`：

- `ok=true`
- 不存在 `needs_fix`。
- `true_damage` / `hp_loss`：仍为 `structural_only`，当前只验证 bypass 普通乘区语义，尚未建立 executable TBGD emission 主路径。
- `trigger_window`：仍为 `structural_only`，当前只支持 actor/primary-target local，global/per-hit scope 未完成。
- `resource_delta`：仍为 `structural_only`，ModifySPNew 正例依赖 manual input binding smoke。
- `heal` / `shield`：当前无 fixed mainline executable 样例时保持 `blocked`。
- `queue`：已有 provenance policy，但无 executable queue 机制，保持 `blocked`。

## Validation

在 `hsr_v075_baseline_clean/hsr` 下已通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir /tmp/hsr_v8_regression_v0_200
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_203 --output-dir /tmp/hsr_v8_regression_v0_203
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_204 --output-dir /tmp/hsr_v8_regression_v0_204
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_205 --output-dir /tmp/hsr_v8_regression_v0_205
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_206 --output-dir /tmp/hsr_v8_regression_v0_206
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_207 --output-dir /tmp/hsr_v8_regression_v0_207
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_208 --output-dir /tmp/hsr_v8_regression_v0_208
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_209 --output-dir /tmp/hsr_v8_regression_v0_209
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_210 --output-dir /tmp/hsr_v8_regression_v0_210
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_211 --output-dir /tmp/hsr_v8_regression_v0_211
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_212 --output-dir /tmp/hsr_v8_regression_v0_212
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_213 --output-dir /tmp/hsr_v8_regression_v0_213
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_214 --output-dir /tmp/hsr_v8_regression_v0_214
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_215 --output-dir /tmp/hsr_v8_regression_v0_215
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_216 --output-dir /tmp/hsr_v8_regression_v0_216
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_217 --output-dir /tmp/hsr_v8_regression_v0_217
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_218 --output-dir /tmp/hsr_v8_regression_v0_218
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_219 --output-dir /tmp/hsr_v8_regression_v0_219
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_220 --output-dir /tmp/hsr_v8_regression_v0_220
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_221 --output-dir /tmp/hsr_v8_regression_v0_221
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_222 --output-dir /tmp/hsr_v8_regression_v0_222
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_223 --output-dir /tmp/hsr_v8_regression_v0_223
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_224 --output-dir /tmp/hsr_v8_regression_v0_224
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir validation_outputs_v0_225
```

全部 `ok=true`。

## Remaining Risk

可以继续搭建下一层机制，但以下边界不能被误认为已完整：

- 没有 executable TBGD emission 的 true damage / hp loss 还不能算主线完整机制。
- trigger window 还不是完整游戏事件系统，global watcher、being-hit、per-hit scope 仍未实现。
- queue 只有 source policy，没有 runtime executable 机制。
- Heal/Shield 当前不伪造 fixed 样例；无可证明 fixed 主线样例时保持 blocked。
- Condition evaluator 目前是非 mutation 的结构化验证，还不是完整触发条件 VM。
