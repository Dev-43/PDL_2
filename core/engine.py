"""
BehaviorShield â€” Core Engine
============================
DB reader + feature engineering + ML inference pipeline.

ML Model: Isolation Forest trained on normal Windows process behavior.
          Anomaly score 0.0 = perfectly normal, 1.0 = highly anomalous.
          With only normal training data this is the correct approach â€”
          it learns the normal baseline and flags deviations.

Platform:  Windows + Linux
DB:        logs.db written by the C++ logger (WAL mode, 1s interval)

v2.1 fixes:
  - net_sent/recv: use MEAN rate not SUM (PDH gives bytes/sec, summing
    rates across N samples inflates the value N-fold)
  - Features normalized by sample_count to be interval-agnostic
    (model was trained at 3s interval; running at 1s caused 3x larger
    variance/count features â†’ false anomalies)
  - Deduplication: only keep highest-risk window per (pid, process_name)
  - System process whitelist: known Windows/Linux OS processes never flagged
  - POPUP_THRESHOLD separate from RISK_HIGH (popups at 0.95+, table at 0.70+)
"""

from __future__ import annotations

import json
import os
import platform
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# â”€â”€ ML Model â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_ML_DIR = Path(__file__).parent.parent / "ml"

def _candidate_ml_dirs() -> list[Path]:
    dirs: list[Path] = []
    env_ml = os.environ.get("BEHAVIORSHIELD_ML_DIR")
    if env_ml:
        dirs.append(Path(env_ml))

    dirs.append(_ML_DIR)
    dirs.append(Path.cwd() / "ml")

    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent / "ml")
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass) / "ml")

    unique: list[Path] = []
    seen: set[str] = set()
    for d in dirs:
        key = str(d)
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique

def _load_model():
    model_path = None
    params_path = None
    for d in _candidate_ml_dirs():
        m = d / "anomaly_model.pkl"
        if m.exists():
            model_path = m
            params_path = d / "score_params.json"
            break

    if model_path is None:
        return None, None, None, "model file not found"
    try:
        import joblib
        model = joblib.load(model_path)
        params = json.loads(params_path.read_text()) if (params_path and params_path.exists()) else {"s_min": -0.5, "s_max": 0.5}
        return model, params["s_min"], params["s_max"], f"loaded from {model_path}"
    except Exception as e:
        print(f"[ML] Failed to load model: {e}")
        return None, None, None, f"load error: {e}"

_MODEL, _SCORE_MIN, _SCORE_MAX, _MODEL_LOAD_STATUS = _load_model()

ML_FEATURE_COLS = [
    "sample_count", "ram_avg", "ram_max", "ram_var", "ram_growth",
    "cpu_avg", "cpu_max", "cpu_var", "net_sent_total", "net_recv_total",
    "connections_max", "thread_avg", "handle_avg", "is_elevated",
]

def ml_anomaly_score(feature_vec: list[float]) -> float:
    """
    Run Isolation Forest on a feature vector.
    Returns anomaly score in [0.0, 1.0]:  0 = normal, 1 = highly anomalous.
    Falls back to 0.0 if model unavailable.
    """
    if _MODEL is None:
        return 0.0
    try:
        X = np.array(feature_vec, dtype=float).reshape(1, -1)
        raw = float(_MODEL.decision_function(X)[0])
        # Normalize to [0,1], flip so high = anomalous
        norm = (raw - _SCORE_MIN) / (_SCORE_MAX - _SCORE_MIN + 1e-9)
        return float(np.clip(1.0 - norm, 0.0, 1.0))
    except Exception:
        return 0.0


# â”€â”€ Constants â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

WINDOW_SECONDS   = 30
RISK_HIGH        = 0.70    # Amber/red in table and FP queue
RISK_MEDIUM      = 0.40    # Amber highlight in table
POPUP_THRESHOLD  = 0.95    # Only pop up for truly extreme scores (user-adjustable)
MAX_CHART_POINTS = 60      # Reduced from 120 â†’ faster chart redraws

