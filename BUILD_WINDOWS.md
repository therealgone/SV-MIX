# Building a Windows installer (Setup.exe)

This walks through turning the SVMixer source into a distributable
`SVMixer-Setup-<version>.exe` you can hand to someone else to install,
without them needing Python installed at all.

**This must be run on Windows** — PyInstaller builds a native executable
for whatever OS it's run on, it does not cross-compile from Linux/macOS.

## 1. Prerequisites (one-time setup)

1. **Python 3.11 or 3.12** — https://www.python.org/downloads/windows/
   During install, check **"Add python.exe to PATH"**.
   (3.13 is supported by SVMixer itself, but some of librosa's dependencies
   have historically lagged behind the newest Python on Windows — 3.11/3.12
   are the safest bet for a smooth `pip install`.)
2. **ffmpeg** — download a Windows build from
   https://www.gyan.dev/ffmpeg/builds/ (the "essentials" build is enough),
   unzip it somewhere permanent (e.g. `C:\ffmpeg`), then add its `bin`
   folder (e.g. `C:\ffmpeg\bin`) to your system `PATH`
   (Settings → System → About → Advanced system settings → Environment
   Variables → edit `Path`). Confirm it worked with `ffmpeg -version` in a
   **new** terminal window.
3. **Inno Setup** — https://jrsoftware.org/isdl.php (free). This is what
   turns the built app into the actual `Setup.exe` installer wizard.
4. **Git** (to clone the repo) or just copy the project folder over some
   other way — either is fine.

## 2. Get the code and install dependencies

