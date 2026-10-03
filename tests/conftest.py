"""Fixtures inherit Windows ACLs and remain under the new project only."""
from pathlib import Path
import uuid
import pytest
import cadtoolbox.geometry

@pytest.fixture
def case_dir():
    root = Path(__file__).resolve().parents[1]/'.cache/migration-tests'/uuid.uuid4().hex
    root.mkdir(parents=True)
    return root
