# Mocap feedback transcripts (canonical classifier pins)

Provenance: extracted verbatim from the live session log
`work/logs/game-live-20260903-160200.log` (2026-09-03, `Marx Video Test`,
Mocap 1.3.10, client locale zh_cn). Timestamps and log prefixes are stripped;
what remains is exactly the chat text the classifier receives.

The sequence below is the evidence for failure F6 (two-step start):

| File | Log time | Meaning |
|---|---|---|
| `zh_cn/waiting-for-selection.txt` | 16:16:44 | First `start`: entered waiting-for-selection, NOT recording |
| `zh_cn/waiting-cancelled.txt` | 16:17:10 | `stop` while waiting: nothing was recorded → idle |
| `zh_cn/save-rejected-empty.txt` | 16:17:40 | `save` with nothing recorded: rejected (two lines) |
| `zh_cn/recording-started.txt` | 16:18:55 | Second `start`: real recording began |
| `zh_cn/recording-stopped.txt` | 16:20:09 | `stop` while recording: take captured, awaiting save/discard |
| `zh_cn/save-success.txt` | 16:20:41 | Save accepted |
| `unknown/axiom-tip.txt` | 16:15:48 | Unrelated mod chatter: must classify as UNKNOWN |

Classifier rules (plan v2 §Phase D):

- Exact-match on these pinned lines (after stripping formatting section
  codes `§…`). The stop message contains literal `\n` escapes in the log;
  the classifier matches the stable first line
  `录制停止——等待选择中……` and ignores trailing help lines.
- Any unmatched feedback → `unknown` → **fails closed**. Never guess.
- `en_us` pins are provisional (no English-locale live run yet). A wrong pin
  can only cause a fail-closed mismatch, never a false success; replace them
  with real strings after the first en_us session and record the change in
  `docs/test-results.md`.
- Prefer a stable translation/content key once the mod exposes one
  (`last_feedback_key`); text pins are the fallback surface.
