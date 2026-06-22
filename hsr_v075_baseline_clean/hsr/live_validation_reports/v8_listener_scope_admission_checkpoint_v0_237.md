# v8 v0_237 Listener Scope Admission 检查点

## 范围

- `EventDispatchSystem` 新增通用 `dispatch_event()`，action window 与 status callback wrapper 均收束到该入口。
- `StatusCallbackIR` 增加 `scope_kind / source_mode / admission_status / blocking_dependency`，listener scope 不再只靠验证脚本推断。
- `RuleBook` 增加按 `event + scope` 与 `modifier + event + scope` 的 callback 查询索引。
- `CombatExecutor` 将 damage / toughness / break 产出的 `GameEvent` 送入 dispatcher，dispatch records 纳入 settlement。
- per-hit 事件保留 `current_hit_target_id / primary_action_target_id / emission ids / source_trace`，不再只用 primary target 描述多目标命中。

## 当前可信范围

- status-local executable callback 可通过 `dispatch_event()` 执行，并继续通过 settlement traceability、snapshot replay、source audit。
- per-hit / being-hit / global listener 可以被真实结构化匹配；未 admission 的 listener 只产生 process-only blocked record，不改 state。
- 多目标 damage/toughness hit event 已具备 per-hit event payload，并通过 dispatcher 记录分发过程。
- event dispatch 本身为 `trusted_for_current_scope`；global / being-hit / per-hit listener 执行仍保持 blocked，直到 source、scope、condition、target、effect 全部 admitted。

## 仍不纳入本阶段

- 不实现队列插队、追击、反击、敌人 AI、bounce RNG。
- 不默认执行 global listener、being-hit listener、per-hit trigger。
- 不根据 raw event 名称硬猜 hit event 到 TBGD callback 的完整映射；缺少明确 callback event 时只记录 blocked dependency。

## 验证

运行目录：`hsr_v075_baseline_clean/hsr`

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_227 --output-dir /tmp/hsr_v8_regression_v0_227
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_235 --output-dir /tmp/hsr_v8_regression_v0_235
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_236 --output-dir /tmp/hsr_v8_regression_v0_236
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_237 --output-dir /tmp/hsr_v8_v0_237
git diff --check
```

当前新验证结果：

- `compileall` 通过
- `validate_v0_225 ok=true`
- `validate_v0_227 ok=true`
- `validate_v0_235 ok=true`
- `validate_v0_236 ok=true`
- `validate_v0_237 ok=true`
- `git diff --check` 通过
- status-local dispatch：通过
- blocked scoped listener：通过，样例为真实 `per_hit_target_local` callback，after snapshot 不变
- multi-target dispatch：通过，per-hit payload 与 dispatcher records 存在
