# V1 Release Checklist

**Local AI Video Clipper — release readiness gate.**

This checklist exists because M10 accepted the current AI performance/quality trade-off for V1
(`PROJECT_PROGRESS.md` → "Milestone 10 - V1 Scope Review"), and M11 then set out to verify — with real evidence,
not assumptions — that the state M10 accepted actually holds up at the scale and in the failure modes V1 claims to
support. It does not replace [`SETUP.md`](SETUP.md) (first install) or [`DEVELOPMENT.md`](DEVELOPMENT.md) (day-to-day
quality gates); it is the gate to run **before cutting a release**, and it points back to both rather than
repeating them.

Every item below is labelled:
- **[VERIFIED — M11, 2026-10-11]**: directly observed this session, with the evidence stated. Re-verify if the
  relevant code has changed since.
- **[MANUAL]**: not automatable from the repo alone; the person preparing the release must do this themselves.
- **[LIMITATION]**: a known, accepted constraint — not a blocker, but the release notes should not contradict it.
- **[OPEN / UNATTRIBUTED]**: observed, unresolved, and explicitly not assigned a cause without evidence.

---

## 1. Pre-release environment

- [ ] **[MANUAL]** Python 3.10+ installed and on `PATH`. Tested with 3.10.11 (`SETUP.md` §1).
- [ ] **[MANUAL]** FFmpeg + FFprobe installed and on `PATH`. Tested with FFmpeg 9.0.1/9.0.2 (`SETUP.md` §2).
- [ ] **[MANUAL]** Ollama installed and running, with the default model pulled.
  **[VERIFIED — M11]** `ollama list` showed `qwen2.5:3b` (1.9 GB) present and the `ollama.exe` process running
  throughout M11 testing.
- [ ] **[MANUAL]** Python packages installed from `requirements.txt` into a virtual environment
  (`SETUP.md` §5). M11 ran everything through the repo's own `.venv` (Python 3.10.11); a fresh clone must create
  its own.
- [ ] **[MANUAL]** Required/optional configuration reviewed — see the env var table in `SETUP.md` §8
  (`OLLAMA_MODEL`, `CLIPPER_HOST`, `CLIPPER_MAX_UPLOAD_MB`, etc.). This checklist does not repeat that table.
- [ ] **[MANUAL]** `input/` and `output/` directories are writable by the process that will run `python -m app.ui`
  (both are created on demand and are git-ignored).
- [ ] **[MANUAL]** Disk-space planning for large uploads:
  **[VERIFIED — M11]** a real upload spools to `%TEMP%` (observed on the C: drive in this environment) and is
  then copied to `CLIPPER_UPLOAD_DIR` (observed on the D: drive, under the project root) — **not simultaneously at
  full 2× for the whole transfer**, as `SETUP.md`'s "about twice their size" estimate suggests, but roughly 1×
  on each of two drives *in sequence* (spool, then copy), overlapping only briefly at the handoff. The spooled
  temp file is deleted within about a second of the request completing (directly observed, not inferred). Before
  a release involving uploads near `CLIPPER_MAX_UPLOAD_MB`, confirm free space on **both** the `%TEMP%` drive and
  the `CLIPPER_UPLOAD_DIR` drive — they may be different drives, as they are on this machine.
  - No disk-space preflight check exists in the application before an upload starts — see §6.

---

## 2. Automated quality gates

Exact commands, verified against this repository's actual configuration and the latest M11 run (not copied from
stale doc text):

```bash
pytest -q                                  # full suite
ruff check app benchmarks tests            # lint, tracked application/test/benchmark code
mypy app benchmarks                        # type check
```

- [ ] **[VERIFIED — M11, 2026-10-11]** `pytest -q` → **491 passed, 1 skipped**, run via the project's own
  `.venv` interpreter. (`DEVELOPMENT.md`'s quality-gates section currently states "487 passed, 1 skipped" — that
  figure predates M09–M11 and is stale; this checklist's count is the one actually observed this session. See
  the note at the end of this section.)
