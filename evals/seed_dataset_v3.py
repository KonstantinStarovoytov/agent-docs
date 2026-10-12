from uuid import NAMESPACE_URL, uuid5

from langfuse import Langfuse

from src.config import settings

DATASET_NAME = "rag/retrieval-v3"


langfuse = Langfuse(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key.get_secret_value(),
    base_url=settings.langfuse_base_url,
)


CASES = [
    # ============================================================
    # SUBAGENTS
    # ============================================================
    {
        "question": "How can Claude subagents preload skills?",
        "category": "subagents",
        "difficulty": "easy",
        "relevant": [
            {
                "title": "Create custom subagents",
                "heading_contains": "Control subagent capabilities",
            }
        ],
    },
    {
        "question": "How do I restrict which tools a custom subagent can use?",
        "category": "subagents",
        "difficulty": "semantic",
        "relevant": [
            {
                "title": "Create custom subagents",
                "heading_contains": "Control subagent capabilities",
            }
        ],
    },
    {
        "question": "Can a Claude Code subagent use MCP servers?",
        "category": "subagents",
        "difficulty": "easy",
        "relevant": [
            {
                "title": "Create custom subagents",
            }
        ],
    },
    {
        "question": "Where do I configure a custom Claude Code subagent?",
        "category": "subagents",
        "difficulty": "easy",
        "relevant": [
            {
                "title": "Create custom subagents",
                "heading_contains": "Write subagent files",
            }
        ],
    },
    {
        "question": "How can a Claude subagent remember information between sessions?",
        "category": "subagents",
        "difficulty": "semantic",
        "relevant": [
            {
                "title": "Create custom subagents",
            },
            {
                "title": "How Claude remembers your project",
            },
        ],
    },
    {
        "question": "Why would I use a subagent instead of doing the work in the main conversation?",
        "category": "subagents",
        "difficulty": "hard",
        "relevant": [
            {
                "title": "Create custom subagents",
            },
            {
                "title": "Extend Claude Code",
                "heading_contains": "Compare similar features",
            },
        ],
    },
    # ============================================================
    # SKILLS
    # ============================================================
    {
        "question": "What file defines a Claude Code skill?",
        "category": "skills",
        "difficulty": "keyword",
        "relevant": [
            {
                "title": "Extend Claude with skills",
            }
        ],
    },
    {
        "question": "Where should I store reusable instructions that Claude loads only when needed?",
        "category": "skills",
        "difficulty": "semantic",
        "relevant": [
            {
                "title": "Extend Claude with skills",
            },
            {
                "title": "Extend Claude Code",
            },
            {
                "title": "How Claude remembers your project",
                "heading_contains": "When to add to CLAUDE.md",
            },
            {
                "title": "How Claude remembers your project",
                "heading_contains": "Related resources",
            },
        ],
    },
    {
        "question": "How can I invoke a Claude Code skill manually?",
        "category": "skills",
        "difficulty": "easy",
        "relevant": [
            {
                "title": "Extend Claude with skills",
            }
        ],
    },
    {
        "question": "How do I stop Claude from invoking a skill automatically?",
        "category": "skills",
        "difficulty": "hard",
        "relevant": [
            {
                "title": "Extend Claude with skills",
            }
        ],
    },
    {
        "question": "When should I move instructions from CLAUDE.md into a skill?",
        "category": "skills",
        "difficulty": "semantic",
        "relevant": [
            {
                "title": "Extend Claude with skills",
            },
            {
                "title": "Extend Claude Code",
            },
            # Label gap, full corpus 2026-10-12: costs.md has a section with
            # exactly this advice (reports/full-corpus-eval-2026-10.md).
            {
                "vendor": "anthropic",
                "source_contains": "/docs/en/costs.md",
                "heading_contains": "Move instructions from CLAUDE.md to skills",
            },
        ],
    },
    {
        "question": "Are custom slash commands now represented as skills?",
        "category": "skills",
        "difficulty": "keyword",
        "relevant": [
            {
                "title": "Extend Claude with skills",
            }
        ],
    },
    # ============================================================
    # MCP
    # ============================================================
    {
        "question": "How can Claude Code connect to external tools and services?",
        "category": "mcp",
        "difficulty": "semantic",
        "relevant": [
            {
                "title": "Connect Claude Code to tools via MCP",
            }
        ],
    },
    {
        "question": "How do I add an MCP server to Claude Code?",
        "category": "mcp",
        "difficulty": "easy",
        "relevant": [
            {
                "title": "Connect Claude Code to tools via MCP",
            },
            # Label gap, full corpus 2026-10-12: the MCP quickstart's
            # "Add and verify a server" walks through `claude mcp add`.
            {
                "vendor": "anthropic",
                "source_contains": "/docs/en/mcp-quickstart.md",
            },
        ],
    },
    {
        "question": "What is the difference between local, project, and user MCP server scopes?",
        "category": "mcp",
        "difficulty": "hard",
        "relevant": [
            {
                "title": "Connect Claude Code to tools via MCP",
            }
        ],
    },
    {
        "question": "Can Claude Code authenticate to a remote MCP server using OAuth?",
        "category": "mcp",
        "difficulty": "keyword",
        "relevant": [
            {
                "title": "Connect Claude Code to tools via MCP",
            }
        ],
    },
    {
        "question": "Can I make an MCP server available only to a specific subagent?",
        "category": "mcp",
        "difficulty": "hard",
        "relevant": [
            {
                "title": "Create custom subagents",
            },
            {
                "title": "Connect Claude Code to tools via MCP",
            },
        ],
    },
    # ============================================================
    # MEMORY / CLAUDE.MD
    # ============================================================
    {
        "question": "Where should I put project-wide instructions for Claude Code?",
        "category": "memory",
        "difficulty": "semantic",
        "relevant": [
            {
                "title": "How Claude remembers your project",
            }
        ],
    },
    {
        "question": "How does Claude Code load project memory?",
        "category": "memory",
        "difficulty": "easy",
        "relevant": [
            {
                "title": "How Claude remembers your project",
            }
        ],
    },
    {
        "question": "Can CLAUDE.md import instructions from another file?",
        "category": "memory",
        "difficulty": "keyword",
        "relevant": [
            {
                "title": "How Claude remembers your project",
            }
        ],
    },
    {
        "question": "What is the difference between user-level and project-level Claude instructions?",
        "category": "memory",
        "difficulty": "hard",
        "relevant": [
            {
                "title": "How Claude remembers your project",
            }
        ],
    },
    # ============================================================
    # PLUGINS / FEATURE SELECTION
    # ============================================================
    {
        "question": "How can I package Claude Code skills, hooks, and subagents together?",
        "category": "plugins",
        "difficulty": "semantic",
        "relevant": [
            {
                "title": "Create plugins",
            },
            {
                "title": "Extend Claude Code",
                "heading_contains": "Combine features",
            },
        ],
    },
    {
        "question": "When should I use a skill instead of a subagent?",
        "category": "comparison",
        "difficulty": "hard",
        "relevant": [
            {
                "title": "Extend Claude Code",
                "heading_contains": "Compare similar features",
            }
        ],
    },
    {
        "question": "What is the difference between reusable skills and isolated workers in Claude Code?",
        "category": "comparison",
        "difficulty": "semantic",
        "relevant": [
            {
                "title": "Extend Claude Code",
                "heading_contains": "Compare similar features",
            },
            {
                "title": "Create custom subagents",
            },
            {
                "title": "Extend Claude with skills",
            },
        ],
    },
    {
        "question": "How do skills affect Claude Code context usage?",
        "category": "context",
        "difficulty": "semantic",
        "relevant": [
            {
                "title": "Extend Claude Code",
                "heading_contains": "Understand how features load",
            },
            {
                "title": "Extend Claude Code",
                "heading_contains": "Understand context costs",
            },
            {
                "title": "Extend Claude with skills",
                "heading_contains": "Skill content lifecycle",
            },
            # Label gap, full corpus 2026-10-12: "The context window" section
            # explains that skills load on demand (descriptions only at start).
            {
                "vendor": "anthropic",
                "source_contains": "/docs/en/how-claude-code-works.md",
                "heading_contains": "The context window",
            },
        ],
    },
    {
        "question": "How do I choose between CLAUDE.md, skills, hooks, and subagents?",
        "category": "comparison",
        "difficulty": "hard",
        "relevant": [
            {
                "title": "Extend Claude Code",
            }
        ],
    },
    # ============================================================
    # AGENT SDK SKILLS
    # ============================================================
    {
        "question": "How are skills loaded when using the Claude Agent SDK?",
        "category": "agent-sdk",
        "difficulty": "easy",
        "relevant": [
            {
                "title": "Extend agents with skills",
                "heading_contains": "How skills work with the Agent SDK",
            }
        ],
    },
    {
        "question": "Where does the Claude Agent SDK discover skills from?",
        "category": "agent-sdk",
        "difficulty": "semantic",
        "relevant": [
            {
                "title": "Extend agents with skills",
                "heading_contains": "How skills work with the Agent SDK",
            }
        ],
    },
    {
        "question": "How can I restrict which skills are available in an Agent SDK session?",
        "category": "agent-sdk",
        "difficulty": "hard",
        "relevant": [
            {
                "title": "Extend agents with skills",
            }
        ],
    },
    {
        "question": "Why does the Agent SDK say a skill is not in the session allowlist?",
        "category": "agent-sdk",
        "difficulty": "keyword",
        "relevant": [
            {
                "title": "Extend agents with skills",
                "heading_contains": "Skill not being used",
            }
        ],
    },
    {
        "question": ("Where should I define project-specific rules in Cursor?"),
        "relevant": [
            {
                "vendor": "cursor",
                "source_contains": "rules",
            },
        ],
        "category": "cursor-rules",
        "difficulty": "easy",
    },
    {
        "question": (
            "How can I give Cursor reusable instructions for a specific task?"
        ),
        "relevant": [
            {
                "vendor": "cursor",
                "source_contains": "skills",
            },
        ],
        "category": "cursor-skills",
        "difficulty": "semantic",
    },
    {
        "question": ("Can Cursor connect to external tools using MCP?"),
        "relevant": [
            {
                "vendor": "cursor",
                "source_contains": "mcp",
            },
        ],
        "category": "cursor-mcp",
        "difficulty": "easy",
    },
    {
        "question": ("How can Cursor delegate work to specialized subagents?"),
        "relevant": [
            {
                "vendor": "cursor",
                "source_contains": "subagent",
            },
        ],
        "category": "cursor-subagents",
        "difficulty": "semantic",
    },
    # -----------------------------
    # Codex
    # -----------------------------
    {
        "question": ("How does Codex use AGENTS.md?"),
        "relevant": [
            {
                "vendor": "openai",
                "source_contains": "agents-md",
            },
        ],
        "category": "codex-agents-md",
        "difficulty": "easy",
    },
    {
        "question": ("Where should repository instructions for Codex be stored?"),
        "relevant": [
            {
                "vendor": "openai",
                "source_contains": "agents-md",
            },
        ],
        "category": "codex-agents-md",
        "difficulty": "semantic",
    },
    {
        "question": ("How can Codex connect to an MCP server?"),
        "relevant": [
            {
                "vendor": "openai",
                "source_contains": "mcp",
            },
        ],
        "category": "codex-mcp",
        "difficulty": "easy",
    },
    {
        "question": ("How do I create a reusable skill for Codex?"),
        "relevant": [
            {
                "vendor": "openai",
                "source_contains": "skill",
            },
        ],
        "category": "codex-skills",
        "difficulty": "easy",
    },
    # -----------------------------
    # MCP
    # -----------------------------
    {
        "question": ("What are the main components of MCP architecture?"),
        "relevant": [
            {
                "vendor": "model-context-protocol",
                "source_contains": "architecture",
            },
        ],
        "category": "mcp-architecture",
        "difficulty": "easy",
    },
    {
        "question": ("How does an MCP server expose tools to a client?"),
        "relevant": [
            {
                "vendor": "model-context-protocol",
                "source_contains": "server",
            },
        ],
        "category": "mcp-tools",
        "difficulty": "semantic",
    },
    {
        "question": ("What is the difference between an MCP client and MCP server?"),
        "relevant": [
            {
                "vendor": "model-context-protocol",
                "source_contains": "architecture",
            },
            {
                "vendor": "model-context-protocol",
                "source_contains": "client",
            },
            {
                "vendor": "model-context-protocol",
                "source_contains": "server",
            },
        ],
        "category": "mcp-architecture",
        "difficulty": "semantic",
    },
    {
        "question": ("How should authorization be handled for an MCP server?"),
        "relevant": [
            {
                "vendor": "model-context-protocol",
                "source_contains": "authorization",
            },
        ],
        "category": "mcp-security",
        "difficulty": "easy",
    },
    # -----------------------------
    # Cross-vendor / ambiguous
    # -----------------------------
    {
        "question": ("Which file gives repository-wide instructions to Codex?"),
        "relevant": [
            {
                "vendor": "openai",
                "source_contains": "agents-md",
            },
        ],
        "category": "cross-vendor",
        "difficulty": "semantic",
    },
    {
        "question": ("Where are project rules configured in Cursor?"),
        "relevant": [
            {
                "vendor": "cursor",
                "source_contains": "rules",
            },
        ],
        "category": "cross-vendor",
        "difficulty": "semantic",
    },
    {
        "question": (
            "Which Claude Code feature should I use for reusable on-demand workflows?"
        ),
        "relevant": [
            {
                "vendor": "anthropic",
                "source_contains": "skills",
            },
            {
                "vendor": "anthropic",
                "title": "Extend Claude Code",
                "heading_contains": "Compare similar features",
            },
            {
                "vendor": "anthropic",
                "title": "How Claude remembers your project",
                "heading_contains": "Related resources",
            },
        ],
        "category": "cross-vendor",
        "difficulty": "semantic",
    },
    # Exact-keyword cases: important for future BM25
    {
        "question": "What is AGENTS.md?",
        "relevant": [
            {
                "vendor": "openai",
                "source_contains": "agents-md",
            },
        ],
        "category": "exact-keyword",
        "difficulty": "keyword",
    },
    {
        "question": "What is SKILL.md used for?",
        "relevant": [
            {
                "vendor": "anthropic",
                "source_contains": "skills",
            },
            {
                "vendor": "openai",
                "source_contains": "skill",
            },
            # Label gap, full corpus 2026-10-12: glossary > Skill defines a
            # skill as "A `SKILL.md` file containing instructions...".
            {
                "vendor": "anthropic",
                "source_contains": "/docs/en/glossary.md",
                "heading_contains": "Skill",
            },
        ],
        "category": "exact-keyword",
        "difficulty": "keyword",
    },
]


def main() -> None:
    langfuse.create_dataset(
        name=DATASET_NAME,
        description=(
            "Retrieval benchmark for Claude Code documentation. "
            "Contains exact, semantic, ambiguous and keyword-heavy queries."
        ),
        metadata={
            "version": "2",
            "type": "retrieval",
            "items": len(CASES),
        },
    )

    for case in CASES:
        # Deterministic ID:
        # rerunning this script updates the same item instead of duplicating it.
        item_id = str(
            uuid5(
                NAMESPACE_URL,
                f"{DATASET_NAME}:{case['question']}",
            )
        )

        langfuse.create_dataset_item(
            id=item_id,
            dataset_name=DATASET_NAME,
            input={
                "question": case["question"],
            },
            expected_output={
                "relevant": case["relevant"],
            },
            metadata={
                "category": case["category"],
                "difficulty": case["difficulty"],
            },
        )

    print(f"Seeded {len(CASES)} cases into '{DATASET_NAME}'")


if __name__ == "__main__":
    main()
