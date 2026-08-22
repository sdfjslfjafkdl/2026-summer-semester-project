"""배포 계약 테스트.

컨테이너·Railway 환경에서 깨지기 쉬운 지점만 못박는다.
  - 근거 검색 캐시가 없거나 쓸 수 없어도 500을 내지 않는다(볼륨이 비어 있는 첫 기동).
  - 헬스체크 경로가 railway.json 설정과 실제 라우트에서 일치한다.
  - 이미지에 API 키를 굽지 않는다.
  - 키 없이 LLM_ENABLED=true 여도 규칙 기반으로 폴백한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import PROJECT_ROOT, Settings, get_settings
from app.services import evidence_search

HEALTHCHECK_PATH = "/api/health"


@pytest.fixture
def empty_index_dir(tmp_path, monkeypatch):
    """캐시가 전혀 없는 상태. Railway 볼륨을 처음 붙였을 때와 같다."""
    target = tmp_path / "runtime" / "index"
    monkeypatch.setenv("INDEX_DIR", str(target))
    get_settings.cache_clear()
    evidence_search._index = None
    yield target
    get_settings.cache_clear()
    evidence_search._index = None


def test_search_works_with_empty_volume(client, empty_index_dir):
    """볼륨이 비어 있어도 첫 검색 요청이 성공해야 한다."""
    assert not empty_index_dir.exists()

    response = client.get("/api/evidence/search", params={"q": "청년 주거", "top_k": 3})
    assert response.status_code == 200
    assert response.json()["data"]["hits"]

    # 첫 요청이 캐시를 만들어 둔다
    assert (empty_index_dir / evidence_search.INDEX_FILENAME).exists()


def test_health_works_with_empty_volume(client, empty_index_dir):
    """헬스체크는 캐시와 무관하게 떠야 한다. Railway 가 이걸로 배포 성공을 판정한다."""
    body = client.get(HEALTHCHECK_PATH).json()
    assert body["data"]["status"] == "ok"
    assert body["data"]["panel_rows"] == 1056


def test_search_survives_unwritable_cache_dir(client, tmp_path, monkeypatch):
    """캐시 디렉터리에 쓸 수 없어도 검색은 500이 아니라 200이어야 한다.

    볼륨 소유자가 root 이고 프로세스가 비root 일 때 실제로 일어날 수 있는 상황이다.
    캐시는 원본 문서에서 다시 만들 수 있는 부가물이라 요청을 실패시킬 이유가 없다.
    """
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    monkeypatch.setenv("INDEX_DIR", str(readonly / "index"))
    readonly.chmod(0o555)  # 하위 디렉터리 생성 불가
    get_settings.cache_clear()
    evidence_search._index = None

    try:
        response = client.get("/api/evidence/search", params={"q": "고려인", "top_k": 3})
        assert response.status_code == 200
        assert response.json()["data"]["hits"]
    finally:
        readonly.chmod(0o755)
        get_settings.cache_clear()
        evidence_search._index = None


def test_railway_healthcheck_matches_real_route(client):
    config = json.loads((PROJECT_ROOT / "railway.json").read_text(encoding="utf-8"))
    assert config["deploy"]["healthcheckPath"] == HEALTHCHECK_PATH
    assert config["build"]["builder"] == "DOCKERFILE"
    assert client.get(HEALTHCHECK_PATH).status_code == 200


def test_port_is_read_in_python_not_by_the_shell():
    """시작 커맨드에 쉘 확장을 쓰지 않는다.

    Railway 가 시작 커맨드를 쉘 없이 실행해 '${PORT:-8000}' 이 문자열 그대로
    uvicorn 에 넘어가면서 "is not a valid integer" 로 죽은 적이 있다.
    포트를 읽는 주체를 파이썬으로 옮겨 실행 방식과 무관하게 만든다.
    """
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    railway = json.loads((PROJECT_ROOT / "railway.json").read_text(encoding="utf-8"))

    assert 'CMD ["python", "-m", "app.server"]' in dockerfile
    assert "${PORT" not in dockerfile.split("CMD")[-1], "CMD 에 쉘 확장이 남아 있습니다"
    assert "startCommand" not in railway["deploy"], "시작 커맨드는 Dockerfile CMD 한 곳에만 둔다"


def test_resolve_port_handles_every_input():
    """포트 때문에 서버가 못 뜨는 상황을 만들지 않는다."""
    from app.server import DEFAULT_PORT, resolve_port

    assert resolve_port("8080") == 8080
    assert resolve_port(" 3000 ") == 3000
    assert resolve_port(None if "PORT" not in __import__("os").environ else "8000") in (
        DEFAULT_PORT,
        8000,
    )
    # 플랫폼이 이상한 값을 줘도 기본값으로 뜬다
    assert resolve_port("") == DEFAULT_PORT
    assert resolve_port("${PORT:-8000}") == DEFAULT_PORT  # 실제로 겪은 값
    assert resolve_port("not-a-number") == DEFAULT_PORT
    assert resolve_port("0") == DEFAULT_PORT
    assert resolve_port("99999") == DEFAULT_PORT


def test_server_module_binds_all_interfaces():
    """컨테이너 밖에서 접근하려면 0.0.0.0 에 바인딩해야 한다."""
    from app.server import DEFAULT_HOST

    assert DEFAULT_HOST == "0.0.0.0"


def test_no_buildkit_cache_mounts():
    """BuildKit cache mount 를 쓰지 않는다.

    Railway 는 mount id 에 서비스별 cacheKey 접두사(s/<service-id>-...)를 요구한다.
    그걸 박으면 Dockerfile 이 특정 서비스에 묶여 로컬에서 빌드할 수 없게 되므로,
    이식성을 택하고 도커 레이어 캐시에 맡긴다.
    """
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    offending = [line.strip() for line in dockerfile.splitlines() if "--mount=type=cache" in line]
    assert not offending, f"Railway 가 거부하는 cache mount 가 있습니다: {offending}"


def test_dockerfile_puts_project_on_import_path():
    """이미지는 의존성만 설치하고 프로젝트 자체는 설치하지 않는다.

    따라서 /app 이 import 경로에 있어야 `app` 패키지를 찾는다. 로컬 개발 환경은
    `uv pip install -e .` 로 편집 설치돼 있어 이 문제가 드러나지 않는다.
    빌드 스테이지(아티팩트 생성)와 런타임 스테이지(uvicorn) 양쪽 모두 필요하다.
    """
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.count("PYTHONPATH=/app") >= 2, (
        "빌드·런타임 두 스테이지 모두에 PYTHONPATH=/app 이 있어야 합니다"
    )


def test_dependency_layer_is_separate_from_source():
    """의존성 설치가 소스 COPY 보다 앞에 와야 레이어 캐시가 산다."""
    lines = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
    install_at = next(i for i, line in enumerate(lines) if "uv pip install" in line)
    source_at = next(i for i, line in enumerate(lines) if line.strip().startswith("COPY app"))
    assert install_at < source_at


def test_image_does_not_bake_secrets():
    """ANTHROPIC_API_KEY 는 런타임 환경변수로만 받는다."""
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    for line in dockerfile.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "ANTHROPIC_API_KEY" not in stripped, f"Dockerfile 이 키를 굽고 있습니다: {line}"

    ignored = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert ".env" in ignored, ".env 가 이미지에 들어가면 안 됩니다"


def test_dockerignore_excludes_runtime_and_dev_paths():
    ignored = set((PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").split())
    for path in ("tests", "evals", "data/index", ".pytest_cache", "__pycache__", ".git", ".venv"):
        assert path in ignored, f".dockerignore 에 {path} 가 없습니다"


def test_llm_falls_back_to_rules_without_key():
    """키가 없으면 LLM_ENABLED=true 여도 규칙 기반으로 동작한다."""
    settings = Settings(llm_enabled=True, anthropic_api_key="")
    assert settings.llm_active is False

    with_key = Settings(llm_enabled=True, anthropic_api_key="sk-ant-test")
    assert with_key.llm_active is True

    disabled = Settings(llm_enabled=False, anthropic_api_key="sk-ant-test")
    assert disabled.llm_active is False


def test_cors_origins_come_from_environment(monkeypatch):
    """배포 후 프론트 도메인 추가는 코드 수정 없이 환경변수로만 한다."""
    settings = Settings(cors_origins="https://a.example, https://b.example")
    assert settings.cors_origins == ["https://a.example", "https://b.example"]


def test_artifacts_are_present_for_runtime():
    """아티팩트는 빌드 시점에 만들어 이미지에 포함한다. 런타임 생성은 하지 않는다."""
    artifact_dir = get_settings().resolve(get_settings().artifact_dir)
    assert (artifact_dir / "did_twfe_v1.json").exists()
    assert (artifact_dir / "oot_validation_v1.json").exists()

    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "scripts/build_artifacts.py" in dockerfile

    ignored = set((PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").split())
    assert "data/artifacts" in ignored, "빌드 스테이지가 새로 만들므로 복사 대상이 아니다"


def test_compose_mounts_source_for_reload():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "--reload" in compose
    assert "./app:/app/app" in compose
    assert "env_file" in compose


def test_index_dir_is_configurable(monkeypatch, tmp_path):
    """볼륨 경로는 환경변수로 갈아끼운다. 코드에 경로를 박지 않는다."""
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "somewhere"))
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.resolve(settings.index_dir) == tmp_path / "somewhere"
    finally:
        get_settings.cache_clear()


def test_relative_paths_resolve_under_project_root():
    settings = Settings(index_dir=Path("data/index"))
    assert settings.resolve(settings.index_dir) == PROJECT_ROOT / "data" / "index"
