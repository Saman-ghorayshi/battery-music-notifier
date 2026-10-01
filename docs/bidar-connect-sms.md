# BIDAR Connect — Full SMS Architecture Spec

> Version 1.0 · Status: DRAFT for implementation
> Repo: battery-music-notifier · Product line: BIDAR
> Goal: **the user never touches the phone.** The laptop becomes a complete
> SMS client — read, triage, reply, manage — with a pluggable backend that
> ends in a SIM card on the desk and no phone at all.

---

## 0. Product thesis

KDE Connect stopped at mirroring and now filters bank codes out. Phone Link
requires a Microsoft account, Play Services, and their cloud. Nobody sells
"your SIM, no phone." BIDAR Connect is a LAN-first, account-free, E2E-when-
remote SMS client whose backends graduate from *phone untouched* → *phone as
a modem in a drawer* → *no phone, a $12 modem on the desk*.

Safety features remain free forever. Convenience monetizes (Pro).

---

## 1. System overview

```
┌────────────────────────────── LAPTOP ───────────────────────────────┐
│  GUI (pywebview, existing)  ── new "Messages" tab                   │
│  SmsClient (new module battery_notifier/sms_client.py)              │
│    · SQLite store (source of truth for the UI)                      │
│    · Backends: PhoneMirrorBackend · PhoneModemBackend ·             │
│                ModemDockBackend (pyserial AT)                        │
│    · Transports: LAN socket (primary) · CF relay (E2E only)         │
└──────────────┬───────────────────────────────┬──────────────────────┘
               │ SmsGateway protocol v1        │
        ┌──────┴──────┐                 ┌──────┴──────┐
        │   PHONE     │                 │  SIM DOCK   │
        │ Mode A mirr.│                 │ SIM7600/A76 │
        │ Mode B modem│                 │ USB dongle  │
        └─────────────┘                 └─────────────┘
```

**Rule #1 — the UI never knows the backend.** Every backend implements the
same five operations: `backfill()`, `events()`, `send()`, `mark_read()`,
`delete_thread()`. Capability differences are advertised in `HELLO`.

**Rule #2 — SMS/calls never transit the Cloudflare relay in plaintext.**
LAN-direct is the primary transport. Remote transit uses end-to-end
encryption (§6). The worker stores ciphertext only.

**Rule #3 — OTP codes are stripped before any AI or relay sees them (§7).**

---

## 2. SmsGateway protocol v1

Transport framing (LAN): existing TCP socket server, new port **8100** to
keep guard traffic (8000) and message traffic separated. Length-prefixed
JSON frames: `4-byte big-endian length + UTF-8 JSON`. Same envelopes are
carried over the relay inside E2E boxes (§6.3).

### 2.1 Envelopes

```jsonc
// HELLO — first frame both ways; advertises capabilities
{"t":"hello","proto":1,"role":"backend"|"client",
 "caps":{"backfill":true,"send":true,"mark_read":false,"delete":false,
         "calls":true,"mode":"mirror"|"default_app"|"modem",
         "max_backfill":5000}}

// BACKFILL REQ → RESP (paged)
{"t":"sms.backfill.req","since":0,"limit":500}
{"t":"sms.backfill.resp","page":1,"pages":7,"msgs":[ /* §2.2 rows */ ]}

// EVENT — backend → client push (new/changed rows, calls)
{"t":"sms.event","kind":"received"|"sent"|"status"|"read_changed",
 "msg":{ /* row */ }}
{"t":"call.event","kind":"ringing"|"ended"|"missed",
 "call":{"number":"+98912...","name":"Mom","ts":1690000000,
         "state":"incoming"}}

// SEND — client → backend, status returns as sms.event(kind=sent|status)
{"t":"sms.send.req","ref":"cli-uuid-1","to":"+98912...","body":"سلام"}
{"t":"sms.send.ack","ref":"cli-uuid-1","accepted":true}

// WRITE OPS — only when caps.mark_read / caps.delete are true
{"t":"sms.mark_read","ids":[123,124,125]}
{"t":"sms.thread.delete","thread_id":17}

// HEARTBEAT
{"t":"ping"} / {"t":"pong"}
```

