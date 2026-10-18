import pytest

from tests.genomics_helpers import build_pack


@pytest.fixture(scope="session")
def genomics_pack(tmp_path_factory):
    """One small synthetic pack shared by the GO-61 tests (hand-built persons)."""
    return build_pack(tmp_path_factory.mktemp("pack"))
