import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Objects are Windows-only")
def test_child_process_can_apply_bounded_job_object():
    client_dir = Path(__file__).resolve().parents[1]
    command = (
        "from windows_job import apply_current_process_limits; "
        "apply_current_process_limits(memory_gb=8, cpu_cores=8); "
        "print('JOB_LIMITS_OK')"
    )
    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=client_dir,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert "JOB_LIMITS_OK" in result.stdout


def test_cpu_rate_maps_logical_core_cap_to_job_object_scale():
    from windows_job import cpu_rate_for_cores

    assert cpu_rate_for_cores(8, 32) == 2500
    assert cpu_rate_for_cores(8, 8) == 10000
    assert cpu_rate_for_cores(8, 4) == 10000
