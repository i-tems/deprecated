from pathlib import Path
import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24 * 7

    class Config:
        env_file = ".env"


settings = Settings()

# Data paths
DATA_DIR = Path("/app/data")
_data_dir_env = os.environ.get("DATA_DIR")
if _data_dir_env:
    DATA_DIR = Path(_data_dir_env)

EVALUATIONS_DIR = DATA_DIR / "evaluations"
SKILL_EVALUATIONS_DIR = DATA_DIR / "skill-evaluations"
RUNNING_EVALUATIONS_DIR = DATA_DIR / "running-evaluations"
CONFIG_FILE = DATA_DIR / "config.json"
PROFILE_FILE = DATA_DIR / "profile.json"
TRAINING_LOG_FILE = DATA_DIR / "training-log.json"
USERS_FILE = DATA_DIR / "users.json"
