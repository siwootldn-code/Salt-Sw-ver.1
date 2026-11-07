"""
Salt Sw ver.1 - Internationalization (i18n) Module
한국어(국내 현장 작업자 최적화 쉬운 용어) 및 영문(해외/수출용 ASTM 표준 용어) 언어 팩
"""

TRANSLATIONS = {
    "KO": {
        # App Title & Tabs
        "app_title": "SALT SW VER.1 — 만능재료시험기 제어 시스템",
        "tab_dashboard": "시험 및 실시간 모니터링",
        "tab_hardware": "장비 연결 및 정밀 교정",
        "brand_sub": "만능재료시험기 통합 제어 프로그램",
        
        # Test Modes
        "mode_title": "시험 종류 선택",
        "mode_tensile": "인장 시험",
        "mode_compression": "압축 시험",
        "mode_bending": "굽힘 시험",
        "mode_holding": "유지 시험",
        
        # Specimen
        "spec_title": "시편 정보 입력",
        "spec_id": "시편 번호:",
        "spec_mat": "재질:",
        "spec_type": "시편 형태:",
        "spec_type_flat": "판재 (납작한 시편)",
        "spec_type_round": "봉재 (둥근 환봉)",
        "spec_width": "폭 (mm):",
        "spec_dia": "직경 (mm):",
        "spec_thick": "두께 (mm):",
        "spec_l0": "표점거리 (mm):",
        
        # Conditions
        "cond_title": "시험 조건 설정",
        "cond_speed": "시험 속도 (mm/min):",
        "cond_drop": "파단 감지 기준 (%):",
        "cond_bend_type": "굽힘 방식:",
        "cond_bend_3p": "3점 굽힘",
        "cond_bend_4p": "4점 굽힘",
        "cond_span": "지지대 간격 (지간거리, mm):",
        "cond_hold_type": "유지 제어 방식:",
        "cond_hold_load": "하중 유지 (크리프 시험)",
        "cond_hold_disp": "변위 유지 (응력 이완 시험)",
        "cond_hold_val": "목표 유지값 (N 또는 mm):",
        "cond_hold_dur": "유지 시간 (초):",
        
        # Machine Control Buttons
        "ctrl_title": "장비 조작",
        "btn_start": "시험 시작",
        "btn_stop": "비상 정지",
        "btn_origin": "원점 복귀",
        "btn_reset": "데이터 초기화",
        
        # Exports
        "export_title": "성적서 및 데이터 저장",
        "btn_excel": "엑셀 데이터 저장 (.xlsx)",
        "btn_pdf": "시험 성적서 출력 (.pdf)",
        
        # Readout Tiles
        "tile_load": "하중",
        "tile_disp": "변위 (이동거리)",
        "tile_stress": "응력",
        "tile_strain": "변형률",
        
        # Graph
        "graph_title": "실시간 시험 곡선 그래프",
        "graph_ss": "응력 - 변형률 곡선",
        "graph_ld": "하중 - 변위 곡선",
        
        # Results Table
        "results_title": "시험 결과 분석표",
        "col_pmax": "최대 하중 (N)",
        "col_rm": "인장 강도 (MPa)",
        "col_rp02": "항복 강도 (MPa)",
        "col_e": "탄성 계수 (GPa)",
        "col_a": "연신율 (%)",
        "col_dl": "파단 변위 (mm)",
        "col_u": "흡수 에너지 (J)",
        "col_status": "시험 상태",
        "status_fractured": "파단 완료",
        "status_completed": "시험 완료",
        
        # Hardware Tab
        "hw_conn_title": "통신 포트 및 장비 설정",
        "hw_mode": "동작 모드:",
        "hw_mode_sim": "가상 시뮬레이터 (장비 없이 테스트)",
        "hw_mode_real": "실제 시험기 연결 (봉신 P2020 / P2014)",
        "hw_port": "통신 포트:",
        "btn_refresh": "포트 새로고침",
        "hw_baud": "통신 속도:",
        "hw_format": "통신 규격:",
        "btn_connect": "장비 연결",
        "btn_disconnect": "장비 연결 해제",
        "hw_status_disconnected": "● 장비 미연결 (가상 시뮬레이터 동작 중)",
        "hw_status_connected": "● 정상 연결됨",
        
        # Tare & Calibration
        "tare_title": "영점 맞춤",
        "btn_tare_load": "하중 영점 맞춤 (0.00 N)",
        "btn_tare_disp": "변위 영점 맞춤 (0.000 mm)",
        
        "calib_title": "장비 정밀 교정",
        "calib_load_title": "1) 로드셀 2점 하중 교정",
        "btn_calib_zero": "현재 센서값을 무부하 영점으로 설정",
        "calib_ref_label": "기준 하중값:",
        "btn_calib_span": "스팬 교정 실행",
        "calib_load_factor": "현재 하중 보정 계수:",
        
        "calib_speed_title": "2) 이동 속도 교정",
        "calib_target_speed": "목표 속도 (mm/min):",
        "calib_measured_dist": "1분간 실측 이동거리 (mm):",
        "btn_calib_speed": "속도 보정값 계산 및 적용",
        "calib_speed_factor": "현재 속도 보정 계수:",
        
        "packet_title": "실시간 데이터 수신 모니터",
        "btn_clear_log": "화면 지우기",
        
        # Status Bar
        "status_ready": "장비 상태: 대기 중 | 가상 시뮬레이터 모드",
        "status_running": "시험 진행 중... [모드: {mode}, 시편: {specimen}]",
        "status_done": "시험 완료: {reason} | 총 계측점: {count}개"
    },
    
    "EN": {
        # App Title & Tabs
        "app_title": "SALT SW VER.1 — Universal Testing Machine Control System",
        "tab_dashboard": "Test Control & Real-time Monitoring",
        "tab_hardware": "Hardware & Precision Calibration",
        "brand_sub": "Universal Testing Machine Control System",
        
        # Test Modes
        "mode_title": "Select Test Mode",
        "mode_tensile": "Tensile Test",
        "mode_compression": "Compression Test",
        "mode_bending": "Flexural / Bending Test",
        "mode_holding": "Holding Test",
        
        # Specimen
        "spec_title": "Specimen Parameters",
        "spec_id": "Specimen ID:",
        "spec_mat": "Material:",
        "spec_type": "Specimen Geometry:",
        "spec_type_flat": "Flat (Rectangular)",
        "spec_type_round": "Round (Cylindrical)",
        "spec_width": "Width (mm):",
        "spec_dia": "Diameter (mm):",
        "spec_thick": "Thickness (mm):",
        "spec_l0": "Gauge Length (mm):",
        
        # Conditions
        "cond_title": "Control Parameters",
        "cond_speed": "Test Speed (mm/min):",
        "cond_drop": "Fracture Threshold (%):",
        "cond_bend_type": "Bending Method:",
        "cond_bend_3p": "3-Point Bending",
        "cond_bend_4p": "4-Point Bending",
        "cond_span": "Support Span (L, mm):",
        "cond_hold_type": "Holding Control Mode:",
        "cond_hold_load": "Load Hold (Creep)",
        "cond_hold_disp": "Displacement Hold (Relaxation)",
        "cond_hold_val": "Target Value (N or mm):",
        "cond_hold_dur": "Hold Duration (sec):",
        
        # Machine Control Buttons
        "ctrl_title": "Machine Operation",
        "btn_start": "START TEST",
        "btn_stop": "EMERGENCY STOP",
        "btn_origin": "Zero Return",
        "btn_reset": "Reset Data",
        
        # Exports
        "export_title": "Data Export",
        "btn_excel": "Export Excel (.xlsx)",
        "btn_pdf": "Export Certificate (.pdf)",
        
        # Readout Tiles
        "tile_load": "LOAD",
        "tile_disp": "DISPLACEMENT",
        "tile_stress": "STRESS",
        "tile_strain": "STRAIN",
        
        # Graph
        "graph_title": "Real-time Test Curve",
        "graph_ss": "Stress - Strain Curve",
        "graph_ld": "Load - Displacement Curve",
        
        # Results Table
        "results_title": "Mechanical Properties Results",
        "col_pmax": "Peak Load (N)",
        "col_rm": "Tensile Strength (MPa)",
        "col_rp02": "Yield Strength (MPa)",
        "col_e": "Young's Modulus (GPa)",
        "col_a": "Elongation (%)",
        "col_dl": "Break Disp (mm)",
        "col_u": "Absorbed Energy (J)",
        "col_status": "Status",
        "status_fractured": "Fractured",
        "status_completed": "Completed",
        
        # Hardware Tab
        "hw_conn_title": "Serial Interface & Hardware Setup",
        "hw_mode": "Operation Mode:",
        "hw_mode_sim": "Virtual Physical Simulator",
        "hw_mode_real": "Hardware (Bongshin P2020 / P2014)",
        "hw_port": "Serial COM Port:",
        "btn_refresh": "Refresh Ports",
        "hw_baud": "Baudrate:",
        "hw_format": "Data Format:",
        "btn_connect": "Connect",
        "btn_disconnect": "Disconnect",
        "hw_status_disconnected": "● Disconnected (Virtual Simulator Active)",
        "hw_status_connected": "● Connected",
        
        # Tare & Calibration
        "tare_title": "Zero / Tare Calibration",
        "btn_tare_load": "Tare Load (0.00 N)",
        "btn_tare_disp": "Tare Disp (0.000 mm)",
        
        "calib_title": "Precision Calibration",
        "calib_load_title": "1) Load Cell 2-Point Calibration",
        "btn_calib_zero": "Set Current Load as Zero Offset",
        "calib_ref_label": "Reference Load:",
        "btn_calib_span": "Execute Span Calibration",
        "calib_load_factor": "Current Load Scale Factor:",
        
        "calib_speed_title": "2) Crosshead Speed Calibration",
        "calib_target_speed": "Target Speed (mm/min):",
        "calib_measured_dist": "Measured Distance in 60s (mm):",
        "btn_calib_speed": "Calculate & Apply Speed Factor",
        "calib_speed_factor": "Current Speed Scale Factor:",
        
        "packet_title": "Raw RS-232 Packet Monitor",
        "btn_clear_log": "Clear Log",
        
        # Status Bar
        "status_ready": "Machine Status: READY | Virtual Simulator Mode",
        "status_running": "Testing in progress... [Mode: {mode}, Specimen: {specimen}]",
        "status_done": "Test Completed: {reason} | Total Samples: {count}"
    }
}