# â”€â”€ System Process Whitelist â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# These are known legitimate Windows/Linux OS processes.
# They will never generate a popup or appear in the confirmation queue,
# but they DO still appear in the table with their real score.
SYSTEM_PROCESSES: frozenset[str] = frozenset({
    # Windows core
    "system", "system idle process", "registry", "smss.exe", "csrss.exe",
    "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe", "lsaiso.exe",
    "svchost.exe", "spoolsv.exe", "dwm.exe", "sihost.exe", "taskhostw.exe",
    "explorer.exe", "runtimebroker.exe", "searchindexer.exe", "wmiprvse.exe",
    "dllhost.exe", "conhost.exe", "fontdrvhost.exe", "audiodg.exe",
    "secure system", "memory compression",
    # Windows shell / UI
    "shellexperiencehost.exe", "startmenuexperiencehost.exe",
    "searchprotocolhost.exe", "searchfilterhost.exe", "applicationframehost.exe",
    "ctfmon.exe", "textinputhost.exe", "lockapp.exe",
    # Windows Update / telemetry
    "msiexec.exe", "trustedinstaller.exe", "tiworker.exe",
    "musnotification.exe", "musnotifyicon.exe", "usocoreworker.exe",
    # Security
    "msmpeng.exe", "nissrv.exe", "mpcmdrun.exe", "securityhealthservice.exe",
    "securityhealthsystray.exe",
    # Linux core
    "systemd", "kthreadd", "ksoftirqd", "kworker", "rcu_sched",
    "init", "dbus-daemon", "NetworkManager", "dhclient", "sshd",
    "Xorg", "pulseaudio", "gnome-shell",
})


# â”€â”€ DB Path Resolution â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def get_default_db_path() -> str:
    override = os.environ.get("BEHAVIORSHIELD_DB")
    if override:
        return override
    system = platform.system()
    if system == "Windows":
        return r"C:\ProgramData\SysLogger\logs.db"
    elif system == "Linux":
        return "/opt/syslogger/logs.db"
    return "logs.db"


# â”€â”€ Data Classes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@dataclass
class ProcessFeatures:
    """One feature vector â€” one process in one 30-second window."""
    pid:              int
    process_name:     str
    window_start:     str
    sample_count:     int

    ram_avg_kb:       float = 0.0
    ram_max_kb:       float = 0.0
    ram_variance:     float = 0.0
    ram_growth_rate:  float = 0.0
    ram_always_zero:  int   = 0

    cpu_avg:          Optional[float] = None
    cpu_max_spike:    Optional[float] = None
    cpu_variance:     Optional[float] = None

    net_sent_total:   Optional[float] = None
    net_recv_total:   Optional[float] = None
    connections_max:  Optional[float] = None

    thread_growth:    Optional[float] = None
    thread_avg:       Optional[float] = None
    handle_avg:       Optional[float] = None
    is_elevated:      Optional[int]   = None
    parent_pid:       Optional[int]   = None

    exe_path:         str   = ""
    appearance_freq:  float = 0.0

    # ML score (primary) + heuristic top signal for UI
    risk_score:       float = 0.0
    top_signal:       str   = ""

    @property
    def verdict(self) -> str:
        if self.risk_score >= RISK_HIGH:   return "HIGH RISK"
        if self.risk_score >= RISK_MEDIUM: return "SUSPICIOUS"
        return "BENIGN"

    @property
    def verdict_level(self) -> int:
        if self.risk_score >= RISK_HIGH:   return 2
        if self.risk_score >= RISK_MEDIUM: return 1
        return 0


@dataclass
class SystemSnapshot:
    """Aggregated system-wide metrics for the Live Graphs tab."""
    timestamp:         float = 0.0
    cpu_avg:           float = 0.0
    ram_avg_kb:        float = 0.0
    ram_total_kb:      float = 0.0
    net_sent_total:    float = 0.0
    net_recv_total:    float = 0.0
    thread_total:      int   = 0
    handle_total:      int   = 0
    connections_total: int   = 0
    process_count:     int   = 0
    elevated_count:    int   = 0
    risk_score_avg:    float = 0.0
    risk_score_max:    float = 0.0


@dataclass
class WarningEvent:
    timestamp:     str
    processes:     list[ProcessFeatures] = field(default_factory=list)
    dismissed:     bool = False
    user_response: str  = ""


