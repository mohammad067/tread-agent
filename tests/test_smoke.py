"""Smoke test: the package imports and exposes its version.

This is the M3.1 baseline test proving the scaffold and toolchain work end-to-end.
Real behavioral tests arrive with each component batch (M3.3+).
"""

import market_state_engine


def test_package_version_is_exposed() -> None:
    assert market_state_engine.__version__ == "0.1.0"
