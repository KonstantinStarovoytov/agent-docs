import time

from langfuse import Langfuse

from evals.evaluators import (
    hit_at_1,
    hit_at_5,
    hit_at_10,
    reciprocal_rank,
)
from src.config import settings
from src.rag.multi_query_retriever import (
    search_queries_hybrid,
)
from src.rag.query_transformer import (
    QueryTransformer,
)
from src.rag.reranker import (
    CohereReranker,
)

DATASET_NAME = "rag/retrieval-query-transform-v1"

PER_QUERY_K = 20
FINAL_K = 10
RERANK_TOP_N = 10


langfuse = Langfuse(
    public_key=(settings.langfuse_public_key),
    secret_key=(settings.langfuse_secret_key.get_secret_value()),
    base_url=(settings.langfuse_base_url),
)


transformer = QueryTransformer()
reranker = CohereReranker()


def get_heading(document) -> str:
    metadata = document.metadata

    return " > ".join(
        value
        for value in (
            metadata.get("h1"),
            metadata.get("h2"),
            metadata.get("h3"),
        )
        if value
    )


def build_output(
    reranked,
) -> dict:
    return {
        "results": [
            {
                "rank": result.rerank_rank,
                "vendor": result.document.metadata.get("vendor"),
                "product": result.document.metadata.get("product"),
                "title": result.document.metadata.get("title"),
                "heading": get_heading(result.document),
                "source": result.document.metadata.get("source"),
                "multi_query_rank": result.original_rank,
                "multi_query_rrf_score": result.retrieval_score,
                "rerank_score": result.rerank_score,
            }
            for result in reranked
        ]
    }


def retrieve_and_rerank(
    *,
    original: str,
    queries: list[str],
) -> dict:
    results = search_queries_hybrid(
        queries=queries,
        per_query_k=PER_QUERY_K,
        final_k=FINAL_K,
    )

    # Cohere Trial:
    # max 10 requests / minute.
    time.sleep(6.5)

    #
    # IMPORTANT:
    # Cohere always evaluates candidates
    # against the ORIGINAL user question.
    #
    reranked = reranker.rerank(
        query=original,
        results=results,
        top_n=RERANK_TOP_N,
    )

    return build_output(reranked)


#
# -------------------------------------------------
# B: ORIGINAL + ENGLISH
# -------------------------------------------------
#


def original_english_task(
    *,
    item,
    **kwargs,
):
    question = item.input["question"]

    transformed = transformer.transform(question)

    return retrieve_and_rerank(
        original=question,
        queries=[
            question,
            transformed.english,
        ],
    )


#
# -------------------------------------------------
# C: ORIGINAL + SEMANTIC VARIANT
# -------------------------------------------------
#


def original_semantic_task(
    *,
    item,
    **kwargs,
):
    question = item.input["question"]

    transformed = transformer.transform(question)

    return retrieve_and_rerank(
        original=question,
        queries=[
            question,
            transformed.semantic_variant,
        ],
    )


EVALUATORS = [
    hit_at_1,
    hit_at_5,
    hit_at_10,
    reciprocal_rank,
]


def main() -> None:
    dataset = langfuse.get_dataset(DATASET_NAME)

    #
    # -------------------------------------------------
    # ORIGINAL + ENGLISH
    # -------------------------------------------------
    #

    print()
    print("Running Original + English...")

    english_result = dataset.run_experiment(
        name=("query-transform-original-english-v1"),
        description=(
            "Original query + faithful "
            "English translation, "
            "Hybrid retrieval + "
            "multi-query RRF + Cohere"
        ),
        task=original_english_task,
        evaluators=EVALUATORS,
        metadata={
            "query_strategy": "original+english",
            "retriever": "multi-query-hybrid",
            "fusion": "multi-query-RRF",
            "reranker": "rerank-v4.0-fast",
            "per_query_k": PER_QUERY_K,
            "final_k": FINAL_K,
        },
        max_concurrency=1,
    )

    print(english_result.format())

    #
    # -------------------------------------------------
    # ORIGINAL + SEMANTIC
    # -------------------------------------------------
    #

    print()
    print("Running Original + Semantic Variant...")

    semantic_result = dataset.run_experiment(
        name=("query-transform-original-semantic-v1"),
        description=(
            "Original query + semantic "
            "English variant, "
            "Hybrid retrieval + "
            "multi-query RRF + Cohere"
        ),
        task=original_semantic_task,
        evaluators=EVALUATORS,
        metadata={
            "query_strategy": "original+semantic",
            "retriever": "multi-query-hybrid",
            "fusion": "multi-query-RRF",
            "reranker": "rerank-v4.0-fast",
            "per_query_k": PER_QUERY_K,
            "final_k": FINAL_K,
        },
        max_concurrency=1,
    )

    print(semantic_result.format())

    langfuse.flush()


if __name__ == "__main__":
    main()
