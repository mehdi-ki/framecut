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
    background: #0d131b;
    color: #e9f0f5;
    font-family: 'Noto Sans', 'DejaVu Sans', sans-serif;
    font-size: 12px;
}

QMainWindow {
    background: #080d13;
}

QWidget#editorRoot {
    background: #080d13;
}

QFrame#topbar {
    background: #111a24;
    border: 1px solid #223243;
    border-radius: 12px;
}

QFrame#modebar {
    background: #0f1721;
    border: 1px solid #1f2c39;
    border-radius: 9px;
}

QFrame#workspaceRail {
    background: #101821;
    border: 1px solid #223243;
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
    background: #101821;
}

QFrame#previewToolbar,
QFrame#previewSubbar {
    background: #101923;
    border: 1px solid #1e2d3b;
    border-radius: 7px;
}

QFrame#contextToolbar {
    background: #101923;
    border: 1px solid #223744;
    border-radius: 8px;
}

QToolButton#contextAction {
    color: #a9c2c9;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px;
    min-width: 30px;
    min-height: 26px;
    font-size: 14px;
    font-weight: 700;
}

QToolButton#contextAction:hover {
    color: #effffb;
    background: #214143;
    border-color: #4d8b83;
}

QToolButton#contextAction:disabled {
    color: #566576;
    background: transparent;
}

QFrame#headerDivider {
    background: #2a3a4a;
    border: none;
    max-width: 1px;
}

QFrame#panel QLabel,
QFrame#mediaPanel QLabel,
QFrame#previewPanel QLabel,
QFrame#inspectorPanel QLabel,
QFrame#timelinePanel QLabel {
    background: transparent;
}

QLabel#brand {
    color: #7ce8d6;
    font-size: 16px;
    font-weight: 800;
    letter-spacing: 1px;
}

QLabel#versionLabel {
    color: #718296;
    font-size: 10px;
    font-weight: 700;
}

QLabel#projectTitle {
    color: #f2f7fa;
    font-size: 12px;
    font-weight: 700;
}

QLabel#eyebrow,
QLabel#heading,
QLabel#sectionTitle {
    color: #aec3d2;
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
    color: #8294a6;
}

QLabel#subtle {
    font-size: 11px;
}

QLabel#statusPill {
    color: #91e1d1;
    background: #17302f;
    border: 1px solid #2b665e;
    border-radius: 9px;
    padding: 4px 8px;
    font-size: 10px;
    font-weight: 700;
}

QLabel#statusPill[dirty="true"] {
    color: #f3c978;
    background: #342c1b;
    border-color: #765d2b;
}

QPushButton {
    color: #dbe6ed;
    background: #1a2632;
    border: 1px solid #2d4050;
    border-radius: 7px;
    padding: 6px 11px;
    min-height: 28px;
}

QPushButton:hover {
    background: #243442;
    border-color: #466072;
}

QPushButton:pressed {
    background: #13202a;
}

QPushButton:disabled {
    color: #566576;
    background: #151d25;
    border-color: #202c38;
}

QPushButton#primary,
QPushButton#exportButton {
    color: #061a18;
    background: #72e2d0;
    border: 1px solid #72e2d0;
    font-weight: 800;
}

QPushButton#primary:hover,
QPushButton#exportButton:hover {
    color: #051714;
    background: #9af1e3;
    border-color: #9af1e3;
}

QPushButton#secondary {
    color: #bcc6d2;
    background: #1a1e25;
    border-color: #2e3540;
}

QPushButton#iconButton {
    color: #aebdca;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 5px 8px;
    min-height: 26px;
}

QPushButton#iconButton:hover {
    color: #f1fffc;
    background: #20303c;
    border-color: #3b5666;
}

QToolButton#headerToolButton,
QToolButton#panelMenuButton {
    color: #a9bbc9;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 4px;
    min-width: 30px;
    min-height: 27px;
    font-size: 15px;
    font-weight: 700;
}

QToolButton#headerToolButton:hover,
QToolButton#panelMenuButton:hover {
    color: #effffb;
    background: #223441;
    border-color: #3d5a6b;
}

QToolButton#headerToolButton:pressed,
QToolButton#panelMenuButton:pressed {
    background: #17232d;
}

QFrame#timelineToolGroup {
    background: transparent;
    border: none;
}

QFrame#timelineControlGroup {
    background: #17232e;
    border: 1px solid #263b4a;
    border-radius: 8px;
}

QLabel#timelineGroupLabel {
    color: #758293;
    background: transparent;
    font-size: 8px;
    font-weight: 800;
    letter-spacing: 1px;
    padding: 0 2px;
}

QFrame#timelineSeparator {
    background: #303844;
    border: none;
    max-width: 1px;
}

