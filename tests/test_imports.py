import subprocess
import sys

import pytest

# Each module must import on its own: the other tests always load the planner first, which hides
# circular imports between `algorithms` and `support`.
MODULES = ["relief_kitchen.algorithms.csp", "relief_kitchen.algorithms.planner", "relief_kitchen.support.model_helpers",
           "relief_kitchen.support.motion", "relief_kitchen.support.report", "relief_kitchen.support.run",
           "relief_kitchen.viz.page_delivery", "relief_kitchen.planning.__main__", "relief_kitchen.uncertainty.__main__"]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_alone(module):
    res = subprocess.run([sys.executable, "-c", f"import {module}"], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
