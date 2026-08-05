# corpus_v2 intake template

Stage 24.7 does not import production data. Fill one row per candidate source after human review.

| Field | Required value | Notes |
| --- | --- | --- |
| stable id | `cv2_<topic>_<format>` | Must not reuse corpus_v1 document ids. |
| file name / relative path | Pending fixture or reviewed local fixture path | No upload-dir or production path. |
| source URL / organization | Authoritative source or `unknown` | Do not invent URLs. |
| license / usage boundary | License name or `unknown` | Unknown keeps item pending_review. |
| publication / fetched date | ISO date or `unknown` / `pending_review` | Network fetch is out of scope. |
| department / disease topics / type / language | Controlled metadata | Used for coverage matrix only. |
| content SHA-256 | 64 hex only after reviewed fixture exists | Use `unknown` before review. |
| parser expectation | Parser/version and OCR/Vision flags | Real providers remain disabled. |
| governance | current/due/expired/pending_review | Expired remains non-retrievable. |
