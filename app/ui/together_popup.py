import base64
import hashlib

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
                               QWidget)

from . import theme
from ..config import IMAGE_FILTER, settings
from ..session_link import linkFor, parseCode
from ..together import ensureProfile, randomName

PHOTO_SIZE = 96
PHOTO_MAX_BYTES = 12 * 1024
_AVATAR_COLORS = ["#1DB954", "#E8115B", "#8E8EE5", "#F59B23", "#27856A", "#AF2896", "#477D95", "#D84000"]


def photoFromFile(filePath):
    """Square 96×96 JPEG (≤ 12 KB) as base64, or None if the file is not an image."""
    image = QImage(filePath)
    if image.isNull():
        return None
    side = min(image.width(), image.height())
    image = image.copy(QRect((image.width() - side) // 2, (image.height() - side) // 2, side, side))
    image = image.scaled(PHOTO_SIZE, PHOTO_SIZE, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    for quality in (85, 70, 55, 40, 25):
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "JPG", quality)
        if data.size() <= PHOTO_MAX_BYTES:
            break
    return base64.b64encode(bytes(data)).decode("ascii")


def avatarPixmap(photo, name, size):
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size * 2, size * 2)
    painter.setClipPath(path)
    image = QImage()
    if photo:
        try:
            image.loadFromData(QByteArray(base64.b64decode(photo)))
        except Exception:
            image = QImage()
    if not image.isNull():
        painter.drawImage(QRect(0, 0, size * 2, size * 2), image)
    else:
        colorIndex = int(hashlib.md5((name or "?").encode("utf-8")).hexdigest(), 16) % len(_AVATAR_COLORS)
        painter.fillRect(0, 0, size * 2, size * 2, QColor(_AVATAR_COLORS[colorIndex]))
        initials = "".join(word[0] for word in (name or "?").split()[:2]).upper() or "?"
        font = QFont("Segoe UI")
        font.setPixelSize(int(size * 0.8))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(QRect(0, 0, size * 2, size * 2), Qt.AlignCenter, initials)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return pixmap


class ProfileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        ensureProfile()
        self.setWindowTitle("Il tuo profilo")
        self.setMinimumWidth(420)
        self.photo = settings.get("profilePhoto") or ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        titleLabel = QLabel("Il tuo profilo")
        titleLabel.setObjectName("h2")
        layout.addWidget(titleLabel)
        hint = QLabel("Lo vedono le persone con cui ascolti insieme.")
        hint.setObjectName("small")
        layout.addWidget(hint)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.avatarLabel = QLabel()
        self.avatarLabel.setFixedSize(72, 72)
        row.addWidget(self.avatarLabel)
        column = QVBoxLayout()
        nameRow = QHBoxLayout()
        self.nameEdit = QLineEdit(settings.get("profileName") or "")
        self.nameEdit.setMaxLength(32)
        self.nameEdit.setPlaceholderText("Il tuo nome")
        self.nameEdit.textChanged.connect(self._refreshAvatar)
        randomButton = QPushButton("Casuale")
        randomButton.setToolTip("Genera un nome casuale")
        randomButton.clicked.connect(lambda: self.nameEdit.setText(randomName()))
        nameRow.addWidget(self.nameEdit, 1)
        nameRow.addWidget(randomButton)
        column.addLayout(nameRow)
        photoRow = QHBoxLayout()
        photoButton = QPushButton("Scegli foto...")
        photoButton.clicked.connect(self._choosePhoto)
        self.removeButton = QPushButton("Rimuovi foto")
        self.removeButton.clicked.connect(self._removePhoto)
        photoRow.addWidget(photoButton)
        photoRow.addWidget(self.removeButton)
        photoRow.addStretch()
        column.addLayout(photoRow)
        row.addLayout(column, 1)
        layout.addLayout(row)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancelButton = QPushButton("Annulla")
        cancelButton.clicked.connect(self.reject)
        saveButton = QPushButton("Salva")
        saveButton.setObjectName("accent")
        saveButton.clicked.connect(self._save)
        buttons.addWidget(cancelButton)
        buttons.addWidget(saveButton)
        layout.addLayout(buttons)
        self._refreshAvatar()

    def _refreshAvatar(self):
        self.avatarLabel.setPixmap(avatarPixmap(self.photo, self.nameEdit.text(), 72))
        self.removeButton.setEnabled(bool(self.photo))

    def _choosePhoto(self):
        filePath, _ = QFileDialog.getOpenFileName(self, "Scegli una foto", "", IMAGE_FILTER)
        if not filePath:
            return
        photo = photoFromFile(filePath)
        if photo:
            self.photo = photo
            self._refreshAvatar()

    def _removePhoto(self):
        self.photo = ""
        self._refreshAvatar()

    def _save(self):
        settings.set("profileName", self.nameEdit.text().strip()[:32] or randomName())
        settings.set("profilePhoto", self.photo)
        settings.save()
        self.accept()


class PersonRow(QWidget):
    def __init__(self, peer, isMe):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(10)
        avatar = QLabel()
        avatar.setFixedSize(30, 30)
        avatar.setPixmap(avatarPixmap(peer.get("photo"), peer.get("name"), 30))
        layout.addWidget(avatar)
        nameLabel = QLabel(peer.get("name") + (" (tu)" if isMe else ""))
        layout.addWidget(nameLabel, 1)


class TogetherPopup(QFrame):
    """Ascolta insieme: create a room, join with a code or link, see who is listening."""

    codeEntered = Signal(str)

    def __init__(self, window):
        super().__init__(window, Qt.Popup)
        self.window = window
        self.controller = window.together
        self.setObjectName("togetherPopup")
        self.setStyleSheet(f"QFrame#togetherPopup {{ background: {theme.ELEVATED}; border: 1px solid #3A3A3A; border-radius: 10px; }}")
        self.setFixedWidth(380)
        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(16, 14, 16, 14)
        self.mainLayout.setSpacing(10)
        self.content = None
        self.anchor = None
        self.controller.roomChanged.connect(self.rebuild)
        self.controller.peersChanged.connect(self.rebuild)
        self.controller.connectionChanged.connect(lambda connected: self.rebuild())
        self.rebuild()

    def rebuild(self):
        if self.content is not None:
            self.mainLayout.removeWidget(self.content)
            self.content.hide()
            self.content.deleteLater()
        self.content = QWidget()
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.mainLayout.addWidget(self.content)
        titleLabel = QLabel("Ascolta insieme")
        titleLabel.setObjectName("h3")
        layout.addWidget(titleLabel)

        profile = self.controller.profile()
        profileRow = QHBoxLayout()
        avatar = QLabel()
        avatar.setFixedSize(36, 36)
        avatar.setPixmap(avatarPixmap(profile.get("photo"), profile.get("name"), 36))
        profileRow.addWidget(avatar)
        nameLabel = QLabel(profile.get("name") or "")
        profileRow.addWidget(nameLabel, 1)
        editButton = QPushButton("Modifica profilo")
        editButton.clicked.connect(self._editProfile)
        profileRow.addWidget(editButton)
        layout.addLayout(profileRow)

        if not self.controller.inRoom():
            explanation = QLabel("Ascoltate la stessa canzone nello stesso momento, anche da città diverse. "
                                 "Tutti possono mettere play, pausa, saltare e cambiare canzone.")
            explanation.setObjectName("small")
            explanation.setWordWrap(True)
            layout.addWidget(explanation)
            createButton = QPushButton("Crea una stanza")
            createButton.setObjectName("accent")
            createButton.clicked.connect(self._create)
            layout.addWidget(createButton)
            orLabel = QLabel("oppure incolla un codice o un link:")
            orLabel.setObjectName("small")
            layout.addWidget(orLabel)
            joinRow = QHBoxLayout()
            self.codeEdit = QLineEdit()
            self.codeEdit.setPlaceholderText("SONUS-XXXX-XXXX o link")
            self.codeEdit.returnPressed.connect(self._join)
            joinButton = QPushButton("Entra")
            joinButton.clicked.connect(self._join)
            joinRow.addWidget(self.codeEdit, 1)
            joinRow.addWidget(joinButton)
            layout.addLayout(joinRow)
            self.errorLabel = QLabel("")
            self.errorLabel.setObjectName("small")
            self.errorLabel.setStyleSheet("color: #F15E6C;")
            self.errorLabel.hide()
            layout.addWidget(self.errorLabel)
            playlistHint = QLabel("Funziona anche con i codici delle playlist condivise (SONUSP-…).")
            playlistHint.setObjectName("small")
            playlistHint.setWordWrap(True)
            layout.addWidget(playlistHint)
        else:
            code = self.controller.code
            codeLabel = QLabel(code)
            codeLabel.setObjectName("h2")
            codeLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
            codeLabel.setAlignment(Qt.AlignCenter)
            layout.addWidget(codeLabel)
            copyRow = QHBoxLayout()
            copyLinkButton = QPushButton("Copia link")
            copyLinkButton.setObjectName("accent")
            copyLinkButton.clicked.connect(lambda: self._copy(linkFor(code), "Link copiato: mandalo ai tuoi amici"))
            copyCodeButton = QPushButton("Copia codice")
            copyCodeButton.clicked.connect(lambda: self._copy(code, "Codice copiato"))
            copyRow.addWidget(copyLinkButton)
            copyRow.addWidget(copyCodeButton)
            layout.addLayout(copyRow)
            connected = self.controller.link.isConnected()
            statusLabel = QLabel("● Connesso" if connected else "● Connessione in corso...")
            statusLabel.setObjectName("small")
            statusLabel.setStyleSheet(f"color: {theme.ACCENT if connected else '#F59B23'};")
            layout.addWidget(statusLabel)
            peopleLabel = QLabel(f"Nella stanza ({len(self.controller.peers)})")
            peopleLabel.setObjectName("sub")
            layout.addWidget(peopleLabel)
            for peerId, peer in sorted(self.controller.peers.items(), key=lambda item: item[1].get("joinedAt") or 0):
                layout.addWidget(PersonRow(peer, peerId == self.controller.myId()))
            delayRow = QHBoxLayout()
            delayRow.addWidget(QLabel("Ritardo"))
            delayRow.addStretch()
            self.delayLabel = QLabel("")
            self.delayLabel.setObjectName("h3")
            delayRow.addWidget(self.delayLabel)
            layout.addLayout(delayRow)
            from .equalizer_page import EqSlider
            self.delaySlider = EqSlider(Qt.Horizontal)
            self.delaySlider.setRange(0, 60)
            self.delaySlider.setValue(self.controller.delayMs() // 50)
            self.delaySlider.setToolTip("Doppio click = nessun ritardo")
            self.delaySlider.mouseDoubleClickEvent = lambda event: self.delaySlider.setValue(0)
            self.delaySlider.valueChanged.connect(self._onDelayChanged)
            layout.addWidget(self.delaySlider)
            delayHint = QLabel("Vale solo per te: se in chiamata su Discord senti gli altri in ritardo, aumentalo finché la musica combacia.")
            delayHint.setObjectName("small")
            delayHint.setWordWrap(True)
            layout.addWidget(delayHint)
            self._showDelay(self.controller.delayMs())
            leaveButton = QPushButton("Esci dalla stanza")
            leaveButton.clicked.connect(self.controller.leaveRoom)
            layout.addWidget(leaveButton)
        for label in self.content.findChildren(QLabel):
            if label.wordWrap():
                label.setMinimumHeight(label.heightForWidth(self.width() - 32))
        self.adjustSize()
        if self.isVisible() and self.anchor is not None:
            self._place()

    def _showDelay(self, delayMs):
        self.delayLabel.setText("Nessuno" if delayMs <= 0 else f"+{delayMs / 1000:.2f} s")

    def _onDelayChanged(self, value):
        delayMs = value * 50
        self._showDelay(delayMs)
        self.controller.setDelay(delayMs)

    def _copy(self, text, message):
        QGuiApplication.clipboard().setText(text)
        self.window.showStatus(message)

    def _create(self):
        self.controller.createRoom()
        self._copy(linkFor(self.controller.code), "Stanza creata: link copiato, mandalo ai tuoi amici")

    def _join(self):
        parsed = parseCode(self.codeEdit.text())
        if not parsed:
            self.errorLabel.setText("Codice non valido: deve essere tipo SONUS-ABCD-EFGH")
            self.errorLabel.show()
            self.adjustSize()
            return
        self.window.handleCode(self.codeEdit.text())

    def _editProfile(self):
        self.hide()
        dialog = ProfileDialog(self.window)
        if dialog.exec() == ProfileDialog.Accepted:
            self.controller.updateProfile()
            self.rebuild()

    def showAbove(self, anchor):
        self.anchor = anchor
        self.rebuild()
        self._place()
        from .effects import popIn
        popIn(self)
        self.show()

    def _place(self):
        self.adjustSize()
        position = self.anchor.mapToGlobal(self.anchor.rect().topLeft())
        self.move(max(0, position.x() + self.anchor.width() - self.width()), max(0, position.y() - self.height() - 8))
