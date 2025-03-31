import streamlit as st
import requests
import json
import time
import threading
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

# BFF 서비스 URL
BFF_URL = "http://localhost:8000"

def log_to_ui(message):
    """UI에 로그 메시지 추가"""
    st.session_state.logs.append({
        "timestamp": datetime.now().strftime('%H:%M:%S'),
        "message": message
    })

# 로그 조회 함수 추가
def fetch_logs():
    while True:
        try:
            response = requests.get(f"{BFF_URL}/logs")
            if response.status_code == 200:
                logs = response.json()
                # 세션 상태에 로그 저장
                st.session_state.logs = logs
                # 상태 변경 감지를 위한 카운터 증가
                st.session_state.log_update_counter += 1
        except Exception as e:
            pass  # 오류 무시
        time.sleep(2)  # 2초마다 로그 조회

# 메트릭 조회 함수 추가
def fetch_metrics():
    while True:
        try:
            response = requests.get(f"{BFF_URL}/metrics")
            if response.status_code == 200:
                metrics = response.json()
                # 세션 상태에 메트릭 저장
                st.session_state.metrics = metrics
                # 상태 변경 감지를 위한 카운터 증가
                st.session_state.metrics_update_counter += 1
        except Exception as e:
            pass  # 오류 무시
        time.sleep(2)  # 2초마다 메트릭 조회

# 초기화
if 'logs' not in st.session_state:
    st.session_state.logs = []
    st.session_state.log_update_counter = 0
    st.session_state.metrics = {
        "deadlines_exceeded": 0,
        "circuit_breaker_trips": 0,
        "backpressure_rejections": 0,
        "total_requests": 0,
        "successful_requests": 0,
        "failed_requests": 0,
        "avg_response_time": 0
    }
    st.session_state.metrics_update_counter = 0
    # 로그 조회 스레드 시작
    log_thread = threading.Thread(target=fetch_logs, daemon=True)
    log_thread.start()
    # 메트릭 조회 스레드 시작
    metrics_thread = threading.Thread(target=fetch_metrics, daemon=True)
    metrics_thread.start()

st.title("gRPC 에러 처리 테스트")

# 탭 생성
tab1, tab2, tab3 = st.tabs(["테스트 실행", "모니터링", "로그 및 메트릭"])

# 탭 1: 테스트 실행
with tab1:
    # 사이드바에 테스트 컨트롤 배치
    st.header("테스트 도구")

    # 데드라인 테스트
    st.subheader("데드라인 테스트")
    st.write("데드라인 패턴은 요청에 타임아웃을 설정하여 장시간 실행되는 요청이 서버 자원을 독점하는 것을 방지합니다.")
    deadline = st.slider("타임아웃 (초)", 1, 10, 5)
    if st.button("데드라인 테스트 실행"):
        log_to_ui(f"데드라인 테스트 시작 (타임아웃: {deadline}초)")
        try:
            response = requests.get(f"{BFF_URL}/test/deadline?timeout={deadline}")
            if response.status_code == 200:
                result = response.json()
                log_to_ui(f"테스트 결과: {result['status']}")
                log_to_ui(f"상세 내용: {result['message']}")
            else:
                log_to_ui(f"에러 발생: {response.status_code} - {response.text}")
        except Exception as e:
            log_to_ui(f"요청 중 에러 발생: {str(e)}")

    # 서킷브레이커 테스트
    st.subheader("서킷브레이커 테스트")
    st.write("서킷브레이커 패턴은 연속된 오류가 발생할 때 잠시 요청을 차단하여 문제가 있는 서비스로의 접근을 막습니다.")
    error_rate = st.slider("에러 발생률 (%)", 0, 100, 50)
    if st.button("서킷브레이커 테스트 실행"):
        log_to_ui(f"서킷브레이커 테스트 시작 (에러율: {error_rate}%)")
        try:
            response = requests.get(f"{BFF_URL}/test/circuit-breaker?error_rate={error_rate}")
            if response.status_code == 200:
                result = response.json()
                log_to_ui(f"테스트 결과: {result['status']}")
                log_to_ui(f"상세 내용: {result['message']}")
            else:
                log_to_ui(f"에러 발생: {response.status_code} - {response.text}")
        except Exception as e:
            log_to_ui(f"요청 중 에러 발생: {str(e)}")

    # 백프레셔 테스트
    st.subheader("백프레셔 테스트")
    st.write("백프레셔 패턴은 서버가 처리할 수 있는 동시 요청 수를 제한하여 과부하를 방지합니다.")
    request_count = st.slider("동시 요청 수", 1, 100, 20)
    if st.button("백프레셔 테스트 실행"):
        log_to_ui(f"백프레셔 테스트 시작 (동시 요청: {request_count}개)")
        try:
            response = requests.get(f"{BFF_URL}/test/backpressure?requests={request_count}")
            if response.status_code == 200:
                result = response.json()
                log_to_ui(f"테스트 결과: {result['status']}")
                log_to_ui(f"상세 내용: {result['message']}")
                if 'success_count' in result:
                    log_to_ui(f"성공: {result['success_count']}, 실패: {result['failed_count']}")
            else:
                log_to_ui(f"에러 발생: {response.status_code} - {response.text}")
        except Exception as e:
            log_to_ui(f"요청 중 에러 발생: {str(e)}")