### 2.2 Message row schema (backend-canonical)

```jsonc
{"sms_id":12345,            // provider _id or modem storage index
 "thread_id":17,
 "address":"+989121234567", // normalized E.164 where possible
 "date":1690000000,         // epoch seconds (provider ms /1000)
 "date_sent":1690000000,
 "type":"in"|"out"|"draft"|"failed"|"queued",
 "read":false,
 "sub_id":0,                // dual-SIM slot, 0 if unknown
 "body":"رسید شد",
 "backend":"mirror"|"default_app"|"modem"}
```

Normalization rules: `type` maps Android provider ints
(1=in,2=sent,3=draft,4=outbox,5=failed,6=queued). Persian addresses come
as-is from PDU (§5.4). Unknown fields must be ignored by both sides
(forward compatibility).

### 2.3 Resync semantics

Client keeps a **high-water mark** (`meta.sms_hwm` = max `date`+`sms_id`
tuple seen). On reconnect: `backfill.req since=hwm`, then drain events.
Events are idempotent — the client upserts by (`backend`,`sms_id`).
This survives laptop sleep, Wi-Fi flaps, and backend restarts without
full resyncs. Full resync is a user-triggered repair action.

---

## 3. Backend A — PhoneMirror (main phone, zero friction)

**Status quo of the phone is untouched.** No default-app switch.

| Capability | Detail |
|---|---|
| Backfill | `content://sms` query, projection `_id,thread_id,address,date,date_sent,type,read,body,sub_id`, ORDER BY date DESC, paged by `limit` |
| Live events | (a) `ContentObserver` on `content://sms` (poll-on-change), (b) `NotificationListenerService` as *hint* only — **Android 15+ may hide sensitive bodies** there, so the observer is authoritative and the listener merely triggers a re-query |
| Send | `SmsManager.sendTextMessage()` with `SEND_SMS`; sent/delivered `PendingIntent`s become `sms.event(kind=sent/status)` |
| mark_read | ❌ needs default-app (§4) |
| delete | ❌ |
| Calls | `READ_PHONE_STATE` + `PhoneStateListener` (or `TelephonyCallback`) for ringing; `CALL_LOG` content provider for missed list |

Permissions asked in-context (onboarding trust pattern, same as camera):
`READ_SMS` "so the laptop can show what you haven't read", `SEND_SMS`
"so you can reply from the laptop", `READ_PHONE_STATE` "so you see who's
calling while the phone is across the room".

**Upgrade path:** the app detects mirror mode and offers Tier B with one
button (§4.4) — capability, not dead end.

---

## 4. Backend B — PhoneModem (default SMS app; full control)

### 4.1 What switching unlocks

- `SMS_DELIVER_ACTION` broadcast — **handler-only, full text, ordered,
  immune to the Android-15 sensitive-content hiding** that breaks
  notification-listener designs. We are the mailman, not a listener.
- Write access to `content://sms`: mark-read, delete threads, insert
  outgoing rows (so the phone's own view stays consistent).
- The physical phone becomes a modem in a drawer: plugged in, our
  foreground service running, user never touches it.

### 4.2 Manifest requirements (verify against current AOSP docs at
implementation time — one-hour check flagged in §12)

```xml
<uses-permission android:name="android.permission.RECEIVE_SMS"/>
<uses-permission android:name="android.permission.SEND_SMS"/>
<uses-permission android:name="android.permission.READ_SMS"/>
<uses-permission android:name="android.permission.RESPOND_VIA_MESSAGE"/>
<uses-permission android:name="android.permission.BROADCAST_SMS" tools:ignore="ProtectedPermissions"/>
<uses-permission android:name="android.permission.BROADCAST_WAP_PUSH" tools:ignore="ProtectedPermissions"/>

<receiver android:name=".sms.SmsDeliverReceiver" android:exported="true"
          android:permission="android.permission.BROADCAST_SMS">
  <intent-filter><action android:name="android.provider.Telephony.SMS_DELIVER"/></intent-filter>
</receiver>
<service android:name=".sms.RespondViaMessageService"
         android:permission="android.permission.SEND_RESPOND_VIA_MESSAGE"
         android:exported="true">
  <intent-filter><action android:name="android.intent.action.RESPOND_VIA_MESSAGE"/></intent-filter>
</service>
```

