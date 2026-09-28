# Mirror — finals-day operator manual

**FINALS ENVIRONMENT: THIS PREPARED WINDOWS LAPTOP ONLY**

This is the operator manual for Wed 30 Sep 2026, CDPG Stage II finals, IIM Bangalore. It covers one machine: this laptop, with the folders below. It is not a setup guide for any other machine.

| What | Where (checked on this laptop, 28 Sep 2026) |
|---|---|
| Git repository root | `K:\IIMB_DPI` |
| AA kit and the Mirror app | `K:\IIMB_DPI\aa-kit` (every command runs from here) |
| Python (venv, 3.14.0) | `K:\IIMB_DPI\aa-kit\.venv\Scripts\python.exe` |
| Secrets file | `K:\IIMB_DPI\.env`, at the **repo root**, never opened on screen |
| AA crypto library | `K:\IIMB_DPI\aa-kit\fiu-crypto-lib.jar` (SHA-256 starts `6BFD5853`) |
| ngrok | `K:\IIMB_DPI\tools\ngrok.exe`, static domain `umbilical-starry-marital.ngrok-free.dev` |
| Sealed E8 recording | `K:\IIMB_DPI\aa-kit\captures\E8_20260923_recorded\decrypted.json` (SHA-256 starts `49248032`) |
| App state, outside git | `K:\IIMB_DPI_state\mirror\<store>` |
| Backups | `K:\IIMB_DPI_state\backups\` |

**Status tags used below**
- **[VERIFIED]** — observed on this laptop: in a run, in a test, or by reading the installed files on 28 Sep.
- **[FROM CODE]** — what the installed code does, read from the files; not separately observed.
- **[UNVERIFIED]** — not checked. Confirm it before relying on it.

---

## 1 · What Mirror is

**The problem.** A household's costly moments often leave only one trace in its own bank data: a bank charge for a returned premium, or a collection that stopped. The rules that decide what happens next are public — an insurer's grace period, RBI's overdue rule, where a subsidy is routed. The household rarely sees the two side by side.

**Mirror.** With consent through the Account Aggregator, Mirror reads the household's bank data and learns what the household regularly pays and receives. It checks that against published rules.
- When a rule clock may be running, it shows the evidence, the deadline with its "if", and the cheapest fix.
- Where only the household or the institution can know something, it asks.
- Every sentence is labelled observed, rule, our reading, or only-you-can-tell-us.
- It never moves money and never recommends a product.

**What the finals demo shows**
- A live Anumati consent, started from inside the app.
- A single-use fetch, decrypted on this laptop.
- Mirror's reading of the SELA household.
- Two more sandbox situations: NAGARAJ (silent), and NAVEEN (refused as templated).
- Government protections worth checking, including the options explorer.
- A simulated LPG record, labelled as simulated.

**The five labels. Say exactly one about anything on screen.**

| Label | Means | On screen |
|---|---|---|
| **LIVE** | Real traffic to the Anumati UAT sandbox during the session: consent, callbacks, the single-use fetch, decryption | The journey steps; the chip **FETCHED LIVE · <time>** |
| **RECORDED** | The sealed 23 Sep fetch (E8), or a video of an earlier run | The chip **RECORDED E8 · 23 Sep 2026** |
| **REPLAY** | Real fetched data with time replayed: each refresh is an as-of date, capped at 23 Sep 2026 | The chip **REPLAY · as of <date>** |
| **SIMULATED** | A schema-true stand-in, labelled everywhere: the LPG record, and the customer taps the operator makes | The chip **SIMULATED LPG**; SIMULATED RECORD tags |
| **DEMO LOGIN** | A phone-number entry that opens one of three sandbox households. **Not authentication** | The **DEMO · SANDBOX** tag on the phone screen; the chip **DEMO LOGIN** |

---

## 2 · Finals-day quickstart (fresh Windows session)

Open **one** PowerShell window. It becomes Window B later. Run each block and compare the output with the comments. **Do not continue past a mismatch** — go to §8.

```powershell
Set-Location K:\IIMB_DPI\aa-kit
$env:PYTHONUTF8 = "1"

# 1. Paths: expect six lines of True
Test-Path K:\IIMB_DPI\aa-kit\mirror\serve.py, K:\IIMB_DPI\aa-kit\.venv\Scripts\python.exe, K:\IIMB_DPI\.env, K:\IIMB_DPI\aa-kit\fiu-crypto-lib.jar, K:\IIMB_DPI\tools\ngrok.exe, K:\IIMB_DPI\aa-kit\captures\E8_20260923_recorded\decrypted.json

