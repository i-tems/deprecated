from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    GOOGLE_CLIENT_ID: str = "your-google-client-id"
    GOOGLE_CLIENT_SECRET: str = "your-google-client-secret"
    JWT_SECRET: str = "meetup-secret-jwt-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24 * 7
    FRONTEND_URL: str = "http://localhost:3000"
    ANTHROPIC_API_KEY: str = ""
    EVENT_HASH_SALT: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
