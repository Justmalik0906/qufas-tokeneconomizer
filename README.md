# qufas-tokeneconomizer

**We kill reset.\***

Offload long-log summaries, error explanations, translation, commit messages and draft tests from your coding agent (Claude Code, Codex) to a cheaper model, through any OpenAI-compatible gateway: Qufas, OpenRouter, LiteLLM, Ollama and others.

\*Fewer tokens burned on the main model. This does not change any provider's quota or reset rules.

Not affiliated with or endorsed by Microsoft, UC Berkeley or the TokenEconomizer research project. This skill only offloads sub-tasks to a cheaper model; it does not implement that project's methods.

## Install

Claude Code, all projects:

    git clone https://github.com/Justmalik0906/qufas-tokeneconomizer ~/.claude/skills/qufas-tokeneconomizer

Claude Code, one project: clone into `.claude/skills/qufas-tokeneconomizer` inside the repo.

Codex: put the folder in your project (for example `tools/qufas-tokeneconomizer/`) and add a line to `AGENTS.md`: for logs over 200 lines, large diffs or long errors, run `python tools/qufas-tokeneconomizer/scripts/ask.py <command>`; see `SKILL.md`. Whether your Codex version loads `SKILL.md` natively depends on the version, so check its docs.

Requires Python 3.8+ and nothing else.

## Configure

Set these in your shell profile. Never put a key in this folder or in a chat.

    export QUFAS_API_KEY="..."
    export QUFAS_BASE_URL="https://YOUR-GATEWAY/v1"   # OpenAI-compatible; calls /chat/completions
    export QUFAS_MODEL="your-cheap-model"
    # optional: QUFAS_MODEL_SUMMARIZE, QUFAS_MODEL_REVIEW ... per-task models
    # optional: QUFAS_PRICE_IN / QUFAS_PRICE_OUT  (price per 1M tokens, for `report`)

## Commands

| Command | What it does |
|---|---|
| `summarize` | Summarize a long log or document, citing line numbers |
| `explain-error` | Root cause, evidence and fixes for an error or stack trace |
| `translate --to LANG` | Translate, keeping code blocks and links |
| `commit-msg --diff staged` | Conventional Commits message from a diff |
| `gen-tests` | Draft unit tests (review and run them) |
| `review --diff staged` | Second-opinion review of a change |
| `report` | Local usage summary |

All task commands accept `--format text|md|json`, `--redact`, `--dry-run`, `--note` and `--lang`.

    python scripts/ask.py summarize -i build.log --dry-run   # shows what would be sent, no network
    pytest 2>&1 | python scripts/ask.py explain-error -i -

## Privacy

Input is sent to the gateway you configure. Common secret patterns (private keys, cloud and API keys, bearer tokens, JWTs, URL credentials, password and token assignments) and files such as `.env` or `*.pem` are blocked by default. `--redact` masks them and sends anyway. Usage is logged to `~/.qufas/usage.jsonl` with counts only, never content. The detection is pattern-based, so it is a safety net, not a guarantee.

## Limits

- Cannot lower the main model's reasoning cost or replace it; it only offloads sub-tasks.
- The offloaded model has no tools, so it can't read files or run commands.
- Only tested against a local mock gateway so far. Please run `--dry-run` first, then a small real request, and open an issue if your gateway behaves differently.
- Savings are not measured here. Compare main-agent token totals on the same tasks with and without the skill.
