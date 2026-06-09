#pragma once
#include "Shared.hpp"
#include <vector>

// Abstract base class for Process Monitoring
class ProcessMonitor {
public:
    virtual ~ProcessMonitor() {}

    // Pure virtual function to be implemented by OS-specific classes
    virtual std::vector<ProcessLog> copyProcesses() = 0;
};
