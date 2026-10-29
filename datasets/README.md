# Syllabuddy RAG dataset (synthetic)

`syllabuddy_rag_dataset.csv`: 6,000 rows of retrieval and answer logs. There are 1,200 study questions, and each one retrieves its top 5 chunks from 50 note documents (705 chunks across 8 subjects).

**The data is simulated, not measured.** `generate_dataset.py` builds it from a fixed seed, so running it again gives the same file. The values follow how the app actually works: 200-word chunks, PDF/Word/Markdown/TXT files, top-5 retrieval, and AI or offline mode.

## Columns

| Column | Meaning |
|---|---|
| doc_id | Source document (DOC001–DOC050) |
| doc_type | PDF, Word, Markdown or TXT (the formats the app accepts) |
| chunk_id | Retrieved chunk (CHK00001…) |
| word_count | Words in the chunk (at most 200, the app's chunk size) |
| retrieval_score | Cosine similarity between the question and the chunk (0–1) |
| query_type | factual, analytical, comparative, procedural or summarization |
| answer_quality_score | Quality of the final answer for the question (0–1), the same for all 5 rows of a question |
| record_id | Row id |
| query_id | Question id; the 5 rows of a question share it |
| query_text | The student's question |
| subject / topic | What the question is about |
| chunk_topic | The topic the retrieved chunk actually covers |
| filename | The uploaded file the chunk came from |
| chunk_index | Position of the chunk within its file |
| retrieval_rank | 1 = best match among the 5 retrieved |
| is_relevant | 1 if the chunk's topic matches the question's topic |
| cited_in_answer | 1 if the answer cited this chunk |
| llm_mode | `ai` (written answer) or `offline` (passages only) |
| latency_ms | Time to answer the question |

## Built-in patterns

- Scores fall with rank: about 0.87 at rank 1 down to 0.59 at rank 5.
- Answer quality rises with retrieval quality. AI mode averages 0.89 and offline mode 0.75.
- Factual and summary questions score a bit higher than comparative or analytical ones.
- Regenerate with `uv run python datasets/generate_dataset.py`.
