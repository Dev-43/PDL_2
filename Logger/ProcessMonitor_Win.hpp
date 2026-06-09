#pragma once

// Windows-only. Linux compilers skip this file cleanly.
#ifdef _WIN32

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif

#include "ProcessMonitor.hpp"
#include <windows.h>
#include <tlhelp32.h>
#include <psapi.h>
#include <iostream>
#include <ctime>
#include <cwchar>
#include <map>
#include <chrono>
#include <string>
#include <processthreadsapi.h>
#include <securitybaseapi.h>
#include <iphlpapi.h>
#include <pdh.h>
#pragma comment(lib, "iphlpapi.lib")
#pragma comment(lib, "pdh.lib")

// ─────────────────────────────────────────────────────────────────────────────
//  NetByteTracker  (system-wide interface rates via PDH)
//  Called ONCE per loop — not per process.
// ─────────────────────────────────────────────────────────────────────────────
struct NetSample { uint64_t sent; uint64_t recv; };

class NetByteTracker {
public:
    NetByteTracker() : query_(nullptr), ready_(false) { init(); }
    ~NetByteTracker() { if (query_) PdhCloseQuery(query_); }

    NetSample sample() {
        if (!ready_) return {0, 0};
        PdhCollectQueryData(query_);

        uint64_t sentNow = 0, recvNow = 0;
        PDH_FMT_COUNTERVALUE val;
        for (auto& h : sentCounters_)
            if (PdhGetFormattedCounterValue(h, PDH_FMT_LARGE, nullptr, &val) == ERROR_SUCCESS)
                sentNow += (uint64_t)val.largeValue;
        for (auto& h : recvCounters_)
            if (PdhGetFormattedCounterValue(h, PDH_FMT_LARGE, nullptr, &val) == ERROR_SUCCESS)
                recvNow += (uint64_t)val.largeValue;

        // PDH "Bytes Sent/sec" and "Bytes Received/sec" already return rates.
        return {sentNow, recvNow};
    }

private:
    PDH_HQUERY               query_;
    std::vector<PDH_HCOUNTER> sentCounters_, recvCounters_;
    bool ready_ = false;

    void init() {
        if (PdhOpenQuery(nullptr, 0, &query_) != ERROR_SUCCESS) return;
        DWORD ifBufSz = 0, instBufSz = 0;
        PdhEnumObjectItems(nullptr, nullptr, L"Network Interface",
                           nullptr, &ifBufSz, nullptr, &instBufSz,
                           PERF_DETAIL_WIZARD, 0);
        std::wstring instBuf(instBufSz, L'\0');
        std::wstring ifBuf(ifBufSz, L'\0');
        if (PdhEnumObjectItems(nullptr, nullptr, L"Network Interface",
                               ifBuf.data(), &ifBufSz,
                               instBuf.data(), &instBufSz,
                               PERF_DETAIL_WIZARD, 0) != ERROR_SUCCESS) return;

        const wchar_t* p = instBuf.data();
        while (p && *p) {
            std::wstring iface(p);
            auto addCounter = [&](const wchar_t* metric, std::vector<PDH_HCOUNTER>& vec) {
                std::wstring path = L"\\Network Interface(" + iface + L")\\" + metric;
                PDH_HCOUNTER h;
                if (PdhAddCounter(query_, path.c_str(), 0, &h) == ERROR_SUCCESS)
                    vec.push_back(h);
            };
            addCounter(L"Bytes Sent/sec",     sentCounters_);
            addCounter(L"Bytes Received/sec", recvCounters_);
            p += iface.size() + 1;
        }
        PdhCollectQueryData(query_);  // baseline
        ready_ = true;
    }
};

