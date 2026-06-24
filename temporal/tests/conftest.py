"""Shared pytest setup for the worker test-suite.

The worker runs as ``python -m src.worker`` from the ``temporal`` directory, so
``src`` is a package and its parent directory must be importable. Adding it here
lets tests import the real modules (``src.activities.ai_summarization``,
``src.workflows.ai.summarize_workflow``, ``src.poller`` ...) with their relative
imports intact, while the legacy ``test_summarization.py`` keeps importing the
pure ``activities.summarization`` helpers via its own path insertion.
"""
from __future__ import annotations

import os
import sys

TEMPORAL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if TEMPORAL_DIR not in sys.path:
    sys.path.insert(0, TEMPORAL_DIR)
