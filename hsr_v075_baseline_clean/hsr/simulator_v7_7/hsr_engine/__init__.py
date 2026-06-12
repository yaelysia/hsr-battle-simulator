"""Core rule helpers for the HSR battle simulator.

The simulator now treats model-pack YAML as an external schema and converts it
into a normalized internal representation before battle resolution.  Public
helpers in this package are intentionally small and deterministic so they can be
unit-tested independently from battle routes.
"""
