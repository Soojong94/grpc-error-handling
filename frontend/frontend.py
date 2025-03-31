import streamlit as st
import requests
import time
import threading
import json
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime
import logging
import queue

# 로깅 설정
logging.basicConfig(
    level=logging.ERROR,  # INFO에서 ERROR로 변경
    format='%(asctime)s [%(levelname)s] [FRONTEND] [Thread-%(thread)d] %(message)s',
)
logger = logging.getLogger(__name__)

# BFF 서비스 URL
BFF_URL = "http://localhost:8000"

# 스레드 안전한 데이터 공유를 위한 큐
logs_queue = queue.Queue()
events_queue = queue.Queue()
pattern_status_queue = queue.Queue()
circuit_breaker_status_queue = queue.Queue()
metrics_queue = queue.Queue()

# 전역 변수
logs_data = []
events_data = []
pattern_status_data = {
    "deadline": True,
    "circuit_breaker": True,
    "backpressure": True
}
circuit_breaker_status_data = {
    "state": "CLOSED",
    "failure_count": 0,
    "reset_timeout": 10,
    "remaining_recovery_time": 0
}
metrics_data = {
    "deadlines_exceeded": 0,
    "circuit_breaker_trips": 0,
    "backpressure_rejections": 0,
    "total_requests": 0,
    "successful_requests": 0,
    "failed_requests": 0,
    "avg_response_time": 0
}

# 초기화
if 'error_message' not in st.session_state:
    st.session_state.error_message = None
    st.session_state.is_fetching = False

# API 요청 함수 (재시도 로직 포함)
def make_api_request(method, url, json_data=None, params=None, max_retries=3, retry_delay=1):
    """API 요청을 보내고 실패시 재시도하는 함수"""
    st.session_state.is_fetching = True
    st.session_state.error_message = None
    
    retries = 0
    while retries < max_retries:
        try:
            logger.info(f"API 요청: {method} {url}")
            if method.lower() == "get":
                response = requests.get(url, params=params, timeout=10)
            elif method.lower() == "post":
                response = requests.post(url, json=json_data, timeout=10)
            else:
                logger.error(f"지원되지 않는 HTTP 메서드: {method}")
                st.session_state.error_message = f"지원되지 않는 HTTP 메서드: {method}"
                st.session_state.is_fetching = False
                return None
            
            # 응답 상태 코드 확인
            if response.status_code == 200:
                logger.info(f"API 요청 성공: {url}")
                st.session_state.is_fetching = False
                return response
            else:
                logger.warning(f"API 요청 실패 (상태 코드: {response.status_code}): {url}")
                st.session_state.error_message = f"요청 실패 (상태 코드: {response.status_code})"
                
                # 서버 내부 오류면 재시도
                if 500 <= response.status_code < 600:
                    retries += 1
                    if retries < max_retries:
                        logger.info(f"{retry_delay}초 후 재시도 ({retries}/{max_retries})...")
                        time.sleep(retry_delay)
                        continue
                
                st.session_state.is_fetching = False
                return response
                
        except requests.exceptions.Timeout:
            logger.warning(f"요청 타임아웃: {url}")
            st.session_state.error_message = "요청 타임아웃"
            retries += 1
            if retries < max_retries:
                logger.info(f"{retry_delay}초 후 재시도 ({retries}/{max_retries})...")
                time.sleep(retry_delay)
            else:
                st.session_state.is_fetching = False
                return None
                
        except requests.exceptions.ConnectionError:
            logger.error(f"연결 오류: {url}")
            st.session_state.error_message = "서버에 연결할 수 없습니다"
            retries += 1
            if retries < max_retries:
                logger.info(f"{retry_delay}초 후 재시도 ({retries}/{max_retries})...")
                time.sleep(retry_delay)
            else:
                st.session_state.is_fetching = False
                return None
                
        except Exception as e:
            logger.error(f"API 요청 중 예상치 못한 오류: {str(e)}")
            st.session_state.error_message = f"오류: {str(e)}"
            st.session_state.is_fetching = False
            return None
    
    st.session_state.is_fetching = False
    return None