A minimal Compose viewer activity exists so the phone is never a black
hole if someone opens it directly.

### 4.3 Requesting default status

`Telephony.Sms.Intent.ACTION_CHANGE_DEFAULT` + `EXTRA_PACKAGE_NAME` after
in-context explanation. Mirrors the onboarding trust copy: *"Make BIDAR
your SMS handler so the laptop can mark messages read and manage threads.
You can switch back any time in Settings."*

### 4.4 What the phone loses (the honest fine print)

- **RCS.** Google Messages owns RCS only-when-default; switching drops
  the phone to plain SMS/MMS. In Iran (SMS-first) this costs nothing;
  globally it's the printed caveat.
- MMS receive stays best-effort v1 (WAP-push declared, decode later).
- Dual-SIM: `sub_id` carried end-to-end; send uses default subscription
  v1, per-SIM selection is v1.1.

---

## 5. Backend C — SIM Dock (no phone at all)

### 5.1 Hardware

| Item | Choice | Cost |
|---|---|---|
| USB dongle (start) | SIM7600CE / A7670E dongle | ~$10–15 |
| Standalone product | LilyGO T-A7670E (or T-SIM7600) + 18650 + shell | ~$22 BOM |
| Antenna | LTE whip + u.FL | included/+$2 |
| SIM | user's existing | — |

The dongle plugs into the laptop → **no firmware needed**; the laptop
daemon speaks AT over serial. The standalone board is a later SKU that
forwards via Wi-Fi through the relay (E2E §6.3) so SMS arrives while the
laptop sleeps — buffered in the worker mailbox, delivered on wake.

### 5.2 Modem session (pyserial, 115200 8N1)

```
AT+CPIN?            → +CPIN: READY        (SIM present)
AT+CMGF=0           → OK                  (PDU mode — required for Persian)
AT+CSCS="UCS2"      → OK                  (charset for addrs/text in hex)
AT+CNMI=2,2,0,0,0   → OK                  (route incoming SMS as +CMT URC)
AT+CMGL=4           → PDU list (backfill) 4 = all, unread first is 2/3
AT+CMGR=<idx>       → read one
AT+CMGS=<len>       → send (PDU supplied on prompt, Ctrl-Z)
AT+CMGD=<idx>       → delete
```

Incoming URC: `+CMT: ,<len><CR><LF><PDU>` → decode → `sms.event`.

### 5.3 Daemon design (`battery_notifier/sms_modem.py`)

- Serial reader thread parses URCs asynchronously; command queue with
  lock so CMGS sequences never interleave.
- Watchdog: modem silence > 30 s → `AT` ping ×3 → port re-enumeration
  and session re-init; capability bit `modem.online` in HELLO reflects it.
- Storage: the modem/SIM hold ~20 messages; the daemon drains on
  connect and treats the laptop SQLite as the archive (delete-on-read
  from modem storage after safe insert).

### 5.4 PDU codec (pure module `battery_notifier/sms_pdu.py`)

Deliver-PDU parse and Submit-PDU build, GSM 7-bit packing and **UCS2**
(Persian), TP-MTI/VPF first-octet handling, timestamps (SCTS, incl.
timezone quarter-hours), concatenated-SMS UDH reassembly (8-bit and
16-bit reference) — long Persian messages are multi-part UDH in the wild;
without reassembly the feature is unusable. 100% JVM-style unit-tested
against known-good PDU vectors (§10).

---

## 6. Security architecture

### 6.1 Transport policy

1. **LAN-direct is primary.** Messages, calls, presence — socket 8100,
   same Wi-Fi, nothing leaves the room.
2. Relay transit is used only when LAN is impossible (dock off-LAN,
   phone on cellular) and **only inside E2E boxes**.

### 6.2 Key establishment — rides the existing pairing ceremony

The laptop's `pair` QR already exists. Extend the payload version:

```
BMN1|<relay>|<code>                      (existing, unchanged meaning)
BMN2|<relay>|<code>|<x25519-pub-or-prekey-b64>   (adds channel key)
```

