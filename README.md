# Gideon

Gideon is a Windows personal assistant with voice and command-line interfaces. It listens for “Gideon” and speaks responses through the laptop speakers. Recognized commands run directly; other requests use Ollama, with optional OpenAI or OpenRouter fallback.

## Architecture

```text
microphone / CLI
  -> command parser -> tools and SQLite
  -> unrecognized requests -> Ollama or configured cloud provider
```

The background service runs a phrase listener and reminder scheduler. Ollama requests use a 30-second `keep_alive`. Credentials and OAuth tokens are stored through `keyring`, which uses Windows Credential Manager on Windows. The SQLite database lives in `%LOCALAPPDATA%\Gideon`.

## Install on Windows

PowerShell, from this repository:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[google,windows,dev]"
gideon install-vosk-model
gideon setup
gideon doctor
```

Install Ollama, then pull the default 1.5B quantized local model:

```powershell
winget install Ollama.Ollama
ollama pull qwen2.5:1.5b-instruct-q4_K_M
```

If that exact tag is unavailable in your Ollama release, use `ollama pull qwen2.5:1.5b` and change `local_model` in `%LOCALAPPDATA%\Gideon\config.json`.

## Run

```powershell
gideon start                 # quiet background voice service
gideon status
gideon chat                  # interactive text debugging
gideon chat --once "list tasks"
gideon stop
```

Optional per-user logon startup:

```powershell
gideon install-autostart
gideon uninstall-autostart
```

The compatibility command `python main.py chat` also works. Logs are at `%LOCALAPPDATA%\Gideon\gideon.log`.

## Configuration and providers

Run `gideon setup`, or edit `%LOCALAPPDATA%\Gideon\config.json`. Supported modes are `LOCAL_ONLY`, `CLOUD_ONLY`, and `AUTO`. Recognized commands run directly in all modes. In `AUTO`, model requests try Ollama first, then the configured cloud provider. Set `cloud_provider` to `openai` or `openrouter`.

Keys entered by `gideon setup` go into Windows Credential Manager. Environment variables take precedence over stored credentials: `GIDEON_OPENAI_API_KEY`, `GIDEON_OPENROUTER_API_KEY`, `GIDEON_SPOTIFY_CLIENT_ID`, and `GIDEON_SPOTIFY_CLIENT_SECRET`.

## Gmail and Google Calendar

Create a Google Desktop OAuth client JSON with Gmail API and Google Calendar API enabled. Connect each alias separately:

```powershell
gideon google-setup gmail personal C:\secure\google-client.json
gideon google-setup calendar personal C:\secure\google-client.json
gideon google-setup gmail BU C:\secure\bu-google-client.json
gideon google-setup calendar work C:\secure\work-google-client.json
```

Tokens are stored per alias and service. Gideon requests Gmail modify and Calendar scopes. Sending mail and creating, updating, or deleting calendar events requires a single-use confirmation that expires after five minutes.

Examples:

```text
important unread email in work
search email from professor in BU
draft reply saying I can attend
send email to a@example.com subject Hello body See you tomorrow
tomorrow schedule
find free time this week
create event lunch tomorrow at 1 pm
```

## Local assistant commands

```text
add a task buy milk
list tasks
complete task <id>
delete task <id>                 # confirms
remind me to stretch in 20 minutes
remind me to submit report tomorrow at 9 am daily
start a timer for 10 minutes
create note Project: ship the release
search notes for release
edit note <id> to Project: ship version two
remember that my coffee is black
what do you remember about coffee
forget that coffee               # confirms
calculate (18 + 4) / 2
convert 10 km to miles
summarize clipboard              # clipboard is read only here
good morning
good night
```

Spotify commands use its Web API for playback, search, liked songs, shuffle, repeat, and volume. Windows commands support launching configured apps, changing volume, checking battery status, and locking the PC.

## Android Phone Bridge

The Kotlin companion is in `android/`. It uses camera, flashlight, notification, network, alarm, vibration, and foreground-service permissions. Photos and silent videos are saved under `Android/data/com.gideon.bridge/files/Pictures` or `Movies`.

Build with Android Studio (JDK 17+, Android SDK 35), or:

```powershell
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
.\android\gradlew.bat -p android assembleDebug
adb install -r .\android\app\build\outputs\apk\debug\app-debug.apk
```

Pair over the same LAN or Tailscale network:

1. Start the app and grant camera and notification permissions.
2. On the laptop run `gideon pair-phone`.
3. Enter the displayed code and laptop URL (for example `http://100.64.0.2:8766`) in the app.
4. Tap **Start bridge** and allow Gideon through Windows Firewall on private/Tailscale networks if prompted.

Pairing generates a 256-bit secret, encrypts it to an RSA key whose private half never leaves Android Keystore, and stores the laptop copy in Windows Credential Manager. Every request is HMAC-SHA256 authenticated, timestamp-limited, and nonce replay-protected. Prefer Tailscale for encrypted transport outside a trusted private LAN. Phone commands cover alarms, timers, notifications, ringing, battery/charging, approved URLs/apps, flashlight, front/back photos, and silent video start/stop.

## Development

```powershell
ruff format --check gideon tests
ruff check gideon tests
mypy gideon tests
pytest --cov=gideon
```

## Limitations

- Wake detection uses Vosk speech recognition when its model is installed; otherwise speech recognition uses Google's online service.
- Timers run in memory and stop when Gideon exits. Reminders are stored in SQLite.
- Natural-language dates and task priorities use basic parsing and may need explicit wording.
- Web answers use search result titles and links, without fetching page contents.
- Google and Spotify integrations require account authorization. Cloud models require API keys.
- The Android bridge requires device permissions and pairing. Alarms play the system ringtone; there is no alarm-clock screen.
