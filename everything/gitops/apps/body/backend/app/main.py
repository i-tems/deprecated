from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.middleware.auth_middleware import AuthMiddleware
from app.routers import (
    auth,
    config_router,
    evaluations,
    skills,
    running_evaluations,
    overview,
    profile,
)

app = FastAPI(title="Body Tracker API", version="1.2.0")

app.add_middleware(AuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(config_router.router)
app.include_router(evaluations.router)
app.include_router(skills.router)
app.include_router(running_evaluations.router)
app.include_router(overview.router)
app.include_router(profile.router)


@app.get("/api/health")
def health_check():
    return {"status": "ok"}
