"""Start the Solar Monitor.

    python3 run.py          then open  http://localhost:5000

Settings are environment variables, all optional (see solar_monitor/config.py):
SOLAR_PORT, SOLAR_ADMIN_PASSWORD, SOLAR_DB, SOLAR_REPORTS, SOLAR_DEBUG.
"""

import logging
import os

from solar_monitor import config, create_app, start_services
from solar_monitor.network_utils import lan_ip


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    app = create_app()
    start_services(app)

    port = config.port()
    print("\n  Solar Monitor is running.")
    print("  On this computer:   http://localhost:%d" % port)
    print("  On your network:    http://%s:%d   (use this address for the ESP32)\n" % (lan_ip(), port))
    if not os.environ.get("SOLAR_ADMIN_PASSWORD"):
        print("  Note: no password is set. Anyone on your network can open the dashboard.")
        print("  Set SOLAR_ADMIN_PASSWORD to require one.\n")
    # use_reloader=False: auto-restarts would briefly drop every connection.
    # Debug mode is off by default because it exposes a remote code console.
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("SOLAR_DEBUG") == "1",
            use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
