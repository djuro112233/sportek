"""
Sportek d.o.o. — Knowledge Guardian — Chat CLI
Interactive terminal chat interface for querying internal documents.

Usage:
    python -m modules.03_knowledge_guardian.chat_cli
    python -m modules.03_knowledge_guardian.chat_cli --demo
"""

from __future__ import annotations

import sys
from pathlib import Path

from .rag_engine import RAGEngine
from .doc_processor import DocumentProcessor

MODULE_DIR = Path(__file__).resolve().parent

# ── Colours ────────────────────────────────────────────────────────────────
BOLD = "\033[1m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
DIM = "\033[2m"
RESET = "\033[0m"

DEMO_QUESTIONS = [
    "Koji su koraci finalne inspekcije kvaliteta?",
    "Kako se podešava SHIMA SEIKI mašina za novi model?",
    "Koji su Nike zahtjevi za šavove na gornjem dijelu?",
    "Koja je procedura za rukovanje opasnim hemikalijama?",
    "Koliko često se vrši održavanje SHIMA SEIKI mašina?",
]


def _print_banner() -> None:
    print()
    print(f"{BOLD}{CYAN}{'═' * 60}{RESET}")
    print(f"{BOLD}{CYAN}   KNOWLEDGE GUARDIAN — Sportek d.o.o.{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 60}{RESET}")
    print(f"  {DIM}Interni AI asistent | 10 dokumenata | Pitajte bilo šta{RESET}")
    print(f"  {DIM}Komande: /sources  /stats  /demo  /quit{RESET}")
    print(f"{CYAN}{'─' * 60}{RESET}\n")


def _print_response(resp: dict) -> None:
    """Pretty-print a RAGEngine response."""
    print(f"\n  {BOLD}{GREEN}Guardian:{RESET} {resp['answer']}\n")
    print(f"  {DIM}Confidence: {resp['confidence']:.0%}  |  "
          f"Vrijeme: {resp['response_time_ms']:.0f} ms{RESET}")
    if resp["sources"]:
        print(f"  {DIM}Izvori:{RESET}")
        for s in resp["sources"][:3]:
            print(f"    {DIM}• {s['file']}  ({s['chunk_id']})  "
                  f"relevance={s['relevance']:.4f}{RESET}")
    print()


def _cmd_sources() -> None:
    """List all indexed documents."""
    proc = DocumentProcessor()
    proc.load_documents()
    print(f"\n  {BOLD}Indeksirani dokumenti ({len(proc.documents)}):{RESET}")
    for i, doc in enumerate(proc.documents, 1):
        print(f"    {i:2d}. {doc['file_name']:<45s}  {doc['word_count']:>5,} riječi")
    print()


def _cmd_stats(engine: RAGEngine) -> None:
    """Print store stats."""
    n_chunks = len(engine.store.chunks)
    vocab = len(engine.store.vectorizer.vocabulary_)
    log_path = MODULE_DIR / "logs" / "query_log.csv"
    n_queries = 0
    if log_path.exists():
        n_queries = sum(1 for _ in open(log_path)) - 1  # minus header
    print(f"\n  {BOLD}Knowledge Guardian — Statistike{RESET}")
    print(f"    Chunkova u indeksu:  {GREEN}{n_chunks}{RESET}")
    print(f"    Veličina vokabulara: {GREEN}{vocab}{RESET}")
    print(f"    Ukupno upita:        {GREEN}{max(n_queries, 0)}{RESET}\n")


def _cmd_demo(engine: RAGEngine) -> None:
    """Run 5 demo questions."""
    print(f"\n  {BOLD}{YELLOW}── Demo mod: 5 pitanja ──{RESET}\n")
    for i, q in enumerate(DEMO_QUESTIONS, 1):
        print(f"  {BOLD}[{i}/5] Vi:{RESET} {q}")
        resp = engine.ask(q)
        _print_response(resp)
        print(f"  {CYAN}{'─' * 55}{RESET}")


def main() -> None:
    _print_banner()
    engine = RAGEngine()

    # If --demo flag, run demo and exit
    if "--demo" in sys.argv:
        _cmd_demo(engine)
        return

    while True:
        try:
            user_input = input(f"  {BOLD}Vi:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n  {DIM}Doviđenja!{RESET}\n")
            break

        if not user_input:
            continue

        cmd = user_input.lower()
        if cmd in ("/quit", "/exit", "/q"):
            print(f"\n  {DIM}Doviđenja!{RESET}\n")
            break
        elif cmd == "/sources":
            _cmd_sources()
        elif cmd == "/stats":
            _cmd_stats(engine)
        elif cmd == "/demo":
            _cmd_demo(engine)
        else:
            resp = engine.ask(user_input)
            _print_response(resp)


if __name__ == "__main__":
    main()
