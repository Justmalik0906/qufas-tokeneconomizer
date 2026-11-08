#!/usr/bin/env python3
"""qufas-tokeneconomizer: send low-risk sub-tasks to a cheaper model on the Qufas gateway.

Pure standard library. Reads config from environment variables:
  QUFAS_API_KEY    required (never written to disk by this script)
  QUFAS_BASE_URL   required, OpenAI-compatible base URL, e.g. https://<host>/v1
  QUFAS_MODEL      default model name
  QUFAS_MODEL_<TASK>  optional per-task override, e.g. QUFAS_MODEL_SUMMARIZE
  QUFAS_PRICE_IN / QUFAS_PRICE_OUT  optional price per 1M tokens, for `report`

Usage log (no prompt or response content): ~/.qufas/usage.jsonl
"""
import argparse, fnmatch, json, os, re, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

HOME = Path(os.environ.get("QUFAS_HOME", Path.home() / ".qufas"))
LOG = HOME / "usage.jsonl"
CACHE = HOME / "cache"
DEFAULT_MAX_CHARS = 200_000
NUMBERED = ("summarize", "explain-error")  # tasks whose input is sent with line numbers

# ---------- secret protection ----------
SENSITIVE_NAMES = [".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*",
                   "id_ed25519*", "credentials", "credentials.*", "secrets.*", ".netrc"]
PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----)?")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("api-key-sk", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("bearer-token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/\-]{20,}=*")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("url-credentials", re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s:/@]+:[^\s@/]+@")),
    ("secret-assignment", re.compile(
        r"(?i)\b(?:api[_-]?key|secret(?:[_-]?key)?|access[_-]?key|auth[_-]?token|token|passwd|password|pwd)"
        r"\b[\"']?\s*[:=]\s*[\"']?(?![$({<\[])([^\s\"'(){}<>,;]{8,})")),
]

def scan(text):
    """Return list of (label, line_number) for every sensitive match (values are never returned)."""
    hits = []
    for label, rx in PATTERNS:
        for m in rx.finditer(text):
            if label == "secret-assignment" and text[m.end():m.end() + 1] == "(":
                continue  # a function call such as token = get_token(), not a literal value
            hits.append((label, text.count("\n", 0, m.start()) + 1))
    return sorted(hits, key=lambda h: h[1])

def redact(text):
    for label, rx in PATTERNS:
        if label == "secret-assignment":
            text = rx.sub(lambda m: m.group(0) if text[m.end():m.end() + 1] == "(" else
                          m.group(0).replace(m.group(1), f"[REDACTED:{label}]"), text)
        else:
            text = rx.sub(lambda m: f"[REDACTED:{label}]" + "\n" * m.group(0).count("\n"), text)
    return text

def is_sensitive_name(path):
    name = Path(path).name.lower()
    return any(fnmatch.fnmatch(name, pat) for pat in SENSITIVE_NAMES)

# ---------- input ----------
def die(msg, code=2):
    print(f"qufas-tokeneconomizer: {msg}", file=sys.stderr)
    sys.exit(code)

def git_diff(spec):
    if spec in ("staged", "cached"):
        args = ["git", "diff", "--staged"]
    elif spec in ("unstaged", "working"):
        args = ["git", "diff"]
    else:
        if spec.startswith("-"):
            die("--diff must be 'staged', 'unstaged', or a revision such as HEAD~1")
        args = ["git", "diff", spec]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        die(f"git failed: {e}")
    if out.returncode != 0:
        die(f"git diff failed: {out.stderr.strip()}")
    if not out.stdout.strip():
        die("diff is empty, nothing to send", 4)
    return out.stdout

