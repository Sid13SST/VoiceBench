Hand-written Gnani API replies for the offline tests (`tests/test_gnani_*.py`).
None of them came from a live call. The success bodies follow the fields the
Gnani STT REST reference lists (`success`, `request_id`, `transcript`, and
for prisma-v3.0 `detected_language_code`); the error bodies use the error
codes of the Gnani error reference (the 402 body carries only a message: no code for it is relied on). No real key, request id or account
data is in them.