# 2. Python and the venv
.venv\Scripts\python.exe --version                                            # Python 3.14.0
.venv\Scripts\python.exe -c "import flask, dotenv, requests; print('deps ok')"  # deps ok

# 3. Java (must be 21 or newer; PowerShell may show this in red, which is normal)
java -version

# 4. The installed Mirror files and the E8 recording (first 8 characters of each hash)
Get-FileHash mirror\serve.py, mirror\web\app.js, mirror\options.py, fiu-crypto-lib.jar, captures\E8_20260923_recorded\decrypted.json | ForEach-Object { $_.Hash.Substring(0,8) + '  ' + (Split-Path $_.Path -Leaf) }
# expect: 80E44BA1 serve.py · 0F3514A9 app.js · D9CEA8CB options.py · 6BFD5853 fiu-crypto-lib.jar · 49248032 decrypted.json

# 5. Nothing already running: all three lines must print nothing
Get-NetTCPConnection -LocalPort 8787,8080 -State Listen -ErrorAction SilentlyContinue
Get-Process ngrok -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object CommandLine -match 'mirror.serve|webhook_server' | Select-Object ProcessId, CommandLine

# 6. Loose files in captures\ must be 0 before the live run
"loose files in captures\: $((Get-ChildItem captures -File).Count)"
# if not 0, archive them (this moves files; nothing is deleted):
$a = "captures\archive_$(Get-Date -Format yyyyMMdd_HHmm)"; New-Item -ItemType Directory $a | Out-Null; Get-ChildItem captures -File | Move-Item -Destination $a

# 7. Fresh stores: expect False, False
Test-Path K:\IIMB_DPI_state\mirror\finals-live-30sep, K:\IIMB_DPI_state\mirror\finals-fallback-30sep
```

**Notes on the checks**
- **.env:** check it exists; never `Get-Content` it. The pre-flight in §4 reports only "set" or "not set".
- **Java 21+:** the 28 Sep decryption succeeded, so Java is installed **[VERIFIED]**. Today's version number: **[UNVERIFIED]** — the pre-flight re-checks it.
- **Loose files:** on 28 Sep, **4 loose consent files** from 17:05–17:07 IST were in `captures\`. Archive them with step 6.
- **Store names:** `K:\IIMB_DPI_state\mirror\finals-30sep` **already exists**. A stuck run on 28 Sep created it, so **do not use it**. Use `finals-live-30sep` for the live run and `finals-fallback-30sep` for the fallback. Do not launch anything with either name before the demo.

---

## 3 · Three windows

Start them in this order: **A, then C, then B.**

### Window A — webhook

```powershell
Set-Location K:\IIMB_DPI\aa-kit
$env:MODE = 'finals-live'
.venv\Scripts\python.exe webhook_server.py
```

- **Expect** the Flask banner, including `Running on http://127.0.0.1:8080`, and a "development server" warning. The warning is normal. **[VERIFIED 28 Sep]**
- **Leave it running.**
- `MODE` is only a label stamped on each capture.
- The webhook writes each callback's raw body to `captures\` before parsing it.

### Window C — ngrok

```powershell
& "K:\IIMB_DPI\tools\ngrok.exe" http 8080 --url=https://umbilical-starry-marital.ngrok-free.dev
```

- **Expect:** `Session Status online` and `Forwarding https://umbilical-starry-marital.ngrok-free.dev -> http://localhost:8080` **[VERIFIED 28 Sep]**.
- **Always use `--url`.** Without it, ngrok picks a random hostname that Anumati doesn't know, and callbacks silently never arrive.
- Only one ngrok session may run on this account.

### Window B — health checks, then Mirror

```powershell
Set-Location K:\IIMB_DPI\aa-kit
$env:PYTHONUTF8 = "1"
Invoke-RestMethod http://127.0.0.1:8080/health | ConvertTo-Json -Compress
Invoke-RestMethod https://umbilical-starry-marital.ngrok-free.dev/health -Headers @{ 'ngrok-skip-browser-warning' = '1' } | ConvertTo-Json -Compress
```

- **Both must return** JSON with `"ok":true` and `"mode":"finals-live"`.
- **HTML or an error on the second line** means the tunnel is not ready. Do not launch the live run; see §8.

Then launch Mirror:

