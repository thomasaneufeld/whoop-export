# WHOOP Data Export + Dashboard

Export your personal WHOOP data to local JSON/CSV files and view it in a local web dashboard.

## Prerequisites

- Python 3.8+
- A WHOOP account with an active membership
- Google Chrome (the login flow opens Chrome specifically)

## Step 1: Create a WHOOP Developer App

> This step must be done manually in your browser.

1. Go to https://developer.whoop.com and sign in with your WHOOP account
2. Create a new application (sandbox tier works fine for personal use)
3. You need a privacy policy URL. Create a simple Google Doc that says the app is for personal use only and no data is shared with third parties, then publish it (File > Share > Publish to web) and paste that URL
4. Set the redirect URI to `http://localhost:3000/callback`
5. Note your **Client ID** and **Client Secret**

## Step 2: Get the Project Files

Unzip the files you received into a folder on your computer (e.g. `whoop-export` on your Desktop).

## Step 3: Install Dependencies

### Quick setup with Claude Code

Open Claude Code in your whoop-export folder and paste:

```
Install the Python dependencies from requirements.txt
```

### Manual

```bash
pip install -r requirements.txt
```

## Step 4: Configure Credentials

### Quick setup with Claude Code

```
Copy .env.example to .env and open it for me to fill in my
WHOOP Client ID and Client Secret
```

### Manual

Copy `.env.example` to `.env` and fill in your values:

```
WHOOP_CLIENT_ID=your_client_id_here
WHOOP_CLIENT_SECRET=your_secret_here
TIMEZONE=America/Los_Angeles
```

Set `TIMEZONE` to your local timezone (e.g. `America/New_York`, `America/Chicago`, `Europe/London`). This ensures your dashboard data lines up with the dates in the WHOOP app. Defaults to `America/Los_Angeles` if not set.

Never share your `.env` file with anyone.

## Step 5: Login (One Time)

> This step requires you to interact with the browser. Chrome will open and you need to sign in to WHOOP and click Grant.

### Quick setup with Claude Code

```
Run the WHOOP login command: python whoop.py login
```

### Manual

```bash
python whoop.py login
```

Chrome opens to WHOOP's authorization page. Sign in, then click **Grant** when prompted. You only need to do this once. Tokens auto-refresh on every export after that.

## Step 6: Export Your Data

### Quick setup with Claude Code

```
Run the WHOOP data export: python whoop.py export
```

### Manual

```bash
python whoop.py export
```

The first run pulls your full WHOOP history. After that it pulls the last 30 days and merges with existing data, so nothing gets lost.

Options:
- `python whoop.py export --all` pulls everything again
- `python whoop.py export --start 2024-01-01 --end 2024-06-30` for a specific range

Data is saved to `data/` as both JSON and CSV.

## Step 7: View the Dashboard

### Quick setup with Claude Code

```
Start a local web server on port 8080 to serve the dashboard,
then open http://localhost:8080/dashboard.html in Chrome
```

### Manual

Start a local web server:

```bash
python -m http.server 8080
```

Then open http://localhost:8080/dashboard.html in your browser.

The dashboard has three tabs:
- **Today/Yesterday** -- recovery scores, vitals, sleep breakdown, strain, workouts
- **Trends** -- time-series charts for recovery, HRV, sleep, strain, RHR
- **Cardio** -- cardiovascular health metrics, training mix, recovery by workout type

After running a new export, just refresh the page to see updated data.

### Customize the Dashboard

The dashboard is a single HTML file with Chart.js. It's fully customizable -- just ask Claude Code to add new tabs, charts, layouts, or metrics. All your exported data is available in `dashboard_data.json` so Claude can build whatever views you want on top of it.

## Step 8 (Optional): Daily Auto-Export on Windows

### Quick setup with Claude Code

```
Set up a Windows scheduled task to run run_whoop.bat daily at 9am.
Update the path in run_whoop.bat to match this folder.
Enable "run as soon as possible after a missed schedule" so it
catches up when I turn on my computer. The bat script should kill
any existing dashboard server on port 8080, run the export, then
start the dashboard server in the background.
```

### Manual setup

The included `run_whoop.bat` script runs the export and starts the dashboard server. Before using it, **edit the path on line 2** to match your install folder:

```batch
cd /d "C:\your\path\to\whoop-export"
```

To schedule it with Windows Task Scheduler:

1. Open Task Scheduler
2. Create a new task
3. Set the trigger to daily at your preferred time (e.g. 9:00 AM)
4. Under Settings, check "Run task as soon as possible after a scheduled start is missed" so it runs when you turn on your computer if you missed the schedule
5. Set the action to run `run_whoop.bat`

## Security Notes

- Your `.env`, `tokens.json`, `data/`, and `dashboard_data.json` contain personal credentials and health data. The `.gitignore` excludes them from git, and you should never share them.
- The client secret stays in `.env` and is never printed or logged by the script.
- Tokens are stored in `tokens.json` and refresh automatically. If login ever stops working, just run `python whoop.py login` again.
