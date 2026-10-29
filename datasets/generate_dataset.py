"""Generates a SYNTHETIC retrieval/QA log for Syllabuddy, shaped like the sample the project started from.

Each query retrieves its top 5 chunks, so every query produces 5 rows (rank 1-5).
Values are simulated, not measured, but follow the app's real behaviour:
- chunks are at most 200 words (app/config.py CHUNK_WORDS) and come from PDF / Word / Markdown / TXT files
- higher-ranked chunks score higher, and chunks from the query's own topic score higher than off-topic ones
- answer quality rises with retrieval quality; offline mode (no LLM, passages only) scores lower
- AI answers take seconds, offline answers take milliseconds

Run:  uv run python datasets/generate_dataset.py
"""

import csv
import random
from pathlib import Path

SEED = 42
N_QUERIES = 1200  # x 5 retrieved chunks = 6000 rows
TOP_K = 5
CHUNK_WORDS = 200
DOC_TYPES = {"PDF": ".pdf", "Word": ".docx", "Markdown": ".md", "TXT": ".txt"}
QUERY_TYPES = ["factual", "analytical", "comparative", "procedural", "summarization"]

SUBJECTS = {
    "Database Management Systems": ["ER Model", "Relational Algebra", "SQL Joins", "Functional Dependencies",
                                    "Normalization", "Transactions and ACID", "Concurrency Control", "B+ Tree Indexing"],
    "Operating Systems": ["Process Scheduling", "Threads", "Synchronization", "Semaphores", "Deadlocks",
                          "Paging", "Virtual Memory", "File Systems"],
    "Machine Learning": ["Linear Regression", "Gradient Descent", "Overfitting", "Regularization",
                         "Decision Trees", "Random Forests", "Cross-Validation", "Neural Networks"],
    "Computer Networks": ["OSI Model", "TCP vs UDP", "IP Addressing", "Subnetting", "Routing Algorithms",
                          "Congestion Control", "DNS", "HTTP"],
    "Data Structures": ["Arrays and Linked Lists", "Stacks and Queues", "Binary Search Trees", "Heaps",
                        "Hash Tables", "Graph Traversal", "Dynamic Programming", "Sorting Algorithms"],
    "Physics": ["Kinematics", "Newton's Laws", "Work and Energy", "Momentum", "Thermodynamics",
                "Waves", "Optics", "Electrostatics"],
    "Economics": ["Supply and Demand", "Elasticity", "Market Structures", "GDP", "Inflation",
                  "Monetary Policy", "Fiscal Policy", "International Trade"],
    "Biology": ["Cell Structure", "DNA Replication", "Protein Synthesis", "Mitosis and Meiosis",
                "Genetics", "Evolution", "Photosynthesis", "Ecology"],
}

TEMPLATES = {
    "factual": ["What is {t}?", "Define {t}.", "What are the key terms in {t}?", "State the main rule of {t}."],
    "analytical": ["Why does {t} matter in {s}?", "What problem does {t} solve?",
                   "What happens if {t} is applied incorrectly?", "Explain the reasoning behind {t}."],
    "comparative": ["Compare {t} and {o}.", "What is the difference between {t} and {o}?",
                    "When would you use {t} instead of {o}?"],
    "procedural": ["How do you apply {t} step by step?", "Walk me through a worked example of {t}.",
                   "What are the steps to solve a {t} problem?"],
    "summarization": ["Summarize {t}.", "Give me a quick revision summary of {t}.",
                      "What are the main points of {t} for my exam?"],
}


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def build_corpus(rng):
    """50 documents, each covering a few topics of one subject, split into chunks."""
    docs, chunks = [], []
    subjects = list(SUBJECTS)
    for d in range(1, 51):
        subject = subjects[(d - 1) % len(subjects)]
        doc_type = rng.choice(list(DOC_TYPES))
        topics = rng.sample(SUBJECTS[subject], k=rng.randint(2, 4))
        slug = subject.lower().replace(" ", "_")
        doc = {"doc_id": f"DOC{d:03d}", "doc_type": doc_type, "subject": subject,
               "filename": f"{slug}_notes_{d:02d}{DOC_TYPES[doc_type]}"}
        docs.append(doc)
        for i in range(rng.randint(8, 20)):
            # Most chunks are full-size; section ends produce shorter ones.
            words = CHUNK_WORDS if rng.random() < 0.55 else rng.randint(40, CHUNK_WORDS - 1)
            chunks.append({**doc, "chunk_index": i, "topic": topics[i % len(topics)], "word_count": words})
    for n, c in enumerate(chunks, start=1):
        c["chunk_id"] = f"CHK{n:05d}"
    return docs, chunks


