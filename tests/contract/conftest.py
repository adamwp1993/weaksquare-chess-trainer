from __future__ import annotations

import pytest

from tests.helpers import build_api
from weaksquare.bridge.api import Api


@pytest.fixture
def api(paths, clock) -> Api:  # type: ignore[no-untyped-def]
    return build_api(paths, clock)