- [ ] **[VERIFIED — M11, 2026-10-11]** `ruff check app benchmarks tests` → all checks passed.
- [ ] **[VERIFIED — M11, 2026-10-11]** `mypy app benchmarks` → no issues found, 42 source files.
- [ ] **[MANUAL]** `ruff check .` (the exact command in `DEVELOPMENT.md`, repo-wide) currently reports **5
  pre-existing warnings, all in the untracked `audit_project.py`** (blind-`except Exception` catches), not in any
  tracked file. If `audit_project.py` is committed in the future (see §6), these must be fixed first, since the
  project's quality bar is "ruff clean repo-wide." If it stays untracked/discarded, this is a non-issue.
- [ ] **[MANUAL]** The opt-in real-model test: `CLIPPER_REAL_E2E=1 pytest tests/test_real_e2e.py -s`
  (`DEVELOPMENT.md` §Tests). This needs a running Ollama with the configured model pulled and a working
  faster-whisper install; it is **not** part of the default `pytest -q` run and was not re-run as part of this
  checklist (the real end-to-end smoke test in §3 covers the same ground through the actual HTTP interface
  instead, which is closer to what a release user will do).

**Note on the stale count:** `DEVELOPMENT.md` line 37 says "487 passed, 1 skipped." This is a pre-existing doc
drift (likely last updated around M08/M09) outside this checklist's scope to fix — flagged here rather than
silently edited elsewhere. If corrected, the current true figure is 491.

---

## 3. Real end-to-end smoke test

This is the one gate that must be run against the **actual** running application, not mocks — a unit-test pass in
§2 does not substitute for this.

1. [ ] **[MANUAL]** Start the real app with the documented command (`SETUP.md` §7 / `start.bat`):
   ```bash
   python -m app.ui
   ```
2. [ ] **[MANUAL]** Upload a valid local video through the real browser form (or an equivalent real HTTP
   multipart POST to `/jobs` — **not** a direct call to any internal function).
