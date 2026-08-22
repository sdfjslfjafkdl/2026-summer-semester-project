"""서버 진입점.

    python -m app.server

포트를 쉘 확장(`--port ${PORT:-8000}`)으로 넘기지 않고 파이썬이 직접 환경변수를 읽는다.
Railway 처럼 시작 커맨드를 쉘 없이 실행하는 플랫폼에서는 `${PORT:-8000}` 이 문자열
그대로 uvicorn 에 전달되어 "is not a valid integer" 로 죽는다. 실제로 그렇게 죽었다.
읽는 주체를 쉘에서 파이썬으로 옮기면 실행 방식과 무관하게 동작한다.
"""

from __future__ import annotations

import logging
import os

DEFAULT_PORT = 8000
DEFAULT_HOST = "0.0.0.0"  # noqa: S104 - 컨테이너 밖에서 접근하려면 모든 인터페이스에 바인딩해야 한다

logger = logging.getLogger(__name__)


def resolve_port(raw: str | None = None) -> int:
    """PORT 환경변수를 정수로 해석한다. 없거나 이상하면 기본값 8000.

    플랫폼이 값을 못 주거나 빈 문자열을 주는 경우까지 포함해, 포트 때문에
    서버가 뜨지 못하는 상황을 만들지 않는다.
    """
    value = os.environ.get("PORT") if raw is None else raw
    if value is None or not value.strip():
        return DEFAULT_PORT
    try:
        port = int(value.strip())
    except ValueError:
        logger.warning("PORT 값이 정수가 아닙니다(%r). 기본값 %d 을 씁니다.", value, DEFAULT_PORT)
        return DEFAULT_PORT
    if not (1 <= port <= 65535):
        logger.warning("PORT 값이 범위를 벗어났습니다(%d). 기본값 %d 을 씁니다.", port, DEFAULT_PORT)
        return DEFAULT_PORT
    return port


def main() -> None:
    import uvicorn

    port = resolve_port()
    host = os.environ.get("HOST", DEFAULT_HOST)
    logger.info("서버를 시작합니다: %s:%d", host, port)
    uvicorn.run("app.main:app", host=host, port=port)


if __name__ == "__main__":
    main()
