import time
from collections import defaultdict
from hashlib import sha1

from src.rag.query_transformer import QueryTransformer
from src.rag.reranker import CohereReranker
from src.rag.retriever import (
    SearchResult,
    search_hybrid,
)

QUERY = "How does an MCP server expose tools to clients?"

PER_QUERY_K = 20
FUSED_K = 20

RERANK_INPUT_K = 10
RERANK_TOP_N = 10

RRF_K = 60


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


def clean_text(text: str) -> str:
    return " ".join(text.split())


def document_key(document) -> str:
    metadata = document.metadata

    raw = "|".join(
        [
            metadata.get(
                "source",
                "",
            ),
            metadata.get(
                "h1",
                "",
            ),
            metadata.get(
                "h2",
                "",
            ),
            metadata.get(
                "h3",
                "",
            ),
            document.page_content,
        ]
    )

    return sha1(raw.encode("utf-8")).hexdigest()


#
# This is our CURRENT dataset ground truth.
#
# It is intentionally shown separately because
# we suspect it may be too broad / incorrect.
#
def matches_current_ground_truth(
    document,
) -> bool:
    metadata = document.metadata

    return (
        metadata.get("vendor") == "model-context-protocol"
        and "server"
        in metadata.get(
            "source",
            "",
        ).lower()
    )


#
# Debug heuristic only.
#
# This is NOT ground truth.
#
def looks_like_tools_target(
    document,
) -> bool:
    metadata = document.metadata

    text = " ".join(
        [
            metadata.get(
                "title",
                "",
            ),
            metadata.get(
                "source",
                "",
            ),
            metadata.get(
                "h1",
                "",
            ),
            metadata.get(
                "h2",
                "",
            ),
            metadata.get(
                "h3",
                "",
            ),
            document.page_content,
        ]
    ).lower()

    return metadata.get("vendor") == "model-context-protocol" and "tool" in text


def labels(document) -> str:
    gt = "GT" if matches_current_ground_truth(document) else "-"

    tools = "TOOLS" if looks_like_tools_target(document) else "-"

    return f"[{gt:<5}] [{tools:<5}]"


def print_document(
    document,
    *,
    text_chars: int = 1000,
) -> None:
    metadata = document.metadata

    print(
        "  Vendor: ",
        metadata.get("vendor"),
    )

    print(
        "  Product:",
        metadata.get("product"),
    )

    print(
        "  Title:  ",
        metadata.get("title"),
    )

    print(
        "  Section:",
        get_heading(document),
    )

    print(
        "  Source: ",
        metadata.get("source"),
    )

    text = clean_text(document.page_content)

    print(
        "  Text:   ",
        text[:text_chars],
    )


def print_search_results(
    results: list[SearchResult],
    *,
    limit: int = 10,
) -> None:
    for rank, result in enumerate(
        results[:limit],
        start=1,
    ):
        print()
        print(f"#{rank:<2} score={result.score:.5f} {labels(result.document)}")

        print_document(result.document)


def print_reranked_results(
    results,
    *,
    limit: int = 10,
) -> None:
    for result in results[:limit]:
        document = result.document

        print()
        print(
            f"#{result.rerank_rank:<2} "
            f"Cohere="
            f"{result.rerank_score:.5f} "
            f"pre_rank="
            f"{result.original_rank:<2} "
            f"{labels(document)}"
        )

        print_document(document)


def main() -> None:
    transformer = QueryTransformer()

    transformed = transformer.build_queries(QUERY)

    queries = transformed.unique_queries()

    #
    # --------------------------------------------------
    # QUERY TRANSFORMATION
    # --------------------------------------------------
    #

    print()
    print("=" * 100)
    print("QUERY TRANSFORMATION")
    print("=" * 100)

    for index, query in enumerate(
        queries,
        start=1,
    ):
        print(f"{index}. {query}")

    #
    # --------------------------------------------------
    # BASELINE HYBRID
    # --------------------------------------------------
    #

    print()
    print("=" * 100)
    print("BASELINE HYBRID")
    print("=" * 100)

    baseline_results = search_hybrid(
        query=QUERY,
        k=PER_QUERY_K,
    )

    print_search_results(
        baseline_results,
        limit=10,
    )

    #
    # --------------------------------------------------
    # BASELINE HYBRID + COHERE
    # --------------------------------------------------
    #

    print()
    print("=" * 100)
    print("BASELINE HYBRID + COHERE")
    print("=" * 100)

    time.sleep(6.5)

    baseline_reranked = reranker.rerank(
        query=QUERY,
        results=baseline_results[:RERANK_INPUT_K],
        top_n=RERANK_TOP_N,
    )

    print_reranked_results(baseline_reranked)

    #
    # --------------------------------------------------
    # INDIVIDUAL QUERY RETRIEVAL
    # --------------------------------------------------
    #

    all_results = []

    for query_index, query in enumerate(
        queries,
        start=1,
    ):
        print()
        print("=" * 100)
        print(f"HYBRID FOR QUERY {query_index}: {query}")
        print("=" * 100)

        results = search_hybrid(
            query=query,
            k=PER_QUERY_K,
        )

        all_results.append(results)

        print_search_results(
            results,
            limit=10,
        )

    #
    # --------------------------------------------------
    # MULTI-QUERY RRF
    # --------------------------------------------------
    #

    documents = {}

    rrf_scores = defaultdict(float)

    rank_details = defaultdict(list)

    for query_index, results in enumerate(
        all_results,
        start=1,
    ):
        for rank, result in enumerate(
            results,
            start=1,
        ):
            key = document_key(result.document)

            documents[key] = result.document

            contribution = 1.0 / (RRF_K + rank)

            rrf_scores[key] += contribution

            rank_details[key].append(
                {
                    "query_index": query_index,
                    "rank": rank,
                    "contribution": contribution,
                }
            )

    fused_items = sorted(
        rrf_scores.items(),
        key=lambda item: item[1],
        reverse=True,
    )[:FUSED_K]

    print()
    print("=" * 100)
    print("MULTI-QUERY RRF")
    print("=" * 100)

    fused_results = []

    for fused_rank, (
        key,
        score,
    ) in enumerate(
        fused_items,
        start=1,
    ):
        document = documents[key]

        print()
        print(f"#{fused_rank:<2} RRF={score:.5f} {labels(document)}")

        print_document(document)

        print("  Votes:")

        for vote in rank_details[key]:
            print(
                "    "
                f"query "
                f"#{vote['query_index']}: "
                f"rank="
                f"{vote['rank']}, "
                f"rrf="
                f"{vote['contribution']:.5f}"
            )

        fused_results.append(
            SearchResult(
                document=document,
                score=score,
            )
        )

    #
    # --------------------------------------------------
    # MULTI-QUERY RRF + COHERE
    # --------------------------------------------------
    #

    print()
    print("=" * 100)
    print("MULTI-QUERY RRF + COHERE")
    print("=" * 100)

    time.sleep(6.5)

    multi_query_reranked = reranker.rerank(
        query=QUERY,
        results=fused_results[:RERANK_INPUT_K],
        top_n=RERANK_TOP_N,
    )

    print_reranked_results(multi_query_reranked)


if __name__ == "__main__":
    main()
