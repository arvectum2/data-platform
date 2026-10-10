"""Public facade must not eager-import the whole platform on every submodule import."""
from __future__ import annotations

import subprocess
import sys


def test_root_namespace_is_lazy_in_fresh_interpreter():
    result = subprocess.run(
        [sys.executable, "-c", "import sys, arvectum_data; "
         "assert 'arvectum_data.engine' not in sys.modules; "
         "assert 'arvectum_data.results' not in sys.modules; "
         "from arvectum_data import AcquisitionEngine, FieldSpec; "
         "from arvectum_data.acquisition import AcquisitionEngine as ExpectedEngine; "
         "assert AcquisitionEngine is ExpectedEngine; "
         "assert 'FieldSpec' in dir(arvectum_data); "
         "assert not hasattr(arvectum_data, 'NO_SUCH_SYMBOL')"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_all_public_names_remain_resolvable():
    import arvectum_data
    assert len(arvectum_data.__all__) == len(set(arvectum_data.__all__))
    for name in arvectum_data.__all__:
        assert getattr(arvectum_data, name) is not None, name
