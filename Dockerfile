# syntax=docker/dockerfile:1

# ─────────────────────────────────────────────────────────────────────
# 빌드 스테이지: uv 로 의존성을 설치하고 분석 아티팩트를 생성한다.
# 아티팩트는 런타임에 만들지 않는다. 기동 시점에 계산이 끼면 헬스체크가 느려지고,
# 컨테이너마다 다른 산출물이 나올 여지가 생긴다.
# ─────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

# 로컬 개발에 쓰는 uv 와 같은 버전으로 고정한다.
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# 의존성 레이어를 소스와 분리해 캐시가 살아 있게 한다.
COPY pyproject.toml README.md ./
# BuildKit cache mount 는 쓰지 않는다. Railway 는 mount id 에 서비스별 cacheKey
# 접두사(s/<service-id>-...)를 요구해서, 그걸 넣으면 이 Dockerfile 이 특정 서비스에
# 묶여 로컬·타 환경에서 못 쓰게 된다. 의존성 레이어를 소스와 분리해 둔 덕분에
# 도커 레이어 캐시만으로도 pyproject.toml 이 바뀔 때만 다시 설치한다.
RUN uv venv /opt/venv && \
    VIRTUAL_ENV=/opt/venv uv pip install -r pyproject.toml

# 의존성만 설치하고 프로젝트 자체는 설치하지 않는다(소스를 그대로 복사해 쓴다).
# 그래서 app 패키지를 찾으려면 /app 이 import 경로에 있어야 한다.
# 로컬은 uv pip install -e . 로 편집 설치돼 있어 이 문제가 드러나지 않는다.
ENV PATH="/opt/venv/bin:$PATH" \
    VIRTUAL_ENV=/opt/venv \
    PYTHONPATH=/app

COPY app ./app
COPY scripts ./scripts
COPY data/raw ./data/raw

# 빌드 시점에 v1 아티팩트를 만들어 이미지에 굽는다.
RUN python scripts/build_artifacts.py && \
    test -f data/artifacts/did_twfe_v1.json && \
    test -f data/artifacts/oot_validation_v1.json

# ─────────────────────────────────────────────────────────────────────
# 런타임 스테이지: 인터프리터와 가상환경, 데이터만 담는다.
# uv, 빌드 캐시, 테스트, 평가 스크립트는 넘어오지 않는다.
# ─────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# 비root 실행. 홈 디렉터리를 주어 파이썬이 임시 파일을 쓸 곳이 있게 한다.
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder --chown=appuser:appuser /app/data /app/data
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser scripts ./scripts
COPY --chown=appuser:appuser pyproject.toml README.md ./

# 근거 검색 캐시는 런타임 쓰기가 발생한다. Railway 볼륨을 /app/data/runtime 에
# 마운트하며, 볼륨이 비어 있어도(또는 쓰기가 막혀도) 서버는 그대로 기동한다.
# 캐시는 원본 문서에서 언제든 다시 만들 수 있는 부가물이기 때문이다.
RUN mkdir -p /app/data/runtime/index && chown -R appuser:appuser /app/data/runtime

ENV PATH="/opt/venv/bin:$PATH" \
    VIRTUAL_ENV=/opt/venv \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    INDEX_DIR=/app/data/runtime/index \
    ARTIFACT_DIR=/app/data/artifacts \
    PORT=8000

# ANTHROPIC_API_KEY 는 이미지에 굽지 않는다. 런타임 환경변수로만 받는다.
# 키가 없으면 LLM_ENABLED=true 여도 규칙 기반 라우터·서술로 폴백한다.

USER appuser

EXPOSE 8000

# Railway 가 주입하는 PORT 를 읽고, 없으면 8000 으로 뜬다.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
