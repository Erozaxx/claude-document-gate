# Claude Document Gate

Česky: [README.cs.md](README.cs.md)

A hook for Claude Code that converts documents to Markdown on your computer before the model reads them.

When your prompt points to a PDF, DOCX, PPTX, XLSX or EPUB file, the hook stops the prompt first. It converts the file locally with [Microsoft MarkItDown](https://github.com/microsoft/markitdown), runs a simple regex sanitization over the text and saves a clean `.md` copy. The model then gets your original request with the file path replaced by the path to that copy.

HTML, CSV, TXT and MD files can be turned on in the [configuration](#configuration). They are off by default so that the hook does not redirect ordinary project files such as a README. For plain text the conversion saves no tokens.

A hook is a small program that Claude Code runs automatically at a set moment. This one runs every time you send a prompt, before the model sees it.

## Why

The main reason is token usage. The model reads plain text and does not have to process a PDF or an Office file, which usually costs much more.

The second effect is basic masking of some sensitive values. It is on by default and can be turned off. The sanitizer replaces e-mail addresses, IPv4 addresses, phone numbers, IBANs, Czech birth numbers (rodné číslo), Bearer tokens and some API keys with markers such as `[REDACTED_EMAIL_3f2a91c0d4]`.

The masking is a side benefit. It does not replace a DLP tool or anonymization. It does not recognize names, postal addresses, company identifiers or text inside images.

## How it works

```
You send a prompt
   |
   v
hook.py runs on your computer, the model has not seen anything yet
   |
   +-- no existing file with a configured extension
   |     -> prompt goes to the model unchanged
   |
   +-- existing document found
         |
         +-- blocked format, too large, empty after conversion
         |   or a configuration error
         |     -> prompt blocked, the reason is shown to you
         |
         +-- otherwise
               1. MarkItDown converts the file to Markdown
               2. regex sanitization masks e-mails, phones, IBANs...
                  (can be turned off)
               3. the copy is saved as sanitized_<name>_<hash>.md
                  (converted_<name>_<hash>.md without sanitization)
               4. your original prompt is blocked
               5. the hook sends the rewritten prompt into the same session
               6. the model works with the .md copy
```

Example on Windows. You type:

```text
Summarize "C:\Users\me\Documents\report.pdf"
```

Claude Code shows that the original prompt was blocked and lists the sanitized file. The model then receives a message like this:

```text
[DOCUMENT_GATE: SANITIZED]
Original user request (all detected document references have been replaced by validated sanitized references):
Summarize "C:\Users\me\local_app\claude_document_gate\sanitized\sanitized_report_9b1c47e0a2d3.md"

Validated local sanitized files:
- "C:\Users\me\local_app\claude_document_gate\sanitized\sanitized_report_9b1c47e0a2d3.md"

The original attachment was blocked BEFORE this turn. Only use the sanitized files above; ...
```

Inside the sanitized copy, a line such as `Contact: jane.doe@example.com, +420 731 456 789` becomes:

```text
Contact: [REDACTED_EMAIL_3f2a91c0d4], [REDACTED_PHONE_8e07b5c219]
```

The same value always gets the same marker on your computer. The model can still tell that two mentions refer to the same address.

## Supported platforms

| Platform | Status |
|---|---|
| Windows, Claude Code installed directly in Windows | Supported |
| WSL (Ubuntu and others) and Linux | Supported |
| macOS | Planned. The installer stops with a warning unless you add `--allow-macos`. |

The hook works with Claude Code, the command-line tool. It does not work in the Claude.ai chat in a browser or in the Claude desktop chat.

## Installation on Windows

### 1. Install Python

You need Python 3.10 to 3.14.

Option 1: download the installer from [python.org](https://www.python.org/downloads/windows/). On the first screen, tick **Add python.exe to PATH**.

Option 2: open PowerShell and run:

```powershell
winget install Python.Python.3.12
```

Close PowerShell, open a new window and check the version:

```powershell
py -3 --version
```

### 2. Download the project

Pick a folder where the project can stay permanently, for example `C:\Tools\claude-document-gate`. Claude Code will run the hook from this folder. Do not move it after installation.

Option A, with git:

```powershell
git clone https://github.com/Erozaxx/claude-document-gate.git C:\Tools\claude-document-gate
```

Option B, without git: open https://github.com/Erozaxx/claude-document-gate, click the green **Code** button and choose **Download ZIP**. Extract the archive and rename the extracted folder `claude-document-gate-main` to `C:\Tools\claude-document-gate`.

### 3. Run the installer

```powershell
cd C:\Tools\claude-document-gate
py -3 install.py
```

The installer:

1. checks the Python version,
2. creates a private Python environment in the `.venv` subfolder, so nothing is installed system-wide,
3. installs `markitdown[all]` into it (needs internet, can take a few minutes),
4. checks that MarkItDown loads and runs the project tests,
5. creates `config.json` from `config.default.json` if it does not exist,
6. only then adds the hook to the Claude Code settings in `%USERPROFILE%\.claude\settings.json`.

Before it changes `settings.json`, it saves a backup next to it as `settings.json.document-gate.bak`. Other hooks and settings stay as they are. Running the installer again is safe and does not add the hook twice.

If step 3 or 4 fails, `settings.json` is not touched.

### 4. Restart Claude Code and check

Close all running Claude Code windows and start Claude Code again. Type `/hooks` to see the registered hooks. A `UserPromptSubmit` hook pointing to `hook.py` in your project folder should be there.

Then try it with any PDF or Word file you have:

```text
Summarize "C:\Users\me\Documents\some-file.pdf"
```

You should see a message that the original prompt was blocked, followed by the model's answer based on the sanitized copy.

## Installation on WSL or Linux

WSL and Windows are separate environments. If you use Claude Code in both, install the hook in both.

### 1. Install Python

On Ubuntu:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
python3 --version
```

The version must be 3.10 to 3.14.

### 2. Download the project

Pick a permanent folder, for example `~/tools/claude-document-gate`. Do not move it after installation.

Option A, with git:

```bash
git clone https://github.com/Erozaxx/claude-document-gate.git ~/tools/claude-document-gate
```

Option B, without git:

```bash
sudo apt install unzip wget
mkdir -p ~/tools
cd ~/tools
wget https://github.com/Erozaxx/claude-document-gate/archive/refs/heads/main.zip
unzip main.zip
mv claude-document-gate-main claude-document-gate
rm main.zip
```

### 3. Run the installer

```bash
cd ~/tools/claude-document-gate
python3 install.py
```

The steps are the same as on Windows. The settings file is `~/.claude/settings.json`, or `$CLAUDE_CONFIG_DIR/settings.json` if you have that variable set.

### 4. Restart Claude Code and check

Restart Claude Code, type `/hooks` and test with a file:

```text
Summarize "/home/me/documents/some-file.pdf"
```

## Recommended setting: turn off file mentions

When you type `@file.pdf`, Claude Code can load the file content into the prompt on its own, before the hook sees it. Set `CLAUDE_CODE_DISABLE_FILE_MENTIONS=1` so that `@path` stays plain text and the hook can handle it. The variable is available in Claude Code 2.1.299 and later.

PowerShell, only for the current window:

```powershell
$env:CLAUDE_CODE_DISABLE_FILE_MENTIONS = '1'
claude
```

PowerShell, permanently for your user account (takes effect in new windows):

```powershell
setx CLAUDE_CODE_DISABLE_FILE_MENTIONS 1
```

bash, only for one start:

```bash
CLAUDE_CODE_DISABLE_FILE_MENTIONS=1 claude
```

bash, permanently:

```bash
echo 'export CLAUDE_CODE_DISABLE_FILE_MENTIONS=1' >> ~/.bashrc
source ~/.bashrc
```

## Usage

Write the prompt as usual and include the file path.

```text
Find all e-mail addresses in docs/report.pdf
What does this contract say about penalties? "C:\Users\me\Documents\contract.docx"
Compare the numbers in "Q3 results.xlsx" and "Q4 results.xlsx"
```

Put paths with spaces in quotes. Without quotes the hook cannot tell where the path ends.

Relative paths are resolved from the folder where Claude Code runs. `@docs/report.pdf` also works if file mentions are turned off.

In WSL you can paste a Windows path. `C:\Users\me\report.pdf` is converted to `/mnt/c/Users/me/report.pdf`.

By default the hook converts `.pdf .docx .pptx .xlsx .epub` and blocks the extensions listed in the next section. Other file types (for example `.md`, `.json` or `.py`) are ignored and the prompt passes unchanged. Both lists can be changed in the [configuration](#configuration).

If you refer to a sanitized copy that the hook created earlier, the prompt passes unchanged. The hook checks the copy's signature first.

The hook also skips messages that Claude Code itself puts into the session: notices about finished background agents (`<task-notification>`), messages from other sessions (`<cross-session-message>`, "Another Claude session sent a message") and its own delivered message (`[DOCUMENT_GATE: SANITIZED]` or `[DOCUMENT_GATE: CONVERTED]`). It recognizes them by how the text starts.

## When the hook blocks the prompt without sending it on

In these cases the prompt is blocked, nothing goes to the model and Claude Code shows the reason:

| Reason | What to do |
|---|---|
| The file has an extension from `block_extensions`. By default `.doc .xls .ppt .zip .7z .png .jpg .jpeg .exe .bin` | Save the file as DOCX, XLSX, PPTX or PDF and try again. |
| The file is larger than 25 MiB | Split the document or export only the part you need. |
| Conversion produced no text | Usually a scanned PDF without a text layer. Run OCR on it in another tool first. |
| The prompt refers to an existing document and is longer than 14,000 characters or contains pasted content | Send a shorter prompt and refer to the file by its path. |
| Claude Code sent the file as an attachment (image, drag and drop) | Write the file path in the prompt instead. |
| The prompt points to a `converted_` copy while sanitization is on | Refer to the original document. The hook converts it again with sanitization. |
| Configuration error, the message starts with `Document gate config error:` | Fix the place named in the message: invalid JSON, unknown key, wrong value in `config.json` or in an environment variable. |

While the configuration is broken, the hook uses the default lists. Prompts without an existing file from those lists pass, prompts with such a file are blocked.

The hook acts only on files that exist on disk. A prompt such as `Save the summary as summary.docx` passes unchanged when there is no such file yet, because no document content can reach the model. In a prompt with several paths, existing files are replaced with copies and the others stay as plain text.

## Configuration

Settings are in `config.json` in the project folder, for example `C:\Tools\claude-document-gate\config.json` or `~/tools/claude-document-gate/config.json`. The installer creates it as a copy of `config.default.json` if it does not exist yet. Updates and new installer runs never overwrite it.

Default content:

```json
{
  "convert_extensions": [".pdf", ".docx", ".pptx", ".xlsx", ".epub"],
  "block_extensions": [".doc", ".xls", ".ppt", ".zip", ".7z", ".png", ".jpg", ".jpeg", ".exe", ".bin"],
  "sanitize": true
}
```

Open it in any text editor:

```powershell
notepad C:\Tools\claude-document-gate\config.json
```

```bash
nano ~/tools/claude-document-gate/config.json
```

The hook reads the configuration on every prompt. A change in `config.json` takes effect with your next prompt, without restarting Claude Code.

### Keys

| Key | Default | Meaning |
|---|---|---|
| `convert_extensions` | `.pdf .docx .pptx .xlsx .epub` | Files to convert. Allowed values: `.pdf .docx .pptx .xlsx .html .htm .epub .csv .txt .md`. |
| `block_extensions` | `.doc .xls .ppt .zip .7z .png .jpg .jpeg .exe .bin` | Existing files with these extensions are blocked without conversion. Any extension is allowed. |
| `sanitize` | `true` | `false` turns off masking. Documents are only converted to Markdown. |

All keys are optional. An unknown key is a configuration error. An extension listed in both lists is blocked. A file whose extension is in neither list is ignored and the prompt passes unchanged.

### Environment variables

| Variable | Replaces | Value |
|---|---|---|
| `DOCUMENT_GATE_EXTENSIONS` | `convert_extensions` | Extensions separated by commas, for example `pdf,docx,md`. The dot is optional, case does not matter. |
| `DOCUMENT_GATE_BLOCK_EXTENSIONS` | `block_extensions` | Same format. An empty value blocks nothing. |
| `DOCUMENT_GATE_SANITIZE` | `sanitize` | `1` or `0`, `true` or `false`, `on` or `off`, `yes` or `no`. |
| `DOCUMENT_GATE_HOME` | data folder | Path to a folder, see [Where files are stored](#where-files-are-stored). |

Order of priority, from lowest: built-in defaults, `config.default.json`, `config.json`, environment variables.

The hook gets its environment variables from Claude Code. After you set or change a variable, restart Claude Code.

### Example: convert .md and .txt files too

In `config.json`, change the `convert_extensions` line to:

```json
  "convert_extensions": [".pdf", ".docx", ".pptx", ".xlsx", ".epub", ".md", ".txt"],
```

From then on, existing `.md` and `.txt` files in your project are handled like any other document. If you write `Fix the typo in README.md`, the model gets a copy of the file instead of the original.

### Example: conversion only, without sanitization

If you only care about tokens, set:

```json
  "sanitize": false
```

Copies are then named `converted_<name>_<hash>.md`, the message for the model starts with `[DOCUMENT_GATE: CONVERTED]` and the text of your prompt is not masked either. When you turn sanitization back on, the hook converts each document again into a `sanitized_` copy the next time you refer to it.

While sanitization is on, the hook blocks any prompt that points directly to an old `converted_` copy, because that copy is not masked. Refer to the original document instead. The hook then converts it again with sanitization.

### Example: block nothing

In `config.json`:

```json
  "block_extensions": [],
```

In WSL or Linux you can use an empty environment variable instead:

```bash
export DOCUMENT_GATE_BLOCK_EXTENSIONS=
```

On Windows, use `config.json` for this. Windows tools often remove a variable instead of setting it to an empty value.

### Setting a variable permanently

PowerShell (takes effect in new windows):

```powershell
setx DOCUMENT_GATE_SANITIZE 0
```

bash:

```bash
echo 'export DOCUMENT_GATE_SANITIZE=0' >> ~/.bashrc
source ~/.bashrc
```

Then restart Claude Code.


## Where files are stored

| | Windows | WSL / Linux |
|---|---|---|
| Copies (`sanitized_` and `converted_`) | `%USERPROFILE%\local_app\claude_document_gate\sanitized\` | `~/local_app/claude_document_gate/sanitized/` |
| Signing key | `%USERPROFILE%\local_app\claude_document_gate\verification.key` | `~/local_app/claude_document_gate/verification.key` |

Each `sanitized_<name>_<hash>.md` or `converted_<name>_<hash>.md` has a `.meta.json` file next to it. It holds the hash of the copy, its signature, the sanitizer version, whether the copy was sanitized and the number of masked values per type. The hook trusts a copy only if the hash and signature match.

`verification.key` is a random key created on first use. It signs the copies and generates the markers. Do not share it. If you delete it, a new one is created and all existing copies are converted again the next time you refer to the original.

Nothing is deleted automatically. If the documents contain customer data, delete old copies yourself.

To store the data elsewhere, set the `DOCUMENT_GATE_HOME` variable to another folder in the environment where Claude Code runs.

## Updating

With git:

```bash
cd ~/tools/claude-document-gate
git pull
python3 install.py
```

Without git: download a new ZIP and extract it over the existing folder. If you edited `session_message.json`, keep your version. Your `config.json` is not part of the ZIP and stays as it is. Then run the installer again:

```powershell
cd C:\Tools\claude-document-gate
py -3 install.py
```

To update MarkItDown to the newest version as well, add `--upgrade`:

```powershell
py -3 install.py --upgrade
```

If you used an earlier version: HTML, CSV, TXT and MD files are no longer converted by default. To get the old behavior, add them to `convert_extensions`.

## Uninstalling

```powershell
py -3 install.py --uninstall
```

(on WSL: `python3 install.py --uninstall`)

On macOS, `--uninstall` works without `--allow-macos`.

This removes only this hook from `settings.json`. Other hooks stay. The previous `settings.json` is saved as `settings.json.document-gate.bak`. The installer prints where the `.venv` folder and the sanitized copies are. It does not delete them, so remove them by hand if you no longer need them. Restart Claude Code afterwards.

If you want to move the project folder, uninstall first, move it, then run `install.py` again in the new location.

## Troubleshooting

### The rewritten prompt did not arrive in the session

The hook blocks your prompt and sends the rewritten one through the session inbox of Claude Code. If that fails, the block message lists the sanitized file and ends with `Session notification failed:` followed by the error type. Your original prompt stays blocked.

1. Type `/status` and check that **Peer address** has a value and does not say `unavailable`.
2. Continue by hand. Copy the sanitized path from the hook message into a new prompt:

```text
Summarize "C:\Users\me\local_app\claude_document_gate\sanitized\sanitized_report_9b1c47e0a2d3.md"
```

The hook lets this prompt through, because it refers only to a signed copy.

### Claude Code shows "Held peer message"

The full message says that the sender did not attest its permission mode. Claude Code held the message from the hook and asks whether to deliver it. This is about verifying the sender. The document and the conversion are fine.

Choose **Deliver this message to Claude**. You have to confirm each message separately.

We do not recommend setting `crossSessionInbound: "accept"` in the settings. It would accept messages from any other session on your computer, not only from this hook.

### The installer fails on pip or network

`settings.json` stays unchanged. Check the internet connection. Behind a company proxy, set `HTTPS_PROXY` before running the installer. Then run the installer again.

If the installer reports that the virtual environment is incomplete, delete the `.venv` folder in the project and run it again.

### The hook does not react at all

Restart Claude Code. Type `/hooks` and check that the hook is listed. Check that the file extension is in `convert_extensions` and that the path is correct. If the file does not exist at that path, the hook lets the prompt through unchanged.

### The model reads the PDF directly on Windows

Claude Code on Windows runs hooks through Git Bash. Git Bash drops backslashes from paths, so a command such as `D:\Tools\...\python.exe` cannot start. Claude Code then reports a non-blocking hook error and sends the prompt with the document to the model.

Run the installer again. It writes the command with forward slashes and double quotes, for example `"D:/Tools/claude-document-gate/.venv/Scripts/python.exe" "D:/Tools/claude-document-gate/hook.py"`, and replaces the old entry. After registration it runs that exact command the same way Claude Code does (Git Bash on Windows, `/bin/sh` on Linux). If the hook cannot start, the installer prints a clear warning and exits with code 1.

The project path must not contain double quotes, `$`, a backtick or a backslash after conversion. The installer stops with an error in that case.

## Limitations and security

### Unofficial delivery protocol

The rewritten prompt is sent into the session through the Claude Code inbox socket. This protocol is not documented as a stable interface. The implementation is based on reverse engineering in [claude-code-socket-transport](https://github.com/PeterSR/claude-code-socket-transport) and on the [cross-session messaging documentation](https://code.claude.com/docs/en/cross-session-messaging). It can change with any Claude Code update. The message format is therefore kept in `session_message.json` so you can adjust it without touching the code.

### Not a hard security boundary

If the hook does not finish within the time limit (180 seconds), Claude Code can let the original prompt through. The same happens when the hook cannot start at all, for example because of a wrong path in `settings.json`. Claude Code treats that as a non-blocking error.

### The model can still open the original

The hook checks only the text of your prompt. The agent can open the original file with another tool, for example Read or a shell command, if it learns the path in some other way. If you need to prevent this, add `PreToolUse` rules that block access to those folders.

### File names are visible

The sanitized copy keeps the original file name, for example `sanitized_Contract_Smith_<hash>.md`.

### Sanitization is only a set of regular expressions

It can miss values in unusual formats and can mask harmless numbers that look like phone numbers. IBANs are checked by length per country, without the checksum. MarkItDown can skip images, embedded objects and some tables.

### Skipped system messages can be imitated

The hook recognizes messages from Claude Code by how they start. This follows the current Claude Code format and can stop working after an update. A prompt that starts the same way, for example with `[DOCUMENT_GATE:`, passes without a check. The hook guards against accidental leaks, it cannot stop its own user from going around it.

### Tested versions

Delivery on Linux and WSL goes through a Unix socket, on Windows through a named pipe. Both were tested in October 2026: WSL with the Claude Code command-line tool, Windows with the Claude desktop app (Claude Code 2.1.295). In both cases the rewritten prompt arrived in the session without manual approval. Other versions can behave differently.

## For advanced users

### Project files

| File | Purpose |
|---|---|
| `hook.py` | Entry point called by Claude Code. Reads the prompt, decides whether to block, sends the rewritten prompt into the session. |
| `document_gate.py` | Finds paths in the prompt, converts files, stores and verifies the sanitized copies. |
| `sanitizer.py` | Regular expressions for masking. |
| `config.py` | Loads and checks the configuration from the files and environment variables. |
| `config.default.json` | Default configuration, part of the project. |
| `config.json` | Your configuration, created by the installer. Not part of the repository. |
| `message_format.py` | Builds the message for the session inbox from `session_message.json`. |
| `session_message.json` | Template of the inbox message and the text the model receives. |
| `session_transport.py` | Writes the message to the Unix socket (Linux, WSL) or the named pipe (Windows). |
| `install.py` | Installer, updater and uninstaller. |
| `tests/` | Tests run by the installer. |

### Installer options

| Option | Effect |
|---|---|
| `--upgrade` | Updates MarkItDown and its dependencies. |
| `--skip-tests` | Skips the tests before registering the hook. |
| `--uninstall` | Removes the hook from `settings.json`. |
| `--allow-macos` | Continues the installation on macOS, which is not supported yet. Not needed for `--uninstall`. |

### Editing session_message.json

`auth_frame` and `message_frame` are the two lines sent to the inbox. They can use `${token}`, `${session_id}`, `${msg_id}` and `${content}`. `body_template` is the text the model receives and becomes `${content}`. It can use `${prompt}` (your rewritten request), `${files}` (list of copies), `${mode}` (`SANITIZED` or `CONVERTED`) and `${adj}` (`sanitized` or `converted (sanitization OFF)`).

If Claude Code changes the inbox format, this is the only file you should need to edit.

### Adding sanitizer rules

Add a new `(name, regex)` pair to `PATTERNS` in `sanitizer.py`. Then increase `SANITIZER_VERSION` by one. Copies created by the older version are no longer trusted, and each document is converted again the next time you refer to it. Old `.md` copies stay on disk until you delete them.

### Running the tests

Windows:

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
```

WSL / Linux:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## License

MIT, see [LICENSE](LICENSE). Copyright (c) 2026 Tomáš Nekolný.

Document conversion is done by [Microsoft MarkItDown](https://github.com/microsoft/markitdown). Thanks to its authors.
