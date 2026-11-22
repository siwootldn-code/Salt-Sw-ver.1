"""
Salt Sw ver.1 - 시편 세팅 확인 카드 (빠른 시험 어시스턴트)

명령을 해석한 계획(TestCommandPlan)을 화면에 펼쳐 보여 주고, 작업자가 시편 치수를 확인·입력한 뒤
[시편 세팅 완료 · 시험 시작]을 눌러야만 시험이 시작되도록 하는 카드 위젯.

상태
- plan    : 명령 해석 결과 + 치수 입력 + 자동 저장 선택 + 시작/취소
- running : 시험 진행 중 (입력란을 닫아 그래프를 가리지 않는다)
- done    : 시험 완료 + 실제 저장된 Excel / PDF 경로
"""

from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QVBoxLayout, QWidget,
)

from core.auto_export import display_path
from core.command_assistant import (
    TestCommandPlan, control_label, material_label, mode_label, standard_label,
)
from core.i18n import TRANSLATIONS
from core.models import SpecimenType
from core.pid_controller import ControlMode


PANEL_STYLE = """
QFrame#assistCard {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-left: 3px solid #1D4ED8;
    border-radius: 4px;
}
QFrame#assistCard QLabel {
    background-color: transparent;
}
QLabel[class="asst-title"] {
    color: #0F172A;
    font-size: 11pt;
    font-weight: 800;
}
QLabel[class="asst-badge"] {
    color: #1D4ED8;
    font-size: 8pt;
    font-weight: 700;
    border: 1px solid #BFDBFE;
    background-color: #EFF6FF;
    border-radius: 3px;
    padding: 2px 8px;
}
QLabel[class="asst-badge-run"] {
    color: #B45309;
    font-size: 8pt;
    font-weight: 700;
    border: 1px solid #FDE68A;
    background-color: #FFFBEB;
    border-radius: 3px;
    padding: 2px 8px;
}
QLabel[class="asst-badge-done"] {
    color: #047857;
    font-size: 8pt;
    font-weight: 700;
    border: 1px solid #A7F3D0;
    background-color: #ECFDF5;
    border-radius: 3px;
    padding: 2px 8px;
}
QLabel[class="asst-key"] {
    color: #64748B;
    font-size: 8.5pt;
    font-weight: 600;
}
QLabel[class="asst-value"] {
    color: #0F172A;
    font-size: 9.5pt;
    font-weight: 700;
}
QLabel[class="asst-field-label"] {
    color: #64748B;
    font-size: 8pt;
    font-weight: 600;
}
QLabel[class="asst-note"] {
    color: #64748B;
    font-size: 8pt;
}
QLabel[class="asst-warn"] {
    color: #B45309;
    font-size: 8.5pt;
    font-weight: 700;
}
QLabel[class="asst-path"] {
    color: #334155;
    font-size: 8pt;
    font-family: 'Consolas', 'Segoe UI', monospace;
}
QLabel[class="asst-running"] {
    color: #1D4ED8;
    font-size: 10pt;
    font-weight: 700;
}
QLabel[class="asst-done"] {
    color: #047857;
    font-size: 10pt;
    font-weight: 700;
}
"""

# 카드에서 확인·입력받는 치수 필드 (키, 소수 자리, 최대값)
DIMENSION_FIELDS = (
    ("width", 2, 500.0),
    ("thickness", 2, 200.0),
    ("diameter", 2, 500.0),
    ("gauge_length", 1, 1000.0),
    ("span_length", 1, 2000.0),
)

FIELD_WARN_STYLE = (
    "QDoubleSpinBox { border: 1px solid #D97706; background-color: #FFFBEB; "
    "color: #B45309; font-weight: 700; }"
)