// ─────────────────────────────────────────────────────────────────────────────
//  Lazy TCP connection cache — rebuilt every ~5 seconds, not every process
// ─────────────────────────────────────────────────────────────────────────────
class ConnectionCache {
public:
    // Returns connection count for a PID, rebuilding table if stale.
    int get(DWORD pid) {
        auto now = std::chrono::steady_clock::now();
        if (!built_ ||
            std::chrono::duration<double>(now - lastBuilt_).count() > 5.0) {
            rebuild();
        }
        auto it = cache_.find(pid);
        return (it != cache_.end()) ? it->second : 0;
    }

private:
    std::map<DWORD, int> cache_;
    std::chrono::steady_clock::time_point lastBuilt_;
    bool built_ = false;

    void rebuild() {
        cache_.clear();
        DWORD size = 0;
        GetExtendedTcpTable(nullptr, &size, FALSE, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0);
        auto* tbl = reinterpret_cast<PMIB_TCPTABLE_OWNER_PID>(malloc(size));
        if (!tbl) return;
        if (GetExtendedTcpTable(tbl, &size, FALSE, AF_INET,
                                TCP_TABLE_OWNER_PID_ALL, 0) == NO_ERROR) {
            for (DWORD i = 0; i < tbl->dwNumEntries; i++)
                cache_[tbl->table[i].dwOwningPid]++;
        }
        free(tbl);
        lastBuilt_ = std::chrono::steady_clock::now();
        built_ = true;
    }
};

// ─────────────────────────────────────────────────────────────────────────────
//  WindowsMonitor
//  Optimized for <1% CPU:
//    • BELOW_NORMAL process priority
//    • Snapshot once, iterate once
//    • Connection table rebuilt lazily (not per-process)
//    • Open handles queried with a light NtQuerySystemInformation fallback
//    • 1-second sleep interval (set in main.cpp)
// ─────────────────────────────────────────────────────────────────────────────
class WindowsMonitor : public ProcessMonitor {
public:
    WindowsMonitor() {
        // Drop our own process to below-normal so we yield aggressively
        SetPriorityClass(GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS);
    }

