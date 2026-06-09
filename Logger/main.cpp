#include <iostream>
#include <vector>
#include <iomanip>
#include <ctime>
#include <string>
#include <stdint.h>
#include <atomic>
#include <csignal>

#ifdef __linux__
    #include <unistd.h>
#endif

#include "Shared.hpp"
#include "ProcessMonitor.hpp"
#include "Database.hpp"

#ifdef _WIN32
    #include "ProcessMonitor_Win.hpp"
#elif defined(__linux__)
    #include "ProcessMonitor_Lin.hpp"
#else
    #error "Unsupported Operating System"
#endif

static std::string resolveDbPath(int argc, char* argv[]) {
    for (int i = 1; i < argc - 1; i++)
        if (std::string(argv[i]) == "--db")
            return argv[i + 1];
#ifdef _WIN32
    const char* pd = getenv("PROGRAMDATA");
    if (pd) return std::string(pd) + "\\SysLogger\\logs.db";
#elif defined(__linux__)
    return "/opt/syslogger/logs.db";
#endif
    return "logs.db";
}

// BATCH_SIZE: flush every N captures in one transaction.
// At 1s interval, BATCH_SIZE=5 → one disk commit per 5 seconds.
static const int BATCH_SIZE = 5;
static std::atomic<bool> g_running{true};

static void onSignal(int) {
    g_running = false;
}

#ifdef _WIN32
BOOL WINAPI onConsoleCtrl(DWORD ctrlType) {
    switch (ctrlType) {
        case CTRL_C_EVENT:
        case CTRL_BREAK_EVENT:
        case CTRL_CLOSE_EVENT:
        case CTRL_SHUTDOWN_EVENT:
            g_running = false;
            return TRUE;
        default:
            return FALSE;
    }
}
#endif

int main(int argc, char* argv[]) {
    std::signal(SIGINT, onSignal);
    std::signal(SIGTERM, onSignal);
#ifdef _WIN32
    SetConsoleCtrlHandler(onConsoleCtrl, TRUE);
#endif

    std::string dbPath = resolveDbPath(argc, argv);
    std::cout << "BehaviorShield Logger starting...\n";
    std::cout << "Database: " << dbPath << "\n";

    ProcessMonitor* monitor = nullptr;
#ifdef _WIN32
    std::cout << "Platform: Windows\n";
    monitor = new WindowsMonitor();
#elif defined(__linux__)
    std::cout << "Platform: Linux\n";
    monitor = new LinuxMonitor();
#endif

    if (!monitor) { std::cerr << "Failed to create monitor\n"; return 1; }
    std::cout << "Logger running at 1s interval (batch writes, BELOW_NORMAL priority).\n";
    std::cout << "Press Ctrl+C to stop.\n";

    Database database(dbPath);

    std::vector<std::vector<ProcessLog>> batch;
    batch.reserve(BATCH_SIZE);
    auto flushBatch = [&]() {
        if (batch.empty()) return;
        database.beginTransaction();
        for (const auto& capture : batch)
            for (const auto& log : capture)
                database.insertLog(log);
        database.commitTransaction();
        batch.clear();
    };

    while (g_running) {
        std::vector<ProcessLog> logs = monitor->copyProcesses();
        batch.push_back(logs);
        std::cout << "\r[" << std::time(nullptr) << "] " << logs.size() << " processes   " << std::flush;

        if ((int)batch.size() >= BATCH_SIZE) {
            flushBatch();
        }

#ifdef _WIN32
        Sleep(1000);
#elif defined(__linux__)
        sleep(1);
#endif
    }

    flushBatch();
    std::cout << "\nLogger stopped cleanly.\n";
    delete monitor;
    return 0;
}
