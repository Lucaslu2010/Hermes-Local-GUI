import sys
import re
import subprocess
from dataclasses import dataclass
from typing import Optional
from output_filter import clean_hermes_output, clean_user_input, is_loading_signal
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QScrollArea,
)


# =========================
# Basic Config
# =========================

HERMES_COMMAND = ["hermes", "--yolo"]

WINDOW_TITLE = "Hermes Companion GUI"


# =========================
# Utility
# =========================


@dataclass
class ChatMessage:
    role: str
    content: str


# =========================
# Avatar Reserved Layer
# =========================

class AvatarActionController:
    """
    Reserved for future avatar control.

    Future features:
    - Convert Hermes output into avatar actions.
    - Control Live2D / PNGTuber / VRM.
    - Generate emotion, mouth movement, gesture, and body motion.
    """

    def __init__(self):
        self.current_state = "idle"

    def on_user_message(self, text: str):
        self.current_state = "listening"

    def on_agent_output(self, text: str):
        self.current_state = "talking"

    def on_agent_finished(self):
        self.current_state = "idle"

    def get_state(self) -> str:
        return self.current_state


class AvatarPanel(QFrame):
    """
    Placeholder panel for future avatar rendering.

    Later you can replace the inner card with:
    - QLabel PNGTuber renderer
    - QWebEngineView Live2D renderer
    - QWebEngineView VRM renderer
    """

    def __init__(self):
        super().__init__()

        self.setObjectName("avatarPanel")
        self.setMinimumWidth(320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.setStyleSheet("""
            QFrame#avatarPanel {
                background-color: #ffffff;
                border-left: 1px solid rgba(230, 230, 230, 180);
            }
        """)

        # Main avatar card
        self.avatar_card = QFrame()
        self.avatar_card.setObjectName("avatarCard")
        self.avatar_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.avatar_card.setStyleSheet("""
            QFrame#avatarCard {
                background-color: rgba(240, 240, 240, 150);
                border-radius: 28px;
                border: none;
            }
        """)

        self.status_label = QLabel("Avatar Reserved Area")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("""
            QLabel {
                color: #111111;
                font-size: 17px;
                font-weight: 600;
                background: transparent;
            }
        """)

        self.state_label = QLabel("State: idle")
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setStyleSheet("""
            QLabel {
                color: #666666;
                font-size: 14px;
                background: transparent;
            }
        """)

        self.note_label = QLabel(
            "Future: Live2D / PNGTuber / VRM\n"
            "Hermes output → action model → avatar motion"
        )
        self.note_label.setAlignment(Qt.AlignCenter)
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet("""
            QLabel {
                color: #888888;
                font-size: 13px;
                background: transparent;
            }
        """)

        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.setSpacing(8)

        card_layout.addStretch()
        card_layout.addWidget(self.status_label)
        card_layout.addWidget(self.state_label)
        card_layout.addSpacing(12)
        card_layout.addWidget(self.note_label)
        card_layout.addStretch()

        self.avatar_card.setLayout(card_layout)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.avatar_card)

        self.setLayout(main_layout)

    def update_state(self, state: str):
        self.state_label.setText(f"State: {state}")
# =========================
# Hermes Worker
# =========================

