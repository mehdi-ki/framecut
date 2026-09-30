"""Framecut's dark, compact editor theme.

The palette is deliberately owned by Framecut instead of copying another
editor's artwork. It follows the reference layout through spacing, hierarchy
and contrast: a quiet graphite canvas, teal action color and warm timeline
accents.
"""

STYLE = """
* {
    outline: none;
}

QWidget {
    background: #111318;
    color: #eef1f5;
    font-family: 'Noto Sans', 'DejaVu Sans', sans-serif;
    font-size: 12px;
}

QMainWindow {
    background: #0b0d10;
}

QFrame#topbar {
    background: #111419;
    border: 1px solid #252a33;
    border-radius: 10px;
}

QFrame#modebar {
    background: transparent;
    border: none;
}

QFrame#workspaceRail {
    background: #0f1116;
    border: 1px solid #252a33;
    border-radius: 10px;
}

QFrame#panel,
QFrame#mediaPanel,
QFrame#previewPanel,
QFrame#inspectorPanel,
QFrame#timelinePanel {
    background: #171a20;
    border: 1px solid #292e38;
    border-radius: 10px;
}

QFrame#previewPanel {
    background: #14171c;
}

QFrame#timelinePanel {
    background: #15181e;
}

QFrame#panel QLabel,
QFrame#mediaPanel QLabel,
QFrame#previewPanel QLabel,
QFrame#inspectorPanel QLabel,
QFrame#timelinePanel QLabel {
    background: transparent;
}

QLabel#brand {
    color: #67e6d4;
    font-size: 17px;
    font-weight: 800;
    letter-spacing: 1px;
}

QLabel#projectTitle {
    color: #f4f6f8;
    font-size: 13px;
    font-weight: 700;
}

QLabel#eyebrow,
QLabel#heading,
QLabel#sectionTitle {
    color: #f0f3f6;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1px;
}

QLabel#sectionTitle {
    padding-top: 5px;
    padding-bottom: 3px;
}

QLabel#muted,
QLabel#subtle {
    color: #8b95a4;
}

QLabel#statusPill {
    color: #91bfb4;
    background: #172b2a;
    border: 1px solid #28504b;
    border-radius: 10px;
    padding: 3px 8px;
}

QPushButton {
    color: #e6eaf0;
    background: #20242c;
    border: 1px solid #343b47;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 26px;
}

QPushButton:hover {
    background: #2a303a;
    border-color: #4b5665;
}

QPushButton:pressed {
    background: #171b21;
}

QPushButton:disabled {
    color: #5f6875;
    background: #191c22;
    border-color: #282d35;
}

QPushButton#primary,
QPushButton#exportButton {
    color: #071c19;
    background: #65e3d0;
    border: 1px solid #65e3d0;
    font-weight: 800;
}

QPushButton#primary:hover,
QPushButton#exportButton:hover {
    color: #051714;
    background: #8aefe1;
    border-color: #8aefe1;
}

QPushButton#secondary {
    color: #bcc6d2;
    background: #1a1e25;
    border-color: #2e3540;
}

QPushButton#iconButton {
    color: #aeb9c8;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 22px;
}

QPushButton#iconButton:hover {
    color: #effffb;
    background: #242a32;
    border-color: #37424f;
}

QPushButton#modeTab {
    color: #8792a1;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 7px 11px;
    min-height: 24px;
}

QPushButton#modeTab:hover,
QPushButton#modeTabActive {
    color: #f0fffc;
    background: #1c302f;
    border-color: #2d625a;
}

QPushButton#modeTabActive {
    color: #6be4d3;
    font-weight: 800;
}

QPushButton#railButton {
    color: #8b95a4;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 9px 4px;
    min-height: 28px;
}

QPushButton#railButton:hover {
    color: #e8f9f5;
    background: #1c242b;
    border-color: #303a45;
}

QPushButton#railButtonActive {
    color: #6be4d3;
    background: #18302d;
    border: 1px solid #2d625a;
    border-radius: 7px;
    padding: 9px 4px;
    min-height: 28px;
    font-weight: 800;
}

QLineEdit,
QComboBox,
QSpinBox,
QDoubleSpinBox,
QFontComboBox {
    color: #e8edf2;
    background: #20242c;
    border: 1px solid #343b47;
    border-radius: 5px;
    padding: 5px 7px;
    min-height: 22px;
}

QLineEdit:hover,
QComboBox:hover,
QSpinBox:hover,
QDoubleSpinBox:hover,
QFontComboBox:hover {
    border-color: #536070;
}

QLineEdit:focus,
QComboBox:focus,
QSpinBox:focus,
QDoubleSpinBox:focus,
QFontComboBox:focus {
    color: #f2fffc;
    background: #1b302e;
    border: 1px solid #62dfce;
}

QComboBox::drop-down {
    width: 22px;
    border: none;
}

QComboBox QAbstractItemView {
    color: #eef1f5;
    background: #20242c;
    border: 1px solid #3b4552;
    selection-background-color: #28504b;
    selection-color: #f3fffd;
}

QCheckBox {
    color: #aeb8c6;
    spacing: 7px;
}

QCheckBox:hover {
    color: #edf7f5;
}

QCheckBox::indicator {
    width: 13px;
    height: 13px;
    border-radius: 3px;
    background: #1d222a;
    border: 1px solid #47515e;
}

QCheckBox::indicator:checked {
    background: #65e3d0;
    border-color: #65e3d0;
}

QSlider::groove:horizontal {
    height: 4px;
    background: #303741;
    border-radius: 2px;
}

QSlider::sub-page:horizontal {
    background: #5edbc9;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    width: 12px;
    margin: -4px 0;
    border-radius: 6px;
    background: #e9fffb;
    border: 2px solid #65e3d0;
}

QListWidget {
    color: #e8edf2;
    background: #12151a;
    border: 1px solid #252b34;
    border-radius: 7px;
    outline: none;
    padding: 4px;
}

QListWidget::item {
    background: #1c2027;
    border: 1px solid #2a313c;
    border-radius: 6px;
    padding: 10px;
    margin: 3px;
}

QListWidget::item:hover {
    background: #252b34;
    border-color: #44505f;
}

QListWidget::item:selected {
    color: #ecfffb;
    background: #1c3b37;
    border-color: #5fdac8;
}

QScrollArea,
QScrollArea > QWidget > QWidget {
    background: transparent;
    border: none;
}

QScrollBar:vertical {
    width: 9px;
    background: transparent;
    margin: 2px;
}

QScrollBar::handle:vertical {
    min-height: 28px;
    background: #394451;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #536171;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    height: 0;
    background: none;
}

QSplitter::handle {
    background: #0b0d10;
}

QSplitter::handle:hover {
    background: #315b57;
}

QStatusBar {
    color: #7f8a9a;
    background: #0b0d10;
    border-top: 1px solid #1f242c;
}

QToolTip {
    color: #f6fffd;
    background: #252c35;
    border: 1px solid #4a5868;
    padding: 5px 7px;
}

QDialog {
    background: #15181e;
}

QStackedWidget#previewCanvas {
    background: #090b0e;
    border: 1px solid #252c35;
    border-radius: 8px;
}

QHeaderView::section {
    color: #9da8b7;
    background: #1a1e25;
    border: none;
    padding: 5px;
}

QFormLayout QLabel {
    color: #9aa5b4;
}
"""