# 로그 조회 함수
def fetch_logs():
    while True:
        try:
            response = make_api_request("get", f"{BFF_URL}/logs", params={"limit": 200})
            if response and response.status_code == 200:
                global logs_data
                logs_data = response.json()
                logs_queue.put(True)  # 데이터가 업데이트되었음을 알림
        except Exception as e:
            logger.error(f"로그 조회 중 오류: {str(e)}")
        time.sleep(10)  # 3초마다 로그 조회

# 이벤트 조회 함수
def fetch_events():
    while True:
        try:
            response = make_api_request("get", f"{BFF_URL}/events")
            if response and response.status_code == 200:
                global events_data
                events_data = response.json()
                events_queue.put(True)  # 데이터가 업데이트되었음을 알림
        except Exception as e:
            logger.error(f"이벤트 조회 중 오류: {str(e)}")
        time.sleep(10)  # 2초마다 이벤트 조회

# 패턴 상태 조회 함수
def fetch_pattern_status():
    while True:
        try:
            response = make_api_request("get", f"{BFF_URL}/patterns/status")
            if response and response.status_code == 200:
                global pattern_status_data
                pattern_status_data = response.json()
                pattern_status_queue.put(True)  # 데이터가 업데이트되었음을 알림
        except Exception as e:
            logger.error(f"패턴 상태 조회 중 오류: {str(e)}")
        time.sleep(10)  # 2초마다 패턴 상태 조회

# 서킷 브레이커 상태 조회 함수
def fetch_circuit_breaker_status():
    while True:
        try:
            response = make_api_request("get", f"{BFF_URL}/circuit-breaker/status")
            if response and response.status_code == 200:
                global circuit_breaker_status_data
                circuit_breaker_status_data = response.json()
                circuit_breaker_status_queue.put(True)  # 데이터가 업데이트되었음을 알림
        except Exception as e:
            logger.error(f"서킷 브레이커 상태 조회 중 오류: {str(e)}")
        time.sleep(1)  # 1초마다 서킷 브레이커 상태 조회

# 메트릭 조회 함수
def fetch_metrics():
    while True:
        try:
            response = make_api_request("get", f"{BFF_URL}/metrics")
            if response and response.status_code == 200:
                global metrics_data
                metrics_data = response.json()
                metrics_queue.put(True)  # 데이터가 업데이트되었음을 알림
        except Exception as e:
            logger.error(f"메트릭 조회 중 오류: {str(e)}")
        time.sleep(2)  # 2초마다 메트릭 조회

# 백그라운드 스레드 시작 부분 수정
try:
    # 꼭 필요한 스레드만 활성화 (로그와 패턴 상태만)
    log_thread = threading.Thread(target=fetch_logs, daemon=True)
    log_thread.start()
    
    pattern_thread = threading.Thread(target=fetch_pattern_status, daemon=True)
    pattern_thread.start()
    
    # 다른 스레드는 주석 처리
    # events_thread = threading.Thread(target=fetch_events, daemon=True)
    # events_thread.start()
    
    # circuit_thread = threading.Thread(target=fetch_circuit_breaker_status, daemon=True)
    # circuit_thread.start()
    
    # metrics_thread = threading.Thread(target=fetch_metrics, daemon=True)
    # metrics_thread.start()
    
    logger.info("백그라운드 스레드 시작 완료")
except Exception as e:
    logger.error(f"백그라운드 스레드 시작 실패: {str(e)}")