def load_input(args):
    """Return (text, source_label, source_path or None)."""
    if getattr(args, "diff", None):
        return git_diff(args.diff), f"git diff {args.diff}", None
    inp = getattr(args, "input", None)
    if not inp:
        die("provide --input FILE (or '-' for stdin)" + (" or --diff" if args.task in ("commit-msg", "review") else ""))
    if inp == "-":
        text = sys.stdin.read()
        if not text.strip():
            die("stdin is empty", 4)
        return text, "stdin", None
    if is_sensitive_name(inp):
        die(f"refusing to send '{inp}': file name looks like a credentials file", 3)
    p = Path(inp)
    if not p.is_file():
        die(f"file not found: {inp}")
    try:
        return p.read_text(encoding="utf-8", errors="replace"), str(p), str(p.resolve())
    except OSError as e:
        die(f"cannot read {inp}: {e}")

def clip(text, max_chars):
    """Keep head and tail when input is too large; returns (text, was_clipped)."""
    if len(text) <= max_chars:
        return text, False
    half = max_chars // 2
    cut = len(text) - max_chars
    return text[:half] + f"\n[... {cut} characters omitted ...]\n" + text[-half:], True

def number_lines(text):
    return "\n".join(f"{i}: {ln}" for i, ln in enumerate(text.splitlines(), 1))

# ---------- prompts ----------
SYSTEM = ("You are a precise assistant helping a coding agent. Be concise. "
          "Do not invent facts that are not in the input. If something is unclear, say so.")

def _base_prompt(args, text):
    t = args.task
    extra = f"\nExtra requirement from the user: {args.note}" if args.note else ""
    lang = f" Write in {args.lang}." if args.lang else " Write in the same language as the input."
    if t == "summarize":
        return (
            "Summarize the following content for a developer who will not read it in full. "
            "The content has line numbers in the form 'N: text'. Output:\n"
            "1. Result (one line: succeeded / failed / unclear)\n"
            "2. Key findings (max 8 bullets; every error, warning or decision must cite its line number as L<N>)\n"
            "3. Suspicious lines worth reading in full (line ranges)\n"
            "Do not omit any error or failure line." + lang + extra + "\n\n---\n" + text)
    if t == "translate":
        return (f"Translate the following text into {args.to}. Preserve Markdown, code blocks, inline code, "
                "URLs, placeholders and numbers exactly. Output only the translation." + extra + "\n\n---\n" + text)
    if t == "commit-msg":
        return ("Write a Git commit message for this diff, in Conventional Commits style: "
                "'type(scope): subject' (max 72 chars, imperative mood), then a blank line and a short body "
                "(why, not a line-by-line what) only if the change is non-trivial. Output only the message."
                + lang + extra + "\n\n---\n" + text)
    if t == "gen-tests":
        fw = f" using {args.framework}" if args.framework else " using the test framework implied by the code"
        return ("Write draft unit tests for the following source code" + fw + ". Cover normal cases, edge cases "
                "and error handling. Output one code block with the test file only, then a short list of "
                "assumptions you made. These are drafts that will be reviewed and run." + extra + "\n\n---\n" + text)
    if t == "review":
        return ("Review the following change as a second opinion. List only concrete problems: bugs, missing "
                "error handling, security issues, unclear logic. For each: severity (high/medium/low), "
                "location, what is wrong, suggested fix. If you find nothing significant, say so instead of "
                "inventing issues. Do not comment on style." + lang + extra + "\n\n---\n" + text)
    if t == "explain-error":
        return ("Explain the error in the following output or stack trace for a developer. The content has line "
                "numbers in the form 'N: text'. Give: (1) the most likely root cause in one or two sentences, "
                "(2) the evidence, citing line numbers as L<N>, (3) up to 3 concrete fixes, most likely first, "
                "(4) what to check next if those fail. Separate what the output proves from what you are guessing. "
                "If the output does not contain enough information, say what is missing instead of guessing."
                + lang + extra + "\n\n---\n" + text)
    die(f"unknown task {t}")

JSON_KEYS = {
    "summarize": '{"result": "succeeded|failed|unclear", "findings": [{"line": 0, "text": ""}], "suspicious_ranges": [{"start": 0, "end": 0, "reason": ""}]}',
    "explain-error": '{"root_cause": "", "evidence_lines": [0], "fixes": [""], "next_checks": [""], "confidence": "high|medium|low"}',
    "review": '{"issues": [{"severity": "high|medium|low", "location": "", "problem": "", "fix": ""}]}',
    "gen-tests": '{"test_code": "", "assumptions": [""]}',
    "commit-msg": '{"type": "", "scope": "", "subject": "", "body": ""}',
    "translate": '{"translation": ""}',
}

