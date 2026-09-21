from fastapi import FastAPI


def create_app(
    *,
    service_id: str,
    version: str = "0.1.0",
    description: str = "",
) -> FastAPI:
    """Capability 서버용 FastAPI 앱 생성.

    Action log 미들웨어는 Core(hub) 가 proxy 시점에 SQL 로 기록하므로 capability
    서버 쪽에선 부착하지 않는다.

    Args:
        service_id: 서비스 식별자 (예: "container", "signal")
        version: 서비스 버전
        description: OpenAPI 설명
    """
    app = FastAPI(
        title=f"{service_id} capability",
        version=version,
        description=description,
    )

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": service_id, "version": version}

    return app