# 탭 2: 모니터링
with tab2:
    st.header("서비스 모니터링")

    # 상태 확인 섹션
    st.subheader("서비스 상태")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.write("BFF 상태")
        if st.button("BFF 상태 확인", key="check_bff"):
            try:
                response = requests.get(f"{BFF_URL}/health")
                if response.status_code == 200:
                    st.success("정상")
                else:
                    st.error("오류")
            except:
                st.error("연결 실패")

    with col2:
        st.write("백엔드 상태")
        if st.button("백엔드 상태 확인", key="check_backend"):
            try:
                response = requests.get(f"{BFF_URL}/backend/health")
                if response.status_code == 200:
                    st.success("정상")
                else:
                    st.error("오류")
            except:
                st.error("연결 실패")

    with col3:
        st.write("DB 상태")
        if st.button("DB 상태 확인", key="check_db"):
            try:
                response = requests.get(f"{BFF_URL}/db/health")
                if response.status_code == 200:
                    st.success("정상")
                else:
                    st.error("오류")
            except:
                st.error("연결 실패")

    # 초기화 버튼 섹션
    st.subheader("시스템 초기화")
    col1, col2 = st.columns(2)

    with col1:
        st.write("서킷브레이커 초기화")
        if st.button("서킷브레이커 초기화", key="reset_circuit"):
            try:
                response = requests.post(f"{BFF_URL}/circuit-breaker/reset")
                if response.status_code == 200:
                    st.success("초기화 성공")
                    log_to_ui("서킷브레이커 초기화 완료")
                else:
                    st.error(f"초기화 실패: {response.text}")
            except Exception as e:
                st.error(f"오류 발생: {str(e)}")


                with col2:
        st.write("백엔드 에러율 초기화")
        if st.button("백엔드 초기화", key="reset_backend"):
            try:
                response = requests.post(f"{BFF_URL}/backend/reset")
                if response.status_code == 200:
                    st.success("초기화 성공")
                    log_to_ui("백엔드 에러율 초기화 완료")
                else:
                    st.error(f"초기화 실패: {response.text}")
            except Exception as e:
                st.error(f"오류 발생: {str(e)}")

    # 서킷브레이커 상태 확인
    st.subheader("서킷브레이커 상태")
    if st.button("상태 확인", key="check_circuit"):
        try:
            response = requests.get(f"{BFF_URL}/circuit-breaker/status")
            if response.status_code == 200:
                result = response.json()
                state_color = "🔴" if result["state"] == "OPEN" else "🟢"
                st.write(f"상태: {state_color} {result['state']}")
                st.write(f"실패 카운트: {result.get('failure_count', 'N/A')}")
                st.write(f"리셋 타임아웃: {result.get('reset_timeout', 'N/A')}초")
            else:
                st.error(f"상태 확인 실패: {response.text}")
        except Exception as e:
            st.error(f"오류 발생: {str(e)}")

