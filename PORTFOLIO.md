# PORTFOLIO.md — turning 8 repos into one hireable story

> Purpose: everything needed to present this work for jobs. Case studies,
> copy-paste resume bullets (EN), hub-site blueprint, and the order to
> improve/present projects. Update after every shipped release.

## The positioning (decide once, repeat everywhere)

> **"Systems/backend engineer who ships hardened products end-to-end —
> from threat model to CI to signed releases."**

Every repo proves a slice of that sentence. Lead resumes, READMEs, and the
hub site with it. Do NOT present as "Python dev" or "I also do AI" —
scattered generalists lose to focused specialists with breadth as bonus.

---

## Project case studies

### 1. Battery Music Notifier  ← flagship
`github.com/Saman-ghorayshi/battery-music-notifier` · Python · CF Workers/D1 · Node/Postgres/Redis · PyInstaller · pytest · GitHub Actions

Cross-platform battery alarm + anti-theft system: phone watches its charger,
laptop screams when it's pulled. Works through censored networks (Iran-tested).

- Two live backends behind one API: Cloudflare Worker + D1 **and** a
  self-hostable Node/Postgres/Redis relay with Docker + Render blueprint
- Security pass driven by a written threat model: SHA-256-hashed device
  tokens, single-use rotating pairing codes, per-IP/user rate shields,
  D1-backed global brute-force counter, JSONL audit trail, kill switch
- Hardened against real platform failures found while testing: WMI wedge
  can't freeze it (timeout-wrapped system probes), hung child processes get
  tree-killed, every external call is bounded
- **117 unit tests** + 70 live/adversarial integration tests against staging
  AND prod; CI matrix 3 OSes × Python 3.9–3.13; tagged v2.0.0 releases with
  signed-off build pipeline producing a Windows exe

Resume bullets:
```
• Designed and shipped a cross-platform alerting product (Windows/Linux/Termux)
  with two interchangeable backends behind an identical API; released as
  tagged versions via CI-built installers.
• Implemented a defense-in-depth security layer: hashed-only credential
  storage, rotating pairing tokens, layered rate limiting incl. a D1-backed
  global counter defeating per-isolate cap evasion, and a JSONL audit trail.
• Raised reliability under hostile conditions: bounded subprocess execution,
  WMI-failure-resistant platform probes, and a 120 s per-test ceiling that
  surfaced 5 real defects pre-release.
```

### 2. Sentinel — autonomous DeFi position keeper
`github.com/Saman-ghorayshi/keeperhub-sentinel` · Python · MCP · Web3 · x402

Two cooperating agents keep an Aave V3 loan alive autonomously: intent-hash
committed before execution, verified after; policy gates; gas-cost-optimized
action selection; shared append-only audit trail; x402 pay-per-run endpoint.

- 68-test suite green; onchain proof transactions on Sepolia
Improvements queued: CI badge + coverage report; dependency pinning; audit →
SQLite view; top-of-README GIF.

### 3. text-steganography
`…/text-steganography` · Python · JS (WebCrypto) · Pillow
Five stego methods (zero-width, SNOW whitespace, PNG LSB, WAV LSB, frame
sequence) + password encryption + live browser demo. **142 tests green.**
Queued: chi-square detector (honest steganalysis), PBKDF2 upgrade.

### 4. WhaleSignal 🐳
`…/whalesignal` · CF Workers ×3 · D1/KV/Queues · Gemini Flash
AI-interpreted whale alerts to Telegram, 100% free tier, 108/108 node tests.
**Gap: never deployed.** Ship = wizard + deploy_all + webhook + screenshots.

### 5. undetect
`…/undetect` · Python · PIL/numpy/scipy
Degrades AI-image detection signatures (metadata strip, DCT band attack,
grain). Verified flips vs DeepAI detector w/ PSNR numbers. Queued: batch
gallery page.

### 6. regexgen *(GitHub only — not cloned locally)*
x402-paid natural-language→regex API. Queued: port Flask→CF Worker to match
the ecosystem story.

### 7. Employee Attrition ROI Optimizer
ML profit-threshold optimization (LR+SMOTE+SHAP). Queued: FastAPI /predict
service + Docker to convert notebook → engineering.

### 8. Entropy Engine
C++20 water-sort solver + raylib visualizer; A* with state canonicalization.
Queued: admissible-heuristic toggle, pin raylib tag, release binaries.

---

## Suggested presentation order

WhaleSignal deploy → Sentinel polish → steg detector → undetect gallery →
attrition service → entropy binaries → regexgen port. (Battery is done.)

---

## Hub site blueprint (`samanghorayshi.dev` or Netlify)

Static Vite+React+TS, Tailwind, deployed Netlify. No backend.

Pages:
1. **Hero**: positioning line + two CTAs (View work · Download flagship)
2. **Projects grid**: 8 cards — GIF/screenshot, stack chips, one metric each,
   links: Live demo | Repo | Case study
3. **Case studies** (3 deep pages): Battery · Sentinel · steg — problem,
   architecture sketch, incidents-and-fixes narrative, test counts
4. **Skills ↔ evidence table**: every claim maps to a repo section link
5. Contact + resume PDF download

Deploy: Netlify drag-drop or connect repo. Add Cloudflare Web Analytics
(free, cookieless) — matches your privacy stance everywhere else.

---

## Resume bullets master list (copy-paste)

See project sections above. Cross-cutting bullets worth adding:

```
• Ran adversarial integration suites against production deployments and used
  findings to ship hardening (global rate counters in D1, request-body
  draining to prevent TCP stalls, circuit breakers around OS services).
• Established supply-chain hygiene: lockfile installs, secret-scan pre-commit
  hook, npm/pip audit CI job, least-privilege API tokens.
```

---

## Next actions checklist

- [ ] Push battery repo + tag v2.0.0 (LAUNCH_RUNBOOK §2–§4)
- [ ] Record demo GIF (RUNBOOK §7)
- [ ] Deploy relay-node publicly (RUNBOOK §6)
- [ ] Deploy WhaleSignal (its PLAN says wizard + deploy_all)
- [ ] Clone regexgen locally (github.com/Saman-ghorayshi — not on disk)
- [ ] Build hub site skeleton (one evening)
- [ ] Fill hub project cards from case studies above
