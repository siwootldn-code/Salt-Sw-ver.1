"""
Salt Sw ver.1 - Multi-step Test Sequence Engine (다단계 시험 시퀀스)
한 번의 시험을 여러 단계(가압 → 유지 → 파단 → 복귀)로 나누어 소프트웨어가 순서대로 지휘한다.

정직성 원칙 (실장비 한계 명시)
- 봉신 P2020 / P2014 는 RS-232 텍스트 인터페이스다. 1~5 kHz 폐루프 변형률 속도 제어는
  불가능하므로 이 모듈은 "소프트웨어 오케스트레이션" 방식만 지원한다.
  각 단계의 목표(하중/변위/시간)에 도달하면 다음 단계 명령을 보내는 방식이며,
  판정 주기는 시리얼 패킷 수신 주기(대략 10~20 Hz)다. 그보다 빠른 과도 응답은 제어하지 않는다.
- 인디케이터의 명령어 체계는 제조사 매뉴얼에 따라 다르므로 SEQUENCE_COMMAND_MAP 의 기본값은
  일반적인 ASCII 니모닉이다. 현장 장비에 맞게 조정해야 하며, 전송한 모든 명령은
  패킷 모니터(장비 연결 탭)에 그대로 기록된다.

가상 시뮬레이터는 같은 컨트롤러를 사용해 단계 전환을 물리 모델(하중/변위)에 반영한다.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class StepAction(Enum):
    """시퀀스 단계 동작"""
    RAMP_LOAD = "RAMP_LOAD"              # 목표 하중까지 가압
    RAMP_DISP = "RAMP_DISP"              # 목표 변위까지 이동
    HOLD = "HOLD"                        # 지정 시간 동안 유지
    RAMP_TO_BREAK = "RAMP_TO_BREAK"      # 파단까지 가압
    RETURN = "RETURN"                    # 원점 복귀


class SequenceCommand(Enum):
    """시퀀스 단계 전환 시 하드웨어로 보내는 명령 종류"""
    SET_SPEED = "SET_SPEED"
    RUN = "RUN"
    HOLD = "HOLD"
    STOP = "STOP"
    RETURN = "RETURN"
    COMPLETE = "COMPLETE"


# 인디케이터 명령어 매핑 (기본 ASCII 니모닉 - 현장 장비 매뉴얼에 맞게 변경)
SEQUENCE_COMMAND_MAP: Dict[SequenceCommand, str] = {
    SequenceCommand.SET_SPEED: "SPD {speed:.2f}",
    SequenceCommand.RUN: "RUN",
    SequenceCommand.HOLD: "HLD",
    SequenceCommand.STOP: "STP",
    SequenceCommand.RETURN: "ORG",
    SequenceCommand.COMPLETE: "STP",
}


def format_sequence_command(command: SequenceCommand, speed_mm_min: float = 0.0) -> str:
    """명령 종류를 실제 전송 문자열로 변환 (끝에 CRLF 포함)"""
    template = SEQUENCE_COMMAND_MAP.get(command, "")
    if not template:
        return ""
    text = template.format(speed=speed_mm_min) if "{speed" in template else template
    return text + "\r\n"


@dataclass
class SequenceStep:
    """시퀀스 한 단계 정의"""
    action: StepAction = StepAction.RAMP_DISP
    target: float = 5.0          # RAMP_LOAD: N, RAMP_DISP: mm, HOLD/RAMP_TO_BREAK/RETURN: 미사용
    speed_mm_min: float = 5.0    # 해당 단계 크로스헤드 속도
    hold_s: float = 0.0          # HOLD 전용 유지 시간(초)
    note: str = ""               # 작업자 메모 (선택)

    # ------------------------------------------------------------------
    @property
    def uses_target(self) -> bool:
        return self.action in (StepAction.RAMP_LOAD, StepAction.RAMP_DISP)

    @property
    def target_unit(self) -> str:
        if self.action == StepAction.RAMP_LOAD:
            return "N"
        if self.action == StepAction.RAMP_DISP:
            return "mm"
        if self.action == StepAction.HOLD:
            return "s"
        return ""

    def validate(self) -> List[str]:
        """단계 정의 오류 목록 (빈 목록이면 정상)"""
        problems: List[str] = []
        if self.uses_target and self.target <= 0:
            problems.append("target")
        if self.speed_mm_min <= 0:
            problems.append("speed")
        if self.action == StepAction.HOLD and self.hold_s <= 0:
            problems.append("hold")
        if self.action in (StepAction.HOLD,) and self.speed_mm_min <= 0:
            problems.append("speed")
        return problems

    def describe(self, lang: str = "KO") -> str:
        """단계 요약 문자열 (예: '목표 하중 500 N · 5.0 mm/min')"""
        from .i18n import TRANSLATIONS
        t = TRANSLATIONS.get(lang, TRANSLATIONS["KO"])
        action = t.get(f"seq_action_{self.action.value}", self.action.value)
        if self.action == StepAction.RAMP_LOAD:
            body = t["seq_desc_load"].format(target=self.target, speed=self.speed_mm_min)
        elif self.action == StepAction.RAMP_DISP:
            body = t["seq_desc_disp"].format(target=self.target, speed=self.speed_mm_min)
        elif self.action == StepAction.HOLD:
            body = t["seq_desc_hold"].format(hold=self.hold_s)
        elif self.action == StepAction.RAMP_TO_BREAK:
            body = t["seq_desc_break"].format(speed=self.speed_mm_min)
        else:
            body = t["seq_desc_return"].format(speed=self.speed_mm_min)
        return f"{action} · {body}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "target": round(float(self.target), 4),
            "speed_mm_min": round(float(self.speed_mm_min), 4),
            "hold_s": round(float(self.hold_s), 3),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "SequenceStep":
        if not isinstance(raw, dict):
            return cls()
        try:
            action = StepAction(str(raw.get("action", "RAMP_DISP")).upper())
        except ValueError:
            action = StepAction.RAMP_DISP
        step = cls(
            action=action,
            target=_as_float(raw.get("target"), 5.0),
            speed_mm_min=_as_float(raw.get("speed_mm_min"), 5.0),
            hold_s=_as_float(raw.get("hold_s"), 0.0),
            note=str(raw.get("note", "") or ""),
        )
        return step


@dataclass
class SequenceProgram:
    """다단계 시퀀스 프로그램 (순서가 있는 단계 목록)"""
    name: str = "표준 인장 4단계"
    steps: List[SequenceStep] = field(default_factory=list)

    # ------------------------------------------------------------------
    # 기본 프리셋
    @classmethod
    def standard(cls) -> "SequenceProgram":
        """가압 → 유지 → 파단 → 복귀 (인장 표준 프리셋)"""
        return cls(name="표준 인장 4단계", steps=[
            SequenceStep(StepAction.RAMP_LOAD, target=500.0, speed_mm_min=5.0),
            SequenceStep(StepAction.HOLD, hold_s=10.0),
            SequenceStep(StepAction.RAMP_TO_BREAK, speed_mm_min=5.0),
            SequenceStep(StepAction.RETURN, speed_mm_min=50.0),
        ])

    @classmethod
    def displacement(cls) -> "SequenceProgram":
        """변위 제어 3단계 (예비 하중 → 소성 구간 유지 → 파단)"""
        return cls(name="변위 제어 3단계", steps=[
            SequenceStep(StepAction.RAMP_DISP, target=0.5, speed_mm_min=2.0),
            SequenceStep(StepAction.HOLD, hold_s=5.0),
            SequenceStep(StepAction.RAMP_DISP, target=12.0, speed_mm_min=5.0),
        ])

    def copy(self) -> "SequenceProgram":
        return SequenceProgram(name=self.name, steps=[SequenceStep(**asdict(s)) for s in self.steps])

    # ------------------------------------------------------------------
    def validate(self) -> List[str]:
        """프로그램 오류 목록. 비어 있으면 사용 가능"""
        if not self.steps:
            return ["empty"]
        problems: List[str] = []
        for idx, step in enumerate(self.steps):
            for code in step.validate():
                problems.append(f"{idx + 1}:{code}")
        return problems

    def is_valid(self) -> bool:
        return not self.validate()

    @property
    def uses_target_load(self) -> bool:
        return any(s.action == StepAction.RAMP_LOAD for s in self.steps)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "steps": [s.to_dict() for s in self.steps]}

    @classmethod
    def from_dict(cls, raw: Any) -> "SequenceProgram":
        if not isinstance(raw, dict):
            return cls.standard()
        steps = [SequenceStep.from_dict(s) for s in raw.get("steps", []) if isinstance(s, dict)]
        program = cls(name=str(raw.get("name") or "표준 인장 4단계"), steps=steps)
        return program if program.steps else cls.standard()


# ----------------------------------------------------------------------
# 오케스트레이션 컨트롤러
# ----------------------------------------------------------------------
@dataclass
class StepEvent:
    """한 단계의 시작/종료 기록"""
    index: int
    action: str
    target: float
    speed_mm_min: float
    hold_s: float
    started_at: float
    ended_at: float = 0.0
    start_disp_mm: float = 0.0
    end_disp_mm: float = 0.0
    start_load_n: float = 0.0
    end_load_n: float = 0.0
    outcome: str = ""

    @property
    def duration_s(self) -> float:
        return max(0.0, self.ended_at - self.started_at)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "action": self.action,
            "target": round(self.target, 4),
            "speed_mm_min": round(self.speed_mm_min, 3),
            "hold_s": round(self.hold_s, 3),
            "started_at": round(self.started_at, 3),
            "ended_at": round(self.ended_at, 3),
            "duration_s": round(self.duration_s, 3),
            "start_disp_mm": round(self.start_disp_mm, 4),
            "end_disp_mm": round(self.end_disp_mm, 4),
            "start_load_n": round(self.start_load_n, 2),
            "end_load_n": round(self.end_load_n, 2),
            "outcome": self.outcome,
        }


@dataclass
class SequenceTransition:
    """단계 전환 통지 (드라이버가 명령을 보내고, UI가 상태를 갱신한다)"""
    index: int
    action: StepAction
    speed_mm_min: float
    commands: List[SequenceCommand] = field(default_factory=list)
    event: Optional[StepEvent] = None       # 종료된 단계 기록 (있을 때만)
    finished: bool = False

    def command_lines(self) -> List[str]:
        """전송할 실제 ASCII 명령 문자열 목록"""
        lines = []
        for cmd in self.commands:
            line = format_sequence_command(cmd, self.speed_mm_min)
            if line:
                lines.append(line)
        return lines


class SequenceController:
    """
    시퀀스 단계 진행 판정기.
    드라이버(가상/실장비)가 매 샘플마다 update()를 호출하면,
    목표에 도달한 단계를 닫고 다음 단계 전환을 돌려준다.
    """

    MAX_TRANSITIONS_PER_CALL = 32
    RETURN_TOLERANCE_MM = 0.05

    def __init__(self, program: SequenceProgram):
        self.program = program if program and program.steps else SequenceProgram.standard()
        self.events: List[StepEvent] = []
        self._index = -1
        self._started = False
        self._finished = False
        self._current: Optional[StepEvent] = None
        self._hold_relax_base = 0.0

    # ------------------------------------------------------------------
    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def is_finished(self) -> bool:
        return self._finished

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def current_step(self) -> Optional[SequenceStep]:
        if 0 <= self._index < len(self.program.steps):
            return self.program.steps[self._index]
        return None

    @property
    def step_count(self) -> int:
        return len(self.program.steps)

    @property
    def speed_mm_min(self) -> float:
        """현재 단계에서 실제로 움직이는 속도 (유지는 0)"""
        step = self.current_step
        if step is None or self._finished or step.action == StepAction.HOLD:
            return 0.0
        return float(step.speed_mm_min)

    @property
    def direction(self) -> int:
        """+1 가압, -1 복귀, 0 유지"""
        step = self.current_step
        if step is None or self._finished:
            return 0
        if step.action == StepAction.HOLD:
            return 0
        if step.action == StepAction.RETURN:
            return -1
        return 1

    # ------------------------------------------------------------------
    def start(self, now: float, load_n: float, disp_mm: float) -> List[SequenceTransition]:
        """첫 단계 시작"""
        self._started = True
        out: List[SequenceTransition] = []
        self._begin_step(0, now, load_n, disp_mm, out)
        return out

    def update(self, now: float, load_n: float, disp_mm: float,
               fractured: bool = False) -> List[SequenceTransition]:
        """현재 단계 완료 여부 판정 후 필요하면 다음 단계로 전환"""
        if not self._started:
            return self.start(now, load_n, disp_mm)
        out: List[SequenceTransition] = []
        for _ in range(self.MAX_TRANSITIONS_PER_CALL):
            if self._finished or self._current is None:
                break
            outcome = self._step_outcome(now, load_n, disp_mm, fractured)
            if not outcome:
                break
            self._close_step(now, load_n, disp_mm, outcome, out)
            if self._finished:
                break
            self._begin_step(self._index + 1, now, load_n, disp_mm, out)
        return out

    def abort(self, now: float, load_n: float, disp_mm: float, outcome: str = "중단",
              reason: str = "") -> List[SequenceTransition]:
        """시험 중지/안전 한계 도달 등으로 시퀀스를 종료"""
        out: List[SequenceTransition] = []
        if self._finished:
            return out
        if self._current is not None:
            self._close_step(now, load_n, disp_mm, outcome, out, finish=False)
        self._finished = True
        out.append(SequenceTransition(
            index=max(0, self._index), action=self.program.steps[self._index].action
            if 0 <= self._index < len(self.program.steps) else StepAction.HOLD,
            speed_mm_min=0.0, commands=[SequenceCommand.STOP], finished=True,
        ))
        return out

    # ------------------------------------------------------------------
    def _begin_step(self, index: int, now: float, load_n: float, disp_mm: float,
                    out: List[SequenceTransition]) -> None:
        if index >= len(self.program.steps):
            self._finished = True
            out.append(SequenceTransition(
                index=index, action=StepAction.RETURN, speed_mm_min=0.0,
                commands=[SequenceCommand.COMPLETE], finished=True,
            ))
            return

        step = self.program.steps[index]
        self._index = index
        self._current = StepEvent(
            index=index,
            action=step.action.value,
            target=step.target,
            speed_mm_min=step.speed_mm_min,
            hold_s=step.hold_s,
            started_at=now,
            start_disp_mm=disp_mm,
            start_load_n=load_n,
        )
        self.events.append(self._current)
        self._hold_relax_base = max(load_n, 1.0)

        commands: List[SequenceCommand] = []
        if step.action == StepAction.HOLD:
            commands = [SequenceCommand.HOLD]
        elif step.action == StepAction.RETURN:
            commands = [SequenceCommand.SET_SPEED, SequenceCommand.RETURN]
        else:
            commands = [SequenceCommand.SET_SPEED, SequenceCommand.RUN]
        out.append(SequenceTransition(
            index=index, action=step.action,
            speed_mm_min=0.0 if step.action == StepAction.HOLD else step.speed_mm_min,
            commands=commands, finished=False,
        ))

    def _close_step(self, now: float, load_n: float, disp_mm: float, outcome: str,
                    out: List[SequenceTransition], finish: bool = True) -> None:
        ev = self._current
        if ev is not None:
            ev.ended_at = now
            ev.end_disp_mm = disp_mm
            ev.end_load_n = load_n
            ev.outcome = outcome
            out.append(SequenceTransition(
                index=ev.index,
                action=self.program.steps[ev.index].action
                if 0 <= ev.index < len(self.program.steps) else StepAction.HOLD,
                speed_mm_min=0.0,
                commands=[SequenceCommand.STOP],
                event=ev,
                finished=not finish,
            ))
        self._current = None

    def _step_outcome(self, now: float, load_n: float, disp_mm: float,
                      fractured: bool) -> Optional[str]:
        step = self.current_step
        if step is None:
            return None
        elapsed = now - (self._current.started_at if self._current else now)

        if step.action == StepAction.RAMP_LOAD:
            if load_n >= step.target:
                return "목표 하중 도달"
        elif step.action == StepAction.RAMP_DISP:
            if disp_mm >= step.target:
                return "목표 변위 도달"
        elif step.action == StepAction.HOLD:
            if elapsed >= max(0.0, step.hold_s):
                return "유지 시간 완료"
        elif step.action == StepAction.RAMP_TO_BREAK:
            if fractured:
                return "파단 감지"
        elif step.action == StepAction.RETURN:
            if disp_mm <= self.RETURN_TOLERANCE_MM:
                return "원점 복귀 완료"
        return None

    # ------------------------------------------------------------------
    def progress_text(self, lang: str = "KO") -> str:
        """현재 단계 표시용 문자열"""
        from .i18n import TRANSLATIONS
        t = TRANSLATIONS.get(lang, TRANSLATIONS["KO"])
        if self._finished:
            return t["seq_finished"]
        step = self.current_step
        if step is None:
            return "-"
        return t["seq_progress"].format(no=self._index + 1, total=self.step_count,
                                        action=t.get(f"seq_action_{step.action.value}", step.action.value))

    def events_as_dicts(self) -> List[Dict[str, Any]]:
        return [ev.to_dict() for ev in self.events]


def _as_float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result != result or result in (float("inf"), float("-inf")):
        return default
    return result