3. [ ] **[MANUAL]** Follow the job through to a terminal state via `/jobs/<id>` (completed or failed).
4. [ ] **[MANUAL]** On success, independently re-probe the output clip(s) with `ffprobe` (not just trusting the
   app's own result page) for: exact requested duration, H.264 video stream, AAC audio stream, correct clip
   count.
5. [ ] **[MANUAL]** Confirm `input/ui_uploads/<job_id>/` no longer exists after the job ends (success or
   failure).
6. [ ] **[MANUAL]** Confirm a failed job leaves no partial clips in `output/ui_jobs/<job_id>/`.

**[VERIFIED — M11, 2026-10-11]** All six steps above were performed for real, multiple times, during Missions 01
and 02 (see §4 for the large-file instances). A smaller/ordinary-sized real run was not re-isolated separately
from the large-file runs, but every large-file run in §4 *is* a real end-to-end smoke test by this same procedure,
at larger scale. A release should still re-run this once more against the exact commit being released, since the
M11 evidence is from the working tree described in §7.

---

## 4. Large-upload and boundary evidence (M11 Missions 01-02)

All of the following used the real Flask app (`python -m app.ui`) and real HTTP multipart requests via `curl`
against the live `/jobs` endpoint — **not** unit tests, not mocked requests, not direct calls to `file.save()`.
Fixtures were genuine, valid, `ffprobe`-verified video files (rawvideo + PCM/AAC audio in real containers), never
sparse or corrupt files.

**[VERIFIED — M11, 2026-10-11] Mission 01 — ~3.42 GB upload:**
- A ~3.42 GB (3,418,103,644-byte) valid video, containing real synthesized speech audio, was uploaded and fully
  processed: HTTP 303 → transcription → AI analysis → selection → FFmpeg render → verification → completed.
- **Two** output clips, independently re-probed at exactly 10.000000 s each, H.264 + AAC.
- `input/ui_uploads/<job_id>/` was removed after completion.
- Disk: spool (→ `%TEMP%` / C:) then copy (→ `CLIPPER_UPLOAD_DIR` / D:) observed in sequence, not as a sustained
  2× simultaneous footprint (see §1). Memory stayed flat (~70-75 MB sampled) through the entire upload and copy;
  it only rose during the Whisper/Ollama stage, unrelated to upload size.

**[VERIFIED — M11, 2026-10-11] Mission 02 — under-limit boundary:**
- File: **8,575,516,268 bytes**. Multipart request total (file + measured 541-byte form overhead):
  **8,575,516,809 bytes**.
- Result: **HTTP 303**, job accepted and run to completion.
- Output: **one** clip, independently re-probed at exactly **8.000000 s**, H.264 + AAC.
- `input/ui_uploads/<job_id>/` was removed after completion.

**[VERIFIED — M11, 2026-10-11] Mission 02 — over-limit boundary:**
- File: **8,601,175,046 bytes**. Multipart request total: **8,601,175,587 bytes**.
- Result: **HTTP 413**, returned in **~0.016 seconds**, after only **~262,144 bytes** had actually been
  transmitted (confirmed via `curl`'s own upload-size counter, not inferred).
- **No job was created** — `input/ui_uploads/` had zero entries afterward; `create_job()` was never reached, since
  Werkzeug's `max_content_length` check rejects based on the `Content-Length` header before the body is read.
  This is genuine server-side enforcement: `curl` sent a real `Content-Length` for a real file; nothing was
  rejected client-side.

**Configured limit, precisely:** `app/ui/app.py` sets `MAX_CONTENT_LENGTH = config.max_upload_mb * 1024 * 1024`
= `8192 * 1024 * 1024` = **8,589,934,592 bytes = exactly 8 GiB**. The configuration variable and the UI text both
call this "8192 MB," which is **binary MiB** internally, not decimal MB (8,589,934,592 bytes ≈ 8.59 decimal GB).
This is not a bug — just worth knowing precisely before sizing a test file or writing release notes that quote
"8 GB."

**What this evidence does and does not show:**
- The under-limit test sat **13.75 MiB below** the cap (99.84% of it); the over-limit test sat **10.72 MiB
  above** (100.13% of it). Together they bracket the cap tightly.
- **This does not prove the exact byte-for-byte boundary** (i.e., exactly 8,589,934,592 vs. 8,589,934,593 bytes).
  Do not describe this evidence as validating the precise boundary — only that acceptance and rejection both work
  correctly in close proximity to it.

---

## 5. Failure handling and cleanup

- [ ] **[VERIFIED — M11, 2026-10-11 Mission 01]** An upload-save I/O failure (e.g. disk full during
  `file.save()`) is now handled: `app/ui/app.py`'s `create_job()` catches `OSError` and renders the app's own
  `error.html` ("The upload could not be saved. Check available disk space and try again.", HTTP 500) instead of
  leaking Flask's generic Internal-Server-Error page. The upload directory is still cleaned up in this path.
  - **How this was verified:** a disposable test-client probe that monkeypatched
    `werkzeug.datastructures.FileStorage.save` to raise `OSError(28, "No space left on device")`, confirming the
    500 response, the friendly page content, and that the raw exception text never reaches the response body.
    This is **simulated**, not a real full disk — stated explicitly per this checklist's own rule: do not claim a
    real disk-full event was induced. A permanent regression test for this exists:
    `tests/test_ui.py::test_upload_save_failure_is_friendly`.
- [ ] **[VERIFIED — M11, 2026-10-11 Mission 02]** The over-limit request (§4) is a **real**, live-HTTP-induced
  413 — not simulated — confirming the pre-existing `RequestEntityTooLarge` → friendly-error path
  (`app/ui/app.py:http_error`) still works at this scale, with no job or upload-directory artifact left behind.
- [ ] **[MANUAL]** A real client-mid-upload disconnect has **not** been tested, simulated, or claimed as tested
  anywhere in M11. If this matters for the release, it remains open.
- [ ] **[MANUAL]** A genuine full-disk condition (not mocked) has **not** been induced in M11 — doing so was
  explicitly out of scope (risk of actually filling a real drive). If this matters for the release, it remains
  open; the `OSError` handling above is the best current evidence for how the app would behave if it happened.

---

## 6. Known limitations and open observations

Carried forward from existing project documentation (not re-litigated here):
- **AI selection quality for V1 was accepted, not perfected, at M10** (`PROJECT_PROGRESS.md` → "Milestone 10").
  qwen2.5:3b AI time is 60-480 s/job on a CPU-only machine and remains the pipeline's dominant cost; selection
  quality is sensitive to prompt/budget changes (M07-M09). Do not describe clip selection as consistently
  accurate in release notes — it is "accepted for V1," not "solved."
- **The opt-in real-model test (`tests/test_real_e2e.py`) is skipped in the default `pytest -q` run** (1 skipped,
  §2) and needs `CLIPPER_REAL_E2E=1` plus live Ollama/Whisper to run at all.
- **Browser-specific upload/progress behavior was not verified in M11.** All M11 HTTP tests used `curl` directly
  against the real endpoint; this is genuine server-side evidence, but it does not cover browser-specific
  behavior (e.g. how Chrome/Firefox render the upload progress indicator, or handle an 8+ GB `<input type=file>`
  selection). `docs/SETUP.md`'s screenshots are the most recent browser evidence on record, from an earlier,
  smaller-scale run (M06).
- **No disk-space preflight check exists** before an upload starts (§1). This was true before M11 and remains
  true; M11 only improved what happens when a save *fails* (§5), not whether the app warns beforehand.

**[OPEN / UNATTRIBUTED]** During Mission 02's under-limit run, while Whisper/Qwen were processing (not during the
upload or copy itself), the C: drive's free space dropped by approximately **4.8 GB** and did not immediately
recover. Inspection of `%TEMP%` for large recently-written files found nothing attributable to this
application's own code (no code path in `app/transcription`, `app/ai`, or `app/ui` writes multi-gigabyte
temporary data outside the already-accounted-for upload spool). No cause is assigned here — this is recorded as
an observed, unexplained anomaly from this session, not a confirmed defect in Video Scliser. If it recurs on a
release candidate, it is worth a dedicated investigation; it should not by itself block a release given the
absence of any evidence tying it to this codebase.

