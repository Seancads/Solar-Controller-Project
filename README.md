# Solar Monitor

An IoT solar power monitor: an ESP32 measures a panel's voltage and current and
sends them to this app (on a Raspberry Pi or any computer). The app shows them
live, logs them, draws trends, raises alerts and makes reports.

| Page | What it does |
|---|---|
| **Dashboard** | Live voltage, current, power, today's peak and energy, a live chart |
| **Analytics** | Daily energy, peak power, power through the day, week-over-week, savings. Works on simulated *or* logged data |
| **Reports** | Pick any period: summary, chart, table, CSV export, printable report. A report for each day is saved automatically at midnight |
| **Alerts** | Low/high voltage, high current, device offline. In-app, plus optional Slack/Discord/webhook, Telegram and email |
| **Devices** | Register ESP32s, get an API key and a ready-made Arduino sketch, see status, signal and uptime |

## The seven modules

Each module is one folder inside `solar_monitor/`. Folder names match the module names.

| # | Module | Folder | Status |
|---|---|---|---|
| 1 | Account Management | `account_management/` | **Partly built.** Register a device and pair it by API key. Not built: user registration and login, and linking a device to a user by MAC address |
| 2 | Hardware Acquisition | `hardware_acquisition/` + `firmware/` | **Built, over HTTP.** The ESP32 posts readings to `/api/ingest`. It does not use MQTT yet |
| 3 | Automated Load Control | *(none yet)* | **Not built.** No relay switching, no battery threshold |
| 4 | Local Gateway & Storage | `gateway_storage/` | **Built, over HTTP.** Receives readings, keeps live state, logs to SQLite, cleans old data. Not MQTT yet |
| 5 | Data Analytics & Visualization | `analytics_visualization/` | **Built.** Dashboard and Analytics pages |
| 6 | Automated Logging & Export | `logging_export/` | **Built.** Reports page, CSV export, a saved report every midnight |
| 7 | Security & Access Control | `security_access_control/` | **Partly built.** One shared password for the web pages. Not built: roles (Admin / Technician) |

Also in the project, but not one of the seven modules: `alerts_notifications/`
(alert rules, the Alerts page, Slack / Telegram / email messages). It works and
is tested, so it was kept. Delete the folder if the capstone should not include it.

A folder for module 3 is not created until the module exists, so there are no empty placeholders.

## Quick start

You need Python 3.9 or newer.

```bash
cd solar-dashboard
pip3 install -r requirements.txt
python3 run.py
```

Open **http://localhost:5000**. On first run it creates a *simulated* device, so
everything works with no hardware. The terminal also prints your network address
(for example `http://192.168.1.39:5000`). Use that address, not `localhost`, from
other devices.

Stop it with `Ctrl+C`. Your data is kept in `data/solar.db`, so it survives restarts. Saved reports go in
`data/reports/`. To back up, copy the `data/` folder while the app is stopped.

## Connect your ESP32

1. Open **Devices > + Add device**, give it a name, leave "Simulated" off, and save.
2. A window appears with the server address and API key. Click **Download Arduino sketch**.
   The address and key are already filled in.
3. Open the sketch in the Arduino IDE (with the "esp32" board package installed).
   Enter your Wi-Fi name and password, then **check the sensor section against your wiring**.
4. Upload it and open the Serial Monitor at 115200 baud. The device card turns
   *Online* within seconds.

The computer running this app and the ESP32 must be on the same network.

### Wiring safety (please read)

* An ESP32 pin must **never exceed 3.3 V**. A solar panel's voltage is higher, so
  the voltage must go through a resistor divider. The sketch explains how to pick
  the resistors. The defaults (100k and 15k) suit a panel up to about 22 V. **Check
  them against your own panel before connecting anything.**
* Use ADC1 pins (32, 33, 34, 35, 36, 39). The other ADC does not work while Wi-Fi is on.
* A current sensor such as the ACS712 outputs up to 5 V. Divide it down too.
* **The sketch has not been run on real hardware** by whoever wrote it. Compare what it
  prints with a multimeter and adjust the calibration values at the top.

### Test without hardware

```bash
curl -X POST http://localhost:5000/api/ingest \
  -H "X-API-Key: PASTE_THE_KEY" -H "Content-Type: application/json" \
  -d '{"voltage": 18.2, "current": 2.1}'
```

`/api/ingest` accepts `voltage` (V) and `current` (A), and optionally `power`,
`firmware`, `rssi` and `uptime_s`. Impossible values are rejected with a 400 and an
explanation. The reply contains the interval the device should use, so you can
change it from the Devices page without re-flashing.

## Alerts and notifications

Alerts are checked on every reading, even when no browser is open.

* An alert fires only after the problem lasts **several readings in a row** (default 3)
  and clears after the same number of good ones. One noisy reading does nothing.
* **Low voltage** only counts during daylight hours (default 07:00 to 17:00),
  because a panel's voltage collapses at night. You can change or switch off the hours.
