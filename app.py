#!/usr/bin/env python3
"""Instagram Baixar - GUI texto (sem preview), filtro e download seletivo."""

from __future__ import annotations

import os
import re
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QSharedMemory, QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from downloader import (
    DEFAULT_OUT,
    download_media_items,
    download_profile_all,
    download_urls,
    profile_out_dir,
    safe_username,
)
from instagram_api import (
    HighlightInfo,
    MediaItem,
    list_highlight_tray,
    list_highlights,
    list_profile_media,
    parse_highlight_id,
    parse_post_url,
    parse_username_or_url,
)
from session import (
    capture_from_chrome,
    clear_session,
    login_with_playwright,
    session_status,
)

ROLE_URL = Qt.ItemDataRole.UserRole
ROLE_CODE = Qt.ItemDataRole.UserRole + 1
ROLE_KIND = Qt.ItemDataRole.UserRole + 2  # "video" | "foto" | "carrossel" | "tray"
ROLE_HL_ID = Qt.ItemDataRole.UserRole + 3  # highlight:123...

STYLE = """
QMainWindow {
  background: #0a0a0a;
}
QWidget {
  background: transparent;
  color: #e8e8e8;
  font-family: "Segoe UI", "Segoe UI Variable", sans-serif;
  font-size: 13px;
}
QLabel#title {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.2px;
  color: #ffffff;
  padding: 2px 0 0 0;
}
QLabel#subtitle {
  color: #9a9a9a;
  font-size: 12.5px;
  line-height: 1.35;
  padding-bottom: 4px;
}
QLabel#hint {
  color: #8a8a8a;
  font-size: 12px;
}
QLabel#section {
  color: #b0b0b0;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.4px;
  text-transform: uppercase;
  padding: 2px 0;
}
QLineEdit, QComboBox {
  background: #141414;
  border: 1px solid #2e2e2e;
  border-radius: 10px;
  padding: 9px 12px;
  color: #f0f0f0;
  selection-background-color: #4a4a4a;
  selection-color: #ffffff;
}
QLineEdit:hover, QComboBox:hover {
  border: 1px solid #454545;
  background: #181818;
}
QLineEdit:focus, QComboBox:focus {
  border: 1px solid #c0c0c0;
  background: #1a1a1a;
}
QComboBox::drop-down {
  border: 0;
  width: 28px;
}
QComboBox QAbstractItemView {
  background: #141414;
  color: #f0f0f0;
  border: 1px solid #2e2e2e;
  border-radius: 8px;
  padding: 4px;
  outline: 0;
  selection-background-color: #3a3a3a;
  selection-color: #ffffff;
}
QListWidget {
  background: #111111;
  border: 1px solid #2e2e2e;
  border-radius: 12px;
  padding: 6px;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 12px;
  outline: 0;
}
QListWidget:hover {
  border: 1px solid #404040;
}
QListWidget::item {
  margin: 2px 1px;
  border-radius: 8px;
  padding: 7px 10px;
  color: #d8d8d8;
}
QListWidget::item:alternate {
  background: #161616;
}
QListWidget::item:hover {
  background: #242424;
  color: #ffffff;
}
QListWidget::item:selected {
  background: #2e2e2e;
  color: #ffffff;
}
QPushButton {
  background: #222222;
  color: #f0f0f0;
  border: 1px solid #3a3a3a;
  border-radius: 10px;
  padding: 9px 16px;
  font-weight: 600;
}
QPushButton:hover {
  background: #2e2e2e;
  border: 1px solid #555555;
  color: #ffffff;
}
QPushButton:pressed {
  background: #1a1a1a;
  border: 1px solid #333333;
  padding-top: 10px;
  padding-bottom: 8px;
}
QPushButton:disabled {
  background: #151515;
  border: 1px solid #252525;
  color: #666666;
}
QPushButton#primary {
  background: #f0f0f0;
  border: 1px solid #ffffff;
  color: #0a0a0a;
}
QPushButton#primary:hover {
  background: #ffffff;
  border: 1px solid #ffffff;
  color: #000000;
}
QPushButton#primary:pressed {
  background: #c8c8c8;
  border: 1px solid #d0d0d0;
}
QPushButton#primary:disabled {
  background: #3a3a3a;
  border: 1px solid #3a3a3a;
  color: #888888;
}
QPushButton#success {
  background: #d8d8d8;
  border: 1px solid #e8e8e8;
  color: #0a0a0a;
}
QPushButton#success:hover {
  background: #ececec;
  border: 1px solid #ffffff;
}
QPushButton#success:pressed {
  background: #b8b8b8;
}
QPushButton#success:disabled {
  background: #2a2a2a;
  border: 1px solid #2a2a2a;
  color: #777777;
}
QPushButton#warn {
  background: #2a2a2a;
  border: 1px solid #5a5a5a;
  color: #e0e0e0;
}
QPushButton#warn:hover {
  background: #383838;
  border: 1px solid #7a7a7a;
  color: #ffffff;
}
QPushButton#warn:pressed {
  background: #1e1e1e;
}
QPushButton#ghost {
  background: transparent;
  border: 1px solid #3a3a3a;
  color: #b0b0b0;
}
QPushButton#ghost:hover {
  background: #1a1a1a;
  border: 1px solid #555555;
  color: #ffffff;
}
QStatusBar {
  background: #050505;
  color: #9a9a9a;
  border-top: 1px solid #222222;
}
QLabel#job {
  font-size: 13px;
  font-weight: 600;
  padding: 8px 12px;
  border-radius: 10px;
  background: #141414;
  border: 1px solid #2e2e2e;
}
QLabel#job[state="idle"] { color: #9a9a9a; }
QLabel#job[state="busy"] {
  color: #e8e8e8;
  background: #1c1c1c;
  border: 1px solid #4a4a4a;
}
QLabel#job[state="ok"] {
  color: #ffffff;
  background: #1a1a1a;
  border: 1px solid #6a6a6a;
}
QLabel#job[state="err"] {
  color: #c8c8c8;
  background: #121212;
  border: 1px solid #505050;
}
QProgressBar {
  background: #141414;
  border: 1px solid #2e2e2e;
  border-radius: 9px;
  text-align: center;
  color: #f0f0f0;
  min-height: 20px;
  max-height: 22px;
  font-size: 11px;
  font-weight: 600;
}
QProgressBar::chunk {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 #6a6a6a, stop:1 #e0e0e0);
  border-radius: 8px;
  margin: 2px;
}
QTextEdit#log {
  background: #0e0e0e;
  border: 1px solid #2e2e2e;
  border-radius: 12px;
  padding: 8px;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 12px;
  color: #b8b8b8;
  selection-background-color: #4a4a4a;
}
QTextEdit#log:hover {
  border: 1px solid #404040;
}
QTextEdit#log:focus {
  border: 1px solid #707070;
}
QScrollBar:vertical {
  background: transparent;
  width: 10px;
  margin: 4px 2px 4px 0;
}
QScrollBar::handle:vertical {
  background: #3a3a3a;
  border-radius: 5px;
  min-height: 28px;
}
QScrollBar::handle:vertical:hover {
  background: #5a5a5a;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
  height: 0;
}
QScrollBar:horizontal {
  background: transparent;
  height: 10px;
  margin: 0 4px 2px 4px;
}
QScrollBar::handle:horizontal {
  background: #3a3a3a;
  border-radius: 5px;
  min-width: 28px;
}
QScrollBar::handle:horizontal:hover {
  background: #5a5a5a;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
  width: 0;
}
QToolTip {
  background: #1a1a1a;
  color: #f0f0f0;
  border: 1px solid #454545;
  border-radius: 8px;
  padding: 6px 8px;
}
"""


