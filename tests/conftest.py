from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.data.panel import get_panel
from app.main import create_app

# 사업내역서 PDF는 담당 공무원 실명이 있어 저장소에 올리지 않는다.
# PDF가 없으면 근거 검색은 등록부(Markdown)만으로 동작하므로, PDF를 전제한 테스트만 건너뛴다.
_pdf_dir = get_settings().resolve(get_settings().evidence_pdf_dir)
PDFS_AVAILABLE = _pdf_dir.exists() and any(_pdf_dir.glob("*.pdf"))

requires_pdfs = pytest.mark.skipif(
    not PDFS_AVAILABLE,
    reason=(
        "사업내역서 PDF가 없습니다. 저장소에 포함되지 않으므로 팀 내부에서 받아 "
        f"{_pdf_dir} 에 넣으면 이 테스트가 실행됩니다."
    ),
)


@pytest.fixture(scope="session")
def panel():
    return get_panel()


@pytest.fixture(scope="session")
def client():
    with TestClient(create_app()) as test_client:
        yield test_client
