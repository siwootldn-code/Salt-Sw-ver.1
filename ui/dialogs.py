"""
Salt Sw ver.1 - 진단형 다이얼로그 (시퀀스 편집 · 시험 이력)
- SequenceDialog: 다단계 시퀀스 단계 편집 (동작/목표/속도/유지 시간)
- HistoryDialog: 자동 저장된 시험 이력 목록, 무결성 검증, 오버레이 불러오기
"""

from typing import Callable, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QDoubleSpinBox, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QGroupBox, QSizePolicy, QCheckBox,
    QFileDialog, QMessageBox
)

from core.auto_export import FOLDER_RULES, resolve_report_dir
from core.history import HistorySummary, TestHistoryStore
from core.i18n import TRANSLATIONS, tr
from core.models import Specimen, TestConfig
from core.sequence import SequenceProgram, SequenceStep, StepAction
from ui.styles import HYUNDAI_THEME_QSS

MODE_LABEL_KEYS = {
    "TENSILE": "mode_tensile",
    "COMPRESSION": "mode_compression",
    "BENDING": "mode_bending",
    "HOLDING": "mode_holding",
    "SEQUENCE": "mode_sequence",
}


def mode_display(mode_name: str, lang: str) -> str:
    key = MODE_LABEL_KEYS.get(mode_name)
    return tr(lang, key) if key else mode_name


