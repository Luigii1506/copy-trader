import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Must be set before collector modules are imported: they read it at import time.
TEST_DATA = Path(tempfile.mkdtemp(prefix="copy-trader-test-"))
os.environ["COPY_TRADER_DATA"] = str(TEST_DATA)


@pytest.fixture
def data_dir() -> Path:
    shutil.rmtree(TEST_DATA, ignore_errors=True)
    TEST_DATA.mkdir()
    return TEST_DATA
