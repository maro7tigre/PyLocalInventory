"""
Password Widget - Displays password entry screen for selected profile
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from ui.widgets.themed_widgets import GreenButton, ColoredLineEdit, PasswordInputWidget
from ui.widgets.preview_widget import PreviewWidget


class CircularCheckBox(QCheckBox):
    """Dark-theme checkbox with a consistent green circle and white tick."""

    _indicator_size = 28
    _text_gap = 12

    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(
            self._indicator_size + self._text_gap + self.fontMetrics().horizontalAdvance(self.text()),
            max(50, hint.height()),
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        indicator_y = (self.height() - self._indicator_size) // 2
        indicator = self.rect().adjusted(1, indicator_y + 1, 0, 0)
        indicator.setWidth(self._indicator_size - 2)
        indicator.setHeight(self._indicator_size - 2)

        if self.isChecked():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#4CAF50"))
        else:
            border = QColor("#66bb6a") if self.underMouse() else QColor("#cfd8dc")
            painter.setPen(QPen(border, 2))
            painter.setBrush(QColor("#2b2b2b"))
        painter.drawEllipse(indicator)

        if self.isChecked():
            painter.setPen(QPen(QColor("#ffffff"), 3.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            left = indicator.left()
            top = indicator.top()
            painter.drawLine(left + 6, top + 13, left + 11, top + 18)
            painter.drawLine(left + 11, top + 18, left + 21, top + 7)

        text_rect = self.rect().adjusted(self._indicator_size + self._text_gap, 0, 0, 0)
        painter.setPen(QColor("#e6e6e6") if self.isEnabled() else QColor("#888888"))
        painter.drawText(
            text_rect,
            Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap,
            self.text(),
        )


class ProfileArea(QWidget):
    """Keeps the profile card at the exact center and options beside it."""

    card_width = 430
    card_height = 372
    options_width = 340
    gap = 24

    def __init__(self, card, options, parent=None):
        super().__init__(parent)
        self.card = card
        self.options = options
        self.card.setParent(self)
        self.options.setParent(self)
        self.setFixedHeight(self.card_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        card_width = min(self.card_width, max(350, self.width() - 390))
        card_x = (self.width() - card_width) // 2
        card_y = (self.height() - self.card_height) // 2
        self.card.setGeometry(card_x, card_y, card_width, self.card_height)

        available_right = self.width() - (card_x + card_width + self.gap)
        options_width = min(self.options_width, max(0, available_right))
        self.options.setGeometry(
            card_x + card_width + self.gap,
            card_y,
            options_width,
            self.card_height,
        )


class PasswordWidget(QWidget):
    """Password entry widget with profile preview - full width responsive design"""
    
    password_submitted = Signal(str, bool, bool)  # password, remember_profile, startup_enabled
    profile_change_requested = Signal()  # Emitted when user wants to change profile
    
    def __init__(self, profile, remember_profile=False, startup_enabled=False, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.remember_profile = remember_profile
        self.startup_enabled = startup_enabled
        self.setup_ui()
        self.apply_styles()
    
    def setup_ui(self):
        """Setup the password entry interface with full-width responsive design"""
        # Main layout with margins
        main_layout = QVBoxLayout(self)
        self.main_layout = main_layout
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(30)
        
        # The card is positioned independently so its center always matches the
        # window center; the option controls sit beside it without shifting it.
        profile_card = QWidget()
        profile_card.setObjectName("profile_card")
        profile_layout = QVBoxLayout(profile_card)
        profile_layout.setContentsMargins(30, 30, 30, 30)
        profile_layout.setSpacing(15)
        
        # Build a two-column header in the profile card: left = preview/info,
        # right = checkboxes (so they appear to the right of the profile)
        card_header = QHBoxLayout()

        # Left column: preview and textual info
        left_col = QVBoxLayout()
        left_col.setSpacing(10)
        left_col.setContentsMargins(0, 0, 0, 0)

        preview_container = QHBoxLayout()
        preview_container.addStretch()
        self.profile_preview = PreviewWidget(100, "individual")
        if self.profile and hasattr(self.profile, 'preview_path') and self.profile.preview_path:
            self.profile_preview.set_image_path(self.profile.preview_path)
        preview_container.addWidget(self.profile_preview)
        preview_container.addStretch()
        left_col.addLayout(preview_container)

        # Profile information
        profile_name = self.profile.name if self.profile else "No Profile"
        self.profile_name_label = QLabel(profile_name)
        self.profile_name_label.setObjectName("profile_name")
        self.profile_name_label.setAlignment(Qt.AlignCenter)
        left_col.addWidget(self.profile_name_label)

        company_name = "Unknown Company"
        if self.profile:
            company_name = self.profile.get_value("company name") or "Unknown Company"

        self.company_name_label = QLabel(company_name)
        self.company_name_label.setObjectName("company_name")
        self.company_name_label.setAlignment(Qt.AlignCenter)
        left_col.addWidget(self.company_name_label)

        card_header.addLayout(left_col, 3)
        profile_layout.addLayout(card_header)

        # Change profile button - full width within card (below header)
        self.change_profile_btn = QPushButton("Change Profile")
        self.change_profile_btn.setObjectName("change_profile_btn")
        self.change_profile_btn.clicked.connect(self.profile_change_requested.emit)
        profile_layout.addWidget(self.change_profile_btn)
        
        # Place the checkboxes outside of the profile card, to its right
        checks_widget = QWidget()
        checks_widget.setObjectName("profile_checks")
        checks_layout = QVBoxLayout(checks_widget)
        checks_layout.setContentsMargins(0, 10, 0, 10)
        checks_layout.setSpacing(18)
        checks_layout.addStretch()

        self.remember_profile_checkbox = CircularCheckBox("Remember this profile")
        self.remember_profile_checkbox.setObjectName("remember_profile_checkbox")
        self.remember_profile_checkbox.setChecked(bool(self.remember_profile))
        checks_layout.addWidget(self.remember_profile_checkbox)

        self.startup_checkbox = CircularCheckBox("Start PyLocalInventory when Windows starts")
        self.startup_checkbox.setObjectName("startup_checkbox")
        self.startup_checkbox.setChecked(bool(self.startup_enabled))
        checks_layout.addWidget(self.startup_checkbox)
        checks_layout.addStretch()

        self.profile_area = ProfileArea(profile_card, checks_widget)
        self.profile_area.setObjectName("profile_container")
        main_layout.addWidget(self.profile_area)
        
        # Password form container
        form_container = QWidget()
        self.form_container = form_container
        form_container.setObjectName("form_container")
        form_wrapper_layout = QVBoxLayout(form_container)
        form_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        
        # Form content - centered with max width
        form_content_wrapper = QHBoxLayout()
        form_content_wrapper.addStretch()
        
        form_content = QWidget()
        form_content.setMaximumWidth(500)  # Match profile card width
        form_content.setMinimumWidth(350)  # Minimum width
        form_layout = QVBoxLayout(form_content)
        form_layout.setContentsMargins(30, 20, 30, 20)
        form_layout.setSpacing(20)
        
        # Password label
        password_label = QLabel("Enter Password:")
        password_label.setObjectName("password_label")
        form_layout.addWidget(password_label)
        
        # Password input - full width within form
        self.password_input = PasswordInputWidget()
        self.password_input.setObjectName("password_input")
        self.password_input.setPlaceholderText("Enter your password...")
        self.password_input.returnPressed().connect(self._submit_password)
        self.password_input.textChanged().connect(self._reset_password_styling)
        form_layout.addWidget(self.password_input)

        # (Checkboxes moved into profile card header)
        
        # Confirm button - full width within form
        self.confirm_btn = GreenButton("Unlock Profile")
        self.confirm_btn.setObjectName("confirm_btn")
        self.confirm_btn.setMinimumHeight(45)  # Make button taller
        self.confirm_btn.clicked.connect(self._submit_password)
        form_layout.addWidget(self.confirm_btn)
        
        form_content_wrapper.addWidget(form_content)
        form_content_wrapper.addStretch()
        form_wrapper_layout.addLayout(form_content_wrapper)
        
        main_layout.addWidget(form_container)
        
        # Focus on password input
        self.password_input.setFocus()
    
    def _submit_password(self):
        """Submit password for validation"""
        password = self.password_input.text()
        remember_profile = self.remember_profile_checkbox.isChecked()
        startup_enabled = self.startup_checkbox.isChecked()
        self.password_submitted.emit(password, remember_profile, startup_enabled)

    def _reset_password_styling(self):
        """Reset password input styling when text changes"""
        self.password_input.reset_border_color()
    
    def set_password_error(self):
        """Set error styling for incorrect password"""
        self.password_input.set_border_color("#f44336")  # Red border
        self.password_input.selectAll()  # Select all text for easy re-entry
    
    def apply_styles(self):
        """Apply custom styling to the password widget"""
        self.setStyleSheet("""
            PasswordWidget {
                background-color: #2b2b2b;
                min-height: 600px;
            }
            
            QWidget#profile_container {
                background-color: transparent;
            }
            
            QWidget#profile_card {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #3c3c3c, stop:1 #2d2d2d);
                border: 2px solid #4CAF50;
                border-radius: 15px;
            }
            
            QLabel#profile_name {
                font-size: 16px;
                color: #cccccc;
                margin: 5px 0px;
                font-weight: normal;
            }
            
            QLabel#company_name {
                font-size: 26px;
                font-weight: bold;
                color: #ffffff;
                margin: 5px 0px 10px 0px;
                line-height: 1.2;
            }
            
            QPushButton#change_profile_btn {
                background-color: transparent;
                color: #2196F3;
                border: 2px solid #2196F3;
                padding: 10px 15px;
                font-size: 15px;
                font-weight: 500;
                border-radius: 8px;
                min-height: 35px;
            }
            
            QPushButton#change_profile_btn:hover {
                background-color: #2196F3;
                color: white;
                border-color: #2196F3;
            }
            
            QPushButton#change_profile_btn:pressed {
                background-color: #1976D2;
                border-color: #1976D2;
            }
            
            QWidget#form_container {
                background-color: transparent;
            }
            
            QLabel#password_label {
                font-size: 18px;
                font-weight: 600;
                color: #e0e0e0;
                margin-bottom: 5px;
            }
            
            PasswordInputWidget#password_input {
                min-height: 45px;
            }
            
            QPushButton#confirm_btn {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4CAF50, stop:1 #45a049);
                color: white;
                border: none;
                padding: 15px 25px;
                font-size: 18px;
                font-weight: bold;
                border-radius: 10px;
                min-height: 45px;
            }
            
            QPushButton#confirm_btn:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #5CBAE6, stop:1 #4CAF50);
            }
            
            QPushButton#confirm_btn:pressed {
                background: #45a049;
            }
            
            QPushButton#confirm_btn:disabled {
                background: #666666;
                color: #999999;
            }
            QCheckBox#remember_profile_checkbox, QCheckBox#startup_checkbox {
                color: #e6e6e6;
                font-size: 15px;
                background-color: transparent;
            }
        """)

    
    def resizeEvent(self, event):
        """Keep the profile card centered vertically whenever space permits."""
        super().resizeEvent(event)
        centered_top = (self.height() - ProfileArea.card_height) // 2
        form_height = self.form_container.minimumSizeHint().height()
        largest_non_overlapping_top = (
            self.height()
            - ProfileArea.card_height
            - self.main_layout.spacing()
            - form_height
            - 20
        )
        top_margin = max(40, min(centered_top, largest_non_overlapping_top))
        margins = self.main_layout.contentsMargins()
        if margins.top() != top_margin or margins.bottom() != 20:
            self.main_layout.setContentsMargins(40, top_margin, 40, 20)
