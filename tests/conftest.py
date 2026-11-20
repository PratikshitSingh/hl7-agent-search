from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from hl7search.parser import parse
from hl7search.seed import demo_messages
from hl7search.store import Store


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def store(db_path: Path) -> Iterator[Store]:
    s = Store(db_path)
    for raw in demo_messages():
        s.insert(parse(raw))
    yield s
    s.close()