Derivation: X25519 ECDH (laptop ephemeral × phone prekey) → HKDF-SHA256
(32 bytes, info `"bidar-sms-v1"`) → libsodium `secretbox` key. Phone
stores its private half in EncryptedSharedPreferences (already in the
app). Laptop persists in DPAPI (`config.toml` secret fields — mechanism
already shipped). BMN1 falls back to LAN-only mode (no key, no relay SMS).

### 6.3 Relay envelope (new worker endpoints)

```
POST /api/sms/up    {"box":"<b64 secretbox(nonce||ct)>"}   → stored, TTL 7d
GET  /api/sms/down  {"boxes":[...]}                        → drained
```

- Boxes addressed by account token-hash pair; server sees sizes and
  timing only. No plaintext, no metadata fields beyond TTL.
- Key rotation = re-run QR pairing (BMN2). Ciphertext versioned
  (`CRY1:` prefix) so algorithms can change without orphaning old boxes.
- Rate limits mirror the existing per-user buckets; box cap 8 KB
  (SMS is tiny; UDH-reassembled longs still ≪ 8 KB).

### 6.4 Threat notes (for the README's trust section)

- Cloudflare operator (us) cannot read messages: E2E, keys never on worker.
- Stolen laptop: keys are DPAPI-bound — a thief gets ciphertext.
- Stolen phone: EncryptedSharedPreferences + no UI path to export keys.
- LAN attacker: sees framing, not content (secretbox everywhere
  including LAN when a key exists — cheap and uniform).

---

## 7. OTP redaction engine (`battery_notifier/redact.py` + phone twin)

**Runs before AI, before relay, before any logging.** Order matters: it
is the innermost filter.

Patterns (extendable, unit-tested §10):
- Keyword-triggered numeric codes: `\b\d{4,8}\b` within a window of
  `code|otp|verify|pin|کد|تایید|اعتبارسنجی|رمز` (case-insensitive, fa/en)
- Card numbers: 16 digits, grouped `1234-5678-...` → mask to last 4
- Iranian national ID: 10 digits with checksum validation
- URLs with token query params → strip query
- 2FA app seeds: `otpauth://` lines removed entirely