# 큐에서 데이터 가져오기
try:
    # 큐에 데이터가 있는지 논블로킹 방식으로 확인
    if not logs_queue.empty():
        logs_queue.get(block=False)
        st.session_state.logs = logs_data
        
    if not events_queue.empty():
        events_queue.get(block=False)
        st.session_state.events = events_data
        
    if not pattern_status_queue.empty():
        pattern_status_queue.get(block=False)
        st.session_state.pattern_status = pattern_status_data
        
    if not circuit_breaker_status_queue.empty():
        circuit_breaker_status_queue.get(block=False)
        st.session_state.circuit_breaker_status = circuit_breaker_status_data
        
    if not metrics_queue.empty():
        metrics_queue.get(block=False)
        st.session_state.metrics = metrics_data
except queue.Empty:
    pass
except Exception as e:
    logger.error(f"큐 처리 중 오류: {str(e)}")

# 세션 상태 초기화 (없을 경우)
if 'logs' not in st.session_state:
    st.session_state.logs = logs_data
if 'events' not in st.session_state:
    st.session_state.events = events_data
if 'pattern_status' not in st.session_state:
    st.session_state.pattern_status = pattern_status_data
if 'circuit_breaker_status' not in st.session_state:
    st.session_state.circuit_breaker_status = circuit_breaker_status_data
if 'metrics' not in st.session_state:
    st.session_state.metrics = metrics_data


# 앱 제목
st.title("gRPC 에러 처리 패턴 모니터링")
st.write("""
이 애플리케이션은 gRPC 기반 시스템에서 발생할 수 있는 슬로우 쿼리 문제를 다양한 에러 처리 패턴으로 
해결하는 방법을 테스트하고 모니터링합니다.
""")

# 에러 메시지 표시
if st.session_state.error_message:
    st.error(st.session_state.error_message)

# API 요청 중 로딩 표시
if st.session_state.is_fetching:
    st.info("요청 처리 중...")

# 탭 생성
tab1, tab2, tab3, tab4 = st.tabs(["대시보드", "에러 처리 패턴", "테스트 실행", "로그 확인"])