Open a terminal (PowerShell or Command Prompt) in the project folder:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller
```

Sanity check it runs before building anything:

```powershell
python run_app.py
```

The window should open with the SVMixer icon in the title bar and taskbar.
Close it once you've confirmed that.

## 3. Build the standalone app with PyInstaller

From the project root, with the virtualenv still active:

```powershell
pyinstaller packaging\windows\SVMixer.spec --noconfirm
```

This produces `dist\SVMixer\` — a folder containing `SVMixer.exe` and
everything it needs. Test it directly before packaging further:

```powershell
dist\SVMixer\SVMixer.exe
```

If it fails to launch with a `ModuleNotFoundError`, the most common cause
is a hidden import PyInstaller's static analysis missed (librosa's
dependency tree is the usual suspect). Add the missing package name to the
`hiddenimports` list near the top of `packaging\windows\SVMixer.spec` and
rebuild. The spec already handles the most common offenders (`librosa`,
`soundfile`, `pydub`, `PySide6.QtMultimedia`) via `collect_all`.

**ffmpeg is not bundled** into this build — SVMixer shells out to whatever
`ffmpeg` it finds on the end user's `PATH` at runtime, same as the source
version. If ffmpeg isn't installed, the app still opens but shows a warning
dialog with install instructions (same one as the source `README.md`
describes). Whoever you distribute this to needs ffmpeg installed
separately, same as you did in step 1.

## 4. Package it as a Setup.exe installer

Open `packaging\windows\installer.iss` in the Inno Setup IDE (double-click
it, or launch Inno Setup and use File → Open), then **Build → Compile**
(or press `Ctrl+F9`).

Or from the command line, if `ISCC.exe` (Inno Setup's compiler) is on your
`PATH`:

```powershell
ISCC packaging\windows\installer.iss
```

The finished installer is written to `dist\installer\SVMixer-Setup-1.0.0.exe`.
That file is what you distribute — running it installs SVMixer with a
Start Menu entry, an optional desktop shortcut, and a proper uninstaller
listed in "Add or Remove Programs".

## 5. For a real/public release

- Bump `MyAppVersion` at the top of `packaging\windows\installer.iss`
  before each release so the installer filename and "Add or Remove
  Programs" entry stay accurate.
- Generate your own AppId GUID (Inno Setup IDE → Tools → Generate GUID)
  and replace the placeholder in `installer.iss` — keeping this **stable
  across versions** is what lets an installer upgrade an existing install
  in place instead of creating a duplicate entry.
- The installer is unsigned, so Windows SmartScreen will show an
  "unrecognized app" warning on first run (this is normal for any indie/
  unsigned installer — it's not an error in the build). Code-signing
  removes this, but requires purchasing a certificate; out of scope here.
- PySide6/Qt is LGPLv3-licensed. Since this build dynamically links Qt
  (PyInstaller doesn't statically link Qt into the exe) and the app's own
  source is openly available, this satisfies LGPL's terms — no separate
  action needed, just don't switch to a statically-linked Qt build without
  re-checking the license implications.

## 6. Packaging for the Microsoft Store (MSIX)

The `Setup.exe` from step 4 is a normal Win32 installer — fine to hand out
directly, but the Store wants an **MSIX** package. The easiest way to get
one is Microsoft's own **MSIX Packaging Tool**, which wraps your existing
installer without needing any code changes.

### One-time setup

1. Create a developer account at
   [Partner Center](https://partner.microsoft.com/dashboard) (one-time fee:
   ~$19 individual / ~$99 company) and reserve your app name (e.g.
   "SVMixer") under **Apps and Games → New product**. Reserving the name
   generates the **Package/Identity/Name** and **Publisher** values you'll
   need below — Partner Center shows them on the app's *Product identity*
   page, and they must match exactly or the Store submission will be
   rejected.
2. Install the **MSIX Packaging Tool**:
   ```powershell
   winget install 9N5LW3JBCXKF
   ```
   (or search "MSIX Packaging Tool" in the Microsoft Store app).
3. Microsoft's own recommendation is to run the capture step on a **clean
   Windows machine or VM** (no other software installed) so the tool only
   picks up files/registry changes SVMixer's installer actually makes —
   doing it on your regular dev machine works too, just double-check the
   captured file list in step 4 below and remove anything unrelated.

### Capture the package

1. Build `Setup.exe` first (steps 1–4 above) if you haven't already.
2. Open **MSIX Packaging Tool** → **Application package** → **On this
   computer**.
3. Point it at `dist\installer\SVMixer-Setup-1.0.0.exe` and let it run —
   click through your installer's normal install wizard as it launches.
4. Once installed, the tool asks you to launch SVMixer once (so it can
   confirm the app's entry point), then click **Next** to finish capturing.
5. On the **Package information** screen, fill in the **Package
   name**/**Publisher**/**Publisher display name** fields with the exact
   values from Partner Center's *Product identity* page, then set a
   **Package version** (e.g. `1.0.0.0` — MSIX requires 4 dotted parts,
   unlike the installer's 3-part version).
6. Finish the wizard — it writes a `.msix` (or `.msixbundle` if it
   detected multiple architectures) file.

### Test it locally before submitting

MSIX packages need a trusted signing certificate to install outside the
Store. The packaging tool self-signs the package with a test certificate
during capture; to sideload it locally:

```powershell
# one-time: trust the tool's test certificate (path shown by the tool
# after capture, typically ends in .cer)
Import-Certificate -FilePath ".\SVMixer.cer" -CertStoreLocation Cert:\LocalMachine\TrustedPeople

# install the package
Add-AppxPackage -Path ".\SVMixer.msix"
```

If it launches correctly from the Start Menu, it's ready to submit.

### Submit to the Store

Upload the `.msix`/`.msixbundle` on your app's Partner Center *Packages*
page. **You don't need a "real" (paid) code-signing certificate for this
step** — Microsoft re-signs the package with its own Store certificate
during certification, so the test-signed file from the packaging tool is
fine to upload as-is. Partner Center also requires separate Store-listing
assets at this stage (description, screenshots, a square icon, etc.) —
those are configured entirely in the Partner Center dashboard, not part
of this repo.
