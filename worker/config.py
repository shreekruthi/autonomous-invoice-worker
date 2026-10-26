import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/worker.sqlite3"
    mode: str = "demo"
    api_key: str = ""
    model: str = "gpt-4.1-mini"
    base_url: str = "https://api.openai.com/v1"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    worker_token: str = "local-worker"
    reviewer_token: str = "local-reviewer"
    approval_threshold_minor: int = 500000
    max_steps: int = 24
    max_tool_attempts: int = 3
    enable_faults: bool = False
    retry_delay: float = 0.15

    def __post_init__(self):
        if self.mode not in {"demo", "openai", "groq"}:
            raise ValueError("WORKER_MODE must be demo, openai or groq")
        if self.mode == "openai" and not self.api_key:
            raise ValueError("OPENAI_API_KEY is required in openai mode; no silent demo fallback")
        if self.mode == "groq" and not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is required in groq mode; no silent demo fallback")
        if not self.worker_token or not self.reviewer_token or self.worker_token == self.reviewer_token:
            raise ValueError("Worker and reviewer tokens must be nonempty and different")
        if min(self.max_steps, self.max_tool_attempts) < 1 or self.approval_threshold_minor < 0:
            raise ValueError("Invalid execution limits")

    @classmethod
    def from_env(cls):
        load_dotenv()
        return cls(
            db_path=os.getenv("WORKER_DB", "data/worker.sqlite3"),
            mode=os.getenv("WORKER_MODE", "demo"),
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            groq_model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
            groq_base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/"),
            worker_token=os.getenv("WORKER_API_TOKEN", "local-worker"),
            reviewer_token=os.getenv("REVIEWER_TOKEN", "local-reviewer"),
            approval_threshold_minor=int(os.getenv("APPROVAL_THRESHOLD_MINOR", "500000")),
            max_steps=int(os.getenv("MAX_STEPS", "24")),
            max_tool_attempts=int(os.getenv("MAX_TOOL_ATTEMPTS", "3")),
            enable_faults=os.getenv("ENABLE_FAULTS", "false").lower() == "true",
        )

    def make_parent(self):
        Path(self.db_path).resolve().parent.mkdir(parents=True, exist_ok=True)
