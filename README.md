# Syllabuddy (RAG + LLM Study Planner)

Upload your notes, set a deadline, and get a study schedule built from your own material, with **Atlas**, a built-in AI study assistant.

## Run

```bash
./run.sh
```

Opens http://localhost:8000. The first run installs dependencies and downloads a small local embedding model.

### Connecting Atlas to an AI

Atlas works with your **Claude Code** login and with **any OpenAI-compatible AI**, local or hosted. On startup it connects automatically when it finds:

- **Claude Code** installed and logged in (`claude`): uses your Claude login, no key needed
- **Ollama** running (`localhost:11434`) or **LM Studio** running (`localhost:1234`): free, private, no key needed
- an API key already set on your computer: `GEMINI_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY`

Anything else (llama.cpp, Jan, vLLM, another provider): open **Setup → AI mode**, pick a provider or **Custom**, and enter the model, server address and key. Keys stay on your computer and are never sent to the browser.

On a server, set the connection with environment variables instead: `STUDY_AI_BASE_URL`, `STUDY_AI_MODEL` and `STUDY_AI_KEY`.

**No AI at all?** The app still works in offline mode: topics come from the headings in your notes (or groups of PDF pages), study time is estimated from how much text each has, and the Atlas tab shows the most relevant passages instead of a written answer.

## Deploy on Render

The repo includes a `render.yaml` Blueprint.

1. On [render.com](https://render.com), choose **New → Blueprint** and pick this repository.
2. When asked for `GEMINI_API_KEY`, paste a free key from [Google AI Studio](https://aistudio.google.com/apikey) (or leave it empty for offline mode).
3. Deploy. The first build takes a few minutes; the embedding model downloads on the first upload.

On the free plan the service sleeps after 15 minutes without visits and its disk is not kept, so quests and uploads reset when it restarts. For lasting data, use a paid instance with a disk mounted at `/data` and set `STUDY_DATA_DIR=/data`.

## How it works

1. **Upload**: your PDF / DOCX / MD / TXT files are split into chunks, embedded locally (`bge-small`) and stored in ChromaDB.
2. **Topics (RAG + Atlas)**: Atlas reads your material and lists the topics to learn, with difficulty and estimated hours. Each topic is linked to the passages in your notes that cover it (vector search).
3. **Schedule**: plain Python fits study sessions into your daily study time before each deadline, earliest deadline first, then adds spaced reviews 1, 3 and 7 days after a topic is learned.
4. **Ask Atlas**: questions are answered from the most relevant passages of your notes, with citations.

**Quick commands**: on the Today screen, tell Atlas things like “add my Maths final on 20 Nov” and it updates your quests and plan.

Tick sessions off as you go; **Rebuild plan** moves missed sessions forward.

## Files

```
app/main.py      API endpoints
app/rag.py       loading, chunking, embeddings, vector search
app/planner.py   topic extraction, scheduling, Q&A
app/llm.py       Atlas's AI connection (any OpenAI-compatible API, auto-detect)
app/agent.py     quick commands (tool calling)
app/db.py        SQLite models
app/static/      web UI (HTML/CSS/JS)
datasets/        synthetic RAG evaluation dataset
tests/           uv run pytest
```