class HermesWorker(QThread):
    output_received = Signal(str)
    error_received = Signal(str)
    process_started = Signal()
    process_stopped = Signal()
    loading_signal = Signal()
    def __init__(self, command):
        super().__init__()
        self.command = command
        self.process: Optional[subprocess.Popen] = None
        self._running = False

    def run(self):
        self._running = True

        try:
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except FileNotFoundError:
            self.error_received.emit(
                f"Cannot find Hermes command: {self.command}\n\n"
                "Please check HERMES_COMMAND in the code."
            )
            self.process_stopped.emit()
            return
        except Exception as e:
            self.error_received.emit(f"Failed to start Hermes:\n{e}")
            self.process_stopped.emit()
            return

        self.process_started.emit()

        try:
            if self.process.stdout is not None:
                for line in self.process.stdout:
                    if not self._running:
                        break

                    if is_loading_signal(line):
                        self.loading_signal.emit()

                    cleaned = clean_hermes_output(
                        line,
                        remove_noise=True,
                    )

                    if cleaned:
                        self.output_received.emit(cleaned)
        except Exception as e:
            self.error_received.emit(f"Error while reading Hermes output:\n{e}")
        finally:
            self._running = False
            self.process_stopped.emit()

    def send_input(self, text: str):
        if not self.process or not self.process.stdin:
            self.error_received.emit("Hermes process is not running.")
            return

        try:
            self.process.stdin.write(text + "\n")
            self.process.stdin.flush()
        except Exception as e:
            self.error_received.emit(f"Failed to send input to Hermes:\n{e}")

    def stop(self):
        self._running = False

        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass

            try:
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass


# =========================
# Chat Panel
# =========================