# 탭 1: 대시보드
with tab1:
    st.header("시스템 상태 대시보드")
    
    # 현재 시간 표시
    st.write(f"최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 패턴 상태 및 시스템 메트릭 표시
    col1, col2, col3 = st.columns(3)
    
    # 현재 메트릭 가져오기
    current_metrics = st.session_state.metrics
    
    with col1:
        st.subheader("요청 통계")
        total = current_metrics.get("total_requests", 0)
        success = current_metrics.get("successful_requests", 0)
        failed = current_metrics.get("failed_requests", 0)
        success_rate = (success / total * 100) if total > 0 else 0
        
        st.metric("총 요청 수", f"{total:,}")
        st.metric("성공률", f"{success_rate:.1f}%")
        st.metric("평균 응답 시간", f"{current_metrics.get('avg_response_time', 0):.2f}초")
    
    with col2:
        st.subheader("에러 통계")
        st.metric("데드라인 초과", f"{current_metrics.get('deadlines_exceeded', 0):,}")
        st.metric("서킷 브레이커 개방", f"{current_metrics.get('circuit_breaker_trips', 0):,}")
        st.metric("백프레셔 거부", f"{current_metrics.get('backpressure_rejections', 0):,}")
    
    with col3:
        # 서킷 브레이커 상태
        st.subheader("서킷 브레이커 상태")
        cb_status = st.session_state.circuit_breaker_status
        state = cb_status.get("state", "UNKNOWN")
        
        # 상태에 따른 색상 지정
        if state == "OPEN":
            st.error(f"상태: {state}")
        elif state == "HALF-OPEN":
            st.warning(f"상태: {state}")
        else:
            st.success(f"상태: {state}")
        
        st.write(f"실패 카운트: {cb_status.get('failure_count', 0)}")
        
        # 복구 타이머가 있는 경우 표시
        remaining = cb_status.get('remaining_recovery_time', 0)
        if remaining > 0 and state == "OPEN":
            st.write(f"자동 복구까지: {remaining:.1f}초")
            st.progress(1 - (remaining / cb_status.get('reset_timeout', 10)))
    
    # 활성화된 패턴 상태 표시
    st.subheader("에러 처리 패턴 상태")
    
    pattern_status = st.session_state.pattern_status
    col1, col2, col3 = st.columns(3)
    
    with col1:
        deadline_status = "활성화" if pattern_status.get("deadline", False) else "비활성화"
        if pattern_status.get("deadline", False):
            st.success(f"데드라인 패턴: {deadline_status}")
        else:
            st.error(f"데드라인 패턴: {deadline_status}")
    
    with col2:
        circuit_status = "활성화" if pattern_status.get("circuit_breaker", False) else "비활성화"
        if pattern_status.get("circuit_breaker", False):
            st.success(f"서킷 브레이커 패턴: {circuit_status}")
        else:
            st.error(f"서킷 브레이커 패턴: {circuit_status}")
    
    with col3:
        backpressure_status = "활성화" if pattern_status.get("backpressure", False) else "비활성화"
        if pattern_status.get("backpressure", False):
            st.success(f"백프레셔 패턴: {backpressure_status}")
        else:
            st.error(f"백프레셔 패턴: {backpressure_status}")
    
    # 이벤트 타임라인
    st.subheader("시스템 이벤트 타임라인")
    
    if not st.session_state.events:
        st.info("이벤트 데이터가 없습니다.")
    else:
        events = st.session_state.events.copy()
        # 최신 이벤트가 위로 오도록 역순 정렬
        events.reverse()
        
        # 이벤트 유형별 아이콘 및 색상 정의
        event_icons = {
            "system": "🖥️",
            "circuit_breaker": "🔌",
            "deadline": "⏱️",
            "backpressure": "🚧",
            "error": "❌",
            "test": "🧪",
            "settings": "⚙️",
            "pattern_change": "🔄"
        }
        
        event_colors = {
            "system": "blue",
            "circuit_breaker": "red",
            "deadline": "orange",
            "backpressure": "purple",
            "error": "crimson",
            "test": "green",
            "settings": "gray",
            "pattern_change": "teal"
        }
        
        # 이벤트 타임라인 표시
        for event in events[:10]:  # 최근 10개 이벤트만 표시
            event_type = event.get("type", "unknown")
            timestamp = event.get("timestamp", "")
            description = event.get("description", "")
            
            icon = event_icons.get(event_type, "ℹ️")
            color = event_colors.get(event_type, "black")
            
            st.markdown(f"""
            <div style="margin-bottom: 10px; border-left: 3px solid {color}; padding-left: 10px;">
                <span style="color: gray; font-size: 0.8em;">{timestamp}</span><br>
                <span style="font-size: 1.2em;">{icon} <span style="color: {color};">{event_type.upper()}</span>: {description}</span>
            </div>
            """, unsafe_allow_html=True)
    
    # 읽기 쉬운 그래프로 변환
    st.subheader("에러 패턴 효과 추이")
    
    # 차트를 위한 데이터 준비 (여기서는 현재 메트릭으로만 간단히 표시)
    labels = ['성공', '데드라인 초과', '서킷 브레이커', '백프레셔 거부']
    values = [
        current_metrics.get("successful_requests", 0),
        current_metrics.get("deadlines_exceeded", 0),
        current_metrics.get("circuit_breaker_trips", 0),
        current_metrics.get("backpressure_rejections", 0)
    ]
    
    # 데이터가 있는 경우에만 차트 표시
    if sum(values) > 0:
        fig, ax = plt.subplots()
        colors = ['#4CAF50', '#FF9800', '#F44336', '#2196F3']
        
        # 값이 0인 항목은 제외
        non_zero_labels = []
        non_zero_values = []
        non_zero_colors = []
        
        for i, value in enumerate(values):
            if value > 0:
                non_zero_labels.append(labels[i])
                non_zero_values.append(value)
                non_zero_colors.append(colors[i])
        
        if non_zero_values:
            ax.pie(non_zero_values, labels=non_zero_labels, colors=non_zero_colors,
                   autopct='%1.1f%%', startangle=90)
            ax.axis('equal')
            st.pyplot(fig)
        else:
            st.info("아직 요청 데이터가 없습니다.")
    else:
        st.info("아직 요청 데이터가 없습니다.")

# 탭 2: 에러 처리 패턴 설정
with tab2:
    st.header("에러 처리 패턴 설정")
    st.write("각 패턴을 활성화/비활성화하여 서로 다른 에러 처리 방식을 테스트할 수 있습니다.")
    
    # 패턴 상태 직접 가져오기
    current_pattern_status = st.session_state.pattern_status
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.subheader("데드라인 패턴")
        st.write("""
        데드라인 패턴은 요청에 타임아웃을 설정하여 지정된 시간 내에 응답이 오지 않으면 요청을 종료합니다.
        이를 통해 시스템이 느린 요청에 의해 차단되는 것을 방지합니다.
        """)
        
        deadline_enabled = st.checkbox("데드라인 패턴 활성화", value=current_pattern_status.get("deadline", True), key="deadline_checkbox")
        if st.button("데드라인 설정 적용"):
            response = make_api_request(
                "post",
                f"{BFF_URL}/patterns/deadline", 
                json_data={"status": deadline_enabled}
            )
            
            if response and response.status_code == 200:
                # 성공 시 즉시 세션 상태 업데이트
                result = response.json()
                st.session_state.pattern_status["deadline"] = result["status"]
                st.success(f"데드라인 패턴이 {'활성화' if deadline_enabled else '비활성화'} 되었습니다.")
                st.rerun()  # UI 즉시 새로고침
            else:
                st.error("설정 적용 실패")
    
    with col2:
        st.subheader("서킷 브레이커 패턴")
        st.write("""
        서킷 브레이커 패턴은 연속된 오류가 발생하면 일시적으로 요청을 차단합니다.
        이를 통해 이미 문제가 있는 시스템에 추가 부하가 가는 것을 방지하고, 자가 복구 시간을 제공합니다.
        """)
        
        circuit_enabled = st.checkbox("서킷 브레이커 패턴 활성화", value=current_pattern_status.get("circuit_breaker", True), key="circuit_checkbox")
        if st.button("서킷 브레이커 설정 적용"):
            response = make_api_request(
                "post",
                f"{BFF_URL}/patterns/circuit_breaker", 
                json_data={"status": circuit_enabled}
            )
            
            if response and response.status_code == 200:
                # 성공 시 즉시 세션 상태 업데이트
                result = response.json()
                st.session_state.pattern_status["circuit_breaker"] = result["status"]
                st.success(f"서킷 브레이커 패턴이 {'활성화' if circuit_enabled else '비활성화'} 되었습니다.")
                st.rerun()  # UI 즉시 새로고침
            else:
                st.error("설정 적용 실패")
    
    with col3:
        st.subheader("백프레셔 패턴")
        st.write("""
        백프레셔 패턴은 시스템이 처리할 수 있는 요청 수를 제한합니다.
        이를 통해 과도한 동시 요청으로 인한 시스템 과부하를 방지하고, 안정적인 서비스를 유지합니다.
        """)
        
        backpressure_enabled = st.checkbox("백프레셔 패턴 활성화", value=current_pattern_status.get("backpressure", True), key="backpressure_checkbox")
        if st.button("백프레셔 설정 적용"):
            response = make_api_request(
                "post",
                f"{BFF_URL}/patterns/backpressure", 
                json_data={"status": backpressure_enabled}
            )
            
            if response and response.status_code == 200:
                # 성공 시 즉시 세션 상태 업데이트
                result = response.json()
                st.session_state.pattern_status["backpressure"] = result["status"]
                st.success(f"백프레셔 패턴이 {'활성화' if backpressure_enabled else '비활성화'} 되었습니다.")
                st.rerun()  # UI 즉시 새로고침
            else:
                st.error("설정 적용 실패")
    
    # 패턴 상세 설명 및 현재 상태
    st.subheader("패턴 설명 및 현재 상태")
    
    # 패턴 상태 요약
    active_patterns = []
    if current_pattern_status.get("deadline", False):
        active_patterns.append("데드라인")
    if current_pattern_status.get("circuit_breaker", False):
        active_patterns.append("서킷 브레이커")
    if current_pattern_status.get("backpressure", False):
        active_patterns.append("백프레셔")
    
    if active_patterns:
        st.success(f"현재 활성화된 패턴: {', '.join(active_patterns)}")
    else:
        st.warning("현재 활성화된 패턴이 없습니다.")
    
    # 서킷 브레이커 상태 확인
    st.subheader("서킷 브레이커 상태")
    cb_status = st.session_state.circuit_breaker_status
    
    # 상태에 따른 표시
    if cb_status.get("state", "") == "OPEN":
        st.error(f"서킷 브레이커 상태: {cb_status.get('state', '')}")
        st.write(f"실패 카운트: {cb_status.get('failure_count', 0)}")
        
        remaining = cb_status.get('remaining_recovery_time', 0)
        if remaining > 0:
            st.write(f"자동 복구까지 남은 시간: {remaining:.1f}초")
            st.progress(1 - (remaining / cb_status.get('reset_timeout', 10)))
            
        if st.button("서킷 브레이커 수동 초기화"):
            response = make_api_request(
                "post",
                f"{BFF_URL}/circuit-breaker/reset"
            )
            
            if response and response.status_code == 200:
                st.success("서킷 브레이커가 초기화되었습니다.")
                st.rerun()
            else:
                st.error("서킷 브레이커 초기화 실패")
    else:
        st.success(f"서킷 브레이커 상태: {cb_status.get('state', '')}")
        st.write(f"실패 카운트: {cb_status.get('failure_count', 0)}")
    
    # 백프레셔 초기화 옵션
    st.subheader("백프레셔 초기화")
    st.write("백프레셔 메커니즘이 요청을 거부하는 경우, 여기서 세마포어를 수동으로 초기화할 수 있습니다.")
    
    if st.button("백프레셔 초기화"):
        response = make_api_request(
            "post",
            f"{BFF_URL}/backend/reset-backpressure"
        )
        
        if response and response.status_code == 200:
            st.success("백프레셔가 초기화되었습니다.")
        else:
            st.error("백프레셔 초기화 실패")

# 탭 3: 테스트 실행
with tab3:
    st.header("슬로우 쿼리 테스트")
    st.write("""
    슬로우 쿼리는 실제 환경에서 가장 흔하게 발생하는 문제 중 하나입니다.
    각 에러 처리 패턴이 슬로우 쿼리에 어떻게 대응하는지 확인해보세요.
    """)
    
    col1, col2 = st.columns(2)
    
    with col1:
        query_delay = st.slider("쿼리 지연 시간 (초)", 1, 10, 5)
        concurrent_requests = st.slider("동시 요청 수", 5, 30, 10)
    
    with col2:
        timeout = st.slider("타임아웃 설정 (초, 데드라인 패턴용)", 1, 5, 3)
        
        # 활성화된 패턴 표시
        active_patterns = []
        if st.session_state.pattern_status.get("deadline", False):
            active_patterns.append("데드라인")
        if st.session_state.pattern_status.get("circuit_breaker", False):
            active_patterns.append("서킷 브레이커")
        if st.session_state.pattern_status.get("backpressure", False):
            active_patterns.append("백프레셔")
            
        if active_patterns:
            st.write(f"활성화된 패턴: {', '.join(active_patterns)}")
        else:
            st.warning("활성화된 패턴이 없습니다!")
    
    if st.button("슬로우 쿼리 테스트 실행"):
        with st.spinner("테스트 실행 중..."):
            response = make_api_request(
                "get",
                f"{BFF_URL}/test/slow-query",
                params={
                    "delay": query_delay,
                    "requests": concurrent_requests,
                    "timeout": timeout
                }
            )
            
            if response and response.status_code == 200:
                try:
                    result = response.json()
                    st.success("테스트 완료!")
                    
                    # 테스트 결과 요약
                    st.subheader("테스트 결과 요약")
                    st.text(result["summary"])
                    
                    # 그래프로 결과 시각화
                    st.subheader("요청 처리 결과")
                    results = result["results"]
                    
                    # 파이 차트 - 요청 결과 분포
                    fig1, ax1 = plt.subplots()
                    labels = ['성공', '데드라인 초과', '서킷 브레이커', '백프레셔 거부', '기타 오류']
                    sizes = [
                        results["success_count"], 
                        results["deadline_exceeded"], 
                        results["circuit_broken"], 
                        results["backpressure_rejected"], 
                        results["other_errors"]
                    ]
                    colors = ['#4CAF50', '#FF9800', '#F44336', '#2196F3', '#9C27B0']
                    
                    # 값이 0인 항목은 제외
                    non_zero_labels = []
                    non_zero_sizes = []
                    non_zero_colors = []
                    
                    for i, size in enumerate(sizes):
                        if size > 0:
                            non_zero_labels.append(labels[i])
                            non_zero_sizes.append(size)
                            non_zero_colors.append(colors[i])
                    
                    if non_zero_sizes:
                        ax1.pie(non_zero_sizes, labels=non_zero_labels, colors=non_zero_colors,
                                autopct='%1.1f%%', startangle=90)
                        ax1.axis('equal')
                        st.pyplot(fig1)
                    
                    # 패턴별 효과 분석
                    if "pattern_effects" in result and result["pattern_effects"]:
                        st.subheader("패턴별 효과 분석")
                        for pattern, effect in result["pattern_effects"].items():
                            st.write(f"**{effect['name']}**: {effect['comment']}")
                            st.progress(float(effect['effectiveness']))
                    
                    # 상세 요청 결과
                    st.subheader("개별 요청 상세")
                    
                    # 테이블 데이터 준비
                    table_data = []
                    for detail in result["results"]["details"]:
                        status_text = {
                            "success": "성공",
                            "deadline_exceeded": "데드라인 초과",
                            "circuit_broken": "서킷 브레이커 차단",
                            "backpressure_rejected": "백프레셔 거부",
                            "error": "오류"
                        }.get(detail["status"], detail["status"])
                        
                        elapsed = detail.get("elapsed", 0)
                        
                        table_data.append({
                            "요청 ID": detail["request_id"],
                            "상태": status_text,
                            "소요시간(초)": f"{elapsed:.2f}" if elapsed else "-"
                        })
                    
                    # 테이블 표시
                    st.dataframe(table_data)
                
                except json.JSONDecodeError:
                    st.error("응답 데이터 처리 실패: 잘못된 JSON 형식")
                except KeyError as e:
                    st.error(f"응답 데이터 처리 실패: 필수 키 누락 - {str(e)}")
                except Exception as e:
                    st.error(f"응답 데이터 처리 중 오류: {str(e)}")
            else:
                if not response:
                    st.error("테스트 요청 실패: 서버에 연결할 수 없습니다")
                else:
                    st.error(f"테스트 실패: {response.status_code} - {response.text}")
    
    # 에러율 설정
    st.header("에러율 설정")
    st.write("백엔드 서비스의 에러 발생률을 설정합니다. 서킷 브레이커 테스트에 유용합니다.")
    
    error_rate = st.slider("에러 발생률 (%)", 0, 100, 0)
    if st.button("에러율 설정"):
        response = make_api_request(
            "post",
            f"{BFF_URL}/backend/error-rate", 
            json_data={"error_rate": error_rate}
        )
        
        if response and response.status_code == 200:
            st.success(f"에러율이 {error_rate}%로 설정되었습니다.")
        else:
            st.error("에러율 설정 실패")

# 탭 4: 로그 확인
with tab4:
    st.header("시스템 로그")
    
    # 로그 관련 컨트롤
    col1, col2 = st.columns(2)
    with col1:
        log_limit = st.slider("표시할 로그 수", 10, 200, 50)
    with col2:
        if st.button("로그 새로고침", key="refresh_logs"):
            st.rerun()
    
    # 로그 필터링
    log_filter = st.text_input("로그 검색 (키워드 입력)", "")
    
    # 패턴별 로그 필터링
    col1, col2, col3 = st.columns(3)
    with col1:
        show_deadline = st.checkbox("데드라인 로그", value=True)
    with col2:
        show_circuit = st.checkbox("서킷 브레이커 로그", value=True)
    with col3:
        show_backpressure = st.checkbox("백프레셔 로그", value=True)
    
    # 로그 레벨 필터링
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        show_info = st.checkbox("INFO", value=True)
    with col2:
        show_warning = st.checkbox("WARNING", value=True)
    with col3:
        show_error = st.checkbox("ERROR", value=True)
    with col4:
        show_debug = st.checkbox("DEBUG", value=False)
    
    # 로그 필터링
    filtered_logs = []
    for log in st.session_state.logs:
        message = str(log.get('message', '')).lower()
        level = log.get('level', '')
        pattern = log.get('pattern', '')
        
        # 키워드 필터링
        if log_filter and log_filter.lower() not in message.lower():
            continue
            
        # 패턴 필터링
        pattern_match = False
        if (pattern == "데드라인" and show_deadline) or \
           (pattern == "서킷브레이커" and show_circuit) or \
           (pattern == "백프레셔" and show_backpressure) or \
           (not show_deadline and not show_circuit and not show_backpressure):
            pattern_match = True
            
        # 레벨 필터링
        level_match = False
        if (level == "INFO" and show_info) or \
           (level == "WARNING" and show_warning) or \
           (level == "ERROR" and show_error) or \
           (level == "DEBUG" and show_debug):
            level_match = True
            
        if pattern_match and level_match:
            filtered_logs.append(log)
    
    # 로그 테이블로 표시
    if filtered_logs:
        st.markdown("### 패턴별 로그")
        
        # 테이블 데이터 준비
        table_data = []
        for log in filtered_logs[-log_limit:]:
            timestamp = log.get('timestamp', '')
            level = log.get('level', '')
            service = log.get('service', '')
            message = log.get('message', '')
            thread = log.get('thread', '')
            pattern = log.get('pattern', '')
            
            table_data.append({
                "시간": timestamp,
                "패턴": pattern,
                "레벨": level,
                "서비스": service,
                "스레드": f"Thread-{thread}" if thread else "",
                "메시지": message
            })
        
        # 테이블 역순으로 정렬 (최신 로그가 위에 오도록)
        table_data.reverse()
        
        # 테이블로 표시
        st.dataframe(
            table_data,
            use_container_width=True,
            height=500,
            column_config={
                "메시지": st.column_config.TextColumn(width="large"),
                "시간": st.column_config.TextColumn(width="small"),
                "레벨": st.column_config.TextColumn(width="small"),
                "패턴": st.column_config.TextColumn(width="small"),
                "서비스": st.column_config.TextColumn(width="small"),
                "스레드": st.column_config.TextColumn(width="small"),
            }
        )
    else:
        st.info("조건에 맞는 로그가 없습니다.")

# 주기적 새로고침 (5초마다)
if "refresh_counter" not in st.session_state:
    st.session_state.refresh_counter = 0
    st.session_state.last_refresh = time.time()

current_time = time.time()
if current_time - st.session_state.last_refresh > 5:
    st.session_state.refresh_counter += 1
    st.session_state.last_refresh = current_time
    st.rerun()