class TestAssistantPanel(QFrame):
    """시편 세팅 확인 카드"""

    start_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def __init__(self, lang: str = "KO", parent=None):
        super().__init__(parent)
        self.setObjectName("assistCard")
        self.setStyleSheet(PANEL_STYLE)
        self.lang = lang
        self.plan: Optional[TestCommandPlan] = None
        self.state = "idle"           # idle | plan | running | done
        self.missing = set()
        self.specimen_id = ""
        self.save_dir = "output/auto_reports"
        self.paths: Dict[str, str] = {}
        self.result_numbers: Dict[str, str] = {}
        self.error_text = ""
        self._spins: Dict[str, QDoubleSpinBox] = {}
        self._field_labels: Dict[str, QLabel] = {}
        self._summary_values: Dict[str, QLabel] = {}
        self._build()
        self.retranslate(lang)
        self.setVisible(False)

    # ------------------------------------------------------------------
    # 구성
    # ------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.lbl_title = QLabel()
        self.lbl_title.setProperty("class", "asst-title")
        self.lbl_badge = QLabel()
        self.lbl_badge.setProperty("class", "asst-badge")
        header.addWidget(self.lbl_title)
        header.addStretch()
        header.addWidget(self.lbl_badge)
        root.addLayout(header)

        # 해석 결과 요약 (2열 x 3행)
        self.summary_widget = QWidget()
        grid = QGridLayout(self.summary_widget)
        self._summary_grid = grid
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        rows = (("mode", "standard"), ("material", "control"), ("pid", "specimen"))
        self._summary_keys: Dict[str, QLabel] = {}
        for row, (left, right) in enumerate(rows):
            for col, key in ((0, left), (2, right)):
                key_label = QLabel()
                key_label.setProperty("class", "asst-key")
                value_label = QLabel("-")
                value_label.setProperty("class", "asst-value")
                self._summary_keys[key] = key_label
                self._summary_values[key] = value_label
                grid.addWidget(key_label, row, col)
                grid.addWidget(value_label, row, col + 1)
        root.addWidget(self.summary_widget)

        self.lbl_notes = QLabel("")
        self.lbl_notes.setProperty("class", "asst-note")
        self.lbl_notes.setWordWrap(True)
        root.addWidget(self.lbl_notes)

        # 시편 형상 · 치수 입력
        self.spec_widget = QWidget()
        spec_row = QHBoxLayout(self.spec_widget)
        spec_row.setContentsMargins(0, 0, 0, 0)
        spec_row.setSpacing(12)

        shape_box = QVBoxLayout()
        shape_box.setSpacing(2)
        self.lbl_shape = QLabel()
        self.lbl_shape.setProperty("class", "asst-field-label")
        self.combo_shape = QComboBox()
        self.combo_shape.setMinimumWidth(96)
        self.combo_shape.currentIndexChanged.connect(self._on_shape_changed)
        shape_box.addWidget(self.lbl_shape)
        shape_box.addWidget(self.combo_shape)
        spec_row.addLayout(shape_box)

        for key, decimals, maximum in DIMENSION_FIELDS:
            field_box = QVBoxLayout()
            field_box.setSpacing(2)
            label = QLabel()
            label.setProperty("class", "asst-field-label")
            spin = QDoubleSpinBox()
            spin.setDecimals(decimals)
            spin.setRange(0.0, maximum)
            spin.setMinimumWidth(96)
            spin.valueChanged.connect(lambda value, k=key: self._on_dimension_changed(k, value))
            self._field_labels[key] = label
            self._spins[key] = spin
            field_box.addWidget(label)
            field_box.addWidget(spin)
            spec_row.addLayout(field_box)
            setattr(self, f"spin_{key}", spin)
        spec_row.addStretch()
        root.addWidget(self.spec_widget)

        self.lbl_missing = QLabel("")
        self.lbl_missing.setProperty("class", "asst-warn")
        root.addWidget(self.lbl_missing)

        # 자동 저장
        self.auto_widget = QWidget()
        auto_row = QHBoxLayout(self.auto_widget)
        auto_row.setContentsMargins(0, 0, 0, 0)
        auto_row.setSpacing(10)
        self.chk_auto = QCheckBox()
        self.chk_auto.setChecked(True)
        self.lbl_save_dir = QLabel("")
        self.lbl_save_dir.setProperty("class", "asst-path")
        auto_row.addWidget(self.chk_auto)
        auto_row.addStretch()
        auto_row.addWidget(self.lbl_save_dir)
        root.addWidget(self.auto_widget)

        # 진행 / 완료 상태
        self.running_widget = QWidget()
        running_box = QVBoxLayout(self.running_widget)
        running_box.setContentsMargins(0, 2, 0, 2)
        running_box.setSpacing(2)
        self.lbl_running = QLabel()
        self.lbl_running.setProperty("class", "asst-running")
        self.lbl_running_hint = QLabel()
        self.lbl_running_hint.setProperty("class", "asst-note")
        running_box.addWidget(self.lbl_running)
        running_box.addWidget(self.lbl_running_hint)
        root.addWidget(self.running_widget)

        self.done_widget = QWidget()
        done_box = QVBoxLayout(self.done_widget)
        done_box.setContentsMargins(0, 2, 0, 2)
        done_box.setSpacing(3)
        self.lbl_done = QLabel()
        self.lbl_done.setProperty("class", "asst-done")
        self.lbl_done_summary = QLabel()
        self.lbl_done_summary.setProperty("class", "asst-value")
        self.lbl_file_excel = QLabel()
        self.lbl_file_excel.setProperty("class", "asst-path")
        self.lbl_file_excel.setWordWrap(True)
        self.lbl_file_excel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_file_pdf = QLabel()
        self.lbl_file_pdf.setProperty("class", "asst-path")
        self.lbl_file_pdf.setWordWrap(True)
        self.lbl_file_pdf.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_error = QLabel()
        self.lbl_error.setProperty("class", "asst-warn")
        self.lbl_error.setWordWrap(True)
        done_box.addWidget(self.lbl_done)
        done_box.addWidget(self.lbl_done_summary)
        done_box.addWidget(self.lbl_file_excel)
        done_box.addWidget(self.lbl_file_pdf)
        done_box.addWidget(self.lbl_error)
        root.addWidget(self.done_widget)

        # 버튼
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.btn_start = QPushButton()
        self.btn_start.setObjectName("btn_start")
        self.btn_start.setMinimumWidth(228)
        self.btn_start.setMinimumHeight(36)
        self.btn_start.clicked.connect(self.start_requested.emit)
        self.btn_cancel = QPushButton()
        self.btn_cancel.setMinimumWidth(92)
        self.btn_cancel.clicked.connect(self.cancel_requested.emit)
        buttons.addWidget(self.btn_start)
        buttons.addWidget(self.btn_cancel)
        buttons.addStretch()
        root.addLayout(buttons)

    # ------------------------------------------------------------------
    # 언어
    # ------------------------------------------------------------------
    def retranslate(self, lang: str):
        self.lang = lang
        t = TRANSLATIONS.get(lang, TRANSLATIONS["KO"])

        self.lbl_title.setText(t["asst_card_title"])
        self.lbl_shape.setText(t["asst_shape"])
        shape_index = self.combo_shape.currentIndex()
        self.combo_shape.blockSignals(True)
        self.combo_shape.clear()
        self.combo_shape.addItems([t["asst_shape_flat"], t["asst_shape_round"]])
        self.combo_shape.setCurrentIndex(max(0, shape_index))
        self.combo_shape.blockSignals(False)
        for key in self._field_labels:
            self._field_labels[key].setText(t[f"asst_{key}"])
            self._spins[key].setSpecialValueText(t["asst_enter"])
        for key, label in self._summary_keys.items():
            label.setText(t[f"asst_sum_{key}"])
        self.chk_auto.setText(t["asst_auto_save"])
        self.lbl_save_dir.setText(t["asst_save_dir"].format(path=self.save_dir))
        self.btn_start.setText(t["asst_start"])
        self.btn_cancel.setText(t["asst_close"] if self.state == "done" else t["asst_cancel"])
        self.lbl_running_hint.setText(t["asst_running_hint"])
        self._render()

    # ------------------------------------------------------------------
    # 카드 상태
    # ------------------------------------------------------------------
    def set_plan(self, plan: TestCommandPlan, specimen_id: str, save_dir: str):
        self.plan = plan
        self.state = "plan"
        self.specimen_id = specimen_id
        self.save_dir = save_dir
        self.paths = {}
        self.result_numbers = {}
        self.error_text = ""

        index = 0 if plan.specimen_type is not SpecimenType.ROUND else 1
        self.combo_shape.blockSignals(True)
        self.combo_shape.setCurrentIndex(index)
        self.combo_shape.blockSignals(False)

        self._spins["width"].setValue(float(plan.width_mm or 0.0))
        self._spins["thickness"].setValue(float(plan.thickness_mm or 0.0))
        self._spins["diameter"].setValue(float(plan.diameter_mm or 0.0))
        self._spins["gauge_length"].setValue(float(plan.gauge_length_mm or 0.0))
        self._spins["span_length"].setValue(float(plan.span_length_mm or 0.0))

        self.missing = set(plan.missing_fields)
        self.chk_auto.setChecked(plan.auto_export)
        self.lbl_save_dir.setText(TRANSLATIONS.get(self.lang, TRANSLATIONS["KO"])["asst_save_dir"]
                                  .format(path=save_dir))
        self._apply_highlights()
        self._update_shape_visibility()
        self._render()
        self.setVisible(True)

    def mark_running(self):
        self.state = "running"
        self._render()

    def set_specimen_id(self, specimen_id: str):
        self.specimen_id = str(specimen_id or "")
        if self.state in ("plan", "running"):
            self._render()

    def flag_missing(self, keys):
        """시작 전 빠진 치수를 표시 (부드러운 강조 + 안내 문구)"""
        self.missing = set(keys)
        self._apply_highlights()
        t = TRANSLATIONS.get(self.lang, TRANSLATIONS["KO"])
        names = [t[f"asst_{key}"] for key in keys]
        self.lbl_missing.setText(t["asst_missing_hint"].format(fields=", ".join(names)))
        self.lbl_missing.setVisible(bool(names))
        if names:
            first = self._spins.get(list(keys)[0])
            if first is not None:
                first.setFocus()

    def mark_completed(self, paths: Dict[str, str], load_n: float, stress_mpa: float,
                       specimen_id: str):
        self.state = "done"
        self.paths = dict(paths)
        self.result_numbers = {
            "load": f"{load_n:,.1f}",
            "stress": f"{stress_mpa:.2f}",
            "specimen": specimen_id,
        }
        self.error_text = ""
        self._render()

    def mark_export_failed(self, error: str):
        self.state = "done"
        self.error_text = str(error)
        self._render()

    def reset(self):
        self.state = "idle"
        self.plan = None
        self.paths = {}
        self.setVisible(False)

    # ------------------------------------------------------------------
    def _render(self):
        """현재 상태에 맞춰 보이는 부분만 다시 그린다"""
        t = TRANSLATIONS.get(self.lang, TRANSLATIONS["KO"])
        plan = self.plan

        if self.state == "plan":
            badge = t["asst_badge_plan"]
            badge_class = "asst-badge"
            self.btn_cancel.setText(t["asst_cancel"])
        elif self.state == "running":
            badge = t["asst_badge_run"]
            badge_class = "asst-badge-run"
        elif self.state == "done":
            badge = t["asst_badge_fail"] if self.error_text else t["asst_badge_done"]
            badge_class = "asst-badge-done"
            self.btn_cancel.setText(t["asst_close"])
        else:
            badge = ""
            badge_class = "asst-badge"
        self.lbl_badge.setText(badge)
        self.lbl_badge.setProperty("class", badge_class)
        self.lbl_badge.style().unpolish(self.lbl_badge)
        self.lbl_badge.style().polish(self.lbl_badge)

        # 요약 값
        if plan is not None:
            self._summary_values["mode"].setText(mode_label(plan.mode, self.lang))
            self._summary_values["standard"].setText(standard_label(plan.mode, self.lang))
            self._summary_values["material"].setText(material_label(plan.material_code, self.lang))
            speed_text = self._speed_text(plan)
            self._summary_values["control"].setText(
                f"{control_label(plan.control_mode, self.lang)} · {speed_text}")
            self._summary_values["pid"].setText(self._pid_text(plan))
            self._summary_values["specimen"].setText(self.specimen_id or "-")
            self._summary_keys["pid"].setVisible(plan.uses_pid)
            self._summary_values["pid"].setVisible(plan.uses_pid)
            # PID 를 쓰지 않으면 시편 번호를 빈 왼쪽 칸으로 당겨 온다
            if plan.uses_pid:
                self._summary_grid.addWidget(self._summary_keys["pid"], 2, 0)
                self._summary_grid.addWidget(self._summary_values["pid"], 2, 1)
                self._summary_grid.addWidget(self._summary_keys["specimen"], 2, 2)
                self._summary_grid.addWidget(self._summary_values["specimen"], 2, 3)
            else:
                self._summary_grid.addWidget(self._summary_keys["specimen"], 2, 0)
                self._summary_grid.addWidget(self._summary_values["specimen"], 2, 1)
            self.lbl_notes.setText(" ".join(plan.note_texts(self.lang)))
            self.lbl_notes.setVisible(self.state == "plan" and bool(plan.note_texts(self.lang)))
            self.lbl_running.setText(t["asst_running"].format(
                mode=mode_label(plan.mode, self.lang), specimen=self.specimen_id or "-"))
        else:
            self.lbl_notes.setText("")

        # 누락 치수 안내
        if self.missing:
            names = [t[f"asst_{key}"] for key in self.missing]
            self.lbl_missing.setText(t["asst_missing_hint"].format(fields=", ".join(names)))
        else:
            self.lbl_missing.setText("")

        # 완료 정보
        if self.state == "done" and not self.error_text:
            self.lbl_done.setText(t["asst_done_title"] if self.paths else t["asst_export_skipped"])
            self.lbl_done.setStyleSheet("" if self.paths else "color: #64748B;")
            if self.paths:
                self.lbl_done_summary.setText(t["asst_done_summary"].format(
                    load=self.result_numbers.get("load", "-"),
                    stress=self.result_numbers.get("stress", "-"),
                    specimen=self.result_numbers.get("specimen", self.specimen_id or "-")))
            else:
                self.lbl_done_summary.setText("")
            excel = self.paths.get("excel", "")
            pdf = self.paths.get("pdf", "")
            self.lbl_file_excel.setText(f'{t["asst_file_excel"]}: {display_path(excel)}' if excel else "")
            self.lbl_file_pdf.setText(f'{t["asst_file_pdf"]}: {display_path(pdf)}' if pdf else "")
            self.lbl_file_excel.setToolTip(excel)
            self.lbl_file_pdf.setToolTip(pdf)
        elif self.state == "done":
            self.lbl_done.setText(t["asst_badge_fail"])
            self.lbl_done_summary.setText("")
            self.lbl_file_excel.setText("")
            self.lbl_file_pdf.setText("")
            self.lbl_done.setStyleSheet("color: #B45309;")
        self.lbl_error.setText(self.error_text)
        self.lbl_error.setVisible(bool(self.error_text))

        self._apply_state()

    def _apply_state(self):
        show_plan = self.state == "plan"
        self.summary_widget.setVisible(self.state in ("plan", "running"))
        self.spec_widget.setVisible(show_plan)
        self.auto_widget.setVisible(show_plan)
        self.lbl_missing.setVisible(show_plan and bool(self.missing))
        self.btn_start.setVisible(show_plan)
        self.btn_cancel.setVisible(self.state in ("plan", "done"))
        self.running_widget.setVisible(self.state == "running")
        self.done_widget.setVisible(self.state == "done")

    # ------------------------------------------------------------------
    def _speed_text(self, plan: TestCommandPlan) -> str:
        control = str(plan.control_mode).upper()
        if control == ControlMode.LOAD_RATE.value:
            return f"{plan.target_rate:,.0f} N/min"
        if control == ControlMode.STRESS_RATE.value:
            return f"{plan.target_rate:g} MPa/s"
        if control == ControlMode.LOAD_HOLD.value:
            return f"{plan.target_holding_val:,.0f} N · {plan.holding_duration_s:g} s"
        return f"{plan.test_speed_mm_min:g} mm/min"

    def _pid_text(self, plan: TestCommandPlan) -> str:
        t = TRANSLATIONS.get(self.lang, TRANSLATIONS["KO"])
        return t.get(f"asst_pid_{plan.pid_profile_id}", plan.pid_profile_id)

    # ------------------------------------------------------------------
    def _on_shape_changed(self, index: int):
        self._update_shape_visibility()

    def _update_shape_visibility(self):
        is_round = self.combo_shape.currentIndex() == 1
        self._field_labels["width"].setVisible(not is_round)
        self._spins["width"].setVisible(not is_round)
        self._field_labels["thickness"].setVisible(not is_round)
        self._spins["thickness"].setVisible(not is_round)
        self._field_labels["diameter"].setVisible(is_round)
        self._spins["diameter"].setVisible(is_round)
        is_bending = self.plan is not None and self.plan.mode.name == "BENDING"
        self._field_labels["span_length"].setVisible(is_bending)
        self._spins["span_length"].setVisible(is_bending)

    def _on_dimension_changed(self, key: str, value: float):
        if value > 0 and key in self.missing:
            self.missing.discard(key)
            self._spins[key].setStyleSheet("")
            t = TRANSLATIONS.get(self.lang, TRANSLATIONS["KO"])
            if self.missing:
                names = [t[f"asst_{item}"] for item in self.missing]
                self.lbl_missing.setText(t["asst_missing_hint"].format(fields=", ".join(names)))
            else:
                self.lbl_missing.setText("")

    def _apply_highlights(self):
        for key, spin in self._spins.items():
            if key in self.missing:
                spin.setStyleSheet(FIELD_WARN_STYLE)
            else:
                spin.setStyleSheet("")

    # ------------------------------------------------------------------
    def selected_specimen_type(self) -> SpecimenType:
        return SpecimenType.ROUND if self.combo_shape.currentIndex() == 1 else SpecimenType.FLAT

    def values(self) -> Dict[str, float]:
        return {
            "width": self._spins["width"].value(),
            "thickness": self._spins["thickness"].value(),
            "diameter": self._spins["diameter"].value(),
            "gauge_length": self._spins["gauge_length"].value(),
            "span_length": self._spins["span_length"].value(),
            "specimen_type": self.selected_specimen_type(),
        }

    def validation_errors(self) -> List[str]:
        """시작 전 확인해야 할 치수 (화면에 보이는 항목만)"""
        errors: List[str] = []
        values = self.values()
        if values["specimen_type"] is SpecimenType.ROUND:
            if values["diameter"] <= 0:
                errors.append("diameter")
        else:
            if values["width"] <= 0:
                errors.append("width")
            if values["thickness"] <= 0:
                errors.append("thickness")
        if values["gauge_length"] <= 0:
            errors.append("gauge_length")
        if self.plan is not None and self.plan.mode.name == "BENDING" and values["span_length"] <= 0:
            errors.append("span_length")
        return errors

    def auto_export_enabled(self) -> bool:
        return self.chk_auto.isChecked()