class SequenceDialog(QDialog):
    """다단계 시험 시퀀스 편집 창"""

    def __init__(self, program: Optional[SequenceProgram], lang: str = "KO", parent=None):
        super().__init__(parent)
        self.lang = lang
        self.t = TRANSLATIONS.get(lang, TRANSLATIONS["KO"])
        self.program = (program.copy() if program else SequenceProgram.standard())
        self._row_widgets: List[dict] = []

        self.setWindowTitle(self.t["seq_dialog_title"])
        self.setStyleSheet(HYUNDAI_THEME_QSS)
        self.resize(820, 470)
        self.setMinimumSize(720, 420)
        self._build_ui()
        self._load_program(self.program)

    # ------------------------------------------------------------------
    def _build_ui(self):
        t = self.t
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(t["seq_name_label"]))
        self.edit_name = QLineEdit(self.program.name)
        name_row.addWidget(self.edit_name, stretch=1)
        layout.addLayout(name_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            t["seq_col_no"], t["seq_col_action"], t["seq_col_target"],
            t["seq_col_speed"], t["seq_col_hold"],
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col in (2, 3, 4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 52)
        self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(4, 120)
        self.table.verticalHeader().setDefaultSectionSize(34)
        layout.addWidget(self.table, stretch=1)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)
        self.btn_add = QPushButton(t["seq_add"])
        self.btn_add.clicked.connect(lambda: self._add_row(SequenceStep(StepAction.RAMP_DISP, 5.0, 5.0)))
        self.btn_remove = QPushButton(t["seq_remove"])
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_up = QPushButton(t["seq_up"])
        self.btn_up.clicked.connect(lambda: self._move_selected(-1))
        self.btn_down = QPushButton(t["seq_down"])
        self.btn_down.clicked.connect(lambda: self._move_selected(1))

        ctrl_row.addWidget(self.btn_add)
        ctrl_row.addWidget(self.btn_remove)
        ctrl_row.addSpacing(12)
        ctrl_row.addWidget(self.btn_up)
        ctrl_row.addWidget(self.btn_down)
        ctrl_row.addStretch()

        self.combo_preset = QComboBox()
        self.combo_preset.addItems([t["seq_preset_standard"], t["seq_preset_disp"]])
        self.combo_preset.setFixedWidth(210)
        ctrl_row.addWidget(self.combo_preset)
        self.btn_preset = QPushButton(t["seq_load"])
        self.btn_preset.clicked.connect(self._apply_preset)
        ctrl_row.addWidget(self.btn_preset)
        layout.addLayout(ctrl_row)

        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet("color: #B91C1C; font-size: 8.5pt; font-weight: 700; background: transparent;")
        layout.addWidget(self.lbl_error)

        self.lbl_hint = QLabel(t["seq_hint"])
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color: #64748B; font-size: 8.5pt; background: transparent;")
        layout.addWidget(self.lbl_hint)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_ok = QPushButton(t["seq_ok"])
        self.btn_ok.setObjectName("btn_start")
        self.btn_ok.setMinimumWidth(120)
        self.btn_ok.clicked.connect(self._on_accept)
        self.btn_cancel = QPushButton(t["seq_cancel"])
        self.btn_cancel.setMinimumWidth(100)
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_ok)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    def _load_program(self, program: SequenceProgram):
        self.edit_name.setText(program.name)
        self.table.setRowCount(0)
        self._row_widgets.clear()
        for step in program.steps:
            self._add_row(step)
        self._validate()

    def _add_row(self, step: SequenceStep):
        row = self.table.rowCount()
        self.table.insertRow(row)

        idx_item = QTableWidgetItem(str(row + 1))
        idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        idx_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.table.setItem(row, 0, idx_item)

        combo = QComboBox()
        for action in StepAction:
            combo.addItem(tr(self.lang, f"seq_action_{action.value}"), action.value)
        combo.setCurrentIndex(max(0, combo.findData(step.action.value)))

        target = QDoubleSpinBox()
        target.setDecimals(2)
        target.setRange(0.01, 1_000_000.0)
        target.setSingleStep(10.0)
        target.setValue(max(0.01, step.target))
        target.setSpecialValueText("-")
        target.setMinimumHeight(28)

        speed = QDoubleSpinBox()
        speed.setDecimals(2)
        speed.setRange(0.01, 500.0)
        speed.setSingleStep(1.0)
        speed.setValue(max(0.01, step.speed_mm_min))
        speed.setMinimumHeight(28)

        hold = QDoubleSpinBox()
        hold.setDecimals(1)
        hold.setRange(0.0, 86400.0)
        hold.setSingleStep(1.0)
        hold.setValue(max(0.0, step.hold_s))
        hold.setMinimumHeight(28)

        self.table.setCellWidget(row, 1, combo)
        self.table.setCellWidget(row, 2, target)
        self.table.setCellWidget(row, 3, speed)
        self.table.setCellWidget(row, 4, hold)

        record = {"action": combo, "target": target, "speed": speed, "hold": hold,
                  "last_target": max(0.01, step.target)}
        self._row_widgets.append(record)

        combo.currentIndexChanged.connect(lambda _idx, rec=record: self._apply_action_state(rec))
        for widget in (target, speed, hold):
            widget.valueChanged.connect(lambda _v: self._validate())
        combo.currentIndexChanged.connect(lambda _idx: self._validate())
        self._apply_action_state(record)
        self._renumber()

    def _apply_action_state(self, record: dict):
        """동작에 따라 목표값/유지 시간 입력 상태와 단위 표시를 바꾼다"""
        action = StepAction(record["action"].currentData())
        target = record["target"]
        if action == StepAction.RAMP_LOAD:
            target.setEnabled(True)
            target.setSuffix(" N")
            if target.value() <= target.minimum():
                target.setValue(record.get("last_target", 500.0))
        elif action == StepAction.RAMP_DISP:
            target.setEnabled(True)
            target.setSuffix(" mm")
            if target.value() <= target.minimum():
                target.setValue(record.get("last_target", 5.0))
        else:
            if target.value() > target.minimum():
                record["last_target"] = target.value()
            target.setEnabled(False)
            target.setSuffix("")
            target.setValue(target.minimum())   # 사용하지 않는 목표값은 '-'로 표시
        record["hold"].setEnabled(action == StepAction.HOLD)
        record["hold"].setSuffix(" s" if action == StepAction.HOLD else "")

    def _renumber(self):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None:
                item.setText(str(row + 1))

    # ------------------------------------------------------------------
    def _remove_selected(self):
        row = self.table.currentRow()
        if row < 0 or self.table.rowCount() <= 0:
            return
        self.table.removeRow(row)
        if 0 <= row < len(self._row_widgets):
            self._row_widgets.pop(row)
        self._renumber()
        self._validate()

    def _move_selected(self, delta: int):
        row = self.table.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= self.table.rowCount():
            return
        records = list(self._row_widgets)
        records[row], records[target] = records[target], records[row]
        self._row_widgets = records
        self._rebuild_from_records()
        self.table.setCurrentCell(target, 0)
        self._validate()

    def _rebuild_from_records(self):
        """위젯 순서 배열을 표에 다시 반영 (행 이동/프리셋용)"""
        steps = [
            SequenceStep(
                action=StepAction(rec["action"].currentData()),
                target=rec["target"].value(),
                speed_mm_min=rec["speed"].value(),
                hold_s=rec["hold"].value(),
            )
            for rec in self._row_widgets
        ]
        self.table.setRowCount(0)
        self._row_widgets.clear()
        for step in steps:
            self._add_row(step)

    def _apply_preset(self):
        program = SequenceProgram.standard() if self.combo_preset.currentIndex() == 0 else SequenceProgram.displacement()
        self._load_program(program)

    # ------------------------------------------------------------------
    def collect_program(self) -> SequenceProgram:
        steps: List[SequenceStep] = []
        for rec in self._row_widgets:
            action = StepAction(rec["action"].currentData())
            if action == StepAction.RAMP_LOAD or action == StepAction.RAMP_DISP:
                target = rec["target"].value()
            else:
                target = 0.0
            steps.append(SequenceStep(
                action=action,
                target=target,
                speed_mm_min=rec["speed"].value(),
                hold_s=rec["hold"].value() if action == StepAction.HOLD else 0.0,
            ))
        return SequenceProgram(name=self.edit_name.text().strip() or self.program.name, steps=steps)

    def _validate(self) -> bool:
        program = self.collect_program()
        problems = program.validate()
        if not problems:
            self.lbl_error.setText("")
            self.btn_ok.setEnabled(True)
            return True

        messages = []
        for problem in problems:
            if problem == "empty":
                messages.append(self.t["seq_empty_error"])
                continue
            index, code = problem.split(":", 1)
            step_index = int(index) - 1
            action = program.steps[step_index].action.value if step_index < len(program.steps) else ""
            label = tr(self.lang, f"seq_action_{action}")
            if code == "hold":
                messages.append(f"{index}. {label}: {self.t['seq_invalid_hold']}")
            elif code == "speed":
                messages.append(f"{index}. {label}: {self.t['seq_invalid_target']}")
            else:
                messages.append(f"{index}. {label}: {self.t['seq_invalid_target']}")
        self.lbl_error.setText("   ".join(messages))
        self.btn_ok.setEnabled(False)
        return False

    def _on_accept(self):
        if self._validate():
            self.accept()

    def result_program(self) -> SequenceProgram:
        return self.collect_program()