QToolButton#timelineToolButton,
QToolButton#timelineToolToggle,
QToolButton#timelineMenuButton,
QToolButton#timelineToolDanger,
QToolButton#sourceToolButton,
QToolButton#sourceToolDanger {
    color: #b3c3cf;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px;
    min-width: 32px;
    min-height: 26px;
    font-size: 14px;
    font-weight: 700;
}

QToolButton#timelineToolButton:hover,
QToolButton#timelineToolToggle:hover,
QToolButton#timelineMenuButton:hover,
QToolButton#sourceToolButton:hover {
    color: #effffb;
    background: #203b40;
    border-color: #3f736f;
}

QToolButton#timelineToolDanger,
QToolButton#sourceToolDanger {
    color: #de9aa4;
}

QToolButton#timelineToolDanger:hover,
QToolButton#sourceToolDanger:hover {
    color: #ffd9dd;
    background: #40272d;
    border-color: #8b4c58;
}

QToolButton#timelineToolButton:pressed,
QToolButton#timelineToolToggle:pressed,
QToolButton#timelineMenuButton:pressed,
QToolButton#sourceToolButton:pressed,
QToolButton#sourceToolDanger:pressed {
    background: #151a20;
}

QToolButton#timelineToolToggle:checked {
    color: #071c19;
    background: #72e2d0;
    border-color: #72e2d0;
}

QToolButton#timelineToolButton:disabled,
QToolButton#timelineToolToggle:disabled,
QToolButton#timelineMenuButton:disabled,
QToolButton#timelineToolDanger:disabled,
QToolButton#sourceToolButton:disabled,
QToolButton#sourceToolDanger:disabled {
    color: #5f6875;
    background: transparent;
}

QLabel#timelineIconLabel {
    color: #9eb5c2;
    background: transparent;
    font-size: 13px;
    font-weight: 800;
    padding-left: 1px;
    padding-right: 1px;
}

QLabel#timelineTotal {
    color: #9aa7b7;
    padding-left: 4px;
}

QLabel#sourceRangeLabel {
    color: #8ea5b4;
    font-size: 10px;
}

QLabel#modeBadge {
    color: #78d7c6;
    background: #17302f;
    border: 1px solid #2b665e;
    border-radius: 6px;
    padding: 3px 6px;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: .5px;
}

QLabel#modeBadge[pro="true"] {
    color: #f3cb82;
    background: #342c1b;
    border-color: #765d2b;
}

QComboBox#editModeCombo[pro="true"] {
    color: #ffe2a7;
    background: #352d1d;
    border-color: #765d2b;
}

QLabel#emptyState {
    color: #7e96a6;
    background: #101923;
    border: 1px dashed #2a4654;
    border-radius: 8px;
    padding: 14px 10px;
    min-height: 48px;
}

QFrame#timelineControlGroup QSpinBox {
    min-height: 20px;
    padding: 2px 4px;
}

QPushButton#modeTab {
    color: #879aaa;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 7px 11px;
    min-height: 24px;
}

QPushButton#modeTab:hover,
QPushButton#modeTabActive {
    color: #f0fffc;
    background: #19312f;
    border-color: #2f675f;
}

QPushButton#modeTabActive {
    color: #7ce8d6;
    font-weight: 800;
}

QComboBox#workspacePreset,
QComboBox#editModeCombo,
QComboBox#mediaViewCombo {
    color: #d9f5ef;
    background: #172d31;
    border: 1px solid #2d5d59;
    border-radius: 6px;
    padding: 4px 7px;
    min-height: 22px;
    min-width: 86px;
}

QComboBox#editModeCombo {
    min-width: 66px;
}

QComboBox#mediaViewCombo {
    min-width: 70px;
}

QCheckBox#mediaFavorites {
    color: #e7cb78;
    spacing: 4px;
}

QToolButton#mediaFavoriteButton {
    color: #e7cb78;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 3px 7px;
    min-width: 28px;
    min-height: 24px;
    font-size: 16px;
}

QToolButton#mediaFavoriteButton:hover {
    color: #fff3b0;
    background: #3a3521;
    border-color: #76612d;
}

QToolButton#mediaFavoriteButton:disabled {
    color: #59626a;
    background: transparent;
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
    background: #17232e;
    border: 1px solid #2d4050;
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 24px;
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
    background: #17312f;
    border: 1px solid #72e2d0;
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
    background: #72e2d0;
    border-color: #72e2d0;
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
    background: #0e161e;
    border: 1px solid #20303e;
    border-radius: 8px;
    outline: none;
    padding: 5px;
}

QListWidget::item {
    background: #17232e;
    border: 1px solid #263b4a;
    border-radius: 7px;
    padding: 8px;
    margin: 3px;
}

