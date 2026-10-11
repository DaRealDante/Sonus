"""Sonus - installa / aggiorna / disinstalla.

Usato da INSTALLA_E_AGGIORNA.bat e DISINSTALLA_TUTTO.bat (che chiamano solo questo script).
Usa solo la libreria standard di Python.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
import zipfile

LOCAL = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
ROAMING = os.environ.get("APPDATA", os.path.expanduser("~"))
HOME = os.path.join(LOCAL, "Sonus", "Sorgente")
INSTALL_DIR = os.path.join(LOCAL, "Programs", "Sonus")
DATA_DIR = os.path.join(ROAMING, "Sonus")
REPO_URL = "https://github.com/DaRealDante/Sonus"
HERE = os.path.dirname(os.path.abspath(__file__))
CI = "--ci" in sys.argv
SKIP_DIRS = {".git", ".venv", "build", "dist", "build_bin", "installer", "__pycache__"}


def say(text=""):
    print(text, flush=True)


def finish(code=0):
    if CI:
        sys.exit(code)
    say()
    try:
        input("Premi Invio per chiudere...")
    except EOFError:
        pass
    sys.exit(code)


def fail(text):
    say()
    say(f"[ERRORE] {text}")
    say("Fai uno screenshot di questa finestra e mandalo.")
    finish(1)


def run(command, **kwargs):
    result = subprocess.run(command, **kwargs)
    if result.returncode != 0:
        fail("Comando non riuscito: " + " ".join(str(part) for part in command[:4]) + " ...")
    return result


def samePath(first, second):
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def safeCopy(sourcePath, destinationPath):
    for attempt in range(3):
        try:
            return shutil.copy2(sourcePath, destinationPath)
        except PermissionError:
            try:
                if os.path.exists(destinationPath):
                    os.chmod(destinationPath, 0o666)
                    os.remove(destinationPath)
            except OSError:
                pass
            time.sleep(0.5)
    try:
        return shutil.copy2(sourcePath, destinationPath)
    except OSError as error:
        if os.path.splitext(sourcePath)[1].lower() in (".bat", ".md", ".txt"):
            say(f"  (salto {os.path.basename(sourcePath)}: bloccato da Windows o dall'antivirus)")
            return destinationPath
        raise error


def copySource(source, destination):
    def ignore(directory, names):
        return [name for name in names if name in SKIP_DIRS]
    shutil.copytree(source, destination, ignore=ignore, dirs_exist_ok=True, copy_function=safeCopy)


def extractUpdate(zipPath):
    say(f"Estraggo l'aggiornamento {os.path.basename(zipPath)}...")
    with tempfile.TemporaryDirectory() as tempFolder:
        with zipfile.ZipFile(zipPath) as archive:
            archive.extractall(tempFolder)
        for root, directories, files in os.walk(tempFolder):
            if os.path.basename(root) == "app" and "config.py" in files:
                copySource(os.path.dirname(root), HOME)
                say("Aggiornamento estratto.")
                return
    fail("Lo zip non contiene Sonus.")


def fileMd5(path):
    with open(path, "rb") as handle:
        return hashlib.md5(handle.read()).hexdigest()


def appVersion(root=None):
    with open(os.path.join(root or HOME, "app", "config.py"), encoding="utf-8") as handle:
        match = re.search(r'VERSION\s*=\s*"([^"]+)"', handle.read())
    return match.group(1) if match else "0"


def findIscc():
    candidates = [
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Inno Setup 6", "ISCC.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Inno Setup 6", "ISCC.exe"),
        os.path.join(LOCAL, "Programs", "Inno Setup 6", "ISCC.exe"),
    ]
    return next((path for path in candidates if os.path.isfile(path)), None)


def restoreUpdateRepo():
    """Keeps UPDATE_REPO filled in after copying a new zip over the source (the zip ships it empty)."""
    if not os.path.isdir(os.path.join(HOME, ".git")) or not shutil.which("git"):
        return
    remote = subprocess.run(["git", "-C", HOME, "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", remote)
    if not match:
        return
    configPath = os.path.join(HOME, "app", "config.py")
    with open(configPath, encoding="utf-8") as handle:
        configText = handle.read()
    newText = re.sub(r'UPDATE_REPO\s*=\s*"[^"]*"', f'UPDATE_REPO = "{match.group(1)}/{match.group(2)}"', configText)
    if newText != configText:
        with open(configPath, "w", encoding="utf-8") as handle:
            handle.write(newText)


def build(root=None):
    root = root or HOME
    if not CI:
        restoreUpdateRepo()
    os.chdir(root)
    venvPython = os.path.join(root, ".venv", "Scripts", "python.exe")
    if not os.path.isfile(venvPython):
        say("[1/4] Creo l'ambiente Python...")
        run([sys.executable, "-m", "venv", ".venv"])
    else:
        say("[1/4] Ambiente Python trovato")

    hashFile = os.path.join(root, ".venv", "requirements.md5")
    currentHash = fileMd5("requirements.txt")
    previousHash = open(hashFile).read().strip() if os.path.isfile(hashFile) else ""
    if currentHash != previousHash:
        say("[2/4] Installo le librerie (solo la prima volta o se sono cambiate)...")
        run([venvPython, "-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "-r", "requirements.txt"])
        with open(hashFile, "w") as handle:
            handle.write(currentHash)
    else:
        say("[2/4] Librerie gia' aggiornate")

    version = appVersion(root)
    os.makedirs("build_bin", exist_ok=True)
    for name, code in (("deno.exe", "import deno;print(deno.find_deno_bin())"),
                       ("ffmpeg.exe", "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")):
        target = os.path.join("build_bin", name)
        if not os.path.isfile(target):
            sourcePath = subprocess.run([venvPython, "-c", code], capture_output=True, text=True).stdout.strip()
            if not sourcePath or not os.path.isfile(sourcePath):
                fail(f"{name} non trovato")
            shutil.copy2(sourcePath, target)

    say(f"[3/4] Creo Sonus.exe (versione {version})...")
    if not CI:
        subprocess.run(["taskkill", "/im", "Sonus.exe", "/f"], capture_output=True)
    run([venvPython, "-m", "PyInstaller", "--noconfirm", "--windowed", "--log-level", "ERROR",
         "--name", "Sonus", "--icon", os.path.join("assets", "icon.ico"),
         "--add-data", "assets;assets",
         "--add-binary", r"build_bin\deno.exe;bin", "--add-binary", r"build_bin\ffmpeg.exe;bin",
         "--collect-submodules", "yt_dlp", "--collect-all", "yt_dlp_ejs", "--collect-all", "sounddevice",
         "--collect-submodules", "spotify_scraper", "--hidden-import", "scipy.signal", "--collect-submodules", "paho",
         "--collect-all", "winrt", "--hidden-import", "winrt.windows.media", "--hidden-import", "winrt.windows.media.playback",
         "--hidden-import", "winrt.windows.storage", "--hidden-import", "winrt.windows.storage.streams", "--hidden-import", "winrt.windows.foundation",
         "--exclude-module", "imageio_ffmpeg", "--exclude-module", "tkinter", "main.py"])

    say("[4/4] Creo l'installer da condividere...")
    iscc = findIscc()
    if not iscc:
        say("Inno Setup non trovato: provo a installarlo con winget (solo la prima volta)...")
        subprocess.run(["winget", "install", "-e", "--id", "JRSoftware.InnoSetup", "--scope", "user",
                        "--accept-package-agreements", "--accept-source-agreements"], capture_output=True)
        iscc = findIscc()
    if not iscc and CI:
        fail("Inno Setup non trovato sul server di build")
    if not iscc:
        portable = os.path.join(root, f"Sonus_portable_v{version}")
        shutil.make_archive(portable, "zip", os.path.join(root, "dist", "Sonus"))
        say()
        say("Inno Setup non e' installato, quindi ho creato solo la versione portatile:")
        say(f"  {portable}.zip")
        say("Per avere l'installer: installa Inno Setup dalla pagina che si apre ora, poi riapri questo file.")
        webbrowser.open("https://jrsoftware.org/isdl.php")
        finish(0)

    environment = dict(os.environ, KM_VERSION=version)
    run([iscc, "/Q", "installer.iss"], env=environment)
    setupPath = os.path.join(root, "installer", f"Sonus_Setup_v{version}.exe")
    if CI:
        say(f"Installer pronto: {setupPath}")
        sys.exit(0)
    say("Installo / aggiorno Sonus su questo PC...")
    run([setupPath, "/SILENT", "/NOCANCEL", "/TASKS=desktopicon"])
    say()
    say("==========================================")
    say(f" FATTO! Sonus v{version} e' installato e aggiornato.")
    say()
    say(" Per i tuoi amici manda il file:")
    say(f"   {setupPath}")
    say("==========================================")
    subprocess.run(["explorer", os.path.join(root, "installer")])
    finish(0)


GITIGNORE = """.venv/
build/
dist/
build_bin/
installer/
__pycache__/
*.pyc
*.zip
*.spec
"""


def git(*arguments, check=True, capture=False):
    result = subprocess.run(["git", *arguments], capture_output=capture, text=True)
    if check and result.returncode != 0:
        fail("git " + " ".join(arguments) + " non riuscito" + (f": {result.stderr.strip()}" if capture and result.stderr else ""))
    return result


def publish():
    say("==========================================")
    say("  Sonus - pubblica aggiornamento su GitHub")
    say("==========================================")
    if not shutil.which("git"):
        say("Git non trovato: lo installo con winget...")
        subprocess.run(["winget", "install", "-e", "--id", "Git.Git", "--scope", "user",
                        "--accept-package-agreements", "--accept-source-agreements"])
        say("Fatto. CHIUDI questa finestra e riapri PUBBLICA_AGGIORNAMENTO.bat")
        finish(0)
    if not os.path.isfile(os.path.join(HOME, "app", "config.py")):
        fail("Prima installa Sonus con INSTALLA_E_AGGIORNA.bat")
    os.chdir(HOME)
    with open(".gitignore", "w", encoding="utf-8") as handle:
        handle.write(GITIGNORE)
    if not os.path.isdir(".git"):
        git("init", "-b", "main")
    remote = git("remote", "get-url", "origin", check=False, capture=True).stdout.strip()
    # Sonus is published ONLY on its own repository, never on the old Synth Music one
    if not remote:
        remote = REPO_URL
        git("remote", "add", "origin", remote)
    elif "sonus" not in remote.lower():
        say(f"Il repository collegato era {remote}: passo a {REPO_URL}")
        remote = REPO_URL
        git("remote", "set-url", "origin", remote)
    match = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", remote)
    if not match:
        fail(f"Indirizzo GitHub non valido: {remote}")
    repoSlug = f"{match.group(1)}/{match.group(2)}"
    configPath = os.path.join("app", "config.py")
    with open(configPath, encoding="utf-8") as handle:
        configText = handle.read()
    newText = re.sub(r'UPDATE_REPO\s*=\s*"[^"]*"', f'UPDATE_REPO = "{repoSlug}"', configText)
    if newText != configText:
        with open(configPath, "w", encoding="utf-8") as handle:
            handle.write(newText)
    if not git("config", "user.name", check=False, capture=True).stdout.strip():
        git("config", "user.name", match.group(1))
        git("config", "user.email", f"{match.group(1)}@users.noreply.github.com")
    version = appVersion()
    tag = f"v{version}"
    remoteTags = git("ls-remote", "--tags", "origin", check=False, capture=True).stdout
    if f"refs/tags/{tag}" in remoteTags:
        fail(f"La versione {version} e' gia' pubblicata. Serve una versione nuova (VERSION in app/config.py).")
    # Always publish from the "main" branch, whatever branch this folder is on (e.g. a copy prepared on another branch).
    branch = git("rev-parse", "--abbrev-ref", "HEAD", check=False, capture=True).stdout.strip()
    if branch and branch != "main" and branch != "HEAD":
        git("checkout", "-B", "main", check=False, capture=True)
    if git("fetch", "origin", "main", check=False, capture=True).returncode == 0:
        # GitHub may have commits made elsewhere (e.g. a friend's pull request): put this version on top of them,
        # so the push is accepted. The files on disk (this new version) are what gets published.
        git("reset", "--soft", "origin/main", check=False)
    git("add", "-A")
    git("commit", "-m", f"Sonus {tag}", check=False)
    git("tag", "-f", tag)
    say("Invio a GitHub (la prima volta si apre il browser per fare il login)...")
    git("push", "-u", "origin", "HEAD:main")
    git("push", "origin", tag)
    actionsUrl = f"https://github.com/{repoSlug}/actions"
    say()
    say("==========================================")
    say(f" Inviato! GitHub sta creando l'installer di {tag} (circa 10-15 minuti).")
    say(" Quando ha finito, tutte le app Sonus (la tua e quelle dei tuoi amici)")
    say(" vedranno l'aggiornamento da sole.")
    say(f" Puoi seguire il lavoro qui: {actionsUrl}")
    say("==========================================")
    webbrowser.open(actionsUrl)
    finish(0)


def uninstall():
    say("==========================================")
    say("  Sonus - disinstallazione completa")
    say("==========================================")
    if input("Disinstallare Sonus da questo PC? (s/n) ").strip().lower() != "s":
        sys.exit(0)
    subprocess.run(["taskkill", "/im", "Sonus.exe", "/f"], capture_output=True)
    uninstaller = os.path.join(INSTALL_DIR, "unins000.exe")
    if os.path.isfile(uninstaller):
        say("Rimuovo l'app...")
        subprocess.run([uninstaller, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
        time.sleep(3)
    shutil.rmtree(INSTALL_DIR, ignore_errors=True)
    say("Rimuovo il codice e i file di build...")
    shutil.rmtree(os.path.join(LOCAL, "Sonus"), ignore_errors=True)
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    for name in ("Sonus.lnk", "Sonus - Aggiorna.lnk"):
        try:
            os.remove(os.path.join(desktop, name))
        except OSError:
            pass
    if input("Eliminare anche playlist, canzoni scaricate, testi, video e impostazioni di Sonus? (s/n) ").strip().lower() == "s":
        shutil.rmtree(DATA_DIR, ignore_errors=True)
        say("Dati eliminati.")
    say()
    say("Fatto! Sonus e' stato rimosso.")
    say("Per reinstallare da zero: estrai Sonus.zip e apri INSTALLA_E_AGGIORNA.bat")
    finish(0)


def findDownloadedZip():
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    if not os.path.isdir(downloads):
        return None
    candidates = [os.path.join(downloads, name) for name in os.listdir(downloads)
                  if name.lower().startswith("sonus") and name.lower().endswith(".zip") and "portable" not in name.lower()]
    if not candidates:
        return None
    newest = max(candidates, key=os.path.getmtime)
    configPath = os.path.join(HOME, "app", "config.py")
    if os.path.isfile(configPath) and os.path.getmtime(newest) <= os.path.getmtime(configPath):
        return None
    return newest


def removeOldDesktopShortcut():
    for desktop in (os.path.join(os.path.expanduser("~"), "Desktop"),
                    os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")):
        for name in ("Sonus - Aggiorna.lnk",):
            try:
                os.remove(os.path.join(desktop, name))
            except OSError:
                pass


def main():
    arguments = sys.argv[1:]
    if "--uninstall" in arguments:
        uninstall()
    if CI:
        build(HERE)
    if "--publish" in arguments:
        if os.path.isfile(os.path.join(HERE, "app", "config.py")) and not samePath(HERE, HOME):
            copySource(HERE, HOME)
        publish()
    say("==========================================")
    say("  Sonus - installazione e aggiornamento")
    say("==========================================")
    say()
    os.makedirs(HOME, exist_ok=True)
    removeOldDesktopShortcut()
    zipArguments = [argument for argument in arguments if argument.lower().endswith(".zip") and os.path.isfile(argument)]
    if not zipArguments and "--continue" not in arguments:
        downloadedZip = findDownloadedZip()
        if downloadedZip:
            answer = input(f"Ho trovato {os.path.basename(downloadedZip)} in Download, piu' nuovo della versione attuale. Usarlo? (s/n) ")
            if answer.strip().lower() in ("s", "si", "y", ""):
                zipArguments = [downloadedZip]
    relaunch = False
    if os.path.isfile(os.path.join(HERE, "app", "config.py")) and not samePath(HERE, HOME):
        say(f"Copio Sonus in {HOME} ...")
        copySource(HERE, HOME)
        say("Fatto: la cartella che hai scaricato ora si puo' cancellare.")
        relaunch = True
    if zipArguments:
        extractUpdate(zipArguments[0])
        relaunch = True
    if not os.path.isfile(os.path.join(HOME, "app", "config.py")):
        fail("Codice di Sonus non trovato: apri questo file dalla cartella Sonus estratta, oppure trascinaci sopra Sonus.zip")
    if relaunch and "--continue" not in arguments:
        result = subprocess.run([sys.executable, os.path.join(HOME, "sonus_build.py"), "--continue"])
        sys.exit(result.returncode)
    build()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        import traceback
        details = traceback.format_exc()
        try:
            os.makedirs(os.path.join(LOCAL, "Sonus"), exist_ok=True)
            with open(os.path.join(LOCAL, "Sonus", "errore_aggiornamento.txt"), "w", encoding="utf-8") as logFile:
                logFile.write(details)
        except OSError:
            pass
        say()
        say(details)
        fail("Errore imprevisto (salvato anche in %LOCALAPPDATA%\\Sonus\\errore_aggiornamento.txt)")
