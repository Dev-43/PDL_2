#pragma once
extern "C" {
#include "sqlite3.h"
}
#include "Shared.hpp"
#include <string>
#include <iostream>
#include <ctime>

class Database {
private:
    sqlite3* db = nullptr;
public:
    Database(const std::string& dbName) {
        if (sqlite3_open(dbName.c_str(), &db) != SQLITE_OK) {
            std::cerr << "Cannot open database: " << sqlite3_errmsg(db) << std::endl;
            if (db) {
                sqlite3_close(db);
                db = nullptr;
            }
            return;
        }
        // Performance PRAGMAs — critical for <1% CPU
        sqlite3_exec(db, "PRAGMA journal_mode=WAL;",   nullptr, nullptr, nullptr);
        sqlite3_exec(db, "PRAGMA synchronous=NORMAL;", nullptr, nullptr, nullptr);
        sqlite3_exec(db, "PRAGMA cache_size=-8000;",   nullptr, nullptr, nullptr);
        sqlite3_exec(db, "PRAGMA temp_store=MEMORY;",  nullptr, nullptr, nullptr);
        createTable();
        addExePathColumnIfMissing();
        sqlite3_exec(db, "CREATE INDEX IF NOT EXISTS idx_ts ON logs(timestamp DESC);", nullptr, nullptr, nullptr);
    }
    ~Database() {
        if (db) {
            sqlite3_exec(db, "PRAGMA wal_checkpoint(TRUNCATE);", nullptr, nullptr, nullptr);
            sqlite3_close(db);
        }
    }
    void createTable() {
        if (!db) return;
        const char* sql =
            "CREATE TABLE IF NOT EXISTS logs ("
            "pid INTEGER, process_name TEXT, parent_pid INTEGER, ram_kb INTEGER,"
            "cpu_usage REAL, thread_count INTEGER, open_handles INTEGER,"
            "net_sent INTEGER, net_recv INTEGER, connections INTEGER,"
            "is_elevated INTEGER, window_title TEXT, exe_path TEXT, timestamp INTEGER);";
        sqlite3_exec(db, sql, nullptr, nullptr, nullptr);
    }
    void addExePathColumnIfMissing() {
        if (!db) return;
        sqlite3_stmt* s;
        sqlite3_prepare_v2(db, "PRAGMA table_info(logs);", -1, &s, nullptr);
        bool has = false;
        while (sqlite3_step(s) == SQLITE_ROW) {
            const char* c = (const char*)sqlite3_column_text(s, 1);
            if (c && std::string(c) == "exe_path") { has = true; break; }
        }
        sqlite3_finalize(s);
        if (!has)
            sqlite3_exec(db, "ALTER TABLE logs ADD COLUMN exe_path TEXT DEFAULT '';", nullptr, nullptr, nullptr);
    }
    void beginTransaction()  { if (db) sqlite3_exec(db, "BEGIN;",  nullptr, nullptr, nullptr); }
    void commitTransaction() { if (db) sqlite3_exec(db, "COMMIT;", nullptr, nullptr, nullptr); }
    void insertLog(const ProcessLog& log) {
        if (!db) return;
        const char* sql =
            "INSERT INTO logs (pid,process_name,parent_pid,ram_kb,cpu_usage,thread_count,"
            "open_handles,net_sent,net_recv,connections,is_elevated,window_title,exe_path,timestamp)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?);";
        sqlite3_stmt* stmt;
        if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK) return;
        sqlite3_bind_int(stmt,    1,  log.pid);
        sqlite3_bind_text(stmt,   2,  log.processName.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_int(stmt,    3,  log.parentPid);
        sqlite3_bind_int64(stmt,  4,  log.ramUsageKB);
        sqlite3_bind_double(stmt, 5,  log.cpuUsage);
        sqlite3_bind_int(stmt,    6,  log.threadCount);
        sqlite3_bind_int(stmt,    7,  log.openHandles);
        sqlite3_bind_int64(stmt,  8,  log.networkBytesSent);
        sqlite3_bind_int64(stmt,  9,  log.networkBytesRecv);
        sqlite3_bind_int(stmt,    10, log.activeConnections);
        sqlite3_bind_int(stmt,    11, log.isElevated ? 1 : 0);
        sqlite3_bind_text(stmt,   12, log.windowTitle.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(stmt,   13, log.exePath.c_str(),     -1, SQLITE_TRANSIENT);
        sqlite3_bind_int64(stmt,  14, log.timestamp);
        sqlite3_step(stmt);
        sqlite3_finalize(stmt);
    }
};
