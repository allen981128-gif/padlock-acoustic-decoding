"""Qt style sheets for the Padlock Collector desktop application."""

APP_STYLE = r"""
* {
    font-family: "Segoe UI Variable", "Segoe UI";
    outline: none;
}
QMainWindow, QWidget#AppRoot {
    background: #080c12;
    color: #e9eef7;
    font-size: 10pt;
}
QWidget#ContentSurface {
    background: #0b1018;
}
QWidget#PageSurface, QWidget#ScrollContent, QWidget#ScrollViewport {
    background: #0b1018;
}
QFrame#RecognitionWorkspace {
    background: #0f1621;
    border: 1px solid #202c3b;
    border-radius: 14px;
}
QFrame#RecognitionTabRail {
    background: #0c131d;
    border: 0;
    border-bottom: 1px solid #202c3b;
    border-top-left-radius: 13px;
    border-top-right-radius: 13px;
}
QPushButton#RecognitionTab {
    background: transparent;
    color: #8295ad;
    border: 0;
    border-radius: 0;
    padding: 12px 20px 11px 20px;
    min-width: 150px;
    min-height: 20px;
    font-weight: 650;
}
QPushButton#RecognitionTab:hover {
    background: #101b29;
    color: #c9d8e9;
}
QPushButton#RecognitionTab:checked {
    background: #132238;
    color: #f2f6fc;
    border-bottom: 2px solid #4da3ff;
}
QStackedWidget#RecognitionStack {
    background: transparent;
    border: 0;
}
QWidget#RecognitionPane {
    background: transparent;
    border: 0;
}
QFrame#RecognitionSection {
    background: transparent;
    border: 0;
}
QFrame#RecognitionStatusBand {
    background: #0c141f;
    border: 1px solid #1d2b3b;
    border-radius: 10px;
}
QFrame#CompactCard {
    background: #111824;
    border: 1px solid #202c3b;
    border-radius: 14px;
}
QFrame#OperationStrip {
    background: #0d1622;
    border: 1px solid #26364a;
    border-radius: 11px;
}
QLabel#OperationTitle {
    color: #eaf1fb;
    font-size: 10pt;
    font-weight: 700;
}
QLabel#OperationDetail {
    color: #7f91a8;
    font-size: 9pt;
}
QLabel#ControlState {
    background: #0b111a;
    border: 1px solid #26364a;
    border-radius: 9px;
    color: #9fcfff;
    padding: 7px 10px;
    font-weight: 700;
}
QFrame#Sidebar {
    background: #0d131d;
    border-right: 1px solid #1d2735;
}
QFrame#TopBar {
    background: #0b1018;
    border-bottom: 1px solid #1d2735;
}
QFrame#Card {
    background: #111824;
    border: 1px solid #202c3b;
    border-radius: 14px;
}
QFrame#Card:hover {
    border-color: #2d4056;
}
QFrame#SoftCard {
    background: #0e151f;
    border: 1px solid #1b2634;
    border-radius: 12px;
}
QFrame#MetricCard {
    background: #101824;
    border: 1px solid #1f2b3a;
    border-radius: 12px;
}
QLabel#BrandMark {
    color: #7dd3fc;
    font-size: 22pt;
    font-weight: 800;
}
QLabel#BrandName {
    color: #f6f8fc;
    font-size: 16pt;
    font-weight: 750;
}
QLabel#BrandCaption {
    color: #708198;
    font-size: 9pt;
}
QLabel#PageTitle {
    color: #f5f7fb;
    font-size: 21pt;
    font-weight: 760;
}
QLabel#PageSubtitle {
    color: #8392a8;
    font-size: 10pt;
}
QLabel#SectionTitle {
    color: #eef3fb;
    font-size: 12pt;
    font-weight: 700;
}
QLabel#SectionHint {
    color: #7f8da3;
    font-size: 9pt;
}
QLabel#MetricLabel {
    color: #7f8da3;
    font-size: 8.5pt;
    font-weight: 600;
}
QLabel#MetricValue {
    color: #f1f5fb;
    font-size: 18pt;
    font-weight: 760;
}
QLabel#FieldLabel {
    color: #aab5c5;
    font-size: 9pt;
    font-weight: 600;
}
QLabel#Pill {
    background: #172231;
    border: 1px solid #28374a;
    border-radius: 13px;
    color: #aab7c8;
    padding: 6px 11px;
    font-weight: 650;
}
QLabel#StatusValue {
    color: #edf2f8;
    font-weight: 700;
}
QPushButton {
    background: #172231;
    color: #dbe4ef;
    border: 1px solid #2a3a4e;
    border-radius: 9px;
    padding: 9px 14px;
    min-height: 22px;
    font-weight: 600;
}
QPushButton:hover {
    background: #1d2b3d;
    border-color: #3b536e;
}
QPushButton:pressed {
    background: #121c29;
}
QPushButton:disabled {
    background: #111722;
    color: #536174;
    border-color: #1c2734;
}
QPushButton#Primary {
    background: #2563eb;
    color: #ffffff;
    border-color: #3b82f6;
    font-weight: 700;
}
QPushButton#Primary:hover {
    background: #2f72f3;
}
QPushButton#Secondary {
    background: #112134;
    color: #9bd7ff;
    border-color: #245176;
}
QPushButton#Danger {
    background: #3a1721;
    color: #ffb4c1;
    border-color: #7a2c3d;
    font-weight: 700;
}
QPushButton#Danger:hover {
    background: #51202d;
    border-color: #a43b50;
}
QPushButton#Emergency {
    background: #b42335;
    color: #ffffff;
    border-color: #e0445b;
    font-weight: 800;
    min-height: 34px;
}
QPushButton#Emergency:hover {
    background: #cf2d42;
}
QPushButton#NavButton {
    background: transparent;
    border: 0;
    border-radius: 9px;
    color: #8290a4;
    text-align: left;
    padding: 11px 14px;
    min-height: 26px;
    font-weight: 650;
}
QPushButton#NavButton:hover {
    background: #141f2e;
    color: #d8e1ec;
}
QPushButton#NavButton:checked {
    background: #172b48;
    color: #a8d4ff;
    border-left: 3px solid #4da3ff;
    padding-left: 11px;
}
QPushButton#IconButton {
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
    padding: 0;
    border-radius: 8px;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #0a1018;
    color: #edf2f8;
    border: 1px solid #28374a;
    border-radius: 8px;
    padding: 7px 9px;
    min-height: 25px;
    selection-background-color: #2459a8;
}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: #38506b;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #4b96e6;
}
QComboBox::drop-down {
    border: 0;
    width: 26px;
}
QComboBox QAbstractItemView {
    background: #111824;
    color: #edf2f8;
    border: 1px solid #2c3a4c;
    selection-background-color: #244c7a;
    padding: 4px;
}
QCheckBox {
    color: #b8c3d1;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border: 1px solid #3a4a60;
    border-radius: 5px;
    background: #0a1018;
}
QCheckBox::indicator:checked {
    background: #2f7ee6;
    border-color: #5ba4ff;
}
QCheckBox#OrderedCollect::indicator {
    width: 20px;
    height: 20px;
}
QCheckBox#OrderedCollect::indicator:checked {
    image: none;
}
QTableWidget {
    background: #0b111a;
    alternate-background-color: #0f1722;
    color: #e9eef7;
    border: 1px solid #202c3b;
    border-radius: 10px;
    gridline-color: #192434;
    selection-background-color: #183a62;
    selection-color: #ffffff;
}
QTableWidget::item {
    color: #e9eef7;
}
QTableWidget::item:selected {
    color: #ffffff;
}
QHeaderView::section {
    background: #131d2a;
    color: #8fa0b6;
    padding: 9px 8px;
    border: 0;
    border-bottom: 1px solid #273448;
    font-weight: 700;
}
QTableCornerButton::section {
    background: #131d2a;
    border: 0;
}
QTextEdit {
    background: #080d14;
    color: #a9b7c9;
    border: 1px solid #1c2938;
    border-radius: 10px;
    padding: 7px;
    font-family: "Cascadia Mono", "Consolas";
    font-size: 9pt;
    selection-background-color: #234d7a;
}
QProgressBar {
    background: #0b111a;
    border: 1px solid #253448;
    border-radius: 7px;
    color: #c9d5e4;
    min-height: 18px;
    text-align: center;
}
QProgressBar::chunk {
    background: #3b82f6;
    border-radius: 6px;
}
QScrollArea {
    border: 0;
    background: #0b1018;
}
QScrollArea > QWidget > QWidget {
    background: #0b1018;
}
QScrollArea QWidget#qt_scrollarea_viewport {
    background: #0b1018;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 3px;
}
QScrollBar::handle:vertical {
    background: #263548;
    min-height: 30px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #344a65;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QSplitter::handle {
    background: #111a25;
}
QMessageBox, QInputDialog {
    background: #0b1018;
    color: #e9eef7;
}
QMessageBox QLabel, QInputDialog QLabel {
    color: #e9eef7;
    background: transparent;
}
QMessageBox QPushButton, QInputDialog QPushButton {
    color: #f5f8fc;
    min-width: 56px;
}
QStatusBar {
    background: #0a0f16;
    color: #6f7e92;
    border-top: 1px solid #1b2634;
}
"""