class ChatBubble(QFrame):
    def __init__(self, text: str, sender: str):
        super().__init__()

        self.sender = sender

        self.setObjectName("chatBubble")
        self.setMaximumWidth(680)

        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.label.setStyleSheet("""
            QLabel {
                color: #111111;
                font-size: 15px;
                line-height: 1.4;
                background: transparent;
            }
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(18, 12, 18, 12)
        layout.addWidget(self.label)
        self.setLayout(layout)

        self.setStyleSheet("""
            QFrame#chatBubble {
                background-color: rgba(230, 230, 230, 170);
                border-radius: 22px;
                border: none;
            }
        """)

    def append_text(self, text: str):
        current = self.label.text()

        if current:
            current += "\n"

        current += text

        self.label.setText(current)
class ChatPanel(QWidget):
    user_message_sent = Signal(str)

    def __init__(self):
        super().__init__()
        self.loading_row = None
        self.loading_label = None
        self.loading_timer = QTimer(self)
        self.loading_timer.timeout.connect(self.update_loading_spinner)
        self.loading_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.loading_index = 0
        self.setObjectName("chatPanel")
        self.setStyleSheet("""
            QWidget#chatPanel {
                background-color: #ffffff;
            }
        """)

        self.message_area = QWidget()
        self.message_area.setObjectName("messageArea")
        self.message_area.setStyleSheet("""
            QWidget#messageArea {
                background-color: #ffffff;
            }
        """)

        self.message_layout = QVBoxLayout()
        self.message_layout.setContentsMargins(24, 24, 24, 24)
        self.message_layout.setSpacing(14)
        self.message_layout.addStretch()
        self.message_area.setLayout(self.message_layout)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.message_area)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #ffffff;
                border: none;
            }

            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 0px;
            }

            QScrollBar::handle:vertical {
                background: rgba(180, 180, 180, 120);
                border-radius: 4px;
                min-height: 30px;
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }

            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)

        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("Type your message...")
        self.input_box.returnPressed.connect(self.send_message)
        self.input_box.setMinimumHeight(44)
        self.input_box.setStyleSheet("""
            QLineEdit {
                background-color: rgba(245, 245, 245, 220);
                border: 1px solid rgba(220, 220, 220, 180);
                border-radius: 22px;
                padding-left: 18px;
                padding-right: 18px;
                font-size: 15px;
                color: #111111;
            }

            QLineEdit:focus {
                border: 1px solid rgba(160, 160, 160, 220);
                background-color: #ffffff;
            }
        """)

        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_message)
        self.send_button.setMinimumHeight(44)
        self.send_button.setMinimumWidth(86)
        self.send_button.setStyleSheet("""
            QPushButton {
                background-color: #111111;
                color: #ffffff;
                border: none;
                border-radius: 22px;
                font-size: 14px;
                padding-left: 18px;
                padding-right: 18px;
            }

            QPushButton:hover {
                background-color: #333333;
            }

            QPushButton:pressed {
                background-color: #000000;
            }
        """)

        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(24, 12, 24, 24)
        input_layout.setSpacing(10)
        input_layout.addWidget(self.input_box)
        input_layout.addWidget(self.send_button)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.scroll_area)
        layout.addLayout(input_layout)

        self.setLayout(layout)

    def append_user_message(self, text: str):
        self._append_message("You", text)

    def append_agent_message(self, text: str):
        self._append_message("Hermes", text)

    def create_agent_bubble(self):
        return self._create_message_row("Hermes", "")
    def append_system_message(self, text: str):
        self._append_message("System", text)

    def _create_message_row(self, sender: str, text: str):
        stretch_item = self.message_layout.takeAt(self.message_layout.count() - 1)

        row = QWidget()
        row.setStyleSheet("background-color: transparent;")

        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)

        bubble = None

        if sender == "You":
            row_layout.addStretch()

            bubble = ChatBubble(text, sender)

            bubble.setStyleSheet("""
                QFrame#chatBubble {
                    background-color: rgba(215, 215, 215, 170);
                    border-radius: 24px;
                    border: none;
                }
            """)

            row_layout.addWidget(bubble)

        elif sender == "Hermes":
            bubble = ChatBubble(text, sender)

            bubble.setStyleSheet("""
                QFrame#chatBubble {
                    background-color: rgba(235, 235, 235, 170);
                    border-radius: 24px;
                    border: none;
                }
            """)

            row_layout.addWidget(bubble)
            row_layout.addStretch()

        else:
            system_label = QLabel(text)

            system_label.setAlignment(Qt.AlignCenter)

            system_label.setStyleSheet("""
                QLabel {
                    color: #999999;
                    font-size: 13px;
                    background: transparent;
                }
            """)

            row_layout.addStretch()
            row_layout.addWidget(system_label)
            row_layout.addStretch()

        row.setLayout(row_layout)

        self.message_layout.addWidget(row)

        if stretch_item:
            self.message_layout.addItem(stretch_item)
        else:
            self.message_layout.addStretch()

        self.scroll_to_bottom()

        return bubble

    def _append_message(self, sender: str, text: str):
        self._create_message_row(sender, text)

    def create_agent_bubble(self):
        return self._create_message_row("Hermes", "")

    def scroll_to_bottom(self):
        QApplication.processEvents()
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum())

    def send_message(self):
        text = self.input_box.text().strip()

        if not text:
            return

        self.input_box.clear()
        self.append_user_message(text)
        self.user_message_sent.emit(text)

    def show_loading(self):
        """
        Show a small spinner bubble while Hermes is working but output is filtered.
        """

        if self.loading_row is not None:
            if not self.loading_timer.isActive():
                self.loading_timer.start(90)
            return

        stretch_item = self.message_layout.takeAt(self.message_layout.count() - 1)

        row = QWidget()
        row.setStyleSheet("background-color: transparent;")

        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)

        bubble = QFrame()
        bubble.setObjectName("loadingBubble")
        bubble.setStyleSheet("""
            QFrame#loadingBubble {
                background-color: rgba(235, 235, 235, 170);
                border-radius: 18px;
                border: none;
            }
        """)

        self.loading_label = QLabel(self.loading_frames[self.loading_index])
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet("""
            QLabel {
                color: #777777;
                font-size: 20px;
                background: transparent;
                padding: 4px 10px;
            }
        """)

        bubble_layout = QVBoxLayout()
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.addWidget(self.loading_label)
        bubble.setLayout(bubble_layout)

        row_layout.addWidget(bubble)
        row_layout.addStretch()

        row.setLayout(row_layout)

        self.message_layout.addWidget(row)

        if stretch_item:
            self.message_layout.addItem(stretch_item)
        else:
            self.message_layout.addStretch()

        self.loading_row = row
        self.loading_timer.start(90)
        self.scroll_to_bottom()

    def update_loading_spinner(self):
        if self.loading_label is None:
            return

        self.loading_index = (self.loading_index + 1) % len(self.loading_frames)
        self.loading_label.setText(self.loading_frames[self.loading_index])

    def hide_loading(self):
        """
        Remove loading spinner when real Hermes content arrives.
        """

        self.loading_timer.stop()

        if self.loading_row is None:
            return

        self.loading_row.setParent(None)
        self.loading_row.deleteLater()

        self.loading_row = None
        self.loading_label = None
        self.loading_index = 0
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1200, 760)
        self.setStyleSheet("""
            QMainWindow {
                background-color: #ffffff;
            }

            QSplitter {
                background-color: #ffffff;
            }

            QSplitter::handle {
                background-color: rgba(230, 230, 230, 160);
                width: 1px;
            }
        """)
        self.avatar_controller = AvatarActionController()
        self.current_agent_bubble = None
        self.agent_response_active = False
        self.allow_display_output = False
        self.has_real_agent_output = False
        self.chat_panel = ChatPanel()
        self.avatar_panel = AvatarPanel()

        self.chat_panel.user_message_sent.connect(self.handle_user_message)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.chat_panel)
        splitter.addWidget(self.avatar_panel)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        self.setCentralWidget(splitter)

        self.hermes_worker = HermesWorker(HERMES_COMMAND)
        self.hermes_worker.output_received.connect(self.handle_hermes_output)
        self.hermes_worker.loading_signal.connect(self.handle_hermes_loading)
        self.hermes_worker.error_received.connect(self.handle_error)
        self.hermes_worker.process_started.connect(self.handle_hermes_started)
        self.hermes_worker.process_stopped.connect(self.handle_hermes_stopped)

        self.hermes_worker.start()

    @Slot()
    def handle_hermes_started(self):
        self.chat_panel.append_system_message("Hermes started.")
        self.avatar_panel.update_state("idle")

    @Slot()
    def handle_hermes_loading(self):
        if not self.allow_display_output:
            return

        if self.has_real_agent_output:
            return

        self.chat_panel.show_loading()
        self.avatar_controller.on_agent_output("")
        self.avatar_panel.update_state(self.avatar_controller.get_state())
    @Slot()
    def handle_hermes_stopped(self):
        self.chat_panel.append_system_message("Hermes stopped.")
        self.avatar_controller.on_agent_finished()
        self.avatar_panel.update_state(self.avatar_controller.get_state())

    @Slot(str)
    def handle_user_message(self, text: str):
        self.allow_display_output = True

        self.chat_panel.hide_loading()

        self.agent_response_active = False
        self.current_agent_bubble = None
        self.has_real_agent_output = False

        self.avatar_controller.on_user_message(text)
        self.avatar_panel.update_state(self.avatar_controller.get_state())

        self.hermes_worker.send_input(text)

    @Slot(str)
    @Slot(str)
    def handle_hermes_output(self, text: str):
        if not self.allow_display_output:
            return

        self.has_real_agent_output = True

        self.chat_panel.hide_loading()

        self.avatar_controller.on_agent_output(text)
        self.avatar_panel.update_state(self.avatar_controller.get_state())

        if not self.agent_response_active:
            self.current_agent_bubble = self.chat_panel.create_agent_bubble()
            self.agent_response_active = True

        if self.current_agent_bubble:
            self.current_agent_bubble.append_text(text)

        self.chat_panel.scroll_to_bottom()
    @Slot(str)
    def handle_error(self, error_text: str):
        self.chat_panel.append_system_message(error_text)

    def closeEvent(self, event):
        if self.hermes_worker and self.hermes_worker.isRunning():
            self.hermes_worker.stop()
            self.hermes_worker.wait(3000)

        event.accept()


# =========================
# App Entry
# =========================

def main():
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()