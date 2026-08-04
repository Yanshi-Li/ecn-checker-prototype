# ECN Checker Prototype — Version 1

A standalone Java prototype that validates Engineering Change Notice (ECN)
change lines against simulated master part and released Bill of Materials (BOM)
data.

## Purpose

The prototype demonstrates ECN checks before an ECN is submitted, approved,
implemented, or completed.

This Version 1 prototype does not require Windchill access. It uses CSV files
to simulate data that may later be retrieved from Windchill, a PLM, or an ERP.

## AI usage

This version now includes a hybrid AI-assisted workflow:

- Java remains the deterministic rules engine.
- Python can generate reviewer-friendly summaries and actions from the checker output.
- If no model is configured, the system falls back to deterministic guidance.

```text
ECN CSV + Master BOM CSV + Part Master CSV
                ↓
          Java validation rules
                ↓
      JSON dashboard results
                ↓
      Python assistant (LLM or fallback)
                ↓
      Reviewer summary + next actions
```

## Hybrid workflow

Run the full pipeline with:

```bash
python3 scripts/run_hybrid.py
```

This will:
- compile and run the Java checker,
- generate the reviewer dashboard,
- produce a structured AI summary JSON file,
- and create a simple hybrid HTML view.

### Optional LLM configuration

If you want the Python assistant to use an LLM, configure one of these providers:

OpenAI:

```bash
export OPENAI_API_KEY=your_key
export OPENAI_MODEL=gpt-4o-mini
```

Ollama:

```bash
export OLLAMA_BASE_URL=http://localhost:11434
export OLLAMA_MODEL=llama3.2:latest
```

If no credentials are configured, the assistant uses the built-in deterministic fallback.
