"""Writes subpackage: opt-in, snapshot-backed minimal edit support.

Every write flows through ``pipeline``: lock, snapshot, source-hash check,
plan, confirm token, execute, post-write validate, audit.  The opt-in flag is
``KICAD_ENABLE_WRITES=1``; without it every entry point raises immediately.
"""
