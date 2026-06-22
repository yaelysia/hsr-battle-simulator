# v8 Event Dispatch Foundation Closure Checkpoint v0_238

## Scope

本阶段只收束事件分发基础，不实现队列、追击、反击、敌人 AI 或 bounce RNG。

完成内容：

- `EventDispatchSystem` 增加稳定 listener order key：
  - scope priority
  - unit order
  - status order
  - callback source order
  - task order
- Runtime event 进入统一 event alias matrix：
  - explicit `callback_event` / `tbgd_event`
  - action window `event.window`
  - known runtime events: `damage.hit`、`toughness.hit`、`break.triggered`
- listener blocked reason 统一分类：
  - `source_not_admitted`
  - `scope_not_admitted`
  - `condition_not_admitted`
  - `target_not_admitted`
  - `effect_not_admitted`
  - `downstream_intent_missing`
  - `event_alias_missing`
- action window trigger records 与 status callback/listener records 统一为 `listener_match` record shape。
- coverage matrix 增加 `status_callbacks.blocked_category_counts`。
- 新增 `validate_v0_238`，验证顺序稳定、alias admission、blocked category、record shape 与回归不退化。

## Current Trust Boundary

`event_dispatch_foundation` 标记为 `trusted_for_current_scope`。

可信范围：

- action/status/break 事件都能通过同一个 dispatch 入口形成可审计记录。
- listener match 顺序稳定。
- blocked listener 不产生 mutation。
- action window 与 status callback 输出统一 listener record shape。
- 多目标 hit event 已携带 per-hit target payload。

仍然 blocked 的依赖：

- global listener 真正执行需要后续 global watcher admission。
- being-hit listener 真正执行需要受击事件语义和 target/effect admission。
- per-hit listener 真正执行需要 per-hit trigger 与下游 intent admission。
- 队列、追击、反击、敌方 AI、bounce RNG 不属于本阶段。

## Validation

运行目录：

```text
hsr_v075_baseline_clean/hsr
```

已运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_227 --output-dir /tmp/hsr_v8_regression_v0_227
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_235 --output-dir /tmp/hsr_v8_regression_v0_235
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_237 --output-dir /tmp/hsr_v8_regression_v0_237
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_238 --output-dir /tmp/hsr_v8_v0_238
git diff --check
```

结果：

- v0_225 `ok=True`
- v0_227 `ok=True`
- v0_235 `ok=True`
- v0_237 `ok=True`
- v0_238 `ok=True`
- `git diff --check` passed

v0_238 关键检查：

- listener order stable: passed
- event alias records present: passed
- blocked listener category concrete: passed
- unified listener record shape: passed
- action window trigger record shape: passed
- unknown event alias negative case non-mutating: passed

## Notes

`damage.hit` / `toughness.hit` / `break.triggered` 现在有 canonical runtime event alias，但由于 per-hit / being-hit / global listener 下游承接尚未 admission，默认输出 `downstream_intent_missing`，不产生 mutation。

这不是可执行监听机制完成，而是事件分发基础已收口到可扩展形态。
