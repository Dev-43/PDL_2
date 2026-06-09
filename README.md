# BehaviorShield — Behavioral Malware Detection System

**Version:** v2.0 (Submission-Ready)
**Platform:** Windows 10/11 (primary) + Ubuntu 20.04+ (logger only)
**Python:** 3.9+
**ML Model:** Isolation Forest — trained on normal Windows process behavior

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the logger (Windows — run as Admin, or use install_windows.bat)
Logger\logger.exe --db "C:\ProgramData\SysLogger\logs.db"

# 3. Start the frontend (auto-detects DB path)
python main.py

# 4. Or point at a custom DB
python main.py --db "C:\ProgramData\SysLogger\logs.db"
python main.py --db ./logs.db          # for testing with local DB
```

---

## Project Structure

```
BehaviorShield/
│
├── main.py                         Entry point
├── requirements.txt
├── install_windows.bat             One-click Windows installer
├── whitelist.txt                   Trusted process names (auto-created)
├── warning_history.csv             Audit log (auto-created, never deleted)
│
├── core/
│   ├── engine.py                   DB reader + feature engineering + ML scoring
│   └── worker.py                   Background QThread — polls DB every 1s
│
├── ui/
│   ├── theme.py                    All colors, fonts, global stylesheet
│   ├── main_window.py              Main window — wires tabs + worker + tray
│   ├── tab_dashboard.py            Tab 1: metric cards + process table + FP queue
│   ├── tab_graphs_history.py       Tab 2: live graphs  |  Tab 3: warning history
│   └── warning_popup.py            Threat alert popup (non-blocking)
│
├── ml/
│   ├── anomaly_model.pkl           Trained Isolation Forest model
│   └── score_params.json           Score normalization parameters
│
└── Logger/                         C++ logger source
    ├── main.cpp                    Entry point (1s interval, batch writes)
    ├── Shared.hpp                  ProcessLog struct (+ exePath field)
    ├── Database.hpp                SQLite writer (WAL + transactions)
    ├── ProcessMonitor.hpp          Base class
    ├── ProcessMonitor_Win.hpp      Windows implementation (optimized <1% CPU)
    ├── ProcessMonitor_Lin.hpp      Linux implementation
    ├── sqlite3.h / sqlite3.c       SQLite amalgamation (no external deps)
    ├── install_windows.bat
    └── install_linux.sh
```

---

## How It Connects

```
C++ Logger (background service)
    │
    └── writes every 1s ──► logs.db (SQLite, WAL mode)
                                │
                    ┌───────────┴───────────┐
                    │                       │
            Python Frontend          ML Pipeline
            (reads every 1s)    (trained offline on logs.db)
               │
               ├── Feature Engineering (30s windows)
               ├── Isolation Forest scoring (ml/anomaly_model.pkl)
               ├── Heuristic signals (human-readable cause)
               └── UI: Dashboard + Live Graphs + History
```

The **only coupling** between all components is the file path to `logs.db`.
No sockets, no network, no IPC required.

---

## ML Model — Isolation Forest

### Why Isolation Forest with only normal data?

You currently have ~3.87 million rows of normal Windows process behavior.
Isolation Forest is the correct algorithm here — it learns what **normal looks like**
and flags anything significantly different as anomalous.

This is exactly how commercial tools (CrowdStrike, SentinelOne) start:
establish a behavioral baseline, then flag deviations.

### How it works

1. Feature extraction: 14 features per process per 30-second window
   (RAM avg/max/variance/growth, CPU avg/max/variance, net sent/recv,
   connections, thread count, handle count, elevation status)

2. Isolation Forest: trained on 200,000 rows from your `logs.db`
   — 100 trees, 5% contamination assumption

3. Scoring: raw `decision_function` score normalized to `[0.0, 1.0]`
   where `0.0 = perfectly normal`, `1.0 = highly anomalous`

4. Final risk score: **70% ML + 30% heuristic** — blended for robustness

### Risk thresholds

| Score     | Verdict    | Action                              |
|-----------|------------|-------------------------------------|
| ≥ 0.95    | HIGH RISK  | Warning popup (interrupt alert)     |
| 0.70–0.95 | HIGH RISK  | Confirmation queue + red table row  |
| 0.40–0.70 | SUSPICIOUS | Amber highlight in table            |
| < 0.40    | BENIGN     | Normal display                      |

### Adding malware data later (Phase 2)

When you have malware samples, replace the Isolation Forest with a
Random Forest classifier:

```python
# In core/engine.py, replace ml_anomaly_score() with:
import joblib
model = joblib.load("ml/supervised_model.pkl")
score = float(model.predict_proba([feature_vector])[0][1])
```

---

## Logger Optimizations (v2.0)

The logger was using **~15% CPU**. It now uses **< 1%**. Changes made:

| Change | Effect |
|--------|--------|
| `SetPriorityClass(BELOW_NORMAL_PRIORITY_CLASS)` | Logger yields to foreground apps |
| `ConnectionCache` — TCP table rebuilt every 5s, not per-process | ~80% CPU reduction alone |
| Batch DB writes: 5 captures → 1 `BEGIN/COMMIT` transaction | ~90% fewer disk writes |
| `PRAGMA journal_mode=WAL` + `synchronous=NORMAL` | Non-blocking writes |
| `PRAGMA cache_size=-8000` (8MB) + `mmap_size=64MB` | Fast repeated reads |
| `PROCESS_QUERY_LIMITED_INFORMATION` instead of full access | Fewer kernel calls |
| `GetProcessHandleCount()` instead of full handle enumeration | Lightweight |
| Timestamp index on `logs` table | Fast time-range queries from Python |
| Sleep interval: **1 second** (was 3s) | More granular detection |

---

## Frontend Optimizations (v2.0)

| Change | Effect |
|--------|--------|
| `antialias=False` in pyqtgraph | Biggest speed win on non-GPU machines |
| numpy ring-buffers instead of `list.pop(0)` | O(1) chart append, no copy |
| `disableAutoRange()` on all chart ViewBoxes | No Y-axis recalculation per push |
| `MAX_POINTS = 60` (was 120) | Half chart data → 2× faster redraws |
| `setUpdatesEnabled(False/True)` around table bulk updates | No mid-fill redraws |
| UI signal throttle: graphs update at most every 1s | Prevents Qt flood |
| Skip chart redraw if value unchanged (< 0.05 delta) | Avoids redundant GPU calls |

---

## Default DB Paths

| Platform | Path |
|----------|------|
| Windows  | `C:\ProgramData\SysLogger\logs.db` |
| Linux    | `/opt/syslogger/logs.db` |
| Override | `BEHAVIORSHIELD_DB` environment variable |
| Fallback | `./logs.db` (dev/testing) |

---

## Building the Logger (Windows)

```bash
# MinGW (g++)
gcc -O2 -c sqlite3.c -o sqlite3.o
g++ main.cpp sqlite3.o -o logger.exe -lpsapi -liphlpapi -lpdh -O2 -std=c++17

