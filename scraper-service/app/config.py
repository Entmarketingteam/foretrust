"""Configuration loaded from Doppler-injected environment variables.

No .env files. No dotenv. If a required var is missing, the service
fails loudly at boot so the operator sees "you forgot to doppler run".
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Supabase ---
    supabase_url: str
    supabase_service_role_key: str

    # --- Proxy ---
    proxy_server: str = ""
    proxy_username: str = ""
    proxy_password: str = ""
    proxy_country: str = "us"
    proxy_state: str = "ky"

    # --- Google Sheets ---
    google_service_account_json: str = ""
    google_sheets_spreadsheet_id: str = ""

    # --- CAPTCHA ---
    captcha_provider: str = "twocaptcha"  # "twocaptcha" | "capsolver"
    twocaptcha_api_key: str = ""
    capsolver_api_key: str = ""
    captcha_daily_budget_usd: float = 5.0

    # --- eCCLIX ---
    ecclix_username: str = ""
    ecclix_password: str = ""
    ecclix_counties: str = ""  # comma-separated: scott,clark,madison
    ecclix_batch_threshold: int = 20

    # --- Legal notices ---
    google_alerts_rss_urls: str = ""  # comma-separated
    visualping_api_key: str = ""
    legal_notice_newspaper_urls: str = ""  # comma-separated

    # --- OpenAI (for legal-notice text parsing) ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4-turbo-preview"

    # --- Webshare residential proxy ---
    webshare_username: str = ""
    webshare_password: str = ""

    # --- Browserbase cloud browser ---
    browserbase_api_key: str = ""
    browserbase_project_id: str = ""

    # --- Internal auth ---
    scraper_shared_token: str = ""

    # --- Doppler SDK (optional runtime re-fetch) ---
    doppler_token: str = ""

    model_config = {
        "env_file": None,  # Explicitly: no .env loading
        "case_sensitive": False,
    }

    @property
    def ecclix_county_list(self) -> list[str]:
        if not self.ecclix_counties:
            return []
        return [c.strip() for c in self.ecclix_counties.split(",") if c.strip()]

    @property
    def rss_url_list(self) -> list[str]:
        if not self.google_alerts_rss_urls:
            return []
        return [u.strip() for u in self.google_alerts_rss_urls.split(",") if u.strip()]

    @property
    def newspaper_url_list(self) -> list[str]:
        if not self.legal_notice_newspaper_urls:
            return []
        return [u.strip() for u in self.legal_notice_newspaper_urls.split(",") if u.strip()]


settings = Settings()  # type: ignore[call-arg]