QListWidget::item:hover {
    background: #20313e;
    border-color: #456074;
}

QListWidget::item:selected {
    color: #ecfffb;
    background: #1b403d;
    border-color: #6be3d1;
}

QFrame#inspectorHeader {
    background: #182631;
    border: 1px solid #294151;
    border-radius: 9px;
}

QFrame#inspectorSection {
    background: #111b24;
    border: 1px solid #223442;
    border-radius: 9px;
}

QFrame#inspectorSectionBody {
    background: #0f1821;
    border-top: 1px solid #1d2c39;
    border-bottom-left-radius: 9px;
    border-bottom-right-radius: 9px;
}

QToolButton#inspectorSectionHeader {
    color: #dcebf1;
    background: #16232d;
    border: none;
    border-radius: 8px;
    padding: 8px 9px;
    min-height: 24px;
    text-align: left;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.8px;
}

QToolButton#inspectorSectionHeader:hover {
    color: #8cebdd;
    background: #1a3036;
}

QFrame#inspectorSectionBody QFormLayout QLabel,
QFrame#inspectorSectionBody QLabel {
    color: #9badbb;
}

QListWidget#mediaList,
QListWidget#keyframeList {
    background: #0d151d;
    border: 1px solid #1f2d3a;
}

QStackedWidget#previewCanvas {
    background: #080d13;
    border: 1px solid #263746;
    border-radius: 9px;
}

QComboBox#projectPreset {
    min-width: 112px;
    background: #182632;
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
    background: #0a1017;
    border: 1px solid #182632;
}

QSplitter::handle:hover {
    background: #2c665f;
}

QStatusBar {
    color: #7f95a6;
    background: #080d13;
    border-top: 1px solid #1c2a36;
}

QToolTip {
    color: #f6fffd;
    background: #252c35;
    border: 1px solid #4a5868;
    padding: 5px 7px;
}

QMenu {
    color: #e9eef3;
    background: #1a1e25;
    border: 1px solid #3a4552;
    padding: 5px;
}

QMenu::item {
    border-radius: 5px;
    padding: 6px 28px 6px 10px;
}

QMenu::item:selected {
    color: #effffb;
    background: #28504b;
}

QMenu::separator {
    height: 1px;
    background: #303844;
    margin: 5px 7px;
}

QDialog {
    background: #15181e;
}

QDialog#cinemaDialog {
    background: #080a0d;
}

QDialog#cinemaDialog QFrame,
QDialog#cinemaDialog QLabel {
    background: transparent;
}

QDialog#cinemaDialog QVideoWidget {
    background: #050608;
}

QStackedWidget#previewCanvas {
    background: #080d13;
    border: 1px solid #263746;
    border-radius: 9px;
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

QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #86efd3;
}
QToolButton:focus, QPushButton:focus {
    border: 1px solid #86efd3;
}
QWidget:disabled {
    color: #8396a5;
}
QToolTip {
    background: #203443;
    color: #f1f8fc;
    border: 1px solid #7195a5;
    padding: 6px;
}

/* CapCut-inspired player/timeline surface: flatter graphite panels, a
   brighter cyan action color, and almost no decorative rounding.  The rest
   of the editor keeps its existing dark theme so the redesign stays focused
   on the two areas where editing happens. */
QFrame#modebar {
    background: #1a1a1a;
    border: 1px solid #2b2b2b;
    border-radius: 3px;
}

QPushButton#modeTab,
QPushButton#modeTabActive {
    color: #9a9a9a;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 2px;
    padding: 5px 9px;
    min-height: 22px;
}

QPushButton#modeTab:hover {
    color: #e9e9e9;
    background: #292929;
}

QPushButton#modeTabActive {
    color: #43c9f2;
    background: #233b48;
    border-color: #2f94b5;
    font-weight: 800;
}

QFrame#previewPanel,
QFrame#timelinePanel {
    background: #171717;
    border: 1px solid #2b2b2b;
    border-radius: 3px;
}

QFrame#previewHeader {
    background: #1e1e1e;
    border-bottom: 1px solid #2b2b2b;
    padding: 1px 5px;
}

QFrame#previewPanel QLabel#heading {
    color: #d8d8d8;
    font-size: 10px;
    letter-spacing: .7px;
}

QLabel#previewStatus {
    color: #777777;
    font-size: 10px;
    padding: 0 2px;
    min-height: 14px;
    max-height: 16px;
}

QLabel#previewModePill {
    color: #50c9ee;
    background: #203846;
    border: 1px solid #2d7591;
    border-radius: 2px;
    padding: 2px 6px;
    font-size: 9px;
}

QStackedWidget#previewCanvas {
    background: #050505;
    border: 1px solid #303030;
    border-radius: 2px;
}

