// Lab Session 2: SQLite3 is a library, not a server process.
//
// This program links libsqlite3 directly and calls it in-process — there is no
// daemon, no socket, no auth handshake. It reads the same storage-internals
// PRAGMAs from C++ that the sqlite3 CLI exposes.
//
// Build:
//   g++ -std=c++17 -o sqlite_demo sqlite_demo.cpp -lsqlite3
// Run:
//   ./sqlite_demo students.db

#include <sqlite3.h>
#include <iostream>
#include <string>

static int print_row(void* /*ctx*/, int ncols, char** vals, char** names) {
    for (int i = 0; i < ncols; ++i)
        std::cout << names[i] << " = " << (vals[i] ? vals[i] : "NULL")
                  << (i + 1 < ncols ? " | " : "\n");
    return 0;
}

static void run(sqlite3* db, const std::string& sql) {
    char* err = nullptr;
    std::cout << "\n-- " << sql << "\n";
    if (sqlite3_exec(db, sql.c_str(), print_row, nullptr, &err) != SQLITE_OK) {
        std::cerr << "error: " << (err ? err : "?") << "\n";
        sqlite3_free(err);
    }
}

int main(int argc, char** argv) {
    const std::string path = (argc > 1) ? argv[1] : "students.db";

    sqlite3* db = nullptr;
    if (sqlite3_open(path.c_str(), &db) != SQLITE_OK) {
        std::cerr << "cannot open " << path << ": " << sqlite3_errmsg(db) << "\n";
        return 1;
    }
    std::cout << "Opened " << path << " in-process via libsqlite3 "
              << sqlite3_libversion() << " (no server, no socket)\n";

    run(db, "CREATE TABLE IF NOT EXISTS students("
            "id INTEGER PRIMARY KEY, name TEXT, gpa REAL)");
    run(db, "INSERT INTO students(name, gpa) VALUES('Alice', 3.8)");

    // Storage internals — same PRAGMAs as the CLI.
    run(db, "PRAGMA page_size");
    run(db, "PRAGMA page_count");
    run(db, "PRAGMA mmap_size = 268435456");
    run(db, "PRAGMA mmap_size");
    run(db, "PRAGMA journal_mode");
    run(db, "SELECT count(*) AS n FROM students");

    sqlite3_close(db);
    return 0;
}
