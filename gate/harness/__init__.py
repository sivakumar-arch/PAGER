"""PAGER Paper 2 gate harness. Implements gate/PROTOCOL.md, gate/PINNING.md and gate/AMENDMENTS.md."""

import sys
from pathlib import Path

_GATE = Path(__file__).resolve().parents[1]
if str(_GATE) not in sys.path:            # makes the frozen gate/oracle_residual.py importable
    sys.path.insert(0, str(_GATE))
