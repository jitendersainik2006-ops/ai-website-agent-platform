import os
import sys

# Support explicit CLI flags for isolated in-memory test database mode
cli_isolated = any(arg in sys.argv for arg in ("--isolated", "-i", "--mock", "--mock-db"))
if cli_isolated:
    os.environ["ISOLATED_LOCAL_DB"] = "true"

from app import create_app

app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
