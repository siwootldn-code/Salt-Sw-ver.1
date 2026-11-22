"""
Salt Sw ver.1 - RS-232 Serial UTM Hardware Driver
봉신(Bongshin) 로드셀 및 P2020, P2014 디지털 인디케이터 전용 시리얼 통신 드라이버
Baudrate: 115,200 bps (기본값)
"""

import time
import re
import threading
from typing import Callable, Optional, List, Dict, Any

try:
    import serial
    import serial.tools.list_ports
    HAS_PYSERIAL = True
except ImportError:
    serial = None
    HAS_PYSERIAL = False

from .hardware_interface import HardwareInterface
from .models import DataPoint, ExtensometerSettings, TestConfig, Specimen, TestMode
from .calibration import CalibrationManager
from .pid_controller import (
    ControlMode, PIDProfileManager, SoftPIDController, TrackingSample, build_controller
)
from .sequence import (
    SequenceCommand, SequenceController, SequenceProgram, StepAction,
    format_sequence_command
)


class SerialUTMDriver(HardwareInterface):
    """
    RS-232 시리얼 기반 만능재료시험기 드라이버
    - 봉신(Bongshin) 로드셀 및 P2020, P2014 인디케이터 115,200 bps 지원
    - 백그라운드 고속 데이터 수신 스레드
    - 하중(Load, N/kN/kgf) 및 변위(Displacement, mm) 실시간 파싱
    - 신율계(Extensometer) 선택 채널 파싱 (mV 아날로그 / 엔코더 펄스), 채널이 없으면 크로스헤드 변위로 자동 대체
    - 영점(Tare/Zero) 보정 및 스케일 변환
    - 원시 패킷(Raw Packet) 실시간 모니터링 지원
    """

    def __init__(self):
        super().__init__()
        self.ser: Optional[Any] = None
        self._read_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # 콜백 함수
        self.on_raw_data_received: Optional[Callable[[str], None]] = None
        
        # 시험 제원 및 상태
        self.specimen: Optional[Specimen] = None
        self.config: Optional[TestConfig] = None
        self.start_time: float = 0.0
        
        # 보정 계수 및 영점 (Zero/Tare)
        self.calib_mgr = CalibrationManager()
        self.load_tare: float = 0.0
        self.disp_tare: float = 0.0
        self.last_raw_load: float = 0.0
        self.last_raw_disp: float = 0.0
        
        # 단위 스케일 팩터 (기본: N 단위로 변환)
        # N: 1.0, kN: 1000.0, kgf: 9.80665
        self.load_unit_multiplier: float = 1.0  
        self.disp_unit_multiplier: float = 1.0  # 기본: mm

        # 신율계(Extensometer) 채널 상태 (환경 설정 값 반영)
        self.ext: ExtensometerSettings = ExtensometerSettings()
        self.ext_unit_multiplier: float = 1.0   # 기본: mm
        self.last_raw_ext: float = 0.0
        self.ext_signal_lost: bool = False      # 신율계 사용 설정인데 채널 신호가 없음
        self.disp_channel_present: bool = True  # 패킷에 변위 필드가 있는지 (강성 추정에 필요)

        # 다단계 시퀀스 상태 (RS-232 소프트웨어 오케스트레이션)
        self.sequence_ctl: Optional[SequenceController] = None
        self.sequence_commands: List[str] = []   # 실제 전송한 명령 기록
        self._seq_peak_load: float = 0.0
        self._seq_fractured: bool = False

        # 소프트 PID 하중·응력 속도 제어 상태
        # supports_live_speed_control: 시험 중 SPD 명령을 받는지 여부.
        # 봉신 P2020 / P2014 매뉴얼로 확인되기 전까지는 미지원(False)으로 두고,
        # 초기 강성으로 환산한 고정 속도를 한 번만 넣는 방식으로 운전한다.
        self.supports_live_speed_control: bool = False
        self.pid_manager = PIDProfileManager()
        self.controller: Optional[SoftPIDController] = None
        self.control_trace: List[TrackingSample] = []
        self._ctrl_last_t: float = 0.0
        self._last_sent_speed: float = 0.0
        self._fixed_speed_sent: bool = False

    # ------------------------------------------------------------------
    def set_sequence(self, program: Optional[SequenceProgram]):
        """시퀀스 프로그램 지정 (시험 시작 전)"""
        self._pending_sequence = program

    def current_sequence_status(self) -> str:
        """현재 시퀀스 진행 상태 문자열"""
        if self.sequence_ctl is None:
            return ""
        return self.sequence_ctl.progress_text("KO")

    def set_extensometer(self, settings: Optional[ExtensometerSettings]):
        """환경 설정의 신율계 구성 적용"""
        self.ext = settings.copy() if settings else ExtensometerSettings()
        self.ext_signal_lost = False

    def tare_extensometer(self):
        """현재 신율계 원시값을 영점으로 설정 (mV 오프셋 / 펄스 카운트 기준점)"""
        if self.ext.is_mv:
            self.ext.zero_offset_mv = round(self.last_raw_ext, 5)
            print(f"[SerialUTMDriver] 신율계 영점 설정 (mV): {self.ext.zero_offset_mv}")
        else:
            self.ext.zero_offset_pulse = round(self.last_raw_ext)
            print(f"[SerialUTMDriver] 신율계 영점 설정 (pulse): {self.ext.zero_offset_pulse}")

    @staticmethod
    def list_available_ports() -> List[str]:
        """PC에 연결된 시리얼(COM) 포트 목록 조회"""
        if not HAS_PYSERIAL:
            return ["COM1", "COM2", "COM3", "COM4"]
        try:
            ports = serial.tools.list_ports.comports()
            port_list = [p.device for p in ports]
            return port_list if port_list else ["COM1", "COM2", "COM3"]
        except Exception:
            return ["COM1", "COM2", "COM3"]

    def connect(self, port: str = "COM1", baudrate: int = 115200, timeout: float = 0.5) -> bool:
        """
        RS-232 시리얼 포트 연결 (기본 115,200 bps, 8-N-1)
        """
        if not HAS_PYSERIAL:
            print("[SerialUTMDriver] pyserial 라이브러리가 필요합니다: pip install pyserial")
            return False

        try:
            if self.ser and self.ser.is_open:
                self.ser.close()

            self.ser = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=timeout
            )
            self.is_connected = self.ser.is_open
            print(f"[SerialUTMDriver] {port} 포트 연결 성공 (Baudrate: {baudrate})")
            
            # 연결 즉시 원시 데이터 모니터링을 위해 수신 루프 가동
            self._stop_event.clear()
            self._read_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._read_thread.start()
            
            return self.is_connected
        except Exception as e:
            print(f"[SerialUTMDriver] 포트 {port} 연결 실패: {e}")
            self.is_connected = False
            return False

    def disconnect(self):
        """연결 해제"""
        self.is_running = False
        self._stop_event.set()
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
        self.is_connected = False
        self.ser = None
        print("[SerialUTMDriver] 시리얼 포트 연결 해제됨")

    def start_test(self, specimen: Specimen, config: TestConfig):
        """실제 시험 시작 및 계측 데이터 수집 활성화"""
        self.specimen = specimen
        self.config = config
        self.is_running = True
        self.start_time = time.time()
        self.step_events = []
        self.sequence_name = ""
        self._seq_peak_load = 0.0
        self._seq_fractured = False
        self.sequence_commands = []

        # 환경 설정의 신율계 구성 적용 (사용 안 함이면 채널 무시)
        if config.ext is not None:
            self.set_extensometer(config.ext)

        # 다단계 시퀀스 준비 (소프트웨어 오케스트레이션)
        self.sequence_ctl = None
        if config.mode == TestMode.SEQUENCE:
            self.sequence_ctl = SequenceController(config.sequence)
            self.sequence_name = config.sequence.name

        # 소프트 PID 하중·응력 속도 제어 준비
        self.controller = None
        self.control_trace = []
        self._ctrl_last_t = 0.0
        self._last_sent_speed = 0.0
        self._fixed_speed_sent = False
        if getattr(config, "uses_pid_control", False):
            self.controller = build_controller(config, specimen, self.pid_manager)
            if self.controller is not None:
                # 기준 속도를 초기 강성으로 환산해 두고, 첫 패킷에서 바로 사용한다
                ff = self.controller.feedforward_speed_mm_min
                if ff > 0 and self.supports_live_speed_control and config.live_speed_control:
                    self.set_speed(ff)
                    self.send_command(format_sequence_command(SequenceCommand.RUN))

        # 시작 시 현재 값을 영점으로 자동 보정
        self.tare_load()
        self.tare_displacement()

    def stop_test(self):
        """시험 중지 (비상 정지)"""
        self.is_running = False
        if self.sequence_ctl is not None:
            for line in self._seq_apply(self.sequence_ctl.abort(self._now(), self.last_raw_load,
                                                                self.last_raw_disp, "중단")):
                self.send_command(line)
            self.step_events = self.sequence_ctl.events_as_dicts()
            self.sequence_ctl = None
        if self.on_test_completed:
            self.on_test_completed("사용자 중지 또는 시험 완료")

    def return_to_origin(self):
        """원점 복귀 (하드웨어 제어 지원 시 명령 송신)"""
        self.send_command("ORIGIN\r\n")

    # ------------------------------------------------------------------
    def set_speed(self, speed_mm_min: float):
        """
        시험 중 속도 변경 (지원 여부와 관계없이 명령은 보내고 기록한다).
        하중 제어에서는 1 mm/min 미만의 느린 속도를 쓰므로 소수 4자리까지 보낸다.
        """
        speed = float(speed_mm_min)
        self._last_sent_speed = speed
        text = f"SPD {speed:.4f}" if abs(speed) < 1.0 else f"SPD {speed:.2f}"
        self.send_command(text + "\r\n")

    def current_control_status(self, lang: str = "KO") -> str:
        """소프트 PID 제어 상태 표시 문자열"""
        if self.controller is None:
            return ""
        return self.controller.status_text(lang)

    def tare_load(self):
        """현재 하중을 0으로 세팅 (Zero/Tare)"""
        self.calib_mgr.data.load_zero_offset = self.last_raw_load
        self.calib_mgr.save()
        self.load_tare = 0.0
        print(f"[SerialUTMDriver] 하중 영점 세팅 완료: Zero Offset = {self.calib_mgr.data.load_zero_offset}")

    def tare_displacement(self):
        """현재 변위를 0으로 세팅"""
        self.calib_mgr.data.disp_zero_offset = self.last_raw_disp
        self.calib_mgr.save()
        self.disp_tare = 0.0
        print(f"[SerialUTMDriver] 변위 영점 세팅 완료: Zero Offset = {self.calib_mgr.data.disp_zero_offset}")

    def calibrate_load_span(self, ref_load_val: float, unit: str = "kgf") -> float:
        """
        기준 하중(분동/기준기) 인가 상태에서 스팬 교정 계수(Span Factor) 산출 및 영구 저장
        """
        if unit == "kgf":
            ref_n = ref_load_val * 9.80665
        elif unit == "kN":
            ref_n = ref_load_val * 1000.0
        else:
            ref_n = ref_load_val

        # 현재 수신 중인 순수 센서 하중 (오프셋 뺀 값)
        current_raw_delta = (self.last_raw_load - self.calib_mgr.data.load_zero_offset) * self.load_unit_multiplier
        if abs(current_raw_delta) > 0.001:
            factor = ref_n / current_raw_delta
            self.calib_mgr.data.load_scale_factor = round(factor, 6)
            from datetime import datetime
            self.calib_mgr.data.last_load_calib_date = datetime.now().strftime("%Y-%m-%d %H:%M")
            self.calib_mgr.save()
            return self.calib_mgr.data.load_scale_factor
        return 1.0

    def calibrate_speed(self, target_speed_mm_min: float, measured_dist_mm: float, duration_sec: float = 60.0) -> float:
        """
        목표 속도로 duration_sec 동안 구동 후 실측 이동 거리 기반 속도 보정 계수 산출 및 영구 저장
        """
        actual_speed = (measured_dist_mm / duration_sec) * 60.0
        if actual_speed > 0.001:
            factor = target_speed_mm_min / actual_speed
            self.calib_mgr.data.speed_scale_factor = round(factor, 6)
            from datetime import datetime
            self.calib_mgr.data.last_speed_calib_date = datetime.now().strftime("%Y-%m-%d %H:%M")
            self.calib_mgr.save()
            return self.calib_mgr.data.speed_scale_factor
        return 1.0

    def send_command(self, cmd: str):
        """시리얼 명령 전송"""
        if self.ser and self.ser.is_open:
            try:
                self.ser.write(cmd.encode("ascii"))
            except Exception as e:
                print(f"[SerialUTMDriver] 명령 전송 오류: {e}")

    def _worker_loop(self):
        """시리얼 데이터 지속 수신 루프 (고속 스트리밍 대응)"""
        while not self._stop_event.is_set() and self.ser and self.ser.is_open:
            try:
                line = self.ser.readline().decode("ascii", errors="ignore").strip()
                if not line:
                    continue

                # 원시 패킷 수신 콜백 전달 (UI 모니터링용)
                if self.on_raw_data_received:
                    self.on_raw_data_received(line)

                # 패킷 파싱
                dp = self._parse_packet(line)
                if dp and self.is_running and self.on_data_received:
                    self.on_data_received(dp)
                    finished = self._sequence_tick(dp) or self._control_tick(dp)
                    if finished:
                        self.is_running = False
                        self.sequence_ctl = None
                        if self.on_test_completed:
                            self.on_test_completed(finished)

            except Exception as e:
                time.sleep(0.005)

    def _parse_packet(self, line: str) -> Optional[DataPoint]:
        """
        봉신 및 P2020, P2014 인디케이터 데이터 패킷 파싱
        지원 형식:
        1. CSV 형식: "+0012.35, +0001.20" (하중, 변위)
        2. 공백 구분자: "+0012.35  +0001.20"
        3. 봉신 인디케이터 표준 헤더 포맷: "ST,GS,+0012.35kg, +0001.20mm"
        4. 단일 하중 스트림: "ST,GS,+0012.35kg"
        5. 신율계 채널 포함 (선택 항목):
           - mV 타입: "ST,GS,+0012.35kg, +0001.20mm, +3.421mV" 또는 세 번째 순수 숫자 필드
           - 펄스 타입: "ST,GS,+0012.35kg, +0001.20mm, #12450" 또는 세 번째 순수 숫자 필드
        신율계 미사용 시에는 세 번째 필드가 있어도 무시되며, 사용 설정인데 채널이 없으면
        크로스헤드 변위로 자동 대체하고 ext_signal_lost 플래그를 세운다.
        """
        try:
            current_time = time.time() - self.start_time if self.start_time > 0 else 0.0
            
            # STX(0x02), ETX(0x03) 제거
            cleaned = line.replace("\x02", "").replace("\x03", "")
            
            # 부호 포함 부동소수점 숫자 추출
            numbers = re.findall(r"[-+]?\d*\.?\d+", cleaned)
            if not numbers:
                return None

            raw_load = float(numbers[0])
            self.disp_channel_present = len(numbers) >= 2
            raw_disp = float(numbers[1]) if self.disp_channel_present else (
                current_time * (self.config.test_speed_mm_min / 60.0) if self.config else 0.0)

            self.last_raw_load = raw_load
            self.last_raw_disp = raw_disp

            # 영점(Tare) 및 캘리브레이션 보정 적용 (최종 단위: N 및 mm)
            corrected_raw_load = self.calib_mgr.apply_load(raw_load)
            load_n = (corrected_raw_load - self.load_tare) * self.load_unit_multiplier

            corrected_raw_disp = self.calib_mgr.apply_disp(raw_disp)
            disp_mm = (corrected_raw_disp - self.disp_tare) * self.disp_unit_multiplier

            # 하중이 kN 단위로 들어오는 경우 자동 판정
            # 봉신 인디케이터 기본 설정에 맞춤
            area = self.specimen.cross_sectional_area_mm2 if self.specimen else 1.0
            gauge = self.specimen.gauge_length_mm if self.specimen else 50.0

            # 신율계 채널 (선택)
            ext_raw = self._extract_ext_raw(cleaned, numbers)
            ext_valid = False
            ext_disp_mm = 0.0
            ext_strain_pct = 0.0
            if self.ext.enabled:
                if ext_raw is None:
                    self.ext_signal_lost = True
                else:
                    self.ext_signal_lost = False
                    self.last_raw_ext = ext_raw
                    ext_disp_mm = self.ext.to_displacement(ext_raw) * self.ext_unit_multiplier
                    ext_strain_pct = self.ext.to_strain_pct(ext_disp_mm)
                    ext_valid = True
            elif ext_raw is not None:
                # 미사용 설정이어도 원시값은 모니터링용으로 유지
                self.last_raw_ext = ext_raw

            # 응력: MPa = N / mm^2
            stress_mpa = load_n / area if area > 0 else 0.0

            # 변형률: 신율계 신호가 있으면 신율계 표점거리 기준, 없으면 크로스헤드 변위 기준
            if ext_valid:
                strain_pct = ext_strain_pct
            else:
                strain_pct = (disp_mm / gauge) * 100.0 if gauge > 0 else 0.0

            return DataPoint(
                time_s=round(current_time, 3),
                displacement_mm=round(disp_mm, 4),
                load_n=round(load_n, 2),
                stress_mpa=round(stress_mpa, 2),
                strain_pct=round(strain_pct, 3),
                ext_disp_mm=round(ext_disp_mm, 4),
                ext_strain_pct=round(ext_strain_pct, 3),
                ext_raw=round(ext_raw, 4) if ext_raw is not None else 0.0,
                ext_valid=ext_valid,
            )
        except Exception:
            pass
        return None

    def _extract_ext_raw(self, cleaned: str, numbers: List[str]) -> Optional[float]:
        """
        패킷에서 신율계 원시 신호를 추출한다.
        1) mV 단위 표기 토큰: "+3.421mV"
        2) 펄스 수 표기 토큰: "#12450", "12450pls", "12450 pulse", "12450 counts"
        3) 위 표기가 없고 숫자 필드가 3개 이상이면 세 번째 필드를 선택된 타입으로 해석
        """
        m = re.search(r"([-+]?\d*\.?\d+)\s*m\s*[vV]\b", cleaned)
        if m:
            return float(m.group(1))

        m = re.search(r"([-+]?\d+)\s*(?:pls|plse|pulse|pulses|cnt|counts?)\b", cleaned, re.IGNORECASE)
        if m:
            return float(m.group(1))

        m = re.search(r"#\s*([-+]?\d+)", cleaned)
        if m:
            return float(m.group(1))

        if len(numbers) >= 3:
            return float(numbers[2])
        return None

    # ------------------------------------------------------------------
    # 다단계 시퀀스 · 소프트 PID 제어 진행 처리
    # ------------------------------------------------------------------
    def _now(self) -> float:
        """시험 시작 기준 경과 시간 (초)"""
        return time.time() - self.start_time if self.start_time > 0 else 0.0

    def _seq_apply(self, transitions) -> List[str]:
        """단계 전환을 실제 명령 문자열로 바꾸고 전송 기록에 남긴다"""
        lines: List[str] = []
        for transition in transitions or []:
            for line in transition.command_lines():
                lines.append(line)
                self.sequence_commands.append(line.strip())
        return lines

    def _sequence_tick(self, dp: DataPoint) -> Optional[str]:
        """
        다단계 시퀀스 단계 진행 판정.
        목표(하중/변위/시간) 도달 시 다음 단계 명령을 보내고,
        시퀀스가 끝나면 완료 사유를 돌려준다.
        """
        ctl = self.sequence_ctl
        if ctl is None:
            return None

        # 파단 감지 (피크 대비 하중 하락)
        drop_ratio = self.config.fracture_drop_ratio if self.config else 0.5
        if dp.load_n > self._seq_peak_load:
            self._seq_peak_load = dp.load_n
        elif self._seq_peak_load > 50 and \
                dp.load_n < self._seq_peak_load * (1.0 - drop_ratio):
            self._seq_fractured = True

        if not ctl.is_started:
            for line in self._seq_apply(ctl.start(dp.time_s, dp.load_n, dp.displacement_mm)):
                self.send_command(line)
            return None

        transitions = ctl.update(dp.time_s, dp.load_n, dp.displacement_mm,
                                 fractured=self._seq_fractured)
        for line in self._seq_apply(transitions):
            self.send_command(line)

        if ctl.is_finished:
            self.step_events = ctl.events_as_dicts()
            return "시퀀스 완료 · 파단 감지" if self._seq_fractured else "시퀀스 완료 · 정상 종료"
        return None

    def _control_tick(self, dp: DataPoint) -> Optional[str]:
        """
        소프트 PID 제어 1주기.
        실시간 속도 변경이 가능하면 매 주기 SPD 를 갱신하고,
        미지원이면 초기 강성으로 환산한 고정 속도를 한 번만 보낸다.
        """
        ctrl = self.controller
        if ctrl is None:
            return None

        period = 1.0 / max(1.0, ctrl.control_rate_hz)
        if self._ctrl_last_t > 0 and dp.time_s - self._ctrl_last_t < period:
            return None
        dt = dp.time_s - self._ctrl_last_t if self._ctrl_last_t > 0 else period
        self._ctrl_last_t = dp.time_s

        speed = ctrl.update(dt, dp.load_n, dp.displacement_mm,
                            disp_valid=self.disp_channel_present)
        live = self.supports_live_speed_control and ctrl.live_speed_control
        if live:
            if abs(speed - self._last_sent_speed) >= 0.001:
                self.set_speed(speed)
        elif not self._fixed_speed_sent:
            ff = ctrl.feedforward_speed_mm_min
            if ff > 0:
                self.set_speed(ff)
                self.send_command(format_sequence_command(SequenceCommand.RUN))
                self._fixed_speed_sent = True
                print(f"[SerialUTMDriver] 고정 속도 운전: 강성 {ctrl.stiffness_n_per_mm:,.0f} N/mm "
                      f"→ {ff:.4f} mm/min")

        self.control_trace.append(TrackingSample(
            time_s=round(dp.time_s, 3),
            setpoint_n=round(ctrl.setpoint_load_n, 2),
            load_n=round(dp.load_n, 2),
            speed_mm_min=round(self._last_sent_speed, 3),
            stiffness_n_per_mm=round(ctrl.stiffness_n_per_mm, 1),
        ))

        # 하중 유지: 목표 도달 · 유지 시간 종료 · 과하중 안전 정지
        if ctrl.mode is ControlMode.LOAD_HOLD and ctrl.target_load_n > 0:
            if ctrl.is_finished:
                self.send_command(format_sequence_command(SequenceCommand.STOP))
                return "목표 하중 유지 완료"
            if dp.load_n > ctrl.target_load_n * 1.2:
                self.send_command(format_sequence_command(SequenceCommand.STOP))
                return "과하중 안전 정지 (목표 20% 초과)"
            if not live and dp.load_n >= ctrl.target_load_n:
                self.send_command(format_sequence_command(SequenceCommand.STOP))
                return "목표 하중 도달 (고정 속도 · 실시간 보정 없음)"
        return None
