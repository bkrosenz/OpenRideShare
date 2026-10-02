from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./openrideshare.db")
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    admin_key: str = os.getenv("INVITATION_ADMIN_KEY", "")
    token_minutes: int = int(os.getenv("TOKEN_MINUTES", "30"))
    osrm_url: str = os.getenv("OSRM_URL", "https://router.project-osrm.org")
    waze_feed_url: str = os.getenv("WAZE_FEED_URL", "")
    waze_feed_token: str = os.getenv("WAZE_FEED_TOKEN", "")
    local_wage_cents_per_hour: int = int(os.getenv("LOCAL_WAGE_CENTS_PER_HOUR", "2500"))
    users_per_pod: int = int(os.getenv("USERS_PER_POD", "500"))
    pod_monthly_cost_cents: int = int(os.getenv("POD_MONTHLY_COST_CENTS", "5000"))
    rides_per_user_month: int = int(os.getenv("RIDES_PER_USER_MONTH", "4"))
    venmo_username: str = os.getenv("VENMO_USERNAME", "")


settings = Settings()