```powershell
.venv\Scripts\python.exe -m mirror.serve --data captures\E8_20260923_recorded\decrypted.json --store K:\IIMB_DPI_state\mirror\finals-live-30sep --aa-kit K:\IIMB_DPI\aa-kit --callback-health https://umbilical-starry-marital.ngrok-free.dev/health --demo-login --options
```

**Expect these five lines [FROM CODE]:**

```
Gate 7 on: the app opens on the welcome screen; the sealed recording stays one click away
Options on: Ask Mirror's scheme question lists published options within an amount (nothing stored)
Demo login on (DEMO / SANDBOX, not authentication): the app opens on the phone screen; only the AA test customer can start an AA consent
Mirror (Gate 6) · replay of … · household HH-…
open  http://127.0.0.1:8787   (this laptop only; Ctrl+C to stop)
```

- **Keep the fourth line off camera.** It prints an internal household ID.
- **`--data` is the sealed E8 file.** Mirror reads it and never changes it. It is also what the recorded households open.
- **`--options`:** keep this flag only if the options cut rule passed on this laptop (14 + 10 + 10 + 35 + 111 tests). The files are installed with the right hashes **[VERIFIED]**; the Windows test output was not seen here **[UNVERIFIED]**. Without the flag, the app is the verified demo-login build.

---

## 4 · Browser demo — exact click path

Open **a new tab** at `http://127.0.0.1:8787`, at desktop width, so the operator rail on the left is visible. Every launch has its own page token, so a tab from an earlier launch will fail.

| # | Where | Do | Expect |
|---|---|---|---|
| 1 | Operator rail → **Live AA journey** | **Run pre-flight** | Five checks read **Ready**: client secret set · Java 21+ · crypto library · webhook running · tunnel. Pre-flight reads this laptop only; no call to Anumati. If any check is not Ready → golden fallback (§7) |
| 2 | Phone screen (**DEMO · SANDBOX** tag) | Type `9999999999` → **Continue** | "What Mirror will ask for · For ••••••9999" |
| 3 | Consent terms | Read them: purpose 102, deposit data, monthly, 12 months | — |
| 4 | Same screen | **Ask my Account Aggregator** | This makes the one real consent request |
| 5 | Approve on Anumati | **Open Anumati to approve** — **once** | A new tab opens. The button changes to "Opened — finish on Anumati" |
| 6 | Anumati tab | Choose **ACME Bank** | — |
| 7 | Anumati tab | Enter the UAT test OTP `812093`. It is Anumati's published sandbox value; Mirror never sees it | — |
| 8 | Anumati tab | **Approve** | — |
| 9 | Back to the Mirror tab | Switch tabs. Don't reload | — |
| 10 | Mirror tab | Wait. The steps tick off with times: consent callback → data-ready → collected once → decrypted → checked against the sealed recording | ~30 s plus your clicks (28 Sep: 27 s). The check says **new data**: that is expected (§6) |
| 11 | "Mirror has read your household" | **Now: Ctrl+C in Window C (ngrok), then Window A (webhook).** They are not needed any more. **Don't read the callout's second sentence aloud** ("…data stops by early September…" — false for a live fetch; the fix is not installed) | Member cards for John …9741 and Kiran …9648 |
| 12 | Same screen | **See what needs attention** → run the SELA story | Chips: **FETCHED LIVE · <time>**, **REPLAY · as of 28 Aug 2026**, **DEMO LOGIN**. The LIC card for John and Kiran's questions |
| 13 | Operator rail → **Demo login** | **Sign out** | Phone screen |
| 14 | Phone screen | `9999999998` → **Continue** | NAGARAJ opens **directly** (no Anumati): RECORDED, "Nothing needs you" |
| 15 | NAGARAJ | **What we know** → switch on "Check government protections" → **OK — switch on** → **Now** → **Answer this** → **18–40** | Protections worth checking appear |
| 16 | NAGARAJ | **Ask Mirror** → "Which scheme or policy should we take?" → **See what's within an amount** → **₹250**, then **₹500** | ₹250: Within = PMSBY; More than = PMJJBY (₹436); APY needs one more answer. ₹500: PMSBY and PMJJBY both within, **same order**. Nothing is saved |
| 17 | Operator rail | **Sign out** | Phone screen |
| 18 | Phone screen | `9999999997` → **Continue** | NAVEEN opens directly (RECORDED). **Household** tab: the templated-data refusal |
| 19 | (optional) | **Sign out** → `9999999999` → **Continue** | The **same live SELA** reopens. No new consent |

