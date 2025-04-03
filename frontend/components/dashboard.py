import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import time
from datetime import datetime
import sys
import os
import concurrent.futures

# 상위 디렉토리를 경로에 추가하여 모듈 import 가능하게 설정
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.api import ApiClient
from utils.charts import create_response_time_chart, create_request_counts_chart, create_error_distribution_chart

def render_dashboard():
    """대시보드 렌더링"""
    st.header("시스템 상태 대시보드")
    
    # 현재 시간 표시
    st.write(f"최종 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # API 클라이언트 생성
    api = ApiClient()
    
    # 시스템 상태 확인 - 병렬 요청 처리
    with st.spinner("데이터 로딩 중..."):
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # 병렬로 API 요청 실행
            health_future = executor.submit(api.get_health)
            metrics_future = executor.submit(api.get_metrics)
            pattern_status_future = executor.submit(api.get_pattern_status)
            cb_status_future = executor.submit(api.get_circuit_breaker_status)
            events_future = executor.submit(api.get_events, 5)
            
            # 결과 수집
            health_status = health_future.result()
            metrics = metrics_future.result()
            pattern_status = pattern_status_future.result()
            cb_status = cb_status_future.result()
            events = events_future.result()
    
    # 헬스 상태 표시
    if "backend" in health_status:
        backend_available = health_status["backend"]["available"]
        backend_status = "정상" if backend_available else "오류"
        backend_color = "green" if backend_available else "red"
        
        st.markdown(f"""
        <div style="padding: 10px; border-radius: 5px; background-color: {'#E8F5E9' if backend_available else '#FFEBEE'}; margin-bottom: 20px;">
            <span style="font-weight: bold; color: {backend_color};">백엔드 상태:</span> {backend_status}
            {f"<br><span style='color: #D32F2F; font-size: 0.9em;'>{health_status['backend']['last_error']}</span>" if not backend_available and health_status['backend']['last_error'] else ""}
        </div>
        """, unsafe_allow_html=True)
    
    # 기본 메트릭 표시
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.subheader("요청 통계")
        total = metrics.get("total_requests", 0)
        success = metrics.get("successful_requests", 0)
        failed = metrics.get("failed_requests", 0)
        success_rate = (success / total * 100) if total > 0 else 0
        
        st.metric("총 요청 수", f"{total:,}")
        st.metric("성공률", f"{success_rate:.1f}%")
        st.metric("평균 응답 시간", f"{metrics.get('avg_response_time', 0):.2f}초")
    
    with col2:
        st.subheader("에러 통계")
        st.metric("데드라인 초과", f"{metrics.get('deadlines_exceeded', 0):,}")
        st.metric("서킷 브레이커 개방", f"{metrics.get('circuit_breaker_trips', 0):,}")
        st.metric("백프레셔 거부", f"{metrics.get('backpressure_rejections', 0):,}")
    
    with col3:
        # 서킷 브레이커 상태
        st.subheader("서킷 브레이커 상태")
        
        if "error" not in cb_status:
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
            
            # 수동 초기화 버튼
            if state != "CLOSED":
                if st.button("서킷 브레이커 초기화", key="reset_cb_dashboard"):
                    result = api.reset_circuit_breaker()
                    if result and "error" not in result:
                        st.success("서킷 브레이커가 초기화되었습니다.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"초기화 실패: {result.get('error', '알 수 없는 오류')}")
        else:
            st.error(f"서킷 브레이커 상태 조회 실패: {cb_status.get('error', '알 수 없는 오류')}")
    
    # 활성화된 패턴 상태 표시
    st.subheader("에러 처리 패턴 상태")
    
    if "error" not in pattern_status:
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
    else:
        st.error(f"패턴 상태 조회 실패: {pattern_status.get('error')}")
    
    # 시스템 초기화 버튼
    if st.button("시스템 전체 초기화", key="reset_system_dashboard"):
        result = api.reset_system()
        if result and "error" not in result:
            st.success("시스템이 초기화되었습니다.")
            # 캐시도 함께 초기화
            api.clear_cache()
            time.sleep(1)
            st.rerun()
        else:
            st.error(f"초기화 실패: {result.get('error', '알 수 없는 오류')}")
    
    # 메트릭 차트 표시
    st.subheader("메트릭 추이")
    
    # 응답 시간 트렌드 차트
    response_time_chart = create_response_time_chart(metrics)
    if response_time_chart:
        st.pyplot(response_time_chart)
    else:
        st.info("아직 충분한 응답 시간 데이터가 없습니다.")
    
    # 요청 수 트렌드 차트
    request_counts_chart = create_request_counts_chart(metrics)
    if request_counts_chart:
        st.pyplot(request_counts_chart)
    else:
        st.info("아직 충분한 요청 데이터가 없습니다.")
    
    # 에러 분포 차트
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("에러 유형 분포")
        error_chart = create_error_distribution_chart(metrics)
        if error_chart:
            st.pyplot(error_chart)
        else:
            st.info("아직 에러 데이터가 없습니다.")
    
    with col2:
        # 이벤트 타임라인
        st.subheader("최근 이벤트")
        
        if events and "error" not in events and len(events) > 0:
            for event in events:
                event_type = event.get("type", "unknown")
                timestamp = event.get("timestamp", "")
                description = event.get("description", "")
                
                # 이벤트 유형별 아이콘 정의
                icons = {
                    "system": "🖥️",
                    "circuit_breaker": "🔌",
                    "deadline": "⏱️",
                    "backpressure": "🚧",
                    "error": "❌",
                    "test": "🧪",
                    "settings": "⚙️",
                    "pattern_change": "🔄"
                }
                
                icon = icons.get(event_type, "ℹ️")
                
                st.markdown(f"""
                <div style="margin-bottom: 10px; border-left: 3px solid #2196F3; padding-left: 10px;">
                    <span style="color: gray; font-size: 0.8em;">{timestamp}</span><br>
                    <span>{icon} <b>{event_type.upper()}</b>: {description}</span>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("이벤트 데이터가 없습니다.")