    std::vector<ProcessLog> copyProcesses() override {
        std::vector<ProcessLog> logs;
        logs.reserve(256);

        // Sample network once per full round
        NetSample netRate = netTracker_.sample();

        // Wall-clock delta for CPU%
        auto nowTP = std::chrono::steady_clock::now();
        double wallSec = 0.0;
        if (lastWallTime_.time_since_epoch().count() != 0)
            wallSec = std::chrono::duration<double>(nowTP - lastWallTime_).count();
        lastWallTime_ = nowTP;

        SYSTEM_INFO si;
        GetSystemInfo(&si);
        DWORD numCores = si.dwNumberOfProcessors;
        if (numCores == 0) numCores = 1;

        // Single snapshot of all processes
        HANDLE hSnap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        if (hSnap == INVALID_HANDLE_VALUE) return logs;

        PROCESSENTRY32W pe32;
        pe32.dwSize = sizeof(PROCESSENTRY32W);
        if (!Process32FirstW(hSnap, &pe32)) {
            CloseHandle(hSnap);
            return logs;
        }

        std::map<DWORD, bool> seenPids;

        do {
            DWORD pid = pe32.th32ProcessID;
            seenPids[pid] = true;

            ProcessLog log{};
            log.pid         = (int)pid;
            log.parentPid   = (int)pe32.th32ParentProcessID;
            log.threadCount = (int)pe32.cntThreads;
            log.timestamp   = std::time(nullptr);
            log.cpuUsage    = 0.0;
            log.windowTitle = "";
            log.ramUsageKB  = 0;
            log.openHandles = 0;
            log.activeConnections = 0;
            log.isElevated  = false;
            log.networkBytesSent = 0;
            log.networkBytesRecv = 0;
            log.exePath = "";

            // Process name from snapshot (free — no handle needed)
            {
                char buf[260] = {};
                WideCharToMultiByte(CP_UTF8, 0, pe32.szExeFile, -1,
                                    buf, sizeof(buf), nullptr, nullptr);
                log.processName = buf;
            }

            // Open process with minimal rights
            HANDLE hProc = OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ,
                FALSE, pid);

            if (hProc) {
                // RAM
                PROCESS_MEMORY_COUNTERS pmc = {};
                pmc.cb = sizeof(pmc);
                if (GetProcessMemoryInfo(hProc, &pmc, sizeof(pmc)))
                    log.ramUsageKB = pmc.WorkingSetSize / 1024;

                // CPU delta
                FILETIME cre, ex, ker, usr;
                if (GetProcessTimes(hProc, &cre, &ex, &ker, &usr)) {
                    ULONGLONG nowKU =
                        ((ULONGLONG)ker.dwHighDateTime << 32 | ker.dwLowDateTime) +
                        ((ULONGLONG)usr.dwHighDateTime << 32 | usr.dwLowDateTime);
                    auto it = prevCpuTime_.find(pid);
                    if (it != prevCpuTime_.end() && wallSec > 0.0) {
                        ULONGLONG delta = nowKU - it->second;
                        double wallUnits = wallSec * 1e7 * numCores;
                        log.cpuUsage = (delta / wallUnits) * 100.0;
                        if (log.cpuUsage > 100.0) log.cpuUsage = 100.0;
                    }
                    prevCpuTime_[pid] = nowKU;
                }

                // Open handles (lightweight)
                DWORD hCount = 0;
                GetProcessHandleCount(hProc, &hCount);
                log.openHandles = (int)hCount;

                // Elevation
                HANDLE hToken = nullptr;
                if (OpenProcessToken(hProc, TOKEN_QUERY, &hToken)) {
                    TOKEN_ELEVATION elev = {};
                    DWORD sz = sizeof(elev);
                    if (GetTokenInformation(hToken, TokenElevation, &elev, sz, &sz))
                        log.isElevated = (elev.TokenIsElevated != 0);
                    CloseHandle(hToken);
                }

                // Full exe path
                {
                    wchar_t pathBuf[MAX_PATH] = {};
                    DWORD pathLen = MAX_PATH;
                    if (QueryFullProcessImageNameW(hProc, 0, pathBuf, &pathLen)) {
                        char narrow[MAX_PATH * 2] = {};
                        WideCharToMultiByte(CP_UTF8, 0, pathBuf, -1,
                                            narrow, sizeof(narrow), nullptr, nullptr);
                        log.exePath = narrow;
                    }
                }

                CloseHandle(hProc);
            }

            // Network connections — lazy cache (rebuilt every 5s, not per-process)
            log.activeConnections = connCache_.get(pid);

            logs.push_back(log);

        } while (Process32NextW(hSnap, &pe32));

        CloseHandle(hSnap);

        // Distribute net bytes by connection share
        int totalConns = 0;
        for (const auto& l : logs) totalConns += l.activeConnections;
        if (totalConns > 0 && (netRate.sent > 0 || netRate.recv > 0)) {
            for (auto& l : logs) {
                if (l.activeConnections > 0) {
                    double share = (double)l.activeConnections / totalConns;
                    l.networkBytesSent = (uint64_t)(netRate.sent * share);
                    l.networkBytesRecv = (uint64_t)(netRate.recv * share);
                }
            }
        }

        // Evict dead PIDs from CPU baseline
        for (auto it = prevCpuTime_.begin(); it != prevCpuTime_.end(); ) {
            if (seenPids.find(it->first) == seenPids.end())
                it = prevCpuTime_.erase(it);
            else
                ++it;
        }

        return logs;
    }

    static std::string GetForegroundWindowTitle() {
        HWND hwnd = GetForegroundWindow();
        if (!hwnd) return "";
        wchar_t title[256] = {};
        GetWindowTextW(hwnd, title, 256);
        char buf[512] = {};
        WideCharToMultiByte(CP_UTF8, 0, title, -1, buf, sizeof(buf), nullptr, nullptr);
        return std::string(buf);
    }

private:
    std::map<DWORD, ULONGLONG>            prevCpuTime_;
    std::chrono::steady_clock::time_point lastWallTime_;
    NetByteTracker                         netTracker_;
    ConnectionCache                        connCache_;
};

#endif // _WIN32
