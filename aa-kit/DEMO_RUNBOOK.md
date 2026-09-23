# DEMO RUNBOOK — AA pipeline and household timeline

**Status: live operational document through 30 September 2026.**
Last updated: 23 September 2026 (post-E8).

> **Verification status of this runbook.** Every command marked ✅ was executed successfully on the primary machine (Windows, PowerShell, repo at `K:\IIMB_DPI`) on 23 Sep 2026 during E8. **Nothing in this runbook has yet been tested on a second machine.** Items marked `[NEEDS RECHECK]` are not verified — resolve them before relying on this document.

---

## 1 · Purpose and recovery scenario

Demo hierarchy on finals day (30 Sep 2026):

1. **Primary:** live demo on Saksham's laptop.
2. **Contingency:** the recorded, verified E8 video.
3. **Recovery fallback:** a teammate reproduces the live pipeline on their own machine using this runbook.

This runbook is for level 3. It does not replace the live demo or the video.

What the pipeline does: a customer consents on the Anumati AA sandbox (ACME Bank), Anumati calls our webhook through a public tunnel, we fetch the encrypted financial data once, persist it raw, decrypt it locally, and run the household engine (`hsl/`) to produce a dated, observation-only household timeline. Twelve tests confirm the engine's behaviour on the fetched data.

---

## 2 · Prerequisites

| Requirement | Detail | Status |
|---|---|---|
| OS / shell | Windows, PowerShell. All commands below are PowerShell | ✅ primary |
| Git | Access to this repository | ✅ primary |
| Python (engine and tests) | Python 3.14.0 was used for `hsl/` tests and timeline. `hsl/` uses only the standard library | ✅ primary |
| Python venv (pipeline) | `aa-kit\.venv` (git-ignored, must be created per machine). Dependencies are in `aa-kit\requirements.txt`: `flask>=3.0`, `requests>=2.31`, `python-dotenv>=1.0` | ✅ manifest read from the repo; exact installed versions on primary not recorded |
| Java | Required by the crypto JAR (built for JDK 21 → **Java 21 or newer**) | ✅ works on primary; version not recorded |
| Crypto JAR | `aa-kit\fiu-crypto-lib.jar` (10,662,790 B) is present in the repo folder. `decrypt.py` uses it unless env var `CRYPTO_JAR` points elsewhere | ✅ present on primary. Tracked in git ✅ (verified with `git ls-files`); a teammate can confirm with `git ls-files aa-kit/fiu-crypto-lib.jar` after cloning. Original source: the Anumati activation email (`fiu-crypto-lib.txt`, rename to `.jar`) |
| ngrok | ngrok v3 agent (primary uses 3.39.11). `tools\` is git-ignored, so **ngrok is not in the repo** — install it separately | ✅ primary |
| Anumati credentials | `ANUMATI_CLIENT_ID` (non-secret, `client_005`) and `ANUMATI_CLIENT_SECRET` (**secret**) | obtain from Saksham via a secure channel — never chat, never git |
| Callback URL | Anumati sends callbacks to `https://umbilical-starry-marital.ngrok-free.dev`. This static domain belongs to **Saksham's ngrok account** | see §2.1 — **the main recovery blocker** |

### 2.1 The callback-URL problem (read before finals day)

The callback URL is provisioned **on Anumati's side**, not in our `.env` (`CALLBACK_PUBLIC_URL` is empty on the primary machine). Anumati will only call the static domain above. A teammate therefore has two options:

- **(a)** Use Saksham's ngrok authtoken on their machine (shared through a secure channel), so their ngrok agent can serve the same static domain. The free plan allows **one agent session at a time** — Saksham's ngrok must be stopped first. `[NEEDS RECHECK]` — never tested from a second machine.
- **(b)** Ask Anumati (Kantharaju H G, `kantharaju.hg@perfios-aa.com`) to re-provision callbacks to the teammate's own tunnel URL. Slow; do not depend on this on the day.

**Decide (a) or (b) and test it on the teammate's machine before 29 September.**

### 2.2 `aa-kit\README.md` is out of date

