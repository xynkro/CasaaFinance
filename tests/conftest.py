"""Shared test fixtures for FinancePWA tests."""
import sys
from pathlib import Path

# Ensure project root is on sys.path so `from src.xxx` imports work
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
