from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=["../.env", ".env"],
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )

    database_url: str = "sqlite:///./news.db"
    finnhub_api_key: str = ""
    anthropic_api_key: str = ""
    sec_user_agent: str = ""
    watchlist: list[str] = ["NVDA", "MSFT", "GOOGL", "AAPL", "META"]
    log_level: str = "INFO"
    user_agent: str = "FinancialNewsIntelligence/1.0 (personal research tool)"


settings = Settings()
