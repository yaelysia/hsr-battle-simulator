# v8 Source Authenticity Audit Checkpoint v0_224

## Scope

本阶段不新增游戏机制，专门落地来源真实性审计红线。

已实现：

- 新增 `RuntimeSourceAuditor`，对 runtime `Mutation` 执行自动反查：
  - mutation -> settlement record
  - mutation metadata -> Canonical IR id
  - Canonical IR node -> TBGD `source_path/raw_type/raw_id/evidence`
- timeline/resource mutation 补齐 action 来源：
  - `action_id`
  - `action_level`
  - `definition_id`
  - `action_event_id`
  - `source_trace`
  - `action_event_source_trace`
- status lifecycle 每条 mutation 都有自己的 settlement record，不再只给 `status_details` mutation 记账。
- v0_215/v0_216/v0_217 清掉固定文件名、固定角色、固定 hash 主路径选择。
- v0_224 validation 增加：
  - source audit
  - executable IR source guard
  - non-mutating status guard
  - validation sample policy guard
  - `sample_source_audit_trace_v0_224.json`

## Source Audit Coverage

`validation_outputs_v0_224/sample_source_audit_trace_v0_224.json` 覆盖：

- damage mutation
- resource mutation
- timeline mutation
- status/effect mutation

v0_224 当前要求：

- damage mutation 必须来自 executable `DamageEmissionIR`。
- status/effect mutation 必须来自 executable `EffectIR`，并带 lifecycle/evaluation 结果。
- timeline/resource mutation 必须带 action definition/event 来源。
- blocked/audit-only/discovered-only/placeholder 不允许直接产生 mutation。

## Fixes Found During Validation

- 修复 `SetEnergyBarState` 审计语义：固定 `state/active` 可写机制条，未绑定动态 count 只保留为未命中 evaluation，不作为执行依据。
- 修复 status lifecycle settlement 粒度：`statuses` 与 `status_details` 两条 mutation 均可独立追溯。
- 修正 v0_215 shield 样例选择：必须满足结构化 mainline、shield opcode、supported formula type、dynamic hash amount，不再按 Gepard 文件名选择。

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
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_224 --output-dir validation_outputs_v0_224
```

v0_224 摘要：

- `source_audit.ok=true`
- damage/resource/timeline/status/effect mutation 来源类别均覆盖
- `sample_source_audit_trace_v0_224.json` 完整生成
- static checks 通过
- snapshot completeness、transition contract、settlement traceability、replay 回归通过

## Current Distance

最小可用战斗纵切：底层来源闸门已经比之前更可靠，可以继续搭建新机制。仍缺削韧、击破、DoT、super-break、回合生命周期、队列插队、per-hit trigger、多段/弹射/扩散数值等关键机制。

完整复刻：仍处在基础内核和来源链路阶段。当前更接近“可以安全扩展”的状态，但还不是游戏内完整模拟器。