def _kind_of(m: MediaItem) -> str:
    if m.source == "highlights" or m.typename == "HighlightStory":
        return "destaque"
    if m.typename == "GraphSidecar":
        return "carrossel"
    return "video" if m.is_video else "foto"


class Worker(QThread):
    ok = Signal(object)
    err = Signal(str)
    log = Signal(str)
    # msg, current, total (total<=0 = indeterminado)
    progress = Signal(str, int, int)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.ok.emit(result)
        except (RuntimeError, ValueError, TimeoutError, FileNotFoundError) as e:
            self.err.emit(str(e))
        except Exception:
            self.err.emit(traceback.format_exc()[-2000:])


def _app_icon() -> QIcon:
    base = Path(__file__).resolve().parent
    for name in ("instagram-baixar.ico", "instagram-baixar.png"):
        path = base / name
        if path.is_file():
            return QIcon(str(path))
    return QIcon()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Instagram Baixar v8")
        self.resize(980, 820)
        self.setMinimumSize(760, 640)
        icon = _app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.worker: Worker | None = None
        self.items: list[MediaItem] = []
        self.highlights: list[HighlightInfo] = []
        # media = midias individuais | highlight_tray = pastas de destaque
        self.list_mode: str = "media"
        self.out_dir = DEFAULT_OUT
        self.current_username: str = ""
        self._job_busy = False

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.setSpacing(12)

        title = QLabel("Instagram Baixar")
        title.setObjectName("title")
        layout.addWidget(title)

        hint = QLabel(
            "Conexao automatica sempre headless (escondida).  "
            "Janela so se voce clicar em Abrir navegador e logar.  "
            "Arquivos em downloads/ (pasta unica), um por vez."
        )
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row_s = QHBoxLayout()
        row_s.setSpacing(8)
        self.lbl_session = QLabel("Sessao: ...")
        self.lbl_session.setObjectName("hint")
        row_s.addWidget(self.lbl_session, 1)
        self.btn_login = QPushButton("Abrir navegador e logar")
        self.btn_login.setObjectName("ghost")
        self.btn_login.setToolTip(
            "So se a conexao automatica falhar: abre Chrome VISIVEL "
            "pra voce entrar no Instagram."
        )
        self.btn_logout = QPushButton("Limpar sessao")
        self.btn_logout.setObjectName("warn")
        self.btn_login.clicked.connect(self.do_login)
        self.btn_logout.clicked.connect(self.do_logout)
        row_s.addWidget(self.btn_login)
        row_s.addWidget(self.btn_logout)
        layout.addLayout(row_s)

        row_u = QHBoxLayout()
        row_u.setSpacing(8)
        self.url = QLineEdit()
        self.url.setPlaceholderText(
            "@usuario  |  https://instagram.com/reel/...  |  /reels/...  |  /p/..."
        )
        self.url.returnPressed.connect(self._on_url_enter)
        self.source = QComboBox()
        self.source.addItem("Posts", "posts")
        self.source.addItem("Reels", "reels")
        self.source.addItem("Destaques", "highlights")
        self.source.addItem("Tudo", "all")
        self.source.setCurrentIndex(2)  # destaques por padrao
        self.btn_list = QPushButton("Listar")
        self.btn_list.setObjectName("primary")
        self.btn_list.clicked.connect(self.do_list)
        self.source.currentIndexChanged.connect(self._on_source_changed)
        self.btn_dl_url = QPushButton("Baixar URL")
        self.btn_dl_url.setObjectName("success")
        self.btn_dl_url.setToolTip(
            "Cola URL de post, reel (/reel/ ou /reels/) ou destaque "
            "e baixa na qualidade maxima"
        )
        self.btn_dl_url.clicked.connect(self.do_download_url)
        row_u.addWidget(self.url, 1)
        row_u.addWidget(self.source)
        row_u.addWidget(self.btn_list)
        row_u.addWidget(self.btn_dl_url)
        layout.addLayout(row_u)

        row_f = QHBoxLayout()
        row_f.setSpacing(8)
        lbl_filtro = QLabel("Filtro")
        lbl_filtro.setObjectName("section")
        row_f.addWidget(lbl_filtro)
        self.filter = QComboBox()
        self.filter.addItem("Todos (foto + video)", "all")
        self.filter.addItem("So videos (MP4 / Reels)", "video")
        self.filter.addItem("So fotos", "foto")
        self.filter.currentIndexChanged.connect(self._apply_filter)
        row_f.addWidget(self.filter)
        self.lbl_counts = QLabel("")
        self.lbl_counts.setObjectName("hint")
        row_f.addWidget(self.lbl_counts, 1)
        layout.addLayout(row_f)

        row_sel = QHBoxLayout()
        row_sel.setSpacing(8)
        self.btn_all = QPushButton("Marcar todos")
        self.btn_all.setObjectName("ghost")
        self.btn_none = QPushButton("Desmarcar")
        self.btn_none.setObjectName("ghost")
        self.btn_out = QPushButton("Escolher pasta")
        self.btn_out.setObjectName("ghost")
        self.btn_out.setToolTip("Escolher onde salvar os downloads")
        self.btn_open_out = QPushButton("Abrir pasta destino")
        self.btn_open_out.setObjectName("ghost")
        self.btn_open_out.setToolTip("Abre a pasta de downloads no Explorer")
        self.btn_all.clicked.connect(lambda: self._set_all(True))
        self.btn_none.clicked.connect(lambda: self._set_all(False))
        self.btn_out.clicked.connect(self.pick_out)
        self.btn_open_out.clicked.connect(self.open_out)
        self.lbl_out = QLabel(f"Pasta: {self.out_dir}")
        self.lbl_out.setObjectName("hint")
        row_sel.addWidget(self.btn_all)
        row_sel.addWidget(self.btn_none)
        row_sel.addWidget(self.btn_out)
        row_sel.addWidget(self.btn_open_out)
        row_sel.addWidget(self.lbl_out, 1)
        layout.addLayout(row_sel)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.ListMode)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setSpacing(3)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list.setWordWrap(False)
        self.list.setAlternatingRowColors(True)
        layout.addWidget(self.list, 3)

        row_dl = QHBoxLayout()
        row_dl.setSpacing(8)
        self.btn_dl_sel = QPushButton("Baixar selecionados")
        self.btn_dl_sel.setObjectName("success")
        self.btn_load_hl = QPushButton("Ver midias dos destaques")
        self.btn_load_hl.setObjectName("ghost")
        self.btn_load_hl.setToolTip(
            "Com Destaques listados: carrega as midias so das pastas marcadas "
            "(pra escolher item a item). Ou use Baixar selecionados pra baixar tudo delas."
        )
        self.btn_load_hl.clicked.connect(self.do_load_selected_highlights)
        self.btn_dl_all = QPushButton("Baixar perfil inteiro")
        self.btn_dl_all.setObjectName("ghost")
        self.btn_dl_sel.clicked.connect(self.do_download_selected)
        self.btn_dl_all.clicked.connect(self.do_download_profile)
        row_dl.addWidget(self.btn_dl_sel)
        row_dl.addWidget(self.btn_load_hl)
        row_dl.addWidget(self.btn_dl_all)
        row_dl.addStretch(1)
        layout.addLayout(row_dl)
        self._on_source_changed()

        # Status da tarefa + barra de progresso
        self.lbl_job = QLabel("Pronto")
        self.lbl_job.setObjectName("job")
        self.lbl_job.setProperty("state", "idle")
        self.lbl_job.setWordWrap(True)
        layout.addWidget(self.lbl_job)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)

        row_log = QHBoxLayout()
        row_log.setSpacing(8)
        lbl_logs = QLabel("Logs")
        lbl_logs.setObjectName("section")
        row_log.addWidget(lbl_logs)
        self.btn_clear_log = QPushButton("Limpar log")
        self.btn_clear_log.setObjectName("ghost")
        row_log.addStretch(1)
        row_log.addWidget(self.btn_clear_log)
        layout.addLayout(row_log)

        self._polish_buttons()

        self.log = QTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(150)
        self.log.setPlaceholderText(
            "Aqui aparecem progresso, erros e conclusao de cada etapa..."
        )
        self.btn_clear_log.clicked.connect(self.log.clear)
        layout.addWidget(self.log, 1)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self._keepalive_worker: Worker | None = None
        self._session_timer = QTimer(self)
        self._session_timer.setInterval(60_000)
        self._session_timer.timeout.connect(self._keepalive_session)
        self.refresh_session()
        self._set_job("Pronto. Liste um perfil ou cole uma URL.", "idle")
        self._session_timer.start()

    def _polish_buttons(self) -> None:
        """Cursor e altura minima mais confortaveis em todos os botoes."""
        for btn in self.findChildren(QPushButton):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(34)

    def append_log(self, msg: str) -> None:
        text = msg.rstrip()
        if not text:
            return
        self.log.append(text)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _set_job(self, text: str, state: str = "idle") -> None:
        self.lbl_job.setText(text)
        self.lbl_job.setProperty("state", state)
        self.lbl_job.style().unpolish(self.lbl_job)
        self.lbl_job.style().polish(self.lbl_job)
        self.status.showMessage(text)

    def _set_progress(self, current: int, total: int) -> None:
        if total and total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(min(max(current, 0), total))
            self.progress.setFormat(f"{current}/{total}  (%p%)")
        else:
            # indeterminado (ainda carregando, total desconhecido)
            self.progress.setRange(0, 0)
            self.progress.setFormat("carregando...")

    def _on_progress(self, msg: str, current: int, total: int) -> None:
        self.append_log(msg)
        self._set_job(msg, "busy")
        self._set_progress(current, total)

    def refresh_session(self) -> None:
        st = session_status()
        if st.get("logged_in"):
            src = st.get("source") or "?"
            self.lbl_session.setText(f"Sessao: OK ({src})")
            if not self._job_busy:
                self.status.showMessage("Sessao ativa. Pode listar e baixar.")
        else:
            self.lbl_session.setText("Sessao: desconectado")
            if not self._job_busy:
                self.status.showMessage(
                    "Sem sessao. Aguarde a reconexao automatica ou use Abrir navegador."
                )

    def _keepalive_session(self) -> None:
        """A cada 1 min: renova cookies em segundo plano (sem janela, sem popup)."""
        if self._job_busy:
            return
        w = self._keepalive_worker
        if w is not None and w.isRunning():
            return

        def job(**_kwargs):
            return capture_from_chrome(allow_visible=False)

        def on_ok(_path) -> None:
            self.refresh_session()

        def on_err(_err: str) -> None:
            # silencioso: so atualiza o selo da sessao
            self.refresh_session()

        self._keepalive_worker = Worker(job)
        self._keepalive_worker.ok.connect(on_ok)
        self._keepalive_worker.err.connect(on_err)
        self._keepalive_worker.start()

    def _busy(self, on: bool) -> None:
        self._job_busy = on
        for b in (
            self.btn_login,
            self.btn_list,
            self.btn_dl_sel,
            self.btn_load_hl,
            self.btn_dl_url,
            self.btn_dl_all,
            self.filter,
            self.source,
        ):
            b.setEnabled(not on)
        if not on:
            self._on_source_changed()

    def _on_source_changed(self) -> None:
        src = self.source.currentData() or "posts"
        if src in ("highlights", "destaques"):
            self.btn_list.setText("Listar destaques")
            self.btn_load_hl.setVisible(True)
            self.btn_dl_sel.setText("Baixar destaques marcados")
        else:
            self.btn_list.setText("Listar")
            self.btn_load_hl.setVisible(False)
            self.btn_dl_sel.setText("Baixar selecionados")

    def _run(
        self,
        fn,
        on_ok,
        *args,
        want_log: bool = False,
        want_progress: bool = False,
        busy_label: str = "Trabalhando...",
        dl_total: int = 0,
        **kwargs,
    ) -> None:
        if self.worker and self.worker.isRunning():
            self.append_log("Aguarde: ja existe uma tarefa em andamento.")
            return
        self._busy(True)
        self._set_job(busy_label, "busy")
        if dl_total > 0:
            self._set_progress(0, dl_total)
        else:
            self._set_progress(0, 0)
        self.append_log(f">>> {busy_label}")
        worker_holder: dict = {}

        def wrap(*a, **k):
            k = dict(k)
            if want_log:
                k["on_line"] = lambda line: worker_holder["w"].log.emit(str(line))
            if want_progress:
                k["on_progress"] = (
                    lambda msg, cur, tot: worker_holder["w"].progress.emit(
                        str(msg), int(cur), int(tot)
                    )
                )
            return fn(*a, **k)

        def _on_log(line: str) -> None:
            self.append_log(line)
            if want_log:
                self._parse_dl_progress(line, dl_total)

        def _done(r) -> None:
            self._busy(False)
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
            self.progress.setFormat("100%")
            on_ok(r)

        self.worker = Worker(wrap, *args, **kwargs)
        worker_holder["w"] = self.worker
        self.worker.log.connect(_on_log)
        self.worker.progress.connect(self._on_progress)
        self.worker.ok.connect(_done)
        self.worker.err.connect(self._on_err)
        self.worker.start()

    def _on_err(self, err: str) -> None:
        self._busy(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("erro")
        self._set_job(f"ERRO: {err[:180]}", "err")
        self.append_log("!!! ERRO")
        self.append_log(err)
        QMessageBox.critical(self, "Erro", err[-1500:])
        self.refresh_session()

    def do_login(self) -> None:
        self._run(
            login_with_playwright,
            self._after_login,
            busy_label="Abrindo Chrome VISIVEL. Faca login no Instagram...",
        )

    def _after_login(self, path) -> None:
        self.append_log(f"Sessao salva em {path}")
        self._set_job("Sessao OK. Pode listar midias.", "ok")
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("ok")
        self.refresh_session()

    def do_logout(self) -> None:
        clear_session()
        self.refresh_session()
        self.append_log("Sessao limpa.")

    def pick_out(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Pasta de downloads", str(self.out_dir))
        if d:
            self.out_dir = Path(d)
            self.lbl_out.setText(f"Pasta: {self.out_dir}")

    def open_out(self) -> None:
        dest = self._dest_for()
        dest.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(dest))  # type: ignore[attr-defined]
        except Exception as e:
            QMessageBox.warning(self, "Pasta", f"Nao consegui abrir:\n{dest}\n\n{e}")

    def _dest_for(self, username: str | None = None) -> Path:
        return profile_out_dir(base=self.out_dir)

    def do_list(self) -> None:
        text = self.url.text().strip()
        post = parse_post_url(text)
        if post:
            self.list_mode = "media"
            self.items = []
            self.highlights = []
            self.list.clear()
            kind = "video" if "/reel/" in post else "foto"
            if parse_highlight_id(post):
                kind = "destaque"
            tag = {"video": "MP4", "foto": "FOTO", "destaque": "DESTAQUE"}.get(
                kind, "?"
            )
            item = QListWidgetItem(f"1. [{tag}]  {post}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(ROLE_URL, post)
            item.setData(ROLE_CODE, "url")
            item.setData(ROLE_KIND, kind)
            item.setToolTip(post)
            self.list.addItem(item)
            self.lbl_counts.setText("1 URL pronta para baixar")
            self.append_log(f"URL unica pronta: {post}")
            self._set_job("URL unica pronta (sem listagem de perfil).", "ok")
            return

        try:
            username = parse_username_or_url(text)
        except ValueError as e:
            QMessageBox.warning(self, "URL", str(e))
            return

        src = self.source.currentData() or "posts"

        # Destaques: primeiro so os NOMES das pastas (escolha quais baixar)
        if src in ("highlights", "destaques"):

            def job_tray(**kwargs):
                return list_highlight_tray(username, **kwargs)

            self._run(
                job_tray,
                self._on_highlight_tray,
                want_progress=True,
                busy_label=f"Listando pastas de destaque @{username}...",
            )
            return

        def job(**kwargs):
            return list_profile_media(
                username, limit=None, source=src, **kwargs
            )

        self._run(
            job,
            self._on_listed,
            want_progress=True,
            busy_label=f"Listando @{username} ({src})...",
        )

    def _on_highlight_tray(self, result) -> None:
        user, tray = result
        self.list_mode = "highlight_tray"
        self.items = []
        self.highlights = list(tray)
        name = user.get("username") or "?"
        self.current_username = safe_username(name)
        full = user.get("full_name") or ""
        dest = self._dest_for(self.current_username)
        total_media = sum(h.media_count for h in self.highlights)
        summary = (
            f"Destaques @{name} ({full}): {len(self.highlights)} pastas "
            f"(~{total_media} midias no Instagram)"
        )
        self.append_log(summary)
        self.append_log(
            "Marque as pastas que quer. Depois: "
            "'Baixar destaques marcados' (tudo delas) ou "
            "'Ver midias dos destaques' (escolher item a item)."
        )
        self.append_log(f"Downloads deste perfil irao para: {dest}")
        self.lbl_counts.setText(
            f"@{self.current_username}  |  {len(self.highlights)} destaques  |  "
            f"~{total_media} midias"
        )
        self._set_job(summary, "ok")
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("destaques 100%")
        self._show_highlight_tray()

    def _show_highlight_tray(self) -> None:
        self.list.clear()
        total = len(self.highlights)
        width = max(2, len(str(total)))
        for i, h in enumerate(self.highlights, start=1):
            # titulo pode ter emoji; Qt mostra ok
            label = (
                f"{i:>{width}}. [DESTAQUE]  {h.title}  "
                f"({h.media_count} midias)"
            )
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(ROLE_HL_ID, h.id)
            item.setData(ROLE_CODE, h.id)
            item.setData(ROLE_KIND, "tray")
            item.setData(ROLE_URL, "")
            item.setToolTip(f"{h.title}\nid: {h.id}\n~{h.media_count} midias")
            self.list.addItem(item)
        self.status.showMessage(
            f"{total} pastas de destaque. Marque quais quer baixar."
        )

    def _selected_highlight_ids(self) -> list[str]:
        ids: list[str] = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() != Qt.CheckState.Checked:
                continue
            if it.data(ROLE_KIND) != "tray":
                continue
            hid = it.data(ROLE_HL_ID)
            if hid:
                ids.append(str(hid))
        return ids

    def do_load_selected_highlights(self) -> None:
        """Carrega midias so dos destaques marcados (lista item a item)."""
        if self.list_mode != "highlight_tray":
            QMessageBox.information(
                self,
                "Destaques",
                "Primeiro escolha 'Destaques' e clique Listar destaques.",
            )
            return
        ids = self._selected_highlight_ids()
        if not ids:
            QMessageBox.information(
                self, "Destaques", "Marque pelo menos um destaque na lista."
            )
            return
        user = self.current_username
        if not user:
            QMessageBox.warning(self, "Destaques", "Perfil desconhecido.")
            return
        titles = [
            h.title for h in self.highlights if h.id in ids or h.id.replace("highlight:", "") in {
                x.replace("highlight:", "") for x in ids
            }
        ]
        self.append_log(
            f"Carregando midias de {len(ids)} destaque(s): {', '.join(titles) or ids}"
        )

        def job(**kwargs):
            return list_highlights(user, limit=None, only_ids=ids, **kwargs)

        self._run(
            job,
            self._on_listed,
            want_progress=True,
            busy_label=f"Carregando midias de {len(ids)} destaque(s)...",
        )

    def _on_listed(self, result) -> None:
        user, items = result
        self.list_mode = "media"
        self.items = items
        self.highlights = []
        name = user.get("username") or "?"
        self.current_username = safe_username(name)
        full = user.get("full_name") or ""
        n_vid = sum(1 for m in items if m.is_video)
        n_foto = len(items) - n_vid
        dest = self._dest_for(self.current_username)
        src = self.source.currentData() or "?"
        src_label = self.source.currentText()
        summary = (
            f"Listagem OK [{src_label}]: @{name} ({full}) - {len(items)} itens "
            f"({n_vid} videos, {n_foto} fotos/outros)"
        )
        self.append_log(summary)
        self.append_log(f"Downloads deste perfil irao para: {dest}")
        if src == "reels" and len(items) <= 2:
            tip = (
                "Poucos reels neste perfil (a API do Instagram so devolveu "
                f"{len(items)}). Tente 'Destaques' ou 'Posts' no seletor ao lado."
            )
            self.append_log(tip)
        self.lbl_counts.setText(
            f"@{self.current_username}  |  fonte: {src_label}  |  "
            f"total: {len(items)}  |  videos: {n_vid}  |  fotos: {n_foto}"
        )
        self._set_job(summary, "ok")
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("listagem 100%")
        self._apply_filter()

    def _filtered_items(self) -> list[MediaItem]:
        mode = self.filter.currentData()
        if mode == "video":
            return [m for m in self.items if m.is_video]
        if mode == "foto":
            return [m for m in self.items if not m.is_video]
        return list(self.items)

    def _apply_filter(self) -> None:
        if self.list_mode == "highlight_tray":
            return
        if not self.items and self.list.count() and self.list.item(0).data(ROLE_CODE) == "url":
            return
        visible = self._filtered_items()
        self.list.clear()
        total = len(visible)
        width = max(3, len(str(total)))
        for i, m in enumerate(visible, start=1):
            kind = _kind_of(m)
            tag = {
                "video": "MP4",
                "foto": "FOTO",
                "carrossel": "ALBUM",
                "destaque": "DESTAQUE",
            }[kind]
            extra = ""
            if m.highlight_title:
                extra = f"  |  {m.highlight_title}"
            # Prefer CDN para download (destaques). URL da pagina so como fallback.
            dl = (m.media_url or m.url or "").strip()
            if m.media_url and m.shortcode and "#ig=" not in dl:
                stem = m.shortcode
                if m.highlight_title:
                    stem = f"{m.highlight_title}_{stem}"
                dl = f"{dl}#ig={stem}"
            label = f"{i:>{width}}. [{tag}]  {m.shortcode}{extra}"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(ROLE_URL, dl)
            item.setData(ROLE_CODE, m.shortcode)
            item.setData(ROLE_KIND, kind)
            tip = f"#{i}/{total}  {kind.upper()}\n{m.url}"
            if m.media_url:
                tip += "\n(download direto CDN)"
            if m.caption:
                tip += f"\n{(m.caption or '')[:200]}"
            item.setToolTip(tip)
            self.list.addItem(item)
        mode = self.filter.currentText()
        self.lbl_counts.setText(
            f"@{self.current_username or '?'}  |  "
            f"mostrando {total} de {len(self.items)}  |  filtro: {mode}"
        )
        self.status.showMessage(
            f"{total} midias na lista ({mode}). Marque as que quer baixar."
        )

    def _set_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(state)

    def _selected_urls(self) -> list[str]:
        urls = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                u = it.data(ROLE_URL)
                if u:
                    urls.append(u)
        return urls

    def do_download_selected(self) -> None:
        # Modo pastas de destaque: busca midias das marcadas e baixa tudo
        if self.list_mode == "highlight_tray":
            self._download_selected_highlight_folders()
            return

        urls = self._selected_urls()
        if not urls:
            QMessageBox.information(self, "Download", "Nenhum item marcado.")
            return
        user = self.current_username or None
        dest = self._dest_for(user) if user else self.out_dir
        total = len(urls)

        def on_ok(path) -> None:
            folder = path or dest
            msg = (
                f"Lote terminou ({total} na fila). "
                f"Veja o resumo no log (ok / ja existiam / falhas). Pasta:\n{folder}"
            )
            self.append_log(msg)
            self._set_job("Download do lote concluido (veja resumo no log)", "ok")
            self.progress.setRange(0, total)
            self.progress.setValue(total)
            self.progress.setFormat(f"{total}/{total}")

        self._run(
            download_urls,
            on_ok,
            urls,
            self.out_dir,
            want_log=True,
            username=user,
            busy_label=f"Baixando {total} itens (1 por vez)...",
            dl_total=total,
        )

    def _download_selected_highlight_folders(self) -> None:
        ids = self._selected_highlight_ids()
        if not ids:
            QMessageBox.information(
                self, "Destaques", "Marque pelo menos um destaque na lista."
            )
            return
        user = self.current_username
        if not user:
            QMessageBox.warning(self, "Destaques", "Perfil desconhecido.")
            return

        mode = self.filter.currentData() or "all"
        dest = self._dest_for(user)
        want_nums = {x.replace("highlight:", "") for x in ids}
        titles = [
            h.title
            for h in self.highlights
            if h.id.replace("highlight:", "") in want_nums
        ]
        self.append_log(
            f"Baixando destaques marcados ({len(ids)}): {', '.join(titles)}"
        )

        def job(**kwargs):
            on_progress = kwargs.pop("on_progress", None)
            on_line = kwargs.get("on_line")

            def prog(msg, cur, tot):
                # so progress (ja vai pro log via _on_progress); evita linha duplicada
                if on_progress:
                    on_progress(msg, cur, tot)

            _user, items = list_highlights(
                user,
                limit=None,
                only_ids=ids,
                on_progress=prog,
            )
            if mode == "video":
                items = [m for m in items if m.is_video]
            elif mode == "foto":
                items = [m for m in items if not m.is_video]
            with_cdn = sum(1 for m in items if (m.media_url or "").strip())
            if on_line:
                on_line(
                    f"{len(items)} midias nos destaques ({with_cdn} com URL direta). "
                    "Baixando via CDN..."
                )
            if not items:
                raise RuntimeError("Nenhuma midia nos destaques marcados (ou filtro vazio).")
            if with_cdn == 0:
                raise RuntimeError(
                    "API nao devolveu URLs de midia. Clique em Conectar Chrome "
                    "e liste os destaques de novo."
                )
            return download_media_items(
                items,
                out_dir=self.out_dir,
                username=user,
                on_line=on_line,
            )

        def on_ok(path) -> None:
            folder = path or dest
            msg = (
                f"Destaques terminaram. Veja o resumo no log. Pasta:\n{folder}"
            )
            self.append_log(msg)
            self._set_job("Download dos destaques concluido", "ok")
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
            self.progress.setFormat("100%")

        self._run(
            job,
            on_ok,
            want_log=True,
            want_progress=True,
            busy_label=f"Baixando {len(ids)} destaque(s) marcado(s)...",
        )

    def _on_url_enter(self) -> None:
        text = self.url.text().strip()
        if parse_post_url(text):
            self.do_download_url()
        else:
            self.do_list()

    def do_download_url(self) -> None:
        text = self.url.text().strip()
        post = parse_post_url(text)
        if not post:
            QMessageBox.warning(
                self,
                "URL",
                "Cole a URL completa de um post, reel ou destaque, por exemplo:\n"
                "https://www.instagram.com/p/XXXX/\n"
                "https://www.instagram.com/reel/XXXX/\n"
                "https://www.instagram.com/reels/XXXX/\n"
                "https://www.instagram.com/stories/highlights/18318952564155412/",
            )
            return
        kind = "destaque" if parse_highlight_id(post) else "post/reel"

        def on_ok(path) -> None:
            msg = f"OK - salvo em {path}"
            self.append_log(msg)
            self._set_job(msg, "ok")
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
            self.progress.setFormat("100%")
            if path:
                self.current_username = Path(path).name

        self._run(
            download_urls,
            on_ok,
            [post],
            self.out_dir,
            want_log=True,
            busy_label=f"Baixando {kind}...",
        )

    def do_download_profile(self) -> None:
        try:
            username = parse_username_or_url(self.url.text())
        except ValueError as e:
            QMessageBox.warning(self, "Perfil", str(e))
            return
        mode = self.filter.currentData()
        extra = ""
        if mode == "video":
            extra = (
                "\nObs.: o filtro da lista nao limita o perfil inteiro "
                "(baixa posts + reels)."
            )
        if (
            QMessageBox.question(
                self,
                "Perfil inteiro",
                f"Baixar posts + reels de @{username}?{extra}\n"
                "Vai listar primeiro e depois baixar 1 por vez "
                "(com progresso no log).\n"
                "Destaques: use a aba Destaques.\n"
                "Pode demorar e o Instagram pode limitar.",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.current_username = safe_username(username)
        dest = self._dest_for(username)

        def on_ok(path) -> None:
            msg = f"Perfil concluido em {path}"
            self.append_log(msg)
            self._set_job(msg, "ok")
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
            self.progress.setFormat("100%")

        self._run(
            download_profile_all,
            on_ok,
            username,
            self.out_dir,
            want_log=True,
            want_progress=True,
            busy_label=f"Baixando perfil @{username} -> {dest}",
        )

    def _parse_dl_progress(self, line: str, fallback_total: int) -> None:
        """Atualiza barra a partir de linhas [i/total] do downloader."""
        m = re.search(r"\[(\d+)/(\d+)\]", line)
        if m:
            cur = int(m.group(1))
            tot = int(m.group(2))
            self._set_progress(cur, tot)
            self._set_job(line[:160], "busy")
            return
        # listagem / etapas do perfil
        if any(
            x in line
            for x in (
                "Destaque",
                "Perfil @",
                "[posts]",
                "[reels]",
                "Listando",
                "midias",
                "CDN OK",
                "Ja baixado",
                "FALHOU",
                "Resumo:",
            )
        ):
            self._set_job(line[:160], "busy")
            # "X midias ... Baixando" -> prepara barra
            m2 = re.search(r"(\d+)\s+midias", line)
            if m2 and "Baixando" in line:
                tot = int(m2.group(1))
                if tot > 0:
                    self._set_progress(0, tot)

SINGLE_INSTANCE_KEY = "instagram-baixar-single-instance-v9"


def _try_raise_existing() -> bool:
    """Se ja houver instancia, pede pra ela focar a janela. True = ja existe."""
    sock = QLocalSocket()
    sock.connectToServer(SINGLE_INSTANCE_KEY)
    if not sock.waitForConnected(250):
        # socket zumbi: limpa e segue como instancia unica
        QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
        return False
    sock.write(b"raise\n")
    sock.flush()
    sock.waitForBytesWritten(250)
    sock.disconnectFromServer()
    return True


def _start_instance_server(win: MainWindow) -> QLocalServer:
    """Servidor local: segunda abertura so acorda esta janela."""
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server = QLocalServer(win)
    if not server.listen(SINGLE_INSTANCE_KEY):
        QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
        server.listen(SINGLE_INSTANCE_KEY)

    def on_new() -> None:
        client = server.nextPendingConnection()
        if client:
            client.readAll()
            client.disconnectFromServer()
        win.showNormal()
        win.raise_()
        win.activateWindow()

    server.newConnection.connect(on_new)
    return server


def main() -> None:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Instagram Baixar")
    app.setOrganizationName("instagram-baixar")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLE)

    # Lock nativo: impede 2 processos mesmo se o socket falhar
    shared = QSharedMemory(SINGLE_INSTANCE_KEY + "-mem")
    if not shared.create(1):
        if _try_raise_existing():
            sys.exit(0)
        # memoria zumbi (crash anterior): recria
        if shared.attach():
            shared.detach()
        if not shared.create(1) and _try_raise_existing():
            sys.exit(0)
    else:
        # primeira instancia: ainda assim avisa a antiga via socket, se houver
        pass

    if _try_raise_existing():
        sys.exit(0)

    app._single_mem = shared  # type: ignore[attr-defined]

    icon = _app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    # Conecta sessao ANTES de mostrar a janela (sempre headless / escondido)
    startup_msg = ""
    try:
        path = capture_from_chrome(allow_visible=False)
        startup_msg = f"Sessao pronta em {path}"
    except Exception as e:  # noqa: BLE001
        startup_msg = (
            f"Sessao automatica (headless) falhou: {e}\n"
            "Se precisar, use 'Abrir navegador e logar'."
        )

    win = MainWindow()
    app._single_server = _start_instance_server(win)  # type: ignore[attr-defined]
    if startup_msg:
        win.append_log(startup_msg)
    win.refresh_session()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