# â”€â”€ Database Reader â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class DBReader:
    """
    Reads from logs.db (WAL mode, written by C++ logger at 1s interval).
    Uses bounded time-range reads to keep each poll fast even when the DB grows.
    """

    REQUIRED_COLS = {"pid", "process_name", "timestamp"}
    ALL_EXPECTED  = {
        "pid", "process_name", "parent_pid", "ram_kb", "cpu_usage",
        "thread_count", "open_handles", "net_sent", "net_recv",
        "connections", "is_elevated", "window_title", "timestamp",
    }

    def __init__(self, db_path: str):
        self.db_path    = db_path
        self._cols:     list[str] = []
        self._last_check = 0.0

    @property
    def exists(self) -> bool:
        return os.path.exists(self.db_path)

    @property
    def columns(self) -> list[str]:
        if time.time() - self._last_check > 30:
            self._cols = self._fetch_columns()
            self._last_check = time.time()
        return self._cols

    @property
    def missing_columns(self) -> list[str]:
        return sorted(self.ALL_EXPECTED - set(self.columns))

    @property
    def schema_complete(self) -> bool:
        return len(self.missing_columns) == 0

    def read_recent(self, limit: int = 5000) -> pd.DataFrame:
        """
        Return recent rows for feature computation.
        Uses a rolling 60-second window from the DB â€” avoids loading
        old historical data, keeping queries fast even on a 200MB DB.
        """
        if not self.exists:
            return pd.DataFrame()
        try:
            conn = self._connect()
            cols = self.columns
            if not cols:
                conn.close()
                return pd.DataFrame()

            cutoff = int(time.time()) - 90   # 90s window gives 3 full feature windows
            order  = "timestamp" if "timestamp" in cols else cols[0]
            df = pd.read_sql_query(
                f"SELECT * FROM logs WHERE {order} >= ? ORDER BY {order} DESC LIMIT ?",
                conn, params=(cutoff, limit)
            )
            conn.close()
            return df
        except Exception as e:
            print(f"[DBReader] read_recent error: {e}")
            return pd.DataFrame()

    def read_latest_window(self, seconds: int = 30) -> pd.DataFrame:
        if not self.exists:
            return pd.DataFrame()
        try:
            conn  = self._connect()
            cutoff = int(time.time()) - seconds
            df = pd.read_sql_query(
                "SELECT * FROM logs WHERE timestamp >= ? ORDER BY timestamp DESC",
                conn, params=(cutoff,)
            )
            conn.close()
            return df
        except Exception as e:
            print(f"[DBReader] read_latest_window error: {e}")
            return pd.DataFrame()

    def row_count(self) -> int:
        if not self.exists:
            return 0
        try:
            conn = self._connect()
            cur  = conn.execute("SELECT COUNT(*) FROM logs")
            n    = cur.fetchone()[0]
            conn.close()
            return n
        except Exception:
            return 0

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=3)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA query_only=ON")
        return conn

    def _fetch_columns(self) -> list[str]:
        if not self.exists:
            return []
        try:
            conn = sqlite3.connect(self.db_path, timeout=3)
            cur  = conn.execute("PRAGMA table_info(logs)")
            cols = [row[1] for row in cur.fetchall()]
            conn.close()
            return cols
        except Exception:
            return []


