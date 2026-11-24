"""Test paketi. Testler birbirini `from test_kutu import ...` ile çıplak adla içe aktarır;
kökten `python -m unittest discover` de çalışsın diye bu klasör import yoluna eklenir."""
import sys
from pathlib import Path

_BU = str(Path(__file__).resolve().parent)
if _BU not in sys.path:
    sys.path.insert(0, _BU)