class HistoryDialog(QDialog):
    """자동 저장된 시험 이력 브라우저 (무결성 검증 + 오버레이 불러오기)"""

    def __init__(self, store: TestHistoryStore, lang: str = "KO",
                 load_callback: Optional[Callable[[str], tuple]] = None, parent=None):
        super().__init__(parent)
        self.store = store
        self.lang = lang
        self.t = TRANSLATIONS.get(lang, TRANSLATIONS["KO"])
        self.load_callback = load_callback
        self._summaries: List[HistorySummary] = []
        self._integrity: dict = {}

        self.setWindowTitle(self.t["history_title"])
        self.setStyleSheet(HYUNDAI_THEME_QSS)
        self.resize(900, 470)
        self.setMinimumSize(780, 420)
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    def _build_ui(self):
        t = self.t
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self.lbl_dir = QLabel(t["history_dir"].format(path=self.store.base_dir))
        self.lbl_dir.setStyleSheet("color: #64748B; font-size: 8.5pt; background: transparent;")
        layout.addWidget(self.lbl_dir)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            t["history_col_time"], t["history_col_specimen"], t["history_col_mode"],
            t["history_col_pmax"], t["history_col_rm"], t["history_col_integrity"],
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 152)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 130)
        self.table.setColumnWidth(3, 118)
        self.table.setColumnWidth(4, 100)
        self.table.setColumnWidth(5, 92)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.doubleClicked.connect(lambda _idx: self._load_selected())
        layout.addWidget(self.table, stretch=1)

        status_row = QHBoxLayout()
        self.lbl_count = QLabel("")
        self.lbl_count.setStyleSheet("color: #1D4ED8; font-weight: 700; font-size: 9pt; background: transparent;")
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #475569; font-size: 8.5pt; background: transparent;")
        status_row.addWidget(self.lbl_count)
        status_row.addSpacing(14)
        status_row.addWidget(self.lbl_status, stretch=1)
        layout.addLayout(status_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_refresh = QPushButton(t["history_refresh"])
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_verify = QPushButton(t["history_verify"])
        self.btn_verify.clicked.connect(self._verify_selected)
        self.btn_chain = QPushButton(t["history_verify_chain"])
        self.btn_chain.clicked.connect(self._verify_chain)
        self.btn_load = QPushButton(t["history_load"])
        self.btn_load.setObjectName("btn_start")
        self.btn_load.setMinimumWidth(150)
        self.btn_load.clicked.connect(self._load_selected)
        self.btn_close = QPushButton(t["history_close"])
        self.btn_close.clicked.connect(self.accept)

        btn_row.addWidget(self.btn_refresh)
        btn_row.addWidget(self.btn_verify)
        btn_row.addWidget(self.btn_chain)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_load)
        btn_row.addWidget(self.btn_close)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    def refresh(self):
        t = self.t
        self._summaries = self.store.list()
        self.table.setRowCount(0)
        self._integrity = {}
        ok_count = 0
        for summary in self._summaries:
            integrity = self.store.verify(summary.record_id)
            self._integrity[summary.record_id] = integrity
            if integrity.ok:
                ok_count += 1
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                summary.created_display,
                summary.specimen_id,
                mode_display(summary.mode, self.lang),
                f"{summary.peak_load_n:,.1f}",
                f"{summary.peak_stress_mpa:.2f}",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                    if col in (1, 2) else Qt.AlignmentFlag.AlignCenter
                )
                item.setData(Qt.ItemDataRole.UserRole, summary.record_id)
                self.table.setItem(row, col, item)

            state_item = QTableWidgetItem(
                t["history_integrity_ok"] if integrity.ok
                else f"{t['history_integrity_bad']}"
            )
            state_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            state_item.setForeground(
                Qt.GlobalColor.darkGreen if integrity.ok else Qt.GlobalColor.darkRed
            )
            self.table.setItem(row, 5, state_item)

        self.lbl_count.setText(t["history_count"].format(n=len(self._summaries), ok=ok_count))
        if not self._summaries:
            self.lbl_status.setText(t["history_empty"])
        else:
            self.lbl_status.setText("")
        self.btn_load.setEnabled(bool(self._summaries))
        self.btn_verify.setEnabled(bool(self._summaries))
        self.btn_chain.setEnabled(bool(self._summaries))

    def selected_record_id(self) -> Optional[str]:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _verify_selected(self):
        record_id = self.selected_record_id()
        if record_id is None:
            return
        integrity = self.store.verify(record_id)
        self._integrity[record_id] = integrity
        row = self.table.currentRow()
        item = self.table.item(row, 5)
        if item is not None:
            item.setText(self.t["history_integrity_ok"] if integrity.ok
                         else self.t["history_integrity_bad"])
            item.setForeground(Qt.GlobalColor.darkGreen if integrity.ok else Qt.GlobalColor.darkRed)
        self.lbl_status.setText(
            f"{record_id} · {integrity.note}" if not integrity.ok else f"{record_id} · {self.t['history_integrity_ok']}"
        )

    def _verify_chain(self):
        result = self.store.verify_chain()
        if result.ok:
            self.lbl_status.setText(self.t["history_chain_ok"].format(n=result.total))
        else:
            self.lbl_status.setText(
                self.t["history_chain_bad"].format(n=len(result.problems)) + " — " + "; ".join(result.problems[:3])
            )

    def _load_selected(self):
        record_id = self.selected_record_id()
        if record_id is None or self.load_callback is None:
            return
        ok, message = self.load_callback(record_id)
        self.lbl_status.setText(message)
        if ok:
            self.accept()


