"""
Sportek d.o.o. — Knowledge Guardian — Analytics
Simulates 100 historical queries, generates charts and knowledge_stats.json.

Usage:
    python -m modules.03_knowledge_guardian.analytics
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .rag_engine import RAGEngine

MODULE_DIR = Path(__file__).resolve().parent
RESULT_DIR = MODULE_DIR / "results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# ── Sportek brand colours ──────────────────────────────────────────────────
NAVY = "#0a1628"
TEAL = "#00b4d8"
TEAL_LIGHT = "#48cae4"
TEAL_DARK = "#0077b6"
SLATE = "#1e3a5f"
WHITE = "#ffffff"
ACCENT_COLORS = ["#00b4d8", "#0077b6", "#48cae4", "#023e8a", "#90e0ef", "#caf0f8"]

plt.rcParams.update({
    "figure.facecolor": NAVY,
    "axes.facecolor": NAVY,
    "axes.edgecolor": WHITE,
    "axes.labelcolor": WHITE,
    "xtick.color": WHITE,
    "ytick.color": WHITE,
    "text.color": WHITE,
    "font.size": 11,
    "figure.dpi": 150,
})

# ── Query templates by topic ──────────────────────────────────────────────
TOPIC_QUERIES: dict[str, list[str]] = {
    "QC / Kvalitet": [
        "Koji su koraci finalne inspekcije kvaliteta?",
        "Kako se klasificiraju defekti?",
        "Koji su AQL nivoi za Nike?",
        "Kako se vrši vizuelna inspekcija obuće?",
        "Koje su kritične tačke kontrole kvaliteta?",
        "Koji su kriteriji za odbijanje šarže?",
        "Kako se dokumentiraju defekti?",
    ],
    "Mašine / SHIMA SEIKI": [
        "Kako se podešava SHIMA SEIKI mašina za novi model?",
        "Koliko često se vrši održavanje SHIMA SEIKI mašina?",
        "Koji su koraci za kalibraciju pletaće mašine?",
        "Kako se mijenja igla na SHIMA SEIKI?",
        "Koji su parametri za 3D knit setup?",
        "Kako se podešava tenzija niti?",
    ],
    "Sigurnost": [
        "Koja je procedura za rukovanje opasnim hemikalijama?",
        "Koji su sigurnosni protokoli u proizvodnji?",
        "Koja zaštitna oprema je obavezna?",
        "Kako se postupa u slučaju požara?",
        "Koji su protokoli za evakuaciju?",
        "Kako se vrši prijava nezgode?",
    ],
    "Compliance / Trade": [
        "Koji su zahtjevi za HS klasifikaciju?",
        "Kako funkcioniše CBAM izvještavanje?",
        "Koji su zahtjevi za DPP?",
        "Koji su Nike SMSI zahtjevi?",
        "Kako se vodi dokumentacija za izvoz?",
        "Koji su carinski zahtjevi za EU?",
    ],
    "HR / Onboarding": [
        "Koji su koraci onboarding procesa?",
        "Koliko traje obuka za novog radnika?",
        "Koji su zahtjevi za rad u smjenama?",
        "Kako se vrši evaluacija novih radnika?",
        "Koja dokumentacija je potrebna za zaposlenje?",
    ],
    "Materijali": [
        "Koje su specifikacije za Flyknit materijal?",
        "Koji su zahtjevi za testiranje materijala?",
        "Kako se skladište sirovine?",
        "Koji su kriteriji kvaliteta za niti?",
        "Koje su specifikacije za Crocs materijale?",
        "Koji su zahtjevi za reciklirani materijal?",
    ],
}


def _simulate_queries(engine: RAGEngine, n: int = 100) -> list[dict]:
    """Run *n* random queries and collect results."""
    all_qs = []
    for topic, qs in TOPIC_QUERIES.items():
        for q in qs:
            all_qs.append((topic, q))

    random.seed(42)
    sampled = random.choices(all_qs, k=n)

    results = []
    for topic, question in sampled:
        resp = engine.ask(question)
        resp["topic"] = topic
        results.append(resp)
    return results


# ── Chart 1: Document usage ───────────────────────────────────────────────
def _chart_document_usage(results: list[dict]) -> None:
    doc_counts: dict[str, int] = {}
    for r in results:
        if r["sources"]:
            fname = r["sources"][0]["file"]
            doc_counts[fname] = doc_counts.get(fname, 0) + 1

    docs = sorted(doc_counts.items(), key=lambda x: x[1])
    names = [d[0].replace(".txt", "").replace("_", " ") for d in docs]
    counts = [d[1] for d in docs]

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(names, counts, color=TEAL, edgecolor=TEAL_DARK, linewidth=0.5)
    ax.set_xlabel("Broj upita kao primarni izvor")
    ax.set_title("Knowledge Guardian — Korištenje dokumenata", fontweight="bold", color=TEAL)

    for bar, val in zip(bars, counts):
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                str(val), va="center", color=WHITE, fontsize=10)

    plt.tight_layout()
    fig.savefig(RESULT_DIR / "document_usage.png")
    plt.close(fig)


# ── Chart 2: Query topics pie ─────────────────────────────────────────────
def _chart_query_topics(results: list[dict]) -> None:
    topic_counts: dict[str, int] = {}
    for r in results:
        t = r["topic"]
        topic_counts[t] = topic_counts.get(t, 0) + 1

    labels = list(topic_counts.keys())
    sizes = list(topic_counts.values())
    colors = ACCENT_COLORS[: len(labels)]

    fig, ax = plt.subplots(figsize=(8, 8))
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, autopct="%1.0f%%",
        colors=colors, startangle=140,
        textprops={"color": WHITE, "fontsize": 10},
    )
    for at in autotexts:
        at.set_color(NAVY)
        at.set_fontweight("bold")
    ax.set_title("Distribucija tema upita", fontweight="bold", color=TEAL, pad=20)

    plt.tight_layout()
    fig.savefig(RESULT_DIR / "query_topics.png")
    plt.close(fig)


# ── Chart 3: Response time histogram ──────────────────────────────────────
def _chart_response_time(results: list[dict]) -> None:
    times = [r["response_time_ms"] for r in results]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(times, bins=20, color=TEAL, edgecolor=TEAL_DARK, alpha=0.9)
    ax.axvline(np.mean(times), color="#ff6b6b", linestyle="--", linewidth=1.5,
               label=f"Prosjek: {np.mean(times):.1f} ms")
    ax.set_xlabel("Vrijeme odgovora (ms)")
    ax.set_ylabel("Broj upita")
    ax.set_title("Distribucija vremena odgovora", fontweight="bold", color=TEAL)
    ax.legend(facecolor=SLATE, edgecolor=TEAL)

    plt.tight_layout()
    fig.savefig(RESULT_DIR / "response_time.png")
    plt.close(fig)


# ── Chart 4: Confidence histogram ─────────────────────────────────────────
def _chart_confidence(results: list[dict]) -> None:
    confs = [r["confidence"] for r in results]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(confs, bins=20, color=TEAL_LIGHT, edgecolor=TEAL_DARK, alpha=0.9)
    ax.axvline(np.mean(confs), color="#ff6b6b", linestyle="--", linewidth=1.5,
               label=f"Prosjek: {np.mean(confs):.2f}")
    ax.set_xlabel("Confidence score")
    ax.set_ylabel("Broj upita")
    ax.set_title("Distribucija confidence scorova", fontweight="bold", color=TEAL)
    ax.legend(facecolor=SLATE, edgecolor=TEAL)

    plt.tight_layout()
    fig.savefig(RESULT_DIR / "confidence_distribution.png")
    plt.close(fig)


# ── Stats JSON ─────────────────────────────────────────────────────────────
def _save_stats(results: list[dict], n_chunks: int) -> dict:
    confs = [r["confidence"] for r in results]
    times = [r["response_time_ms"] for r in results]

    doc_counts: dict[str, int] = {}
    for r in results:
        if r["sources"]:
            fname = r["sources"][0]["file"]
            doc_counts[fname] = doc_counts.get(fname, 0) + 1
    top_doc = max(doc_counts, key=doc_counts.get) if doc_counts else ""

    topic_counts: dict[str, int] = {}
    for r in results:
        topic_counts[r["topic"]] = topic_counts.get(r["topic"], 0) + 1

    stats = {
        "total_documents": 10,
        "total_chunks": n_chunks,
        "total_queries": len(results),
        "avg_confidence": round(float(np.mean(confs)), 3),
        "avg_response_time_ms": round(float(np.mean(times)), 1),
        "top_document": top_doc,
        "coverage_by_topic": topic_counts,
    }

    with open(RESULT_DIR / "knowledge_stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    return stats


# ── Main ───────────────────────────────────────────────────────────────────
def main() -> None:
    BOLD = "\033[1m"
    CYAN_C = "\033[96m"
    GREEN_C = "\033[92m"
    RESET_C = "\033[0m"

    print(f"\n{BOLD}{CYAN_C}{'=' * 60}{RESET_C}")
    print(f"{BOLD}{CYAN_C}  Knowledge Guardian — Analytics{RESET_C}")
    print(f"{BOLD}{CYAN_C}{'=' * 60}{RESET_C}\n")

    engine = RAGEngine()
    n_chunks = len(engine.store.chunks)

    print("  Simuliram 100 historijskih upita...")
    results = _simulate_queries(engine, n=100)
    print(f"  {GREEN_C}Gotovo — {len(results)} upita procesirano.{RESET_C}\n")

    print("  Generišem grafove...")
    _chart_document_usage(results)
    print(f"    {GREEN_C}document_usage.png{RESET_C}")
    _chart_query_topics(results)
    print(f"    {GREEN_C}query_topics.png{RESET_C}")
    _chart_response_time(results)
    print(f"    {GREEN_C}response_time.png{RESET_C}")
    _chart_confidence(results)
    print(f"    {GREEN_C}confidence_distribution.png{RESET_C}")

    stats = _save_stats(results, n_chunks)
    print(f"\n  {BOLD}knowledge_stats.json:{RESET_C}")
    print(f"    Ukupno dokumenata:    {stats['total_documents']}")
    print(f"    Ukupno chunkova:      {stats['total_chunks']}")
    print(f"    Ukupno upita:         {stats['total_queries']}")
    print(f"    Prosječan confidence:  {stats['avg_confidence']:.3f}")
    print(f"    Prosječno vrijeme:     {stats['avg_response_time_ms']:.1f} ms")
    print(f"    Top dokument:          {stats['top_document']}")
    print(f"    Teme: {json.dumps(stats['coverage_by_topic'], indent=6)}")

    print(f"\n  Svi rezultati → {RESULT_DIR}/")
    print(f"\n{'=' * 60}\n")


if __name__ == "__main__":
    main()
