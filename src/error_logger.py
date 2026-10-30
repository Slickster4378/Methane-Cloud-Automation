"""
Error Logger v1.0.0
Crude Accountability
Created by: Andrew Zitnik
Last Modified: 08/19/2026

This script wraps around every script call in the .bat file to capture script specific errors.
"""

import subprocess
import sys
from datetime import datetime


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: python error_logger.py <error_log> <script> [arguments...]"
        )
        sys.exit(1)
    error_log = sys.argv[1]
    script = sys.argv[2]
    arguments = sys.argv[3:]
    command = [sys.executable, script] + arguments
    with open(error_log, "a", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        # Display normal output normally
        for line in process.stdout:
            print(line, end="")
        # Timestamp error output
        for line in process.stderr:
            line = line.rstrip()
            timestamped_line = f"[{timestamp()}] {line}"
            print(timestamped_line, file=sys.stderr)
            log.write(timestamped_line + "\n")
        process.wait()
        if process.returncode != 0:
            log.write(f"[{timestamp()}] {script} exited with code {process.returncode}\n")
        log.flush()
    sys.exit(process.returncode)

if __name__ == "__main__":
    main()