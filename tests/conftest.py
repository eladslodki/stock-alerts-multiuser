# tests/conftest.py
"""
Pre-load the real services.forex_data_provider before test collection so that
test_session_break_detector.py's sys.modules.setdefault() mock is a no-op.
This prevents the mocked normalize_symbol from leaking into other test files.
"""
import os
import sys


def pytest_configure(config):
    project_root = os.path.dirname(os.path.dirname(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    try:
        import services.forex_data_provider  # noqa: F401
    except Exception:
        pass
