---
name: qufas-tokeneconomizer
description: Offload low-risk, token-heavy sub-tasks to a cheaper model on the Qufas gateway to save main-model tokens. Use this skill whenever you are about to read a long log, build/test output or document (roughly 200+ lines) just to extract the key points; when you need to translate more than a paragraph; when you need a commit message for a large diff; when you need draft unit tests or boilerplate; when a long traceback or error output needs explaining; or when the user wants a quick second-opinion review. Also use it when the user mentions saving tokens, cutting cost, Qufas, or delegating to a cheaper model.
---

# Qufas offload

Send bulk reading and drafting work to a cheaper model through `scripts/ask.py`, and keep your own context for decisions and code changes. Each call costs you a command and a result to read, so only offload when the input is large enough to be worth it.

## Setup check

The script needs `QUFAS_API_KEY`, `QUFAS_BASE_URL` and `QUFAS_MODEL` in the environment. If a call fails because one is missing, tell the user which variable to set. Never ask the user to paste a key into the chat and never write one into a file.

## When to offload

| Task | Command | Offload when |
|---|---|---|
| Summarize a log or document | `python scripts/ask.py summarize -i FILE` | 200+ lines |
| Translate | `python scripts/ask.py translate -i FILE --to LANGUAGE` | more than one paragraph |
| Commit message | `python scripts/ask.py commit-msg --diff staged` | diff is larger than a screen |
| Draft tests / boilerplate | `python scripts/ask.py gen-tests -i SRC [--framework pytest]` | non-trivial module |
| Explain an error | `python scripts/ask.py explain-error -i FILE` | long traceback or 100+ lines of failing output |
| Second-opinion review | `python scripts/ask.py review --diff staged` | user asks, or a risky change |

Below these sizes, do the work yourself. Run the script from the skill directory, or use its full path.

Pipe command output instead of pasting it: `pytest 2>&1 | python scripts/ask.py summarize -i -`. Add `--format json` when you will process the result programmatically (the output is validated; notes then go to stderr so stdout stays clean) or `--format md` for a Markdown document. Default is plain text. Use `--note "..."` to add a requirement and `--lang` to set the output language.

## When not to offload

- The input contains credentials, private keys, customer data or anything unreleased that the user hasn't cleared for sending. The script blocks common secret patterns and credential-style file names, but that is a safety net, not a guarantee. Don't rely on it for data you already know is sensitive.
- The task needs file edits, shell commands or tool use. The cheaper model has no tools.
- The decision is architectural or hard to reverse. Offloaded output is input to your judgment, not a replacement for it.

## Handling the result

- **Summaries**: line numbers like `L42` refer to the original file, whose path is printed at the end. If the summary says "suspicious lines", read only those ranges from the original rather than the whole file. If it reports a failure but you can't see the cause, read the cited lines before acting.
- **Error explanations**: the cited lines are numbered like summaries. Check the stated root cause against the code before changing anything, since the model only sees the output you sent.
- **Explain-error**: the root cause is a hypothesis. Check the cited lines against the real output and the code before changing anything; if it says information is missing, supply it or investigate yourself.
- **Draft tests**: always review them and run them. Fix or discard any that fail for the wrong reason.
- **Review**: treat as a second opinion. Verify each claimed problem in the code before acting, and don't pad your own review with unverified items.
- **Commit messages**: check that the type and scope match the change, then use it.
- If the output ends with a note that input was clipped, the summary is incomplete. Say so to the user or split the input.

## If the script blocks the input

Exit code 3 means secret-like content was found and nothing was sent. Tell the user what was detected (the message lists line numbers, never values). Offer to remove it. Re-run with `--redact` only if the user agrees to send a masked version.

Use `--dry-run` to show exactly what would be sent without making a network call.

## Usage

`python scripts/ask.py report` shows local call counts and tokens for offloaded work (nothing is uploaded). It doesn't measure savings on the main agent. Those have to be compared by running similar tasks with and without this skill.
