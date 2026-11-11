"""
Error Logger v1.0.0
Crude Accountability
Created by: Andrew Zitnik
Last Modified: 11/10/2026

This script wraps around every script call in the .bat file to capture script specific errors.
"""

import sys, subprocess, threading
from datetime import datetime


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def pump_stderr(stream, log):
    """
    Timestamps each stderr line as it arrives and writes it to the console and the error log.

    Args:
        stream: The child process stderr pipe
        log: Open error log file
    """
    for line in stream:
        timestamped_line = f"[{timestamp()}] {line.rstrip()}"
        print(timestamped_line, file=sys.stderr, flush=True)
        log.write(timestamped_line + "\n")
        log.flush()

def main():
    if len(sys.argv) < 3:
        print(
            "Usage: python error_logger.py <error_log> <script> [arguments...]"
        )
        sys.exit(1)
    error_log = sys.argv[1]
    script = sys.argv[2]
    arguments = sys.argv[3:]
    command = [sys.executable, "-u", script] + arguments   # -u: unbuffered, so lines arrive as they happen
    with open(error_log, "a", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        reader = threading.Thread(target=pump_stderr, args=(process.stderr, log))
        reader.start()
        for line in process.stdout:
            print(line, end="", flush=True)
        reader.join()
        process.wait()
        if process.returncode != 0:
            log.write(f"[{timestamp()}] {script} exited with code {process.returncode}\n")
        log.flush()
    sys.exit(process.returncode)

if __name__ == "__main__":
    main()