# â”€â”€ Feature Engineering â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class FeatureEngine:
    """
    Converts raw log rows â†’ ProcessFeatures objects.
    Scores each process window using the trained Isolation Forest ML model.
    Falls back to heuristic scoring if model is unavailable.
    """

    def compute(
        self,
        df: pd.DataFrame,
        window_seconds: int = WINDOW_SECONDS,
    ) -> list[ProcessFeatures]:
        if df.empty:
            return []

        df = df.copy()
        df = self._normalize_timestamp(df)
        df["time_bucket"]    = (df["ts_sec"] // window_seconds).astype(int)
        df["window_start_ts"] = df["time_bucket"] * window_seconds

        group_keys = ["pid", "time_bucket"]
        if "process_name" in df.columns:
            group_keys = ["pid", "process_name", "time_bucket"]

        results: list[ProcessFeatures] = []
        for keys, grp in df.groupby(group_keys):
            f = self._compute_group(keys, grp, window_seconds)
            results.append(f)

        # Deduplicate: keep only the highest-risk window per (pid, process_name).
        # Without this, a process appearing in multiple overlapping 30s buckets
        # generates duplicate rows in the table and duplicate warning events.
        seen: dict[tuple[int, str], ProcessFeatures] = {}
        for f in results:
            key = (f.pid, f.process_name)
            if key not in seen or f.risk_score > seen[key].risk_score:
                seen[key] = f

        deduped = sorted(seen.values(), key=lambda x: x.risk_score, reverse=True)
        return deduped

    def compute_system_snapshot(self, df: pd.DataFrame) -> Optional[SystemSnapshot]:
        if df.empty:
            return None

        snap = SystemSnapshot(timestamp=time.time())
        if "pid" in df.columns:
            if "timestamp" in df.columns:
                work = df.copy()
                work["timestamp"] = pd.to_numeric(work["timestamp"], errors="coerce").fillna(0)
                work = work.sort_values("timestamp")
                latest = work.groupby("pid", as_index=False).tail(1)
            else:
                latest = df.drop_duplicates(subset=["pid"], keep="first")
        else:
            latest = df

        snap.process_count = latest["pid"].nunique() if "pid" in latest.columns else 0

        if "cpu_usage" in latest.columns:
            cpu_vals = pd.to_numeric(latest["cpu_usage"], errors="coerce").fillna(0)
            # System CPU should be total load (sum across processes), not mean per process.
            snap.cpu_avg = float(np.clip(cpu_vals.sum(), 0.0, 100.0))

        if "ram_kb" in latest.columns and "pid" in latest.columns:
            ram = pd.to_numeric(latest["ram_kb"], errors="coerce").fillna(0)
            snap.ram_avg_kb = float(ram.mean())
            snap.ram_total_kb = float(ram.sum())

        if "net_sent" in latest.columns:
            # net_sent/net_recv are per-sample rates (bytes/s), so use current snapshot values.
            snap.net_sent_total = float(pd.to_numeric(latest["net_sent"], errors="coerce").fillna(0).sum())
        if "net_recv" in latest.columns:
            snap.net_recv_total = float(pd.to_numeric(latest["net_recv"], errors="coerce").fillna(0).sum())
        if "thread_count" in latest.columns:
            snap.thread_total = int(pd.to_numeric(latest["thread_count"], errors="coerce").fillna(0).sum())
        if "open_handles" in latest.columns:
            snap.handle_total = int(pd.to_numeric(latest["open_handles"], errors="coerce").fillna(0).sum())
        if "connections" in latest.columns:
            snap.connections_total = int(pd.to_numeric(latest["connections"], errors="coerce").fillna(0).sum())
        if "is_elevated" in latest.columns:
            elevated = pd.to_numeric(latest["is_elevated"], errors="coerce").fillna(0)
            snap.elevated_count = int((elevated > 0).sum())

        return snap

    # â”€â”€ Private â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _normalize_timestamp(self, df: pd.DataFrame) -> pd.DataFrame:
        if "timestamp" in df.columns:
            ts = df["timestamp"].astype(float)
            if ts.max() > 1e12:
                ts = ts / 1000.0
            df["ts_sec"] = ts
        else:
            df["ts_sec"] = time.time()
        return df

    def _compute_group(self, keys, grp: pd.DataFrame, window_seconds: int) -> ProcessFeatures:
        pid        = int(keys[0])
        proc_name  = str(keys[1]) if len(keys) > 2 else "unknown"
        win_start  = datetime.utcfromtimestamp(
            float(grp["window_start_ts"].iloc[0])
        ).strftime("%H:%M:%S")

        n = len(grp)   # sample count in this window

        f = ProcessFeatures(
            pid            = pid,
            process_name   = proc_name,
            window_start   = win_start,
            sample_count   = n,
            appearance_freq= n / window_seconds,
        )

        # RAM â€” KB absolute values, not rates, so stats are interval-agnostic
        if "ram_kb" in grp.columns:
            ram = grp["ram_kb"].astype(float)
            f.ram_avg_kb    = float(ram.mean())
            f.ram_max_kb    = float(ram.max())
            f.ram_variance  = float(ram.var()) if n > 1 else 0.0
            f.ram_always_zero = int(ram.max() == 0)
            if n > 1 and "ts_sec" in grp.columns:
                span = max(float(grp["ts_sec"].max() - grp["ts_sec"].min()), 1.0)
                f.ram_growth_rate = float((ram.iloc[-1] - ram.iloc[0]) / span)

        # CPU â€” percentage already normalised per sample; mean is interval-agnostic
        if "cpu_usage" in grp.columns:
            cpu = grp["cpu_usage"].astype(float)
            f.cpu_avg       = float(cpu.mean())
            f.cpu_max_spike = float(cpu.max())
            f.cpu_variance  = float(cpu.var()) if n > 1 else 0.0

        # Network â€” PDH gives bytes/sec RATE per sample.
        # Use MEAN (average rate KB/s) not SUM.
        # Summing N samples of a rate gives rate*N, which inflates linearly
        # with poll frequency and creates false "mass data" signals.
        # MEAN gives the average throughput regardless of interval.
        if "net_sent" in grp.columns:
            f.net_sent_total = float(grp["net_sent"].astype(float).mean())   # avg bytes/s
        if "net_recv" in grp.columns:
            f.net_recv_total = float(grp["net_recv"].astype(float).mean())   # avg bytes/s
        if "connections" in grp.columns:
            f.connections_max = float(grp["connections"].astype(float).max())

        # Process tree â€” thread/handle counts are snapshots, use max/mean
        if "thread_count" in grp.columns:
            tc = grp["thread_count"].astype(float)
            f.thread_growth = float(tc.max() - tc.min())
            f.thread_avg = float(tc.mean())
        if "open_handles" in grp.columns:
            f.handle_avg = float(grp["open_handles"].astype(float).mean())
        if "is_elevated" in grp.columns:
            f.is_elevated = int(grp["is_elevated"].astype(float).max())
        if "parent_pid" in grp.columns:
            f.parent_pid = int(grp["parent_pid"].iloc[0])

        # Exe path
        for col in ("exe_path", "exePath"):
            if col in grp.columns:
                paths = grp[col].dropna()
                paths = paths[paths.astype(str).str.strip() != ""]
                if not paths.empty:
                    f.exe_path = str(paths.iloc[-1])
                break

        # â”€â”€ Score: ML model (primary) + heuristic top_signal for UI â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        ml_score = self._ml_score(f)
        heuristic_score, top_signal = self._heuristic_risk(f)

        if _MODEL is not None:
            # Blend: 70% ML + 30% heuristic for robustness
            f.risk_score = round(0.70 * ml_score + 0.30 * heuristic_score, 3)
        else:
            f.risk_score = round(heuristic_score, 3)

        f.top_signal = top_signal if top_signal else (
            f"Anomaly score {ml_score:.2f}" if ml_score > RISK_MEDIUM else ""
        )
        return f

    def _ml_score(self, f: ProcessFeatures) -> float:
        """Build ML feature vector and get anomaly score.
        Feature order must match training: feature_cols.json"""
        if _MODEL is None:
            return 0.0
        vec = [
            float(f.sample_count),
            float(f.ram_avg_kb),
            float(f.ram_max_kb),
            float(f.ram_variance),
            float(f.ram_growth_rate),
            float(f.cpu_avg or 0.0),
            float(f.cpu_max_spike or 0.0),
            float(f.cpu_variance or 0.0),
            float(f.net_sent_total or 0.0),   # now avg bytes/s
            float(f.net_recv_total or 0.0),   # now avg bytes/s
            float(f.connections_max or 0.0),
            float(f.thread_avg or 0.0),
            float(f.handle_avg or 0.0),
            float(f.is_elevated or 0),
        ]
        return ml_anomaly_score(vec)

    def _heuristic_risk(self, f: ProcessFeatures) -> tuple[float, str]:
        """
        Rule-based fallback / signal explainer.
        net_sent_total / net_recv_total are now average bytes/s (not total).
        Thresholds updated accordingly:
          5 MB/s sustained outbound = suspicious exfiltration signal
          50 MB/s = high confidence exfiltration
        """
        signals: list[tuple[float, str]] = []

        # CPU
        if f.cpu_avg is not None:
            if f.cpu_avg > 85:
                signals.append((0.40, f"Sustained CPU {f.cpu_avg:.0f}% - possible cryptominer"))
            elif f.cpu_avg > 60:
                signals.append((0.20, f"Elevated CPU {f.cpu_avg:.0f}%"))

        if f.cpu_max_spike is not None and f.cpu_max_spike > 90:
            signals.append((0.25, f"CPU spike {f.cpu_max_spike:.0f}% - possible ransomware"))

        # RAM
        if f.ram_growth_rate > 1000:
            signals.append((0.25, f"RAM growing {f.ram_growth_rate:.0f} KB/s - possible injection"))
        elif f.ram_growth_rate > 500:
            signals.append((0.15, "Elevated RAM growth rate"))

        if f.ram_always_zero:
            signals.append((0.10, "RAM usage hidden - possible evasion"))

        # Network â€” thresholds are now in avg bytes/s (not total bytes)
        # 50 MB/s avg sustained = strong exfiltration signal
        # 5 MB/s avg = elevated but could be legitimate (browser, backup)
        if f.net_sent_total is not None:
            rate_mb = f.net_sent_total / 1_048_576   # bytes/s â†’ MB/s
            if rate_mb > 50:
                signals.append((0.35, f"Sustained outbound {rate_mb:.1f} MB/s - possible exfiltration"))
            elif rate_mb > 5:
                signals.append((0.15, f"Elevated outbound traffic {rate_mb:.1f} MB/s"))

        # Handle count â€” system processes legitimately have thousands
        if f.handle_avg is not None and f.handle_avg > 2000:
            signals.append((0.20, f"Abnormal handle count {f.handle_avg:.0f} - possible ransomware"))
        elif f.handle_avg is not None and f.handle_avg > 1200:
            signals.append((0.10, f"Elevated handle count {f.handle_avg:.0f}"))

        # Thread explosion
        if f.thread_growth is not None and f.thread_growth > 30:
            signals.append((0.20, f"Thread explosion +{f.thread_growth:.0f} - possible injection"))

        # Elevated privilege â€” minor signal only, not enough alone
        if f.is_elevated:
            signals.append((0.05, "Process running elevated"))

        if not signals:
            return 0.0, ""

        signals.sort(key=lambda x: x[0], reverse=True)
        total = min(sum(s[0] for s in signals), 1.0)
        return round(total, 3), signals[0][1]


# â”€â”€ Whitelist Manager â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class Whitelist:
    def __init__(self, path: str = "whitelist.txt"):
        self.path   = path
        self._names: set[str] = set()
        self._load()

    def add(self, process_name: str):
        self._names.add(process_name.lower())
        self._save()

    def is_trusted(self, process_name: str) -> bool:
        return process_name.lower() in self._names

    def all_names(self) -> list[str]:
        return sorted(self._names)

    def remove(self, process_name: str):
        self._names.discard(process_name.lower())
        self._save()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                self._names = {l.strip().lower() for l in f if l.strip()}

    def _save(self):
        with open(self.path, "w") as f:
            f.write("\n".join(sorted(self._names)))


# â”€â”€ History Log â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class HistoryLog:
    COLUMNS = [
        "timestamp", "process_name", "pid", "risk_score",
        "verdict", "top_signal", "user_response",
    ]

    def __init__(self, path: str = "warning_history.csv"):
        self.path = path
        if not os.path.exists(self.path):
            pd.DataFrame(columns=self.COLUMNS).to_csv(self.path, index=False)

    def append(self, features: ProcessFeatures, user_response: str = "unresolved"):
        row = pd.DataFrame([{
            "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "process_name":  features.process_name,
            "pid":           features.pid,
            "risk_score":    features.risk_score,
            "verdict":       features.verdict,
            "top_signal":    features.top_signal,
            "user_response": user_response,
        }])
        row.to_csv(self.path, mode="a", header=False, index=False)

    def load(self) -> pd.DataFrame:
        try:
            return pd.read_csv(self.path)
        except Exception:
            return pd.DataFrame(columns=self.COLUMNS)

    def export(self, export_path: str) -> bool:
        try:
            self.load().to_csv(export_path, index=False)
            return True
        except Exception:
            return False