Other limitations (upload-size-unrelated AI/pipeline behavior, UI constraints such as single-job-at-a-time, no
cancellation from the browser, in-memory job state) are already documented in `PROJECT_PROGRESS.md`'s per-
milestone "Known limitations" sections and are not repeated here.

---

## 7. Release decision

### Verified during M11 (this session, against the working tree described below)

- [x] Real ~3.42 GB upload: accepted, fully processed, correct output (§4, Mission 01).
- [x] Real upload just under the 8192 MiB cap: accepted, fully processed, correct output (§4, Mission 02).
- [x] Real upload just over the 8192 MiB cap: rejected with HTTP 413, no job or artifact created (§4, Mission 02).
- [x] Upload-save `OSError` now produces a friendly error instead of a generic 500 (§5, Mission 01; simulated
  failure, real regression test).
- [x] Full pytest suite, Ruff (tracked code), and mypy all green at the time of this checklist (§2).

### Must be checked by the person preparing a release

- [ ] All **[MANUAL]** items in §1-§3 above, on the actual machine/environment the release targets.
- [ ] Re-run §2's three commands against the exact commit being released (M11's evidence is from a working tree
  with two uncommitted changes — see below — not yet a tagged commit).
- [ ] Decide on `audit_project.py` (still untracked as of this checklist — commit as a documented dev tool, or
  discard; see M10's "Next Milestone" notes in `PROJECT_PROGRESS.md`).
- [ ] Decide whether the real client-disconnect and genuine full-disk scenarios (§5) need to be tested before
  this release, or deferred.
- [ ] Decide whether the DEVELOPMENT.md stale test count (§2) and the SETUP.md "twice their size" disk estimate
  (§1) should be corrected before release (both are pre-existing doc drift, not errors introduced by M11).

### Working tree this evidence was gathered against

At the time this checklist was written: `app/ui/app.py` and `tests/test_ui.py` have uncommitted changes (the
upload-save `OSError` fix and its regression test, from M11 Mission 01), and `audit_project.py` is untracked.
This checklist's §4 evidence was gathered **after** those uncommitted changes were in place, but the changes
themselves do not affect the upload/boundary behavior measured in §4 (they only change what happens on a save
*failure*, exercised separately in §5).

### GO / NO-GO

**Not decided here.** This checklist does not grant release approval by itself — that is a decision for whoever
is preparing the release, after completing the "must be checked" items above.

- [ ] **GO** — all applicable boxes above checked, remaining limitations in §6 accepted as-is.
- [ ] **NO-GO** — outstanding item(s): _______________________________________________