The README in `aa-kit\` predates the working setup: it uses bash syntax, `cloudflared` with a random URL, and `CALLBACK_PUBLIC_URL` in `.env`. **For the demo, follow this runbook, not the README.** (The README was not modified.)

---

## 3 · Repository setup (teammate machine)

All steps untested on a second machine.

```powershell
# 3.1 Get the code
git clone <origin URL> IIMB_DPI          # [NEEDS RECHECK] origin URL — ask Saksham
Set-Location IIMB_DPI
$REPO = (Get-Location).Path
git log --oneline -3                     # expect c4ac9b8 or later at the top

# 3.2 Local-only configuration: .env at the repo root (git-ignored)
Copy-Item aa-kit\.env.example .env
notepad .env                             # fill ANUMATI_CLIENT_ID and ANUMATI_CLIENT_SECRET; save
git status --short                       # .env must NOT appear (it is ignored)

# 3.3 Python environment for the pipeline
Set-Location "$REPO\aa-kit"
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -c "import flask, dotenv; print('pipeline deps ok')"

# 3.4 Java and crypto
java -version                            # must report 21 or newer
Test-Path "$REPO\aa-kit\fiu-crypto-lib.jar"   # expect True; if False, obtain the JAR and put it there (or set $env:CRYPTO_JAR)
java -jar "$REPO\aa-kit\fiu-crypto-lib.jar" --genkey | Out-Null; "crypto jar exit code: $LASTEXITCODE"   # expect 0; do not print or share the key output

# 3.5 ngrok
ngrok version                            # or the full path to ngrok.exe
ngrok config add-authtoken <token>       # only under option (a); type it locally, never paste it anywhere else
```

**Ready when:** `.env` exists and is ignored; `pipeline deps ok` prints; Java is 21+; the JAR exits 0; ngrok runs.

`run_journey.py` loads `.env` with `python-dotenv`, searching upward from `aa-kit\` — a `.env` at the repo root is found ✅ (primary layout). The webhook does not read `.env`.

---

## 4 · E8 execution path (verified on primary, 23 Sep 2026)

Three PowerShell windows:
**A** = webhook (stays running) · **C** = ngrok (stays running) · **B** = everything else.
On the primary machine `$REPO` is `K:\IIMB_DPI`.

### 4.1 Pre-flight: make sure `captures\` has no loose files ✅

`run_journey.py --collect` uses the **latest** `*_data-ready_payload.json` in `captures\` (non-recursive) and **overwrites** `captures\decrypted.json`. Old loose files cause stale data or a misleading `410`.

```powershell
Set-Location "$REPO\aa-kit"
New-Item -ItemType Directory -Force -Path captures | Out-Null
"loose files in captures\: $((Get-ChildItem captures -File).Count)"     # must be 0
# if not 0, archive them into a dated subfolder:
# $a = "captures\archive_$(Get-Date -Format yyyyMMdd_HHmm)"; New-Item -ItemType Directory $a | Out-Null; Get-ChildItem captures -File | Move-Item -Destination $a
```

### 4.2 Window A — start the webhook ✅

```powershell
Set-Location "$REPO\aa-kit"
$env:MODE = 'e8'          # free-text label stamped on every capture; use e.g. 'finals-live' on the day
.venv\Scripts\python.exe webhook_server.py
```
Expect: Flask banner, `Running on http://127.0.0.1:8080`. Leave running.
Known: Windows Firewall may prompt — allowing Private networks is enough.

### 4.3 Window B — local health ✅

```powershell
Invoke-RestMethod http://localhost:8080/health | ConvertTo-Json -Compress
```
Expect `{"captures":0,…,"mode":"e8","ok":true,…}`. **Do not continue unless `captures` is 0.**

### 4.4 Window C — tunnel on the static domain ✅

```powershell
& "$REPO\tools\ngrok.exe" http 8080 --url=https://umbilical-starry-marital.ngrok-free.dev
# teammate machine: use your own ngrok path
```
Expect `Session Status online` and `Forwarding https://umbilical-starry-marital.ngrok-free.dev -> http://localhost:8080`.
**Never start ngrok without `--url`** — a random hostname is not provisioned at Anumati and callbacks will silently never arrive.

### 4.5 Window B — external health ✅

