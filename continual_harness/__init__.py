# This package is derived from sethkarten/continual-harness (MIT License,
# Copyright (c) 2026 Seth Karten et al.) and has been modified.
# See THIRD-PARTY-NOTICES.txt.
"""Continual Harness — a reset-free, self-improving agent framework.

The framework owns the agent loop, evolution tools (memory/skills/subagents/
evolve/planning), persistent stores, the LLM client, the harness evolver, and a
prompt compiler. Benchmarks attach as data + a thin adapter.
"""
