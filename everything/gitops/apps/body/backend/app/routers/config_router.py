from fastapi import APIRouter
from app.core.config import CONFIG_FILE
from app.core.storage import read_json

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config")
def get_config():
    data = read_json(CONFIG_FILE)
    if data is None:
        return {}
    return data