**The SELA story (step 12)** is the path walked on the 28 Sep live fetch, card for card equal to E8 **[VERIFIED — parity check]**:
1. The hero card at 28 Aug. Answer it.
2. Replay to **7 Sep**. Answer "already paid".
3. Switch on government protections.
4. **Household** → **Run the SIMULATED check** ("rerouted"). Say the LPG sentence (§6).
5. Replay to 12 Sep.

The replay cannot go past **23 Sep 2026**. The options explorer has been checked on **E8 only**; on a live-fetched household it is **[UNVERIFIED]**, so show options on NAGARAJ (step 16).

**Never do these**
- **Don't reload, and don't press Back**, from step 4 until "Mirror has read your household" appears (step 11).
- **Never click "Open Anumati to approve" twice, and never reopen the Anumati link** from history or another tab. The redirect is single-use.
- **Never start a consent for `9999999998` or `9999999997`.** They open recorded households only, and the server refuses an AA start for them **[VERIFIED by test]**. `9999999999` is the only number that reaches Anumati.
- **Never run `run_journey.py --collect`** on a consent the app started.

---

## 5 · Live / recorded / replay / simulated matrix

| Part of the demo | LIVE | RECORDED | REPLAY | SIMULATED | Not built (TARGET) |
|---|---|---|---|---|---|
| Consent at Anumati (ACME, OTP, approve) | ✔ started from the app | — | — | — | Production FIU partner |
| Callbacks, single-use fetch, decrypt | ✔ | — | — | — | — |
| The data Mirror reads after a live run | ✔ fetched today | — | — | — | — |
| Time inside Mirror (as-of dates) | — | — | ✔ from 28 Aug, capped at 23 Sep | — | Real monthly refresh |
| The golden fallback (§7) | — | ✔ the sealed 23 Sep E8 fetch | ✔ | — | — |
| NAGARAJ and NAVEEN | — | ✔ from E8 (same sandbox consent) | ✔ | — | Each household consents for itself |
| The customer's taps (answers) | — | — | — | ✔ the operator taps them | Real customers |
| LPG household record | — | — | — | ✔ always | A consenting holder's own LPG ID |
| Phone-number entry | — | — | — | — | Demo login, **not** authentication. Real login is TARGET |
| Options explorer figures | — | — | — | — | Published rules and tables. No LLM; nothing stored |
| Payments | never | — | — | Hand-off text only | Still never executed by Mirror |

---

## 6 · What to say (short, safe wording)

- **Demo login:** "This is a demo login for the sandbox, not authentication. Each demo number opens one sandbox household. In real use each customer identifies through their own Account Aggregator, and each household consents for itself."
- **Live AA consent:** "This is the real Anumati sandbox consent page. The customer approves at the AA, not in our app. Collection is single-use, so the raw response is saved before we parse it."
- **"New data":** "It says new data because the consent asks for the twelve months up to today, so each day's window is different from our 23 September recording. We walked the demo on Monday's live fetch, and it matched the recording card for card."
- **Sandbox fixture:** "The sandbox data is synthetic and re-dated. One consent returned several holders' accounts — a fixture artefact."
- **Three households:** "Three situations from the organisers' own data: SELA gets clocks and questions, NAGARAJ gets silence, and NAVEEN's data is refused as templated."
- **Fetched live vs replay:** "The consent, the callbacks, the fetch and the decryption happened just now. From here, time is replayed through this data."
- **E8 recording:** "RECORDED means our sealed 23 September fetch, labelled on screen."
- **LPG (verbatim):** "We could not perform a successful live lookup because we do not have a valid consenting LPG ID for this household; the simulated record demonstrates the exact downstream product flow."
- **No balance:** "Ranges come from payment outcomes, not a balance figure."
- **No credit-as-income:** "A regular credit, never 'income'."
- **No action execution:** "Mirror never moves money or acts for you. You act through the institution's own channel."
- **Options explorer:** "It lists the published costs of the protections Mirror shows as worth checking, compared one by one with the amount you pick. It doesn't rank them, doesn't pick one, and doesn't save the amount. Only a bank or post office can enrol you."
- **One FIP:** "The sandbox has one bank, ACME. Multiple banks are argued, not shown."

---

## 7 · The golden fallback (the only fallback path)

**Use it when:**
- pre-flight is not all Ready;
- "Still waiting for Anumati" appears (after 90 s);
- "The consent was not approved";
- "The single-use fetch failed (410)";
- "Decryption failed";
- the page breaks.

