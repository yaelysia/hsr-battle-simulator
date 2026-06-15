"""Parallel combat core boundary for the HSR simulator."""

from .contracts import ActionInput, ActionTransaction, RuleDataView, StateMutator, StateView
from .damage import DamageApplication, DamageApplier, DamageResolver
from .executor import CombatExecutor
from .runtime import CombatRuntime
from .rules import RuleBook, RuleEvaluator
from .state import CombatStateError, StateMutator as StateMutatorImpl, StateStore
from .actions import ActionRuntime
from .coverage import build_canonical_ir_coverage_matrix
from .effects import EffectRuntime
from .effect_registry import EffectRegistry
from .queues import QueueRuntime
from .resources import ResourceRuntime
from .status import StatusRuntime
from .static_checks import run_clean_core_static_checks
from .targets import TargetRuntime
from .timeline import TimelineRuntime

__all__ = [
    "ActionInput",
    "ActionTransaction",
    "RuleDataView",
    "StateMutator",
    "StateView",
    "DamageApplication",
    "DamageApplier",
    "DamageResolver",
    "CombatExecutor",
    "CombatRuntime",
    "RuleBook",
    "RuleEvaluator",
    "CombatStateError",
    "StateMutatorImpl",
    "StateStore",
    "ActionRuntime",
    "EffectRegistry",
    "build_canonical_ir_coverage_matrix",
    "EffectRuntime",
    "QueueRuntime",
    "ResourceRuntime",
    "StatusRuntime",
    "run_clean_core_static_checks",
    "TargetRuntime",
    "TimelineRuntime",
]
