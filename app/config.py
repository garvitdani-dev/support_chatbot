from __future__ import annotations
import json
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)

@dataclass(frozen=True)
class Settings:
    tenants_root: Path = Path(os.getenv('TENANTS_ROOT', str(ROOT / 'data/tenants'))).resolve()
    openai_model: str = os.getenv('OPENAI_MODEL', '')
    embedding_model: str = os.getenv('OPENAI_EMBEDDING_MODEL', '')
    max_iterations: int = int(os.getenv('MAX_RETRIEVAL_ITERATIONS', '3'))
    max_tool_calls: int = int(os.getenv('MAX_TOOL_CALLS', '12'))
    top_k: int = int(os.getenv('RETRIEVAL_TOP_K', '12'))
    rerank_k: int = int(os.getenv('RERANK_TOP_K', '6'))
    max_evidence_chars: int = int(os.getenv('MAX_EVIDENCE_CHARS', '24000'))
    timeout: float = float(os.getenv('OPENAI_TIMEOUT_SECONDS', '45'))
    max_upload_bytes: int = int(os.getenv('MAX_UPLOAD_BYTES', '20971520'))

    @property
    def token_map(self) -> dict[str, list[str]]:
        raw = os.getenv('SUPPORT_API_TOKENS', '{}')
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError('SUPPORT_API_TOKENS must be a JSON object mapping bearer tokens to tenant lists') from exc
        if not isinstance(parsed, dict) or any(
            not isinstance(token, str) or not token or
            not isinstance(tenants, list) or
            any(not isinstance(tenant, str) or not tenant for tenant in tenants)
            for token, tenants in parsed.items()
        ):
            raise ValueError('SUPPORT_API_TOKENS must be a JSON object mapping bearer tokens to tenant lists')
        return parsed

    @property
    def ai_ready(self) -> bool:
        return bool(os.getenv('OPENAI_API_KEY') and self.openai_model and self.embedding_model)

settings = Settings()