QSlider#previewSeek {
    min-height: 8px;
    max-height: 8px;
}

QSlider#previewSeek::groove:horizontal {
    height: 3px;
    background: #3a3a3a;
    border-radius: 1px;
}

QSlider#previewSeek::sub-page:horizontal {
    background: #2db4df;
    border-radius: 1px;
}

QSlider#previewSeek::handle:horizontal {
    width: 8px;
    height: 8px;
    margin: -3px 0;
    background: #f2f2f2;
    border: 1px solid #41c8ef;
    border-radius: 4px;
}

QFrame#playerTransport {
    background: #1d1d1d;
    border-top: 1px solid #282828;
    border-bottom: 1px solid #282828;
    padding: 2px 4px;
}

QPushButton#previewPlayButton,
QPushButton#previewControlButton {
    color: #d9d9d9;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 2px;
    padding: 2px 6px;
    min-width: 28px;
    min-height: 24px;
    font-size: 14px;
}

QPushButton#previewPlayButton {
    color: #55d0f3;
    background: #243a45;
    border-color: #2f7289;
}

QPushButton#previewPlayButton:hover,
QPushButton#previewControlButton:hover {
    color: #ffffff;
    background: #2b3a42;
    border-color: #4a9ab4;
}

QLabel#previewTimecode,
QLabel#previewTimeLabel {
    color: #9a9a9a;
    font-size: 10px;
    padding-left: 5px;
}

QFrame#previewSubbar,
QFrame#previewToolbar {
    background: #1a1a1a;
    border: 1px solid #292929;
    border-radius: 2px;
}

QFrame#previewToolbar {
    border-left: none;
    border-right: none;
    padding: 0;
}

QFrame#previewToolbar QCheckBox,
QFrame#previewToolbar QLabel,
QFrame#previewToolbar QPushButton,
QFrame#previewToolbar QComboBox {
    color: #8a8a8a;
    font-size: 10px;
}

QFrame#previewPerformanceBar {
    background: #171717;
    border-top: 1px solid #262626;
    padding: 0;
}

QFrame#previewPerformanceBar QComboBox,
QFrame#previewPerformanceBar QPushButton,
QFrame#previewPerformanceBar QToolButton {
    min-height: 24px;
    padding-top: 2px;
    padding-bottom: 2px;
    font-size: 10px;
}

QWidget#timelineInlineBar {
    background: #1a1a1a;
    border-top: 1px solid #272727;
    border-bottom: 1px solid #272727;
    min-height: 30px;
    max-height: 32px;
}

QWidget#timelineInlineBar QLabel,
QWidget#timelineInlineBar QCheckBox,
QWidget#timelineInlineBar QToolButton,
QWidget#timelineInlineBar QLineEdit,
QWidget#timelineInlineBar QDoubleSpinBox {
    font-size: 10px;
    min-height: 22px;
    max-height: 24px;
}

QFrame#timelineToolbar {
    background: #1f1f1f;
    border: 1px solid #2c2c2c;
    border-radius: 2px;
}

QFrame#timelineMeta {
    background: #181818;
    border: none;
}

QFrame#timelinePanel QToolButton#timelineToolButton,
QFrame#timelinePanel QToolButton#timelineToolToggle,
QFrame#timelinePanel QToolButton#timelineMenuButton,
QFrame#timelinePanel QToolButton#timelineToolDanger {
    color: #a8a8a8;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 2px;
    padding: 2px;
    min-width: 28px;
    min-height: 25px;
    font-size: 14px;
}

QFrame#timelinePanel QToolButton#timelineToolButton:hover,
QFrame#timelinePanel QToolButton#timelineToolToggle:hover,
QFrame#timelinePanel QToolButton#timelineMenuButton:hover {
    color: #ffffff;
    background: #2c3b43;
    border-color: #3d788d;
}

QFrame#timelinePanel QToolButton#timelineToolToggle:checked {
    color: #06151b;
    background: #3dc0e8;
    border-color: #58d5f5;
}

QFrame#timelinePanel QToolButton#timelineToolDanger {
    color: #e28d99;
}

QFrame#timelinePanel QLabel#timelineTotal,
QFrame#timelineMeta QLabel {
    color: #858585;
    font-size: 10px;
}

QFrame#timelinePanel QScrollArea {
    background: #171717;
    border: 1px solid #292929;
    border-radius: 2px;
}

QFrame#timelinePanel QScrollBar:horizontal {
    height: 10px;
    background: #191919;
}

QFrame#timelinePanel QScrollBar::handle:horizontal {
    min-width: 34px;
    background: #4b4b4b;
    border-radius: 2px;
}

QFrame#timelinePanel QScrollBar::handle:horizontal:hover {
    background: #3da8c9;
}
"""