def main():
    rng = random.Random(SEED)
    docs, chunks = build_corpus(rng)
    by_subject = {}
    for c in chunks:
        by_subject.setdefault(c["subject"], []).append(c)

    rows = []
    for q in range(1, N_QUERIES + 1):
        subject = rng.choice(list(SUBJECTS))
        topic = rng.choice(SUBJECTS[subject])
        other = rng.choice([t for t in SUBJECTS[subject] if t != topic])
        qtype = rng.choice(QUERY_TYPES)
        query = rng.choice(TEMPLATES[qtype]).format(t=topic, s=subject, o=other)
        llm_mode = "ai" if rng.random() < 0.8 else "offline"

        # Candidate chunks: same-topic chunks are much more likely to be retrieved.
        pool = by_subject[subject]
        on_topic = [c for c in pool if c["topic"] == topic]
        off_topic = [c for c in pool if c["topic"] != topic]
        n_on = min(len(on_topic), rng.choice([2, 3, 3, 4, 5]))
        picked = rng.sample(on_topic, n_on) + rng.sample(off_topic, TOP_K - n_on)

        scored = []
        for c in picked:
            relevant = c["topic"] == topic
            base = rng.gauss(0.80 if relevant else 0.58, 0.07)
            base += 0.03 * (c["word_count"] / CHUNK_WORDS)  # fuller chunks carry more context
            scored.append((clamp(base, 0.30, 0.995), relevant, c))
        scored.sort(key=lambda x: x[0], reverse=True)

        top_mean = sum(s for s, _, _ in scored[:3]) / 3
        n_relevant = sum(r for _, r, _ in scored)
        quality = 0.35 + 0.55 * top_mean + 0.03 * n_relevant + rng.gauss(0, 0.04)
        quality += {"factual": 0.03, "summarization": 0.02, "procedural": 0.0,
                    "analytical": -0.02, "comparative": -0.03}[qtype]
        if llm_mode == "offline":
            quality -= 0.15  # passages only, no written answer
        quality = round(clamp(quality, 0.30, 1.0), 3)
        latency = int(rng.gauss(6500, 1800)) if llm_mode == "ai" else int(rng.gauss(220, 60))

        for rank, (score, relevant, c) in enumerate(scored, start=1):
            cited = relevant and (llm_mode == "offline" and rank <= 3 or llm_mode == "ai" and rng.random() < 0.85)
            rows.append({
                "doc_id": c["doc_id"], "doc_type": c["doc_type"], "chunk_id": c["chunk_id"],
                "word_count": c["word_count"], "retrieval_score": round(score, 4), "query_type": qtype,
                "answer_quality_score": quality,
                "record_id": f"REC{len(rows) + 1:05d}", "query_id": f"Q{q:04d}", "query_text": query,
                "subject": subject, "topic": topic, "chunk_topic": c["topic"], "filename": c["filename"],
                "chunk_index": c["chunk_index"], "retrieval_rank": rank, "is_relevant": int(relevant),
                "cited_in_answer": int(bool(cited)), "llm_mode": llm_mode, "latency_ms": max(80, latency),
            })

    out = Path(__file__).with_name("syllabuddy_rag_dataset.csv")
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows ({N_QUERIES} queries x {TOP_K} chunks, {len(chunks)} chunks in {len(docs)} docs) -> {out}")


if __name__ == "__main__":
    main()
