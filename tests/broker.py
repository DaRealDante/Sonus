import os
import socket
import subprocess
import tempfile
import time

import pytest


def freePort():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="session")
def localBroker():
    port = freePort()
    folder = tempfile.mkdtemp()
    configPath = os.path.join(folder, "mosquitto.conf")
    with open(configPath, "w") as configFile:
        configFile.write(f"listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\n")
    process = subprocess.Popen(["mosquitto", "-c", configPath], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.05)
    os.environ["SONUS_BROKERS"] = f"127.0.0.1:{port}:0"
    yield port
    process.terminate()
    process.wait(5)


def waitFor(condition, timeout=6.0):
    from PySide6.QtWidgets import QApplication
    deadline = time.time() + timeout
    while time.time() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def pump(seconds):
    from PySide6.QtWidgets import QApplication
    deadline = time.time() + seconds
    while time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)


def startMosquitto(extraConfig="", websockets=False):
    port = freePort()
    folder = tempfile.mkdtemp()
    configPath = os.path.join(folder, "mosquitto.conf")
    with open(configPath, "w") as configFile:
        configFile.write(f"listener {port} 127.0.0.1\n" + ("protocol websockets\n" if websockets else "")
                         + "persistence false\n" + extraConfig)
    process = subprocess.Popen(["mosquitto", "-c", configPath], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.05)
    return port, process


@pytest.fixture(scope="session")
def passwordBroker():
    """Like the private Sonus server: only with username and password."""
    folder = tempfile.mkdtemp()
    passwordPath = os.path.join(folder, "passwords")
    subprocess.run(["mosquitto_passwd", "-b", "-c", passwordPath, "SonusPlayer", "segreta"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.chmod(folder, 0o755)  # mosquitto may run as its own user
    os.chmod(passwordPath, 0o644)
    port, process = startMosquitto(f"allow_anonymous false\npassword_file {passwordPath}\n")
    yield port
    process.terminate()
    process.wait(5)


@pytest.fixture(scope="session")
def webSocketBroker():
    port, process = startMosquitto("allow_anonymous true\n", websockets=True)
    yield port
    process.terminate()
    process.wait(5)
