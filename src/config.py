from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: SecretStr
    openai_embedding_model: str = "text-embedding-3-small"

    cohere_api_key: SecretStr
    # Used once the primary key hits its rate/quota limit (e.g. a trial
    # key's monthly cap). Unset means no fallback: the original error
    # propagates as before.
    cohere_api_key_fallback: SecretStr | None = None
    cohere_rerank_model: str = "rerank-v4.0-fast"

    qdrant_url: str = "http://localhost:6333"
    # Qdrant Cloud requires a key; a local container does not.
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "agent_docs_v2"
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"
    answer_prompt_version: int | None = Field(default=None, ge=1)
    answer_evaluator_prompt_version: int | None = Field(default=None, ge=1)
    translate_prompt_version: int | None = Field(default=None, ge=1)
    evidence_planner_prompt_version: int | None = Field(default=None, ge=1)
    prompt_strict: bool = False
    openai_chat_model: str = "gpt-6-luna"
    # LLM-as-judge should not be the model it grades. Unset means the judge
    # runs on the generator model and every eval run records that it did.
    openai_judge_model: str | None = None
    # GPT-6 models accept only the default temperature and answer 400 to any
    # other value, so unset means "do not send it". Set 0 for older models.
    openai_temperature: float | None = None

    @field_validator("openai_temperature", mode="before")
    @classmethod
    def _blank_temperature_is_unset(cls, value: object) -> object:
        # A dashboard variable left empty arrives as "", which must not crash startup.
        return None if value == "" else value

    tracing_enabled: bool = True
    # 5 -> 8 covered both aspects in half the multi-aspect set instead of a third.
    generation_top_k: int = Field(default=8, ge=1)
    # Below this Cohere rerank score, a candidate is dropped rather than
    # padding the context. Measured on rag/evidence-coverage-v1: the
    # weakest genuinely relevant chunk scored 0.35 (128 chunks, only 4
    # below 0.4, none below 0.3). None disables the floor.
    min_rerank_score: float | None = Field(default=0.35, ge=0.0, le=1.0)
    # ask_docs answers "couldn't find relevant documentation" without calling
    # the LLM when even the best reranked candidate scores below this.
    # None disables it. See reports/dedup-abstain-2026-10.md.
    min_top_rerank_score: float | None = Field(default=0.55, ge=0.0, le=1.0)

    @field_validator("min_top_rerank_score", mode="before")
    @classmethod
    def _blank_top_score_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    retrieval_strategy: Literal["dense", "hybrid", "hybrid-english"] = "hybrid"
    translate_non_english: bool = True
    retrieval_top_k: int = Field(default=10, ge=1)
    per_query_top_k: int = Field(default=20, ge=1)
    # Max chunks per page (metadata.source) in the candidate pool before
    # rerank; the pool refills from over-fetched candidates. None = no cap.
    max_chunks_per_source_in_pool: int | None = Field(default=None, ge=1)
    # How deep Qdrant reads each side (dense and BM25) before RRF; it is also
    # the length of the fused list. None = 3 x the requested k (the tie-break
    # overfetch). Never less than k.
    hybrid_prefetch_depth: int | None = Field(default=None, ge=1)
    # How many fused candidates the answer pipeline sends to Cohere. The rerank
    # output stays retrieval_top_k. None = retrieval_top_k.
    rerank_pool: int | None = Field(default=None, ge=1)
    qdrant_hybrid_collection: str = "agent_docs_hybrid_v1"
    sparse_embedding_model: str = "Qdrant/bm25"

    # Every served request spends OpenAI and Cohere credits, so the deployed API
    # refuses to start without a token. Unset is allowed only for local CLI use.
    api_token: SecretStr | None = None
    # Optional second token for people trying the service. It has the same
    # rights as API_TOKEN and shares the rate limit; it exists only so it can be
    # rotated or removed without touching the owner's token.
    api_guest_token: SecretStr | None = None
    api_max_question_chars: int = Field(default=500, ge=1)
    # The MCP transport rejects unknown Host headers to block DNS rebinding, so
    # the public hostname must be declared. Empty means localhost only.
    api_allowed_hosts: str = ""
    # Server-wide cap on paid requests, so a looping agent or a leaked token
    # cannot run up the OpenAI and Cohere bill. One machine, so in-memory is fine.
    api_rate_limit_per_minute: int = Field(default=60, ge=1)
    # Per client IP, for requests that bring their own Cohere key instead of
    # a token: they still spend our OpenAI embedding and Qdrant capacity.
    api_byok_rate_limit_per_minute: int = Field(default=30, ge=1)
    # Date the corpus was indexed, shown to callers so they know the docs are a
    # snapshot rather than live pages. Set it when re-indexing.
    index_snapshot: str | None = None


settings = Settings()