class PostTestSaveDialog(QDialog):
    """시험 완료 후 요약 확인 및 저장 폴더 · 분류 방식 선택 창"""

    def __init__(
        self,
        summary_lines: List[str],
        specimen: Specimen,
        config: TestConfig,
        base_dir: str,
        folder_rule: str = "date",
        lang: str = "KO",
        parent=None,
    ):
        super().__init__(parent)
        self.lang = lang
        self.t = TRANSLATIONS.get(lang, TRANSLATIONS["KO"])
        self.specimen = specimen
        self.config = config

        self.selected_base_dir: str = base_dir
        self.selected_rule: str = folder_rule
        self.want_excel: bool = True
        self.want_pdf: bool = True

        self.setWindowTitle(self.t["post_title"])
        self.resize(620, 420)
        self.setStyleSheet(HYUNDAI_THEME_QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # 1) 시험 완료 요약
        sum_group = QGroupBox(self.t["post_summary_group"])
        sum_layout = QVBoxLayout(sum_group)
        lbl_summary = QLabel("\n".join(summary_lines))
        lbl_summary.setWordWrap(True)
        lbl_summary.setStyleSheet("color: #0F172A; font-size: 9.5pt; line-height: 1.4; background: transparent;")
        sum_layout.addWidget(lbl_summary)
        root.addWidget(sum_group)

        # 2) 저장 폴더 및 형식 선택
        save_group = QGroupBox(self.t["post_save_group"])
        grid = QGridLayout(save_group)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        grid.addWidget(QLabel(self.t["post_target_dir"]), 0, 0)
        self.edit_dir = QLineEdit(base_dir)
        self.edit_dir.textChanged.connect(self._update_preview)
        grid.addWidget(self.edit_dir, 0, 1)

        btn_browse = QPushButton(self.t["post_browse"])
        btn_browse.setMinimumWidth(110)
        btn_browse.clicked.connect(self._browse_dir)
        grid.addWidget(btn_browse, 0, 2)

        grid.addWidget(QLabel(self.t["post_rule"]), 1, 0)
        self.combo_rule = QComboBox()
        for rule in FOLDER_RULES:
            self.combo_rule.addItem(self.t[f"save_rule_{rule}"], rule)
        idx = self.combo_rule.findData(folder_rule)
        if idx >= 0:
            self.combo_rule.setCurrentIndex(idx)
        self.combo_rule.currentIndexChanged.connect(self._update_preview)
        grid.addWidget(self.combo_rule, 1, 1, 1, 2)

        grid.addWidget(QLabel(self.t["post_final_path"]), 2, 0)
        self.lbl_preview = QLabel("")
        self.lbl_preview.setWordWrap(True)
        self.lbl_preview.setStyleSheet("color: #1D4ED8; font-weight: 600; font-size: 9pt; background: transparent;")
        grid.addWidget(self.lbl_preview, 2, 1, 1, 2)

        chk_row = QHBoxLayout()
        chk_row.setSpacing(16)
        self.chk_excel = QCheckBox(self.t["post_save_excel"])
        self.chk_excel.setChecked(True)
        self.chk_pdf = QCheckBox(self.t["post_save_pdf"])
        self.chk_pdf.setChecked(True)
        chk_row.addWidget(self.chk_excel)
        chk_row.addWidget(self.chk_pdf)
        chk_row.addStretch()
        grid.addLayout(chk_row, 3, 1, 1, 2)

        root.addWidget(save_group)

        # 3) 하단 버튼
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_skip = QPushButton(self.t["post_btn_skip"])
        btn_skip.setMinimumHeight(34)
        btn_skip.clicked.connect(self.reject)

        btn_save = QPushButton(self.t["post_btn_save"])
        btn_save.setMinimumHeight(34)
        btn_save.setMinimumWidth(160)
        btn_save.setStyleSheet("background-color: #1D4ED8; color: #FFFFFF; font-weight: bold;")
        btn_save.setDefault(True)
        btn_save.clicked.connect(self._on_save)

        btn_row.addWidget(btn_skip)
        btn_row.addWidget(btn_save)
        root.addLayout(btn_row)

        self._update_preview()

    def _browse_dir(self):
        current = self.edit_dir.text().strip() or self.selected_base_dir
        chosen = QFileDialog.getExistingDirectory(self, self.t["post_browse"], current)
        if chosen:
            self.edit_dir.setText(chosen)

    def _update_preview(self):
        base = self.edit_dir.text().strip() or self.selected_base_dir
        rule = self.combo_rule.currentData() or "date"
        resolved = resolve_report_dir(base, self.config, self.specimen, folder_rule=rule, lang=self.lang)
        self.lbl_preview.setText(resolved)

    def _on_save(self):
        if not self.chk_excel.isChecked() and not self.chk_pdf.isChecked():
            QMessageBox.warning(self, self.t["post_title"], self.t["post_need_one"])
            return
        self.selected_base_dir = self.edit_dir.text().strip() or self.selected_base_dir
        self.selected_rule = self.combo_rule.currentData() or "date"
        self.want_excel = self.chk_excel.isChecked()
        self.want_pdf = self.chk_pdf.isChecked()
        self.accept()
