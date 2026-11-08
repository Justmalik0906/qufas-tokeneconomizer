---
name: qufas-tokeneconomizer
description: Reduce avoidable context and tool-output overhead during coding, debugging, and repository exploration while preserving correctness. Use when working on codebases, running tests, investigating errors, or preparing a handoff between sessions.
---

# Qufas TokenEconomizer

A local-first workflow for coding agents. Optimize **cost per successfully completed task**, not just prompt length. Do not claim measured savings without a controlled comparison.

## Operating principles

1. **Search before reading.** Identify likely files using filenames, symbols, or targeted search. Read the smallest relevant code region first; expand only when necessary.
2. **Reuse valid context.** Do not reread unchanged files, rerun identical discovery commands, or repeat confirmed findings. Verify again after relevant changes or when correctness requires it.
3. **Keep tool output focused.** Prefer concise, structured command output for routine operations. Keep the full original log locally when it may be needed. Always retain exit status, failing test names, errors, stack traces, and paths to full logs.
4. **Diagnose before retrying.** If a command fails repeatedly with the same symptoms, compare inputs and environment, identify what changed, and choose a different diagnostic step. Do not automatically stop a complex task merely because several attempts failed.
5. **Preserve cache-friendly context.** Avoid unnecessary large changes to stable instructions or tool configuration. Do not force session resets or compaction just to shorten visible history.
6. **Hand off only when useful.** For long tasks, prepare a compact, accurate state summary that identifies objective, decisions, relevant files, commands run, unresolved errors, and next steps. Do not discard needed details.

## Recommended workflow

### Before editing
- Restate the task in one sentence when needed.
- Locate relevant files and symbols before opening large files.
- Check recent findings or an existing handoff if present, and verify that they still apply.

### While working
- Prefer targeted searches and limited output over full-repository dumps.
- Run the narrowest meaningful test first, then broader tests when appropriate.
- If output is verbose, preserve a full raw copy and provide a concise summary with exact error references.
- Avoid repeating an identical failed tool call unless there is a specific reason.

### At a task boundary
- Record the result, tests performed, remaining risks, and next action.
- If asked for a handoff, use the template below.

## Handoff template

```text
Task:
Status:
Relevant files:
Decisions / confirmed facts:
Commands and test results:
Unresolved issues:
Next safe action:
```

## Safety and correctness

- Never trade correctness, security, or necessary diagnostics for token savings.
- Never suppress failing tests, delete source files, or change tests merely to get a shorter result.
- Do not modify production configuration, credentials, billing, databases, or deployment settings without explicit task authorization.
- Do not upload source code, logs, secrets, or repository metadata to external services.
- Preserve audit evidence and detailed logs for security-sensitive work.
- If optimization may hide useful information, show the original output instead.
- Treat this skill as workflow guidance: it does **not** control private reasoning tokens, bypass subscription limits, or guarantee savings.