# 탭 3: 로그 및 메트릭
with tab3:
    # 메트릭 시각화
    st.header("시스템 메트릭")
    
    # 세션 상태 업데이트 감지를 위한 의존성
    _ = st.session_state.metrics_update_counter
    
    # 메트릭 데이터 표시
    metrics = st.session_state.metrics
    
    # 에러 유형별 카운트
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("데드라인 초과", metrics["deadlines_exceeded"])
    
    with col2:
        st.metric("서킷브레이커 개방", metrics["circuit_breaker_trips"])
    
    with col3:
        st.metric("백프레셔 거부", metrics["backpressure_rejections"])
    
    # 요청 성공/실패율
    st.subheader("요청 처리 통계")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("총 요청 수", metrics["total_requests"])
    
    with col2:
        st.metric("성공 요청", metrics["successful_requests"])
    
    with col3:
        st.metric("실패 요청", metrics["failed_requests"])
    
    # 차트로 시각화 (파이 차트)
    if metrics["total_requests"] > 0:
        success_rate = (metrics["successful_requests"] / metrics["total_requests"]) * 100
        failure_rate = (metrics["failed_requests"] / metrics["total_requests"]) * 100
        
        # 파이 차트 데이터
        fig, ax = plt.subplots()
        ax.pie([success_rate, failure_rate], 
               labels=['성공', '실패'],
               colors=['#4CAF50', '#F44336'],
               autopct='%1.1f%%',
               startangle=90)
        ax.axis('equal')  # 원형 파이 차트
        st.pyplot(fig)
    
    # 응답 시간
    st.subheader("응답 시간")
    st.metric("평균 응답 시간", f"{metrics['avg_response_time']:.3f}초")
    
    # 에러 유형별 비율 (바 차트)
    if sum([metrics["deadlines_exceeded"], metrics["circuit_breaker_trips"], metrics["backpressure_rejections"]]) > 0:
        st.subheader("에러 유형 분석")
        error_data = {
            '유형': ['데드라인 초과', '서킷브레이커 개방', '백프레셔 거부'],
            '횟수': [metrics["deadlines_exceeded"], metrics["circuit_breaker_trips"], metrics["backpressure_rejections"]]
        }
        error_df = pd.DataFrame(error_data)
        st.bar_chart(error_df.set_index('유형'))
    
    # 로그 표시 영역
    st.header("실행 로그")
    if st.button("로그 초기화", key="clear_logs"):
        st.session_state.logs = []
    
    # 로그 검색 필터
    log_filter = st.text_input("로그 검색 (키워드 입력)", "")
    
    # 로그 레벨 필터
    level_options = ["모든 레벨", "INFO", "ERROR", "WARNING"]
    log_level = st.selectbox("로그 레벨 필터", level_options)
    
    # 로그 표시
    log_container = st.container()
    # st.session_state.log_update_counter에 의존하여 UI 갱신
    _ = st.session_state.log_update_counter
    
    with log_container:
        filtered_logs = st.session_state.logs
        
        # 검색어 필터링
        if log_filter:
            filtered_logs = [log for log in filtered_logs if log_filter.lower() in json.dumps(log).lower()]
        
        # 레벨 필터링
        if log_level != "모든 레벨":
            filtered_logs = [log for log in filtered_logs if log.get("level", "") == log_level]
        
        # 로그 표시
        for log in filtered_logs:
            if 'level' in log:
                # 레벨별 색상 설정
                level_color = {
                    "INFO": "blue",
                    "ERROR": "red",
                    "WARNING": "orange"
                }.get(log['level'], "black")
                
                # BFF 로그 형식
                st.markdown(f"**[{log['timestamp']}] [<span style='color:{level_color}'>{log['level']}</span>] [{log['service']}]** {log['message']}", unsafe_allow_html=True)
            else:
                # 프론트엔드 로그 형식
                st.markdown(f"**[{log['timestamp']}]** {log['message']}")

# 사용자 목록 표시
st.header("사용자 목록")
if st.button("사용자 목록 조회"):
    try:
        response = requests.get(f"{BFF_URL}/users")
        if response.status_code == 200:
            users = response.json()
            for user in users:
                st.write(f"ID: {user['user_id']} - 이름: {user['name']} - 이메일: {user['email']}")
        else:
            st.error(f"조회 실패: {response.status_code}")
    except Exception as e:
        st.error(f"오류 발생: {str(e)}")