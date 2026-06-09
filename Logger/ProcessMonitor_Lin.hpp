#pragma once

// This entire file is Linux-only. Windows IntelliSense will skip it cleanly.
#ifdef __linux__

#include "ProcessMonitor.hpp"
#include <string>
#include <vector>
#include <map>
#include <iostream>
#include <fstream>
#include <sstream>
#include <dirent.h>      // Linux only
#include <unistd.h>      // sysconf, _SC_CLK_TCK, readlink
#include <sys/types.h>   // ssize_t
#include <ctime>
#include <cstring>
#include <chrono>
#include <set>

// ─────────────────────────────────────────────────────────────────────────────
//  LinuxMonitor
//
//  Reads per-process info from /proc.  Fields populated:
//    pid, processName, timestamp       — always
//    ramUsageKB                        — /proc/[pid]/status  VmRSS
//    parentPid                         — /proc/[pid]/status  PPid
//    threadCount                       — /proc/[pid]/status  Threads
//    isElevated                        — /proc/[pid]/status  Uid (== 0)
//    cpuUsage                          — /proc/[pid]/stat    utime+stime delta
//    openHandles                       — count of /proc/[pid]/fd/ entries
//    activeConnections                 — /proc/net/tcp + /proc/net/tcp6
//    windowTitle                       — always "" (requires X11/Wayland)
//    net bytes                         — always 0 (v2)
// ─────────────────────────────────────────────────────────────────────────────
class LinuxMonitor : public ProcessMonitor {
public:
    std::vector<ProcessLog> copyProcesses() override {
        std::vector<ProcessLog> logs;

        // Wall-clock delta for CPU% denominator
        auto nowTP   = std::chrono::steady_clock::now();
        double wallSec = 0.0;
        if (lastWallTime_.time_since_epoch().count() != 0)
            wallSec = std::chrono::duration<double>(nowTP - lastWallTime_).count();
        lastWallTime_ = nowTP;

        long clkTck = sysconf(_SC_CLK_TCK);
        if (clkTck <= 0) clkTck = 100;

        // Build TCP inode set for connection counting
        std::set<unsigned long> tcpInodes = parseTcpInodes();

        DIR* procDir = opendir("/proc");
        if (!procDir) return logs;

        std::set<int> seenPids;
        struct dirent* entry;

        while ((entry = readdir(procDir)) != nullptr) {
            if (!isdigit(entry->d_name[0])) continue;

            int pid = std::stoi(entry->d_name);
            seenPids.insert(pid);

            std::string pidStr   = entry->d_name;
            std::string procBase = "/proc/" + pidStr;

            ProcessLog log;
            log.pid               = pid;
            log.timestamp         = std::time(nullptr);
            log.cpuUsage          = 0.0;
            log.windowTitle       = "";
            log.ramUsageKB        = 0;
            log.parentPid         = 0;
            log.threadCount       = 0;
            log.openHandles       = 0;
            log.activeConnections = 0;
            log.isElevated        = false;
            log.networkBytesSent  = 0;
            log.networkBytesRecv  = 0;

            // /proc/[pid]/comm  ->  processName
            {
                std::ifstream f(procBase + "/comm");
                if (f) std::getline(f, log.processName);
                if (!log.processName.empty() && log.processName.back() == '\n')
                    log.processName.pop_back();
            }

            // /proc/[pid]/status  ->  ram, parentPid, threadCount, isElevated
            {
                std::ifstream f(procBase + "/status");
                if (f) {
                    std::string line;
                    while (std::getline(f, line)) {
                        if (line.compare(0, 6, "VmRSS:") == 0) {
                            std::istringstream ss(line);
                            std::string lbl; uint64_t kb;
                            ss >> lbl >> kb;
                            log.ramUsageKB = kb;
                        } else if (line.compare(0, 5, "PPid:") == 0) {
                            std::istringstream ss(line);
                            std::string lbl; int ppid;
                            ss >> lbl >> ppid;
                            log.parentPid = ppid;
                        } else if (line.compare(0, 8, "Threads:") == 0) {
                            std::istringstream ss(line);
                            std::string lbl; int thr;
                            ss >> lbl >> thr;
                            log.threadCount = thr;
                        } else if (line.compare(0, 4, "Uid:") == 0) {
                            std::istringstream ss(line);
                            std::string lbl; int ruid;
                            ss >> lbl >> ruid;
                            log.isElevated = (ruid == 0);
                        }
                    }
                }
            }

            // /proc/[pid]/stat  ->  cpuUsage (delta of utime+stime)
            {
                std::ifstream f(procBase + "/stat");
                if (f) {
                    std::string statLine;
                    std::getline(f, statLine);
                    auto rparen = statLine.rfind(')');
                    if (rparen != std::string::npos) {
                        std::istringstream ss(statLine.substr(rparen + 2));
                        std::string token;
                        unsigned long utime = 0, stime = 0;
                        int field = 3;
                        while (ss >> token) {
                            if (field == 14) utime = std::stoul(token);
                            if (field == 15) { stime = std::stoul(token); break; }
                            field++;
                        }
                        unsigned long totalTicks = utime + stime;
                        auto it = prevCpuTicks_.find(pid);
                        if (it != prevCpuTicks_.end() && wallSec > 0.0) {
                            unsigned long delta = totalTicks - it->second;
                            log.cpuUsage =
                                (static_cast<double>(delta) / clkTck / wallSec) * 100.0;
                            if (log.cpuUsage > 100.0) log.cpuUsage = 100.0;
                            it->second = totalTicks;
                        } else {
                            prevCpuTicks_[pid] = totalTicks;
                        }
                    }
                }
            }

            // /proc/[pid]/fd/  ->  openHandles count
            {
                std::string fdPath = procBase + "/fd";
                DIR* fdDir = opendir(fdPath.c_str());
                if (fdDir) {
                    int count = 0;
                    struct dirent* fde;
                    while ((fde = readdir(fdDir)) != nullptr)
                        if (fde->d_name[0] != '.') count++;
                    closedir(fdDir);
                    log.openHandles = count;
                }
            }

            // /proc/[pid]/fd/ symlinks  ->  activeConnections via socket inodes
            {
                std::string fdPath = procBase + "/fd";
                DIR* fdDir = opendir(fdPath.c_str());
                if (fdDir) {
                    struct dirent* fde;
                    while ((fde = readdir(fdDir)) != nullptr) {
                        if (fde->d_name[0] == '.') continue;
                        std::string link = fdPath + "/" + fde->d_name;
                        char target[256] = {};
                        ssize_t len = readlink(link.c_str(), target, sizeof(target) - 1);
                        if (len > 0) {
                            target[len] = '\0';
                            if (strncmp(target, "socket:[", 8) == 0) {
                                unsigned long inode = std::stoul(std::string(target + 8));
                                if (tcpInodes.count(inode))
                                    log.activeConnections++;
                            }
                        }
                    }
                    closedir(fdDir);
                }
            }

            logs.push_back(log);
        }

        closedir(procDir);

        // Evict dead PIDs from CPU baseline map
        for (auto it = prevCpuTicks_.begin(); it != prevCpuTicks_.end(); ) {
            if (!seenPids.count(it->first))
                it = prevCpuTicks_.erase(it);
            else
                ++it;
        }

        return logs;
    }

private:
    std::map<int, unsigned long>           prevCpuTicks_;
    std::chrono::steady_clock::time_point  lastWallTime_;

    // Parse ESTABLISHED TCP socket inodes from /proc/net/tcp and /proc/net/tcp6
    static std::set<unsigned long> parseTcpInodes() {
        std::set<unsigned long> inodes;
        for (const char* path : {"/proc/net/tcp", "/proc/net/tcp6"}) {
            std::ifstream f(path);
            if (!f) continue;
            std::string line;
            std::getline(f, line); // skip header
            while (std::getline(f, line)) {
                std::istringstream ss(line);
                std::string sl, localAddr, remAddr, state;
                ss >> sl >> localAddr >> remAddr >> state;
                if (state != "01") continue; // 01 = ESTABLISHED
                std::string txq, rxq, tr, tmWhen, retrnsmt, uid, timeout;
                unsigned long inode = 0;
                ss >> txq >> rxq >> tr >> tmWhen >> retrnsmt >> uid >> timeout >> inode;
                if (inode) inodes.insert(inode);
            }
        }
        return inodes;
    }
};

#endif // __linux__