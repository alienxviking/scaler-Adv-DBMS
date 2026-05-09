// raw_io.cpp
// Program to read and write a file using raw system calls
// Compile with: g++ raw_io.cpp -o raw_io

#include <fcntl.h>    // For open(), O_CREAT, O_WRONLY, etc.
#include <unistd.h>   // For read(), write(), close()

// Helper function to calculate string length (since we can't use <cstring>)
int string_length(const char* str) {
    int len = 0;
    while (str[len] != '\0') {
        len++;
    }
    return len;
}

int main() {
    const char* filename = "test_file.txt";
    const char* message = "Hello from raw system calls!\n";
    char buffer[100];

    // 1. Write to the file
    // O_CREAT: Create file if it doesn't exist
    // O_WRONLY: Open for writing only
    // O_TRUNC: Truncate file to 0 length if it exists
    // 0644: File permissions (rw-r--r--)
    int fd_write = open(filename, O_CREAT | O_WRONLY | O_TRUNC, 0644);
    if (fd_write < 0) {
        // Error handling without libraries is tricky, so we just return error code
        return 1;
    }

    // Write the message to the file descriptor
    int bytes_written = write(fd_write, message, string_length(message));
    if (bytes_written < 0) {
        close(fd_write);
        return 2;
    }

    // Close the file descriptor
    close(fd_write);

    // 2. Read from the file
    // O_RDONLY: Open for reading only
    int fd_read = open(filename, O_RDONLY);
    if (fd_read < 0) {
        return 3;
    }

    // Read the content into our buffer
    int bytes_read = read(fd_read, buffer, sizeof(buffer) - 1);
    if (bytes_read < 0) {
        close(fd_read);
        return 4;
    }

    // Null-terminate the string
    buffer[bytes_read] = '\0';

    // 3. Write the read content to standard output (file descriptor 1)
    write(1, "Read from file: ", 16);
    write(1, buffer, bytes_read);

    // Close the file descriptor
    close(fd_read);

    return 0;
}
