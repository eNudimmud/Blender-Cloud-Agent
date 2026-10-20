import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_root: Path = Path("data")
    api_token: str = ""
    secure_cookie: bool = True
    public_origin: str = ""
    blender_bin: str = "blender"
    job_timeout: int = 120
    max_pending_jobs: int = 8
    max_projects: int = 100
    max_jobs: int = 500
    max_storage_bytes: int = 2 * 1024**3
    agent_mode: str = "rules"
    allow_paid_ai: bool = False
    llm_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""

    @classmethod
    def from_env(cls):
        return cls(
            data_root=Path(os.environ.get("DATA_ROOT", "data")).resolve(),
            api_token=os.environ.get("API_TOKEN", ""),
            secure_cookie=os.environ.get("COOKIE_SECURE", "true").lower() == "true",
            public_origin=os.environ.get("PUBLIC_ORIGIN", "").rstrip("/"),
            blender_bin=os.environ.get("BLENDER_BIN", "blender"),
            job_timeout=int(os.environ.get("JOB_TIMEOUT", "120")),
            agent_mode=os.environ.get("AGENT_MODE", "rules"),
            allow_paid_ai=os.environ.get("ALLOW_PAID_AI", "false").lower() == "true",
            llm_url=os.environ.get("LLM_URL", ""),
            llm_model=os.environ.get("LLM_MODEL", ""),
            llm_api_key=os.environ.get("LLM_API_KEY", ""),
        )

    def validate_api(self):
        if len(self.api_token) < 32:
            raise ValueError("API_TOKEN must contain at least 32 characters")
        if self.agent_mode not in {"rules", "llm"}:
            raise ValueError("AGENT_MODE must be rules or llm")
        if not 5 <= self.job_timeout <= 300:
            raise ValueError("JOB_TIMEOUT must be between 5 and 300 seconds")
