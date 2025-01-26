from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8")

    TSP_IMAGE: str = "botbuild/tsp_compiler"
    APP_IMAGE: str = "botbuild/app_schema"


settings = Settings()