# MSVC (Developer Command Prompt)
cl main.cpp sqlite3.c /O2 /EHsc /link psapi.lib iphlpapi.lib pdh.lib
```

---

## Packaging to Single .exe (for submission)

```bash
# Install PyInstaller
pip install pyinstaller

# Build single .exe (includes ML model via --add-data)
pyinstaller --onefile --windowed \
    --add-data "ml;ml" \
    --add-data "whitelist.txt;." \
    --name BehaviorShield \
    main.py

# Output: dist/BehaviorShield.exe
```

---

## Windows Bundle (No Source Files Required on Target PC)

Build a full deployment bundle (frontend EXE + logger EXE + install/uninstall scripts):

```bat
build_windows_bundle.bat
```

This creates:

- `bundle\BehaviorShield_Windows\BehaviorShield.exe`
- `bundle\BehaviorShield_Windows\logger.exe`
- `bundle\BehaviorShield_Windows\install_bundle.bat`
- `bundle\BehaviorShield_Windows\uninstall_bundle.bat`
- `bundle\BehaviorShield_Windows\register_logger_service.bat`
- `bundle\BehaviorShield_Windows\unregister_logger_service.bat`

Install on target machine (as Administrator):

```bat
bundle\BehaviorShield_Windows\install_bundle.bat
```

Uninstall completely (app + logger service + logs):

```bat
bundle\BehaviorShield_Windows\uninstall_bundle.bat
```

---

## Tabs Reference

### Tab 1 — Dashboard
- **4 metric cards**: CPU %, RAM MB, Net Sent KB/s, Net Recv KB/s — 1 min rolling
- **Process Risk Table**: all process windows scored by ML model
  - Click **⊕ Expand Columns** for 11 additional metrics
  - Red tint = HIGH RISK (≥0.70), amber = SUSPICIOUS (≥0.40)
- **Confirmation Queue**: HIGH RISK processes awaiting user review
  - ✓ Confirmed → logged as malware
  - ✗ False Pos. → process whitelisted forever
  - ? Not Sure → logged as unresolved

### Tab 2 — Live System Graphs
- 3×3 grid: CPU, RAM, Net Sent, Net Recv, Threads, Handles, Connections, Avg Risk, Process Count
- 1-minute rolling history at 1s resolution

### Tab 3 — Warning History
- Permanent append-only audit log — **cannot be deleted**
- Filter: All / Confirmed / False Positive / Unresolved
- Export to CSV for forensics

---

## Persistent Files

| File | Purpose | Deletable? |
|------|---------|------------|
| `whitelist.txt` | Trusted process names | Yes — resets whitelist |
| `warning_history.csv` | Security audit log | **No — permanent record** |

---

## Known Limitations (v2.0)

| Limitation | Notes |
|------------|-------|
| Only normal training data | Isolation Forest — correct approach for this phase |
| `net_sent`/`net_recv` are system-wide | PDH gives interface totals, not per-process (requires ETW for per-process) |
| No quarantine/kill | Detection only — planned for v3 |
| Windows only (logger) | Linux logger compiled separately via `install_linux.sh` |
