import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

TEST_DATA = ROOT / "data_test"
os.environ["APP_MODE"] = "local"
os.environ["DATA_DIR"] = str(TEST_DATA)
os.environ["DEFAULT_COST_LIMIT_JPY"] = "1500"


@pytest.fixture(scope="session", autouse=True)
def _clean_data_dir():
    if TEST_DATA.exists():
        shutil.rmtree(TEST_DATA)
    yield
    if TEST_DATA.exists():
        shutil.rmtree(TEST_DATA)
