#pragma once
#include <string>
#include <stdint.h>

struct ProcessLog {
    int pid;
    std::string processName;
    std::string windowTitle;
    double cpuUsage;
    uint64_t ramUsageKB;
    int parentPid;
    int threadCount;
    int openHandles;
    uint64_t networkBytesSent;
    uint64_t networkBytesRecv;
    int activeConnections;
    bool isElevated;
    std::string exePath;      // Full executable path (new field)
    uint64_t timestamp;
};