* **Device offline** fires when a device sends nothing for longer than the rule's
  limit (and never sooner than three of that device's own sending intervals).
* Acknowledging an alert marks it as seen. It stays open until the problem is gone.

To get messages outside the app, open **Alerts > Notifications**, enable a channel,
and press *Save & send test*. Nothing is sent until you do.

* **Slack / Discord**: create an incoming webhook and paste its URL.
* **Telegram**: make a bot with @BotFather (token), message it once, then enter your chat ID.
* **Email**: any SMTP server. For Gmail use `smtp.gmail.com`, port 587, STARTTLS and an *app password*.

Tip: on the Devices page, a simulated device has buttons that make it misbehave
for a short while, so you can see an alert fire and a notification arrive.

## Data, logging and reports

* Readings are logged every 10 seconds by default (5 to 60), and kept for 90 days.
  Change both under **Reports > Logging settings**.
* Energy is power multiplied by time between readings. Gaps where a device was
  silent are *not* counted, so reconnecting never invents energy.
* Reports can be exported as CSV (summary table or every reading) or printed to PDF
  from the browser. Daily reports are saved in the `data/reports/` folder.
* Times use the computer's local time zone.

## Run it on a Raspberry Pi

On Raspberry Pi OS the simplest way to install Flask is `sudo apt install python3-flask`.
Then `python3 run.py` as above. To start it at boot, create
`/etc/systemd/system/solar-monitor.service`:

```ini
[Unit]
Description=Solar Monitor
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/solar-dashboard
Environment=SOLAR_ADMIN_PASSWORD=choose-a-password
ExecStart=/usr/bin/python3 /home/pi/solar-dashboard/run.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

then `sudo systemctl enable --now solar-monitor`. (This service file has not been
tested on a Pi. Adjust the user and paths to match yours.)

## Settings

Set these as environment variables before `python3 run.py`, for example
`SOLAR_ADMIN_PASSWORD=secret python3 run.py`.

| Variable | Meaning |
|---|---|
| `SOLAR_PORT` | Port to listen on (default 5000) |
| `SOLAR_ADMIN_PASSWORD` | Ask for this password (any username) to open the web pages. The ESP32 is unaffected, it uses its API key |
| `SOLAR_DB` | Where to keep the database (default `data/solar.db`) |
| `SOLAR_REPORTS` | Where to save reports (default `data/reports`) |
| `SOLAR_DEBUG=1` | Flask debug mode. Never use on a shared network |

## Security, honestly

This is built for a home or lab network, not the internet.

* It uses plain HTTP, so passwords and keys cross the network unencrypted. Don't expose it to the internet.
* With no `SOLAR_ADMIN_PASSWORD`, anyone on your network can open it and change settings.
* API keys, webhook URLs, bot tokens and email passwords are stored **unencrypted** in `data/solar.db`. Treat that file as private.
* Debug mode is off by default on purpose. It would let anyone on the network run code on your computer.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

There is one test file per module (`tests/test_<module>.py`). They use a throwaway database and local fake servers, so they never touch your data
or the internet. They cover validation, logging, energy maths, restart recovery,
alert behaviour, every notification channel, reports and CSV, and passwords.

## What is simulated or unverified

* The built-in simulator and the Analytics page's **Simulated** source are invented data.
* The ESP32 sketch compiles against stand-in headers but has not run on real hardware.
* Notification senders are tested against local fake servers, not against real Slack,
  Discord, Telegram or an email provider.
* Built and tested on Python 3.9 and 3.12 with Flask 3. Not tested on a Raspberry Pi.

## Project layout

```
run.py                          start the app (python3 run.py)
requirements.txt
firmware/                       ESP32 sketch template        (module 2)
data/                           your database and saved reports (private, not in git)
tests/                          test_<module>.py, one per module
solar_monitor/
  __init__.py                   builds the web app and starts the background threads
  config.py                     file locations and environment settings
  web_helpers.py                small helpers the route files share
  network_utils.py              finds this computer's address for the ESP32
  time_utils.py                 start-of-day helper
  account_management/           module 1
    device_registry.py            devices table: add, rename, API keys
    device_routes.py              Devices page and its /api/devices... addresses
  hardware_acquisition/         module 2
    ingest_routes.py              /api/ingest and /api/device/config (what the ESP32 calls)
    reading_validation.py         rejects impossible voltage / current / power
    simulator.py                  a pretend ESP32 for demos and testing
  gateway_storage/              module 4
    database.py                   SQLite connection, tables, settings, readings
    ingest_pipeline.py            every reading: live state -> database -> alerts
    live_state.py                 latest values, today's peak and energy, online status
    background_tasks.py           simulator, offline watchdog, cleanup threads
    storage_routes.py             logging-interval and retention settings
  analytics_visualization/      module 5
    routes.py                     Dashboard and Analytics pages and their data
    live_data.py                  what the live dashboard shows
    logged_analytics.py           daily and hourly figures from logged readings
    demo_data.py                  invented history for the "Simulated" source
  logging_export/               module 6
    routes.py                     Reports page, CSV download, print view
    report_data.py                date ranges, summaries, time buckets
    csv_export.py                 CSV files
    scheduled_reports.py          saved reports and the midnight daily report
  security_access_control/      module 7
    password_gate.py              the optional shared password
  alerts_notifications/         extra, not one of the seven
    alert_engine.py               rules and the alert engine
    notifier.py                   webhook / Telegram / email
    routes.py                     Alerts page and its addresses
  templates/  static/           web pages and scripts, in one folder per module
```