Output shape: `{"safe_text": "...", "redactions": [{"kind":"otp","at":42}]}`.
The AI Digest consumes `safe_text` only. The *unredacted* text still
displays locally to the user (it's their message) — redaction governs
what LEAVES the device.

---

## 8. Laptop client

### 8.1 Store (SQLite, `~/.config/battery-music-notifier/sms.db`)

```sql
CREATE TABLE contacts(number TEXT PRIMARY KEY, name TEXT, photo BLOB);
CREATE TABLE threads(thread_id INTEGER PRIMARY KEY, number TEXT,
  last_ts INTEGER, unread INTEGER DEFAULT 0, snippet TEXT,
  backend TEXT);
CREATE TABLE messages(id INTEGER PRIMARY KEY,  -- rowid
  backend TEXT, sms_id INTEGER, thread_id INTEGER, address TEXT,
  date INTEGER, date_sent INTEGER, type TEXT, read INTEGER,
  sub_id INTEGER, body TEXT,
  UNIQUE(backend, sms_id));
CREATE TABLE calls(id INTEGER PRIMARY KEY, number TEXT, name TEXT,
  ts INTEGER, kind TEXT);   -- ringing|ended|missed
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
   -- sms_hwm, backend_mode, last_resync...
```

### 8.2 UI — "Messages" tab in the existing GUI

- **Triage view (default):** unread-first cards — sender, time, snippet,
  [Reply] inline. This is the KDE-Connect-killing screen.
- **Threads view:** standard two-pane conversations, mark-read on open
  (Tier B/C), delete thread (Tier B/C), search.
- **Calls strip:** recent + missed, heads-up toast on `call.event`.
- **Backend badge:** mirror / modem / dock + online dot; one-click
  "upgrade to full control" when mirror is active.
- Wire via the existing `Bridge` js_api pattern (`get_threads`,
  `get_messages`, `send_sms`, `mark_read`, `get_calls`, `get_backend`).

### 8.3 Services

- `SmsClient` thread: owns transport + store, exposes the bridge API.
- Auto-start with the GUI (manager `auto_start` — same hook as relay).
- Offline behavior: full local read; sends queue in `type=queued` and
  flush on transport return (status events reconcile).

---

## 9. Phone app additions

| Piece | Notes |
|---|---|
| `SmsGatewayService` (foreground) | Owns observer/deliver-receiver registration, socket client to laptop (discovery: existing mDNS/UDP beacon + ADB bridge fallback) |
| `SmsDeliverReceiver` | Tier B: authoritative incoming path → store-or-forward |
| `RespondViaMessageService` | Tier B requirement; quick-reply intent |
| Messages viewer (Compose) | Minimal threads list + conversation; the laptop is the main UI |
| Permissions onboarding cards | Trust copy per permission, existing pattern |
| Settings toggle | "SMS backend: Mirror / Full (make default)" with the RCS tradeoff explained |

---

## 10. Testing strategy

- **PDU codec:** pure-Python unit tests against published PDU vectors
  (GSM7 + UCS2 + UDH multipart + timestamps). This module has zero
  device dependency — it must be 100% covered.
- **Redaction engine:** golden tests with real-world fa/en OTP formats,
  card numbers, national IDs.
- **Gateway protocol:** socket-pair integration tests in-process
  (fake backend ↔ SmsClient), incl. reconnect-resync and idempotent
  upserts.
- **E2E:** round-trip tests (PyNaCl encrypt → worker envelope shape →
  decrypt), key-derivation from BMN2 QR vector.
- **Modem:** emulator harness — a fake serial endpoint scripted with AT
  sequences incl. `+CMT` timing races and watchdog kill.
- **Device:** on the real phone — Tier A first (safe), then Tier B with
  the default-app switch flow recorded as evidence, then dongle day.

## 11. Monetization mapping

| Feature | Tier |
|---|---|
| Mirror (A) + full control (B) + calls | **Free** (safety-adjacent, adoption engine) |
| AI digest & drafts (on redacted text) | Pro |
| Modem daemon (C) | Pro |
| History beyond 24h on relay mailboxes | Pro |
| SIM Dock hardware | SKU, ships with Pro-for-life |

Pricing unchanged: ~$12 one-time / ~$4·yr; USDT + card-to-card.

## 12. Implementation-time verifications (do before/at Sprint 2 & 3)

1. Re-verify default-SMS manifest/service requirements against current
   AOSP docs (receiver actions, permissions, RESPOND_VIA_MESSAGE shape).
2. Confirm `TelephonyCallback` vs deprecated `PhoneStateListener` for the
   phone's Android level.
3. Dongle AT dialect: SIM7600 vs A7670 `CNMI`/`CMGL` quirks — probe at
   first plug, keep per-modem profiles.
4. MIUI: verify `SMS_DELIVER` is not throttled for a sideloaded default
   app (expected fine — it's handler-path, not background).

## 13. Build plan (acceptance criteria per sprint)

**Sprint 1 — Mirror end-to-end (week)**
LAN framing + protocol v1; SQLite + Messages tab (triage + threads +
reply); phone Tier A (observer + send + calls). ✅ = reply from laptop
lands on a real phone; unread-only view correct after 100-msg backfill;
reconnect resyncs without duplicates.

**Sprint 2 — Full control (week)**
Tier B default-app mode (DELIVER receiver, mark-read/delete from laptop,
minimal phone viewer); E2E (BMN2 pairing, secretbox envelopes, relay
mailboxes). ✅ = mark-read on laptop clears phone badge; message via relay
is unreadable in worker logs; RCS tradeoff shown before switch.

**Sprint 3 — The dock (week + shipping)**
PDU codec + modem daemon + USB dongle support. ✅ = SIM out of phone,
into dongle: send/receive Persian SMS fully from laptop with the phone
powered off. Order the dongle on day one — shipping is the long pole.

**Then:** AI digest on redacted text → Pro tier live → standalone dock
board as the second BIDAR hardware SKU.

---

*Fine print, printed on the box and the README: BIDAR reduces risk and
saves you reaching for the phone; it does not guarantee delivery of any
message, cannot place emergency calls from the laptop, and — in Tier B —
replaces RCS with SMS. Safety features are free forever.*