**Don't improvise a fix on stage.**

1. **Stop everything:** Ctrl+C in **Window C** (ngrok), then **Window A** (webhook), then **Window B** (Mirror).
2. **Window B:** check the port is free.
   ```powershell
   Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue   # must print nothing
   ```
3. **Window B:** relaunch in recorded mode (no network needed).
   ```powershell
   .venv\Scripts\python.exe -m mirror.serve --data captures\E8_20260923_recorded\decrypted.json --store K:\IIMB_DPI_state\mirror\finals-fallback-30sep --demo-login --options
   ```
4. **Browser:** close the old tab, and open a new one at `http://127.0.0.1:8787`.
5. `9999999999` → **Continue**. SELA opens directly with **RECORDED E8 · 23 Sep 2026 · REPLAY · DEMO LOGIN**. Continue from step 12 of §4; steps 13–19 are unchanged.
6. **Say:** "The live link didn't complete, so this is the same app on our sealed 23 September fetch — labelled RECORDED."

**Why this path is trusted.** This recorded launch with `--demo-login --options` is the one used in the Windows options walk on 28 Sep **[VERIFIED — that walk's store exists with SELA and NAGARAJ state]**. It needs no tunnel, webhook, `.env` or Java.

**If the live household has already been read, don't fall back.** It keeps working after ngrok and the webhook are stopped.

---

## 8 · Failure recovery

| Symptom | Check | Command | Retry? | Fallback |
|---|---|---|---|---|
| **Callback timeout.** "Still waiting for Anumati" after 90 s | Is Window C online? Was ngrok started with `--url`? | `Invoke-RestMethod https://umbilical-starry-marital.ngrok-free.dev/health -Headers @{ 'ngrok-skip-browser-warning' = '1' }` | **Don't** reopen the Anumati link. **Don't** start a second consent on stage | §7 |
| **Single-use fetch 410** | — | — | **Never retry the single-use fetch for the same consent.** | §7 |
| **Decryption failed** | The raw response is already saved in `captures\`; look at it after the demo | — | No | §7 |
| **ngrok fails** (offline, `ERR_NGROK_…`, HTML health) | Another ngrok session running? Network up? | `Get-Process ngrok`, then restart Window C with the exact `--url` command | **Once, before** "Ask my Account Aggregator". After the consent has started: no | §7 |
| **Port 8787 in use / two Mirrors** | Windows lets a second Mirror start on the same port, so the browser may be talking to the old one | `Get-NetTCPConnection -LocalPort 8787 -State Listen` · `Get-CimInstance Win32_Process -Filter "Name='python.exe'" \| Where-Object CommandLine -match 'mirror.serve' \| Select-Object ProcessId, CommandLine` | Stop the extra one: Ctrl+C in its window, or `Stop-Process -Id <ProcessId>` for the old one. Then relaunch **once** | §7 |
| **Wrong household on screen** | Header name | Operator rail → **Demo login** → **Sign out**, then type the right number | Yes | — |
| **Browser: "forbidden", buttons do nothing, stale screen** | Is the tab from an earlier launch? | Close the tab; open a new one at `http://127.0.0.1:8787`. **Not** during steps 4–11 of §4 | Yes, outside steps 4–11 | §7 |
| **Pre-flight shows "webhook writes to a DIFFERENT captures folder"** | Window A was started from another folder | Restart Window A from `K:\IIMB_DPI\aa-kit` | Once, before the consent | §7 |
| **"Consent was not approved"** | — | **Back to welcome** in the operator rail | **One** new attempt at most, if time allows | §7 |

---

## 9 · Shutdown

In this order:
1. **Window C (ngrok):** Ctrl+C — as soon as the household is read (§4 step 11).
2. **Window A (webhook):** Ctrl+C.
3. **Window B (Mirror):** Ctrl+C, after the demo.

Then:

```powershell
Get-NetTCPConnection -LocalPort 8787,8080 -State Listen -ErrorAction SilentlyContinue   # must print nothing
Get-Process ngrok -ErrorAction SilentlyContinue                                        # must print nothing

# after a live run: seal its loose capture files with a manifest (moves files; nothing is deleted)
Set-Location K:\IIMB_DPI\aa-kit
$dst = "captures\run_$(Get-Date -Format yyyyMMdd_HHmm)"
New-Item -ItemType Directory -Path $dst | Out-Null
Get-ChildItem captures -File | Move-Item -Destination $dst
$lines = @(Get-ChildItem $dst -File | Where-Object Name -ne 'MANIFEST.sha256.txt' | Sort-Object Name | ForEach-Object { '{0}  {1}' -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash, $_.Name })
$lines | Out-File "$dst\MANIFEST.sha256.txt" -Encoding ascii
"entries: $($lines.Count)"
Get-ChildItem captures\LIVE_*\decrypted.json | Get-FileHash -Algorithm SHA256 | Format-List Hash, Path
```

---

## 10 · Clean rehearsal and reset

- **A fresh store for every run.** Every existing store name is used, including `rehearsal-29sep`, `rehearsal-29sep-b` and `finals-30sep`. For rehearsals, use a time-stamped name:
  ```powershell
  $S = "K:\IIMB_DPI_state\mirror\rehearsal-$(Get-Date -Format yyyyMMdd_HHmm)"; Test-Path $S   # False
  .venv\Scripts\python.exe -m mirror.serve --data captures\E8_20260923_recorded\decrypted.json --store $S --demo-login --options
  ```
  For a live rehearsal, add `--aa-kit K:\IIMB_DPI\aa-kit --callback-health https://umbilical-starry-marital.ngrok-free.dev/health` with Windows A and C running. That makes a **real consent**, so run it only when you mean to.
- **How state is stored.**
  - Each household keeps its own state in its own folder inside the store (`HH-…`).
  - A live-fetched household goes to `<store>\live\<stamp>`.
  - Answers and purposes in one household never touch another.
- **Replay restart.** In a household, **What we know** → **Stop and forget** (it asks twice) → **Restart the replay (demo operator)**. This forgets **that** household's answers only. For a truly clean slate, use a new store instead.
- **What to archive:**
  - loose files in `captures\`, before every live run (§2 step 6);
  - a finished live run's files, sealed with a manifest (§9).
- **What must not be deleted or moved:**
  - `captures\E8_20260923_recorded\`;
  - the `captures\LIVE_*`, `captures\run_*` and `captures\archive_*` folders;
  - `K:\IIMB_DPI_state\backups\`;
  - `K:\IIMB_DPI\.env`;
  - `fiu-crypto-lib.jar`;
  - `K:\IIMB_DPI\tools\ngrok.exe`.
- **Keeping E8 sealed.**
  - Mirror only reads `--data`.
  - Never pass an E8 folder as `--store`. The store belongs under `K:\IIMB_DPI_state\mirror\`, and Mirror refuses any path inside git.
  - Never save anything into `captures\E8_20260923_recorded\`.
  - `run_journey.py --collect` writes `captures\decrypted.json` at the top of `captures\`, **not** into E8. Don't use it on finals day.
  - Check before and after a rehearsal: `(Get-FileHash captures\E8_20260923_recorded\decrypted.json).Hash.Substring(0,8)` must be `49248032`.

---

## 11 · Test commands

**RUN BEFORE FINALS — verification only.** From Window B, with Mirror, the webhook and ngrok **not** running.

```powershell
Set-Location K:\IIMB_DPI\aa-kit
$env:PYTHONUTF8 = "1"
$env:MIRROR_DATA = "K:\IIMB_DPI\aa-kit\captures\E8_20260923_recorded\decrypted.json"
.venv\Scripts\python.exe -m unittest mirror.test_options                  # 14 tests
.venv\Scripts\python.exe -m unittest mirror.test_demo_login               # 10 tests
.venv\Scripts\python.exe -m unittest mirror.test_households               # 10 tests
.venv\Scripts\python.exe -m unittest mirror.test_gate7 mirror.test_gate6  # 35 tests (15 + 20)
.venv\Scripts\python.exe -m unittest mirror.test_mirror mirror.test_batch1b mirror.test_gate23 mirror.test_gate45 mirror.test_batch1c   # 111 tests (16+26+20+34+15)
```

Counts were checked in the test files on 28 Sep. Total: **180**.

**Reading the results**
- **`OK (skipped=…)` with a large skip count** means `MIRROR_DATA` was not set. That is **not a pass**.
- **One skip each in Gate 6 and Gate 7** is their optional browser check skipping itself because Playwright's browser isn't available. Whether it is available on this laptop: **[UNVERIFIED]**.
- **Gate 6 prints one line:** `validation refused the payload: PayloadInvalid: forbidden field(s) ['balance']`. A test causes it on purpose; it is expected.
- **Where the tests run.** They use temporary folders and ports only. They never touch `captures\`, any store in `K:\IIMB_DPI_state`, or the network.

**Pinned to E8 — not live-window tests**
- Every suite above runs against the sealed E8 file. A pass proves the code, not today's live fetch.
- **The HSL tests** (`aa-kit\hsl\test_household.py`, 12 tests, needs `HSL_DATA`) are pinned to E8 by design. On a live fetch they give 11/12, and **that proves nothing**.
- `engine\test_reconcile.py` belongs to a retired thesis and is not part of the finals.

**DO NOT RUN DURING THE LIVE DEMO:**
- no test suite;
- no HSL test;
- no `run_journey.py`;
- no second Mirror.

---

## 12 · Security — do not expose

**Never on screen, in a recording, a screenshot or chat**
- `K:\IIMB_DPI\.env`, and any editor holding it;
- the Anumati client secret;
- the ngrok authtoken, the ngrok dashboard and the ngrok config file;
- the **retrieval secret** in a data-ready callback;
- the raw `*_data-ready_*.json` and `*_payload.json` files;
- `*_getdata_RAW.json`;
- any `decrypted.json` opened as text;
- the webhook's `/captures` page;
- holder mobile numbers, PAN, date of birth or address (the app never shows them; the raw files do);
- internal household IDs (`HH-…`), including Window B's startup banner;
- consent handles and IDs.

**Safe to show**
- The app's screens: they show masked accounts (…9741) and ••••••9999.
- Pre-flight with its Ready checks.
- The consent-terms screen.
- Anumati's page with ACME selected.
- Window A's `POST … 200` lines.
- Window B's `[fetch] … status=200` line.
- The `Get-FileHash` of `LIVE_*\decrypted.json`.
- The health JSON: it shows capture **file names** only.

---

## 13 · Repository map

| Path | What it is | Status |
|---|---|---|
| `aa-kit\mirror\` | The Mirror engine, rulebook (`rules.py`, 2026-09-27), store, contract, language gate, LPG adapter; app server `serve.py`; page `web\`; options explorer `options.py` and `options_rules.py` | BUILT · FINALS |
| `aa-kit\hsl\` | The E7 household engine. Mirror reuses two of its helpers. Frozen | BUILT (frozen) |
| `aa-kit\anumati_client.py`, `run_journey.py`, `webhook_server.py`, `decrypt.py`, `fiu-crypto-lib.jar` | The verified AA pipeline. Mirror imports it unchanged through `--aa-kit` | BUILT · LIVE |
| `aa-kit\captures\` (git-ignored) | `E8_20260923_recorded\` (the sealed reference) · `LIVE_<stamp>\` (fetched live) · `run_*` / `archive_*` (sealed or archived capture files) | RECORDED / LIVE evidence |
| `K:\IIMB_DPI_state\` (outside git) | `mirror\<store>` (app state) · `backups\` | — |
| `engine\` | The retired Payslip–Passbook thesis. Never imported | Frozen |
| Project docs (claude.ai Project "IIM_B_Case", `claude/*.md`) | Guides, runbooks, the warbook; the one-page operator sheet is `claude/finals-day-one-page-runbook.md` | Documentation |

**Not built** (TARGET or FUTURE; never describe them as built):
- a Mirror login, OTP or step-up;
- multi-tenancy;
- a second bank (FIP);
- a live LPG lookup;
- payments;
- messaging;
- voice;
- a production deployment.

**Stale files inside the repo — don't trust them**
- `aa-kit\README.md` (cloudflared and bash era).
- `aa-kit\SHA256SUMS.txt` and `aa-kit\GATE6_GUIDE.md`: Gate 6 package leftovers whose hashes are old.
- `aa-kit\DEMO_RUNBOOK.md` §1, §2.1 and §8: they describe teammate recovery, which is not used.

---

## 14 · Rollback

**Every backup below was checked on this laptop on 28 Sep.** Each block first copies the current files into a rolled-back folder, then restores. Nothing is deleted.

**The quickest rollback of `--options`** needs no file change: launch **without `--options`**. Every screen is then identical to the demo-login build — checked old-versus-new on 28 Sep.

**Options → demo-login** (restores serve 6AEF369A / app 12D9628E):

```powershell
Set-Location K:\IIMB_DPI\aa-kit
$RB = "K:\IIMB_DPI_state\backups\rolled-back-$(Get-Date -Format yyyyMMdd_HHmm)"; New-Item -ItemType Directory -Force "$RB\mirror\web" | Out-Null
Copy-Item mirror\serve.py "$RB\mirror\serve.py"; Copy-Item mirror\web\app.js "$RB\mirror\web\app.js"
Move-Item mirror\options.py, mirror\options_rules.py, mirror\test_options.py "$RB\mirror\"
$BK = "K:\IIMB_DPI_state\backups\demologin-20260928_1749"
Copy-Item "$BK\mirror\serve.py" mirror\serve.py -Force; Copy-Item "$BK\mirror\web\app.js" mirror\web\app.js -Force
Get-FileHash mirror\serve.py, mirror\web\app.js | ForEach-Object { $_.Hash.Substring(0,8) }   # 6AEF369A, 12D9628E
```

Then launch without `--options`.

**Demo-login → household switcher** (31EC47B1 / F962F751). **Not recommended:** it brings back the side panel you rejected.

```powershell
Set-Location K:\IIMB_DPI\aa-kit
$RB = "K:\IIMB_DPI_state\backups\rolled-back-$(Get-Date -Format yyyyMMdd_HHmm)"; New-Item -ItemType Directory -Force "$RB\mirror\web" | Out-Null
Copy-Item mirror\serve.py "$RB\mirror\serve.py"; Copy-Item mirror\web\app.js "$RB\mirror\web\app.js"
Move-Item mirror\test_demo_login.py "$RB\mirror\"
if (Test-Path mirror\options.py) { Move-Item mirror\options.py, mirror\options_rules.py, mirror\test_options.py "$RB\mirror\" }
$BK = "K:\IIMB_DPI_state\backups\households-20260928_1634"
Copy-Item "$BK\mirror\serve.py" mirror\serve.py -Force; Copy-Item "$BK\mirror\web\app.js" mirror\web\app.js -Force
Get-FileHash mirror\serve.py, mirror\web\app.js | ForEach-Object { $_.Hash.Substring(0,8) }   # 31EC47B1, F962F751
```

After this, launch without `--demo-login` and `--options`; those flags no longer exist.

**All the way to the verified Gate 6/7 baseline** (3E7F8F7C / CA88E071):

```powershell
Set-Location K:\IIMB_DPI\aa-kit
$RB = "K:\IIMB_DPI_state\backups\rolled-back-$(Get-Date -Format yyyyMMdd_HHmm)"; New-Item -ItemType Directory -Force "$RB\mirror\web" | Out-Null
Copy-Item mirror\serve.py "$RB\mirror\serve.py"; Copy-Item mirror\web\app.js "$RB\mirror\web\app.js"
foreach ($f in 'options.py','options_rules.py','test_options.py','test_demo_login.py','test_households.py') { if (Test-Path "mirror\$f") { Move-Item "mirror\$f" "$RB\mirror\" } }
$BK = "K:\IIMB_DPI_state\backups\gate7-baseline-20260928_1517"
Copy-Item "$BK\mirror\serve.py" mirror\serve.py -Force; Copy-Item "$BK\mirror\web\app.js" mirror\web\app.js -Force
Get-FileHash mirror\serve.py, mirror\web\app.js | ForEach-Object { $_.Hash.Substring(0,8) }   # 3E7F8F7C, CA88E071
```

**After this:**
- Run the 35 Gate 6+7 tests and the 111 regression tests.
- The finals launch drops `--demo-login` and `--options`. The app opens on the welcome screen, and the three-household sign-out path does not exist.

---

## 15 · Finals morning — one-screen checklist

- □ Laptop charged, and the charger packed
- □ `K:\IIMB_DPI` present (§2, step 1)
- □ venv present; `deps ok`
- □ Java 21+
- □ Crypto jar present (`6BFD5853`)
- □ `.env` present — **not opened**
- □ ngrok executable present
- □ Static ngrok URL ready: Window C shows `Forwarding https://umbilical-starry-marital.ngrok-free.dev`
- □ E8 fallback present (`49248032`)
- □ Port 8787 free (and 8080 before Window A)
- □ Fresh finals store: `finals-live-30sep` and `finals-fallback-30sep` both `False`
- □ One Mirror only
- □ Pre-flight: all five Ready
- □ Browser ready: a new tab at desktop width; the Anumati tab not opened yet
- □ Screen recording ready, started before "Ask my Account Aggregator"
- □ No secrets visible: `.env`, ngrok dashboard and `captures\` closed
- □ Deck open
- □ Fallback path understood (§7): stop C, A, B → recorded launch → new tab → `9999999999`