```powershell
Invoke-RestMethod https://umbilical-starry-marital.ngrok-free.dev/health -Headers @{ 'ngrok-skip-browser-warning' = '1' } | ConvertTo-Json -Compress
```
Expect the same JSON as 4.3. The header stops ngrok's free-tier browser warning page from replacing the JSON.

### 4.6 Window B — create the consent ✅

```powershell
Set-Location "$REPO\aa-kit"
.venv\Scripts\python.exe run_journey.py --mobile 9999999999
```
Defaults (from the script): `--purpose 102`, `--fetch-type PERIODIC`, `--fi-types DEPOSIT`. Use these; they are the verified configuration.
Expect (from the code of `run_journey.py`): a JSON block with `moduleReference`, `consentHandle` and `status` (`CONSENT_REQUESTED`), then the line `OPEN THIS, choose ACME Bank, OTP 812093:` followed by the `redirectUrl`. Consent request, consent response and `last_module_reference.txt` are saved to `captures\`. `[Console text itself not captured during E8]`
The script exits early if `ANUMATI_CLIENT_SECRET` is not set.

### 4.7 Browser — approve ✅

1. Open the printed `redirectUrl` **exactly once** (single-use; a second open returns `NO_CONSENT_REQUEST_FOUND`).
2. Choose **ACME Bank**.
3. Enter the UAT default OTP **`812093`**.
4. Approve.

### 4.8 Window B — confirm both callbacks arrived ✅

```powershell
Invoke-RestMethod http://localhost:8080/health | ConvertTo-Json -Compress
```
Expect `"captures":2` with `latest` listing a `…_consent-lifecycle_payload.json` and a `…_data-ready_payload.json` (E8: 4 seconds apart). Window A shows both POSTs with status 200.
**No callbacks within ~60 s of approving → stop.** Check the tunnel (4.5). Do not reopen the redirect link.

### 4.9 Window B — collect and decrypt (single-use) ✅

```powershell
.venv\Scripts\python.exe run_journey.py --collect
```
Expect:
```
using callback <timestamp>_data-ready_payload.json: moduleReference=... sessionCount=7 expiresAt=...
[fetch] raw response saved to ...\captures\<timestamp>_getdata_RAW.json (784762 bytes) status=200
decrypted 7 session(s) -> captures/decrypted.json
```
**Run it once.** Collection is single-use: a second fetch returns `410` and the payload is gone. If decryption fails after the raw file is saved, stop and escalate; do not re-run `--collect`. Collect before `expiresAt` (~15 minutes after data-ready).

### 4.10 Window B — timeline ✅

```powershell
python -B "$REPO\aa-kit\hsl\timeline.py" --data "$REPO\aa-kit\captures\decrypted.json"
```
Expect first lines `INPUT <absolute path>` and `SHA256 <hash>`, then `HOUSEHOLD 916999974812 — 2 members, 2 accounts, 596 transactions`, the baseline lines and dated events (see §5).

### 4.11 Window B — 12 tests ✅

```powershell
$env:HSL_DATA = "$REPO\aa-kit\captures\decrypted.json"; $env:PYTHONPATH = "$REPO\aa-kit\hsl"
python -B -m unittest test_household
Remove-Item Env:HSL_DATA, Env:PYTHONPATH
```
Expect `Ran 12 tests` … `OK`. Without `HSL_DATA` the tests refuse to run (`RuntimeError`) — this is intended.

### 4.12 Recording the run (for the E8 video)

- Start the screen recorder **before 4.6** and stop it after 4.11. Frame windows A, B, C and the browser.
- Before recording: nothing on screen may show `.env`, the client secret, or the ngrok authtoken.
- Save the video **into `aa-kit\captures\`** (git-ignored) so it is sealed with its evidence in 4.13.
- The file name must say it is a recording, e.g. `E8_recorded_2026-09-24.mp4`. A recording is never presented as live.

### 4.13 Seal the run ✅

Stop the webhook (Ctrl+C in A) and ngrok (Ctrl+C in C) first, so nothing new lands in `captures\`.

```powershell
Set-Location "$REPO\aa-kit"
$dst = "captures\run_$(Get-Date -Format yyyyMMdd_HHmm)"
New-Item -ItemType Directory -Path $dst | Out-Null
Get-ChildItem captures -File | Move-Item -Destination $dst
$lines = @(Get-ChildItem $dst -File | Where-Object Name -ne 'MANIFEST.sha256.txt' | Sort-Object Name | ForEach-Object { '{0}  {1}' -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash, $_.Name })
$lines | Out-File "$dst\MANIFEST.sha256.txt" -Encoding ascii
"entries: $($lines.Count)"; Get-Content "$dst\MANIFEST.sha256.txt"
```
List the files **before** writing the manifest (as above) — writing it in the same pipeline makes it try to hash itself.

---

## 5 · Verification checklist

| Check | How | Pass |
|---|---|---|
| Consent created | 4.6 output; `…_consent_request.json` and `…_consent_response.json` in `captures\` | both present |
| `/aa/consent` arrived | `/health` → `latest` contains `…_consent-lifecycle_payload.json`; Window A POST 200 | yes |
| `/aa/data-ready` arrived | `/health` → `latest` contains `…_data-ready_payload.json`; Window A POST 200 | yes |
| Raw response exists and was persisted before processing | 4.9 prints `raw response saved …` **before** `decrypted …`; `…_getdata_RAW.json` present, ~784,762 B | yes |
| Decryption succeeded | `decrypted 7 session(s)` | 7 |
| `decrypted.json` is fresh | `captures\` had 0 loose files at 4.1; `decrypted.json` LastWriteTime is after the data-ready payload's | yes |
| Intended data, not a stale file | timeline header `INPUT` path is the file just written; `SHA256` equals `Get-FileHash` of that file | equal |
| Same corpus as the verified baseline | `SHA256 49248032661E2509D8F98B3ABB4593BCD8F72CB48790DFEE04DF0FA16BB9584D` (three fetches on 23 Sep all produced this) | equal — **if different, the run may still be valid, but do not present it as the verified corpus until the timeline and tests are checked and the difference is understood** |
| Timeline executes | 4.10 prints header and events | yes |
| Tests | 4.11 | 12 OK |

Reference timeline for the verified corpus (key rows): John Sela Sr — two baseline lines (salary ₹36,645, 11 months; LIC ₹1,526, 12 months), no events. Kiran Sela Jr — events in 2025-11, 2026-01, 2026-02, 2026-03, 2026-05 (BENEFIT STOPPED `APBS IOC REF` ₹142; COMMITMENT STOPPED ₹5,006), 2026-06 (COMMITMENT STOPPED `CMS BAJAJ AUTO C D` ₹1,499), 2026-07.

Never commit `decrypted.json`, raw responses, callbacks or videos. `captures/` is git-ignored — keep it that way.

---

## 6 · Security and data handling

- **No secrets in git.** `.env` and `.env.*` are ignored; only `aa-kit/.env.example` (empty secret) is tracked. Run `git status --short` before every commit.
- **No credentials in chat, screenshots, recordings or documents.** Client secret and ngrok authtoken move only through a secure channel.
- **No raw financial payloads in git.** Everything under `captures/` stays local.
- **Raw FI response is persisted before parsing** (`anumati_client.py` saves before `raise_for_status()`). Do not change this.
- **PAN is never a household join key.** Households join on shared holder mobile. In this sandbox father and son share PAN `DRWPG2761P`, which is impossible in reality.
- **Never send the synthetic SELA PAN to Perfios Hub.** Hub queries live government sources; the result would be meaningless or would expose a real stranger's record.
- **No Hub API calls** as part of this runbook. None are needed for the AA demo.
- **Label honestly.** A recording is a recording; sandbox data is sandbox data. One consent (mobile `9999999999`) returns both SELA members — do not describe the demo as two separate consents.
- **Do not edit `hsl\*.py` with PowerShell `Set-Content` / `Out-File`** on Windows PowerShell — it re-encodes UTF-8 and corrupts `·` and `—`. Use an editor that keeps UTF-8, or a Python script.

---

## 7 · Known failure modes (all encountered in this project)

| Symptom | Cause | Fix |
|---|---|---|
| "Consent Rejected by your Institution(s)" | Client defaults: `dataRange.to` in the future; data window > 12 months; consent validity > 1 year | Fixed in code — dates computed from today. If it reappears, it is an integration bug in our client, not a product finding |
| `NO_CONSENT_REQUEST_FOUND` | Redirect link opened a second time (single-use) | Start a new consent (4.6) |
| No callbacks after approval | Tunnel down; ngrok started without `--url` (random hostname); a second ngrok session elsewhere; URL not provisioned at Anumati | Check 4.5; restart ngrok with `--url`; confirm only one ngrok session exists; provisioning is fixed on Anumati's side |
| `no data-ready callback captured yet` | `--collect` ran before the data-ready callback arrived | Wait for 4.8 to show `captures: 2` |
| `--collect` uses an old callback / returns `410` | Loose files from a previous run in `captures\`; or the payload already collected / expired / wrong credentials (`410` does not distinguish) | Always run 4.1 first. Never re-run `--collect` after a success. After `410`, start a new consent |
| Timeline or tests read stale data | Old versions read `decrypted.json` from the working directory | Fixed (commit `03c479f`): tests need `HSL_DATA`, timeline needs `--data`; both fail loudly otherwise |
| `RuntimeError: Set HSL_DATA …` | `HSL_DATA` not set | Set it as in 4.11 |
| `Invoke-RestMethod` returns HTML instead of JSON via ngrok | ngrok free-tier browser warning page | Add header `ngrok-skip-browser-warning: 1` (4.5) |
| Crypto CLI output looks empty or unparsed | ACME returns ReBIT XML as a string inside the JSON `data` field; the CLI stores it as a raw string | Expected. `hsl/household.py` parses the XML |
| Decryption says no private key | `uatKeyMaterial` must be read at the **root** of the get-data response | Handled by `decrypt.py`; if broken, check that `java` works and `fiu-crypto-lib.jar` is found (`CRYPTO_JAR`) |
| `ModuleNotFoundError` (`flask`, `dotenv`, …) | venv not created or dependencies missing | §3.3 |
| `java` not recognised / crypto error | Java missing or older than 21 | Install Java 21+ |
| Garbled `Â·` / `â€”` when viewing source in PowerShell | Display artefact of `Get-Content` on UTF-8 | Harmless; files are intact. Python prints them correctly |

---

## 8 · If Saksham's laptop is unavailable

Pre-requisite, done **before 29 Sep**: the teammate has completed §3 on their machine and resolved §2.1 (ngrok static domain or re-provisioned URL), and has the client secret in their local `.env`.

On the day, in order:

1. `Set-Location <repo>; git pull; $REPO = (Get-Location).Path`
2. Check readiness: `.venv\Scripts\python.exe -c "import flask, dotenv; print('ok')"` (from `aa-kit`), `java -version`, `Test-Path "$REPO\aa-kit\fiu-crypto-lib.jar"`.
3. Clear `captures\` of loose files (4.1).
4. **Window A:** start the webhook (4.2). **Window B:** local health (4.3).
5. **Window C:** start ngrok with `--url` (4.4). Make sure Saksham's ngrok is not running. **Window B:** external health (4.5).
6. Create the consent: `.venv\Scripts\python.exe run_journey.py --mobile 9999999999` (4.6).
7. Open the `redirectUrl` once → ACME Bank → OTP `812093` → approve (4.7).
8. Confirm `captures: 2` (4.8).
9. `.venv\Scripts\python.exe run_journey.py --collect` — **once** (4.9).
10. Timeline (4.10). Tests (4.11).
11. If any step fails and time is short, switch to the E8 video. Do not improvise fixes on stage.

---

## 9 · Maintenance rule

This runbook is a **live operational document through 30 September 2026**.

Whenever any of the following change — paths, dependencies, commands, tunnel configuration, consent configuration, demo procedure, verification criteria, E8 execution steps — **update this runbook in the same commit.** A change to the pipeline without a matching runbook update is incomplete.

Open items to resolve here:
- [x] Dependency list — `aa-kit\requirements.txt` (resolved 23 Sep)
- [x] `fiu-crypto-lib.jar` is tracked in git (verified)
- [ ] Update or retire the stale `aa-kit\README.md` (§2.2)
- [ ] `[NEEDS RECHECK]` origin URL for §3.1
- [ ] `[NEEDS RECHECK]` §2.1 option (a) or (b) chosen and tested on a second machine
- [ ] Full dry run of §8 on a teammate's machine — **not yet done**