DIALOG_STYLE = r"""
QDialog#ThemedDialog,
QDialog#CodeTransitionDialog,
QDialog#CircleReviewDialog {
    background: #0b1018;
    color: #eef3fb;
    border: 1px solid #26364a;
}
QLabel#DialogEyebrow {
    color: #6fa8e8;
    font-size: 8.5pt;
    font-weight: 750;
    letter-spacing: 0.5px;
}
QLabel#DialogTitle {
    color: #f5f8fc;
    font-size: 17pt;
    font-weight: 760;
}
QLabel#DialogBody {
    color: #aab7c8;
    font-size: 10pt;
    line-height: 1.35;
}
QLabel#DialogCode {
    background: #0a1018;
    color: #f7faff;
    border: 1px solid #31506f;
    border-radius: 12px;
    padding: 12px 18px;
    font-size: 20pt;
    font-weight: 780;
}
QLabel#DialogArrow {
    color: #5f7897;
    font-size: 18pt;
    font-weight: 700;
}
QFrame#DialogPanel {
    background: #101824;
    border: 1px solid #202c3b;
    border-radius: 14px;
}
QFrame#DialogAccentPanel {
    background: #0f1c2b;
    border: 1px solid #294867;
    border-radius: 14px;
}
QPushButton#DialogGhost {
    background: transparent;
    color: #91a2b8;
    border: 1px solid #26364a;
}
QPushButton#DialogGhost:hover {
    background: #121c29;
    color: #dfe8f4;
    border-color: #38516d;
}
QPushButton#DialogPrimary {
    background: #2b6bea;
    color: #ffffff;
    border: 1px solid #4385f5;
    border-radius: 9px;
    padding: 10px 18px;
    min-height: 24px;
    font-weight: 750;
}
QPushButton#DialogPrimary:hover {
    background: #3476f0;
}
QPushButton#DialogDanger {
    background: #351821;
    color: #ffb9c4;
    border: 1px solid #713044;
    border-radius: 9px;
    padding: 10px 18px;
    min-height: 24px;
    font-weight: 700;
}
QPushButton#DialogDanger:hover {
    background: #48202c;
    border-color: #984057;
}
"""