def build_prompt(args, text):
    prompt = _base_prompt(args, text)
    fmt = getattr(args, "format", "text")
    if fmt == "md":
        prompt += "\n\n---\nOutput format: Markdown. Use short headings, bullet lists, and fenced code blocks where they help."
    elif fmt == "json":
        prompt += ("\n\n---\nOutput format: respond with ONLY one valid JSON object, no code fences and no text "
                   "around it, using exactly this shape (empty lists if nothing applies):\n" + JSON_KEYS[args.task])
    return prompt

# ---------- HTTP ----------
def call_api(model, prompt, max_tokens, temperature):
    base = os.environ.get("QUFAS_BASE_URL", "").rstrip("/")
    key = os.environ.get("QUFAS_API_KEY", "")
    if not base:
        die("QUFAS_BASE_URL is not set (OpenAI-compatible base URL, e.g. https://<host>/v1)")
    if not key:
        die("QUFAS_API_KEY is not set")
    url = base + "/chat/completions"
    body = json.dumps({
        "model": model, "max_tokens": max_tokens, "temperature": temperature,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    last = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            last = f"HTTP {e.code}: {detail}"
            if e.code in (429, 500, 502, 503, 504) and attempt == 0:
                time.sleep(2); continue
            break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = f"network error: {e}"
            if attempt == 0:
                time.sleep(2); continue
    die(last or "request failed", 5)

def pick_model(args):
    env_name = "QUFAS_MODEL_" + args.task.upper().replace("-", "_")
    model = args.model or os.environ.get(env_name) or os.environ.get("QUFAS_MODEL")
    if not model:
        die(f"no model set: pass --model or set QUFAS_MODEL (or {env_name})")
    return model

def log_usage(rec):
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass  # logging must never break the task

# ---------- commands ----------
def run_task(args):
    text, label, path = load_input(args)
    hits = scan(text)
    redacted = False
    if hits:
        summary = ", ".join(sorted({h[0] for h in hits}))
        if not args.redact:
            lines = sorted({h[1] for h in hits})[:10]
            die(f"blocked: input appears to contain secrets ({summary}) at line(s) {lines}. "
                "Nothing was sent. Remove them, or re-run with --redact to mask them before sending.", 3)
        text = redact(text); redacted = True
    plain = text
    if args.task in NUMBERED:
        text = number_lines(text)
    text, clipped = clip(text, args.max_chars)
    model = pick_model(args)
    prompt = build_prompt(args, text)

    if args.dry_run:
        print(f"[dry-run] task={args.task} model={model} source={label} chars={len(prompt)} "
              f"redacted={len(hits) if redacted else 0} clipped={clipped}")
        print("---- prompt that would be sent ----")
        print(prompt)
        return

    # keep the original available for follow-up reads when it did not come from a file
    saved = path
    if args.task in NUMBERED and path is None:
        CACHE.mkdir(parents=True, exist_ok=True)
        saved = str(CACHE / f"{int(time.time())}-{args.task}.txt")
        Path(saved).write_text(plain, encoding="utf-8")

    t0 = time.time()
    data = call_api(model, prompt, args.max_tokens, 0.2)
    try:
        out = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        die("unexpected response format from gateway (expected OpenAI-style 'choices')", 5)
    usage = data.get("usage") or {}
    log_usage({"ts": int(t0), "task": args.task, "model": model,
               "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
               "input_chars": len(text), "redactions": len(hits) if redacted else 0,
               "clipped": clipped, "latency_s": round(time.time() - t0, 2)})
    fmt = getattr(args, "format", "text")
    notes = []
    if fmt == "json":
        body = re.sub(r"^```(?:json)?\s*|\s*```$", "", out.strip())
        try:
            out = json.dumps(json.loads(body), ensure_ascii=False, indent=2)
        except ValueError:
            notes.append("model did not return valid JSON; raw text printed instead, treat with care")
    print(out)
    if args.task in NUMBERED and saved:
        notes.append(f"full original: {saved} (line numbers above refer to this content)")
    if clipped:
        notes.append("input was too large; middle part omitted, summary is incomplete")
    if redacted:
        notes.append(f"{len(hits)} secret-like value(s) were masked before sending")
    if args.task in ("gen-tests", "review", "explain-error"):
        notes.append("model output is a draft/second opinion: verify before relying on it")
    for n in notes:
        print(f"[qufas-tokeneconomizer] {n}", file=sys.stderr if fmt == "json" else sys.stdout)

def run_report(args):
    if not LOG.exists():
        print("no usage recorded yet"); return
    cutoff = time.time() - args.days * 86400
    agg = {}
    for line in LOG.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("ts", 0) < cutoff:
            continue
        a = agg.setdefault(r["task"], {"calls": 0, "in": 0, "out": 0, "redacted": 0, "known": 0})
        a["calls"] += 1
        a["redacted"] += r.get("redactions", 0)
        if r.get("prompt_tokens") is not None:
            a["in"] += r["prompt_tokens"]; a["out"] += r.get("completion_tokens") or 0; a["known"] += 1
    if not agg:
        print(f"no usage in the last {args.days} days"); return
    pin, pout = os.environ.get("QUFAS_PRICE_IN"), os.environ.get("QUFAS_PRICE_OUT")
    print(f"Qufas offload usage, last {args.days} day(s)")
    print(f"{'task':<12}{'calls':>6}{'in_tok':>10}{'out_tok':>10}{'cost':>10}")
    tot = 0.0
    for task, a in sorted(agg.items()):
        cost = ""
        if pin and pout:
            c = a["in"] / 1e6 * float(pin) + a["out"] / 1e6 * float(pout); tot += c; cost = f"{c:.4f}"
        print(f"{task:<12}{a['calls']:>6}{a['in']:>10}{a['out']:>10}{cost:>10}")
    if pin and pout:
        print(f"estimated total cost: {tot:.4f} (prices from QUFAS_PRICE_IN/OUT)")
    print("Note: this counts only the offloaded calls, not the savings on the main agent. "
          "Measure savings by comparing main-agent token totals with and without the skill.")

def main():
    ap = argparse.ArgumentParser(prog="ask.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="task", required=True)

    def common(p, diff=False):
        p.add_argument("--input", "-i", help="file path, or '-' for stdin")
        if diff:
            p.add_argument("--diff", help="'staged', 'unstaged' or a git revision such as HEAD~1")
        p.add_argument("--model", help="override model name")
        p.add_argument("--note", help="extra instruction for the model")
        p.add_argument("--format", choices=["text", "md", "json"], default="text",
                       help="output format: text (default), md, or json")
        p.add_argument("--lang", help="output language (default: same as input)")
        p.add_argument("--redact", action="store_true", help="mask secret-like values and send anyway")
        p.add_argument("--dry-run", action="store_true", help="print what would be sent; no network call")
        p.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
        p.add_argument("--max-tokens", type=int, default=1500)

    common(sub.add_parser("summarize", help="summarize a long log or document"))
    p = sub.add_parser("translate", help="translate text"); common(p); p.add_argument("--to", required=True, help="target language")
    common(sub.add_parser("commit-msg", help="write a commit message from a diff"), diff=True)
    common(sub.add_parser("explain-error", help="explain an error, traceback or failing output"))
    p = sub.add_parser("gen-tests", help="draft unit tests"); common(p); p.add_argument("--framework")
    common(sub.add_parser("review", help="second-opinion code review of a diff or file"), diff=True)
    r = sub.add_parser("report", help="show local usage summary"); r.add_argument("--days", type=int, default=7)

    args = ap.parse_args()
    run_report(args) if args.task == "report" else run_task(args)

if __name__ == "__main__":
    main()
