---
name: debug
description: Reproduce, observe, narrow, fix, prove — debugging that refuses to guess.
kind: method
---
Follow this order and do not skip a step because the answer looks obvious:

1. **Reproduce.** State the smallest command or interaction that shows the failure. If you cannot
   reproduce it, say that first — everything after is theory.
2. **Observe.** Read the actual error, log line, or response. Quote it. Do not paraphrase an error
   you have not seen.
3. **Narrow.** Change one thing at a time. A hypothesis that cannot fail is not a hypothesis.
4. **Fix the cause.** If the cause is upstream of where the symptom appears, say so. A guard that
   hides a bad value is not a fix.
5. **Prove.** Run the thing that failed, and run the nearest thing that should still pass. If you
   cannot run it, say what would prove it.
