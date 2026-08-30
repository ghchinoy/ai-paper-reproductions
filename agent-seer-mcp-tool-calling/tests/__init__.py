"""Agent Seer Test Suite package.

Provides automated unit, integration, boundary, and performance benchmark tests.
"""
import os
import sys

# Ensure src directory is available on sys.path
SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
