import streamlit as st
import time
import sys
import os

# 상위 디렉토리를 경로에 추가하여 모듈 import 가능하게 설정
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.api import ApiClient

def render_error_patterns():
    """에러 처리 패턴 설정 페이지 렌더링"""
    st.header("에러 처리 패턴 설정")
    st.write("각 패턴을 활성화/비활성화하여 서로 다른 에러 처리 방식을 테스트할 수 있습니다.")
    
    # API 클라이언트 생성
    api = ApiClient()
    
    # 패턴 상태 가져오기
    pattern_status = api.get_pattern_status()
    if "error" in pattern_status:
        st.error(f"패턴 상태 조회 실패: {pattern_status.get('error')}")
        return
    
    # 패턴 설정 UI
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.subheader("데드라인 패턴")
        st.write("""
        데드라인 패턴은 요청에 타임아웃을 설정하여 지정된 시간 내에 응답이 오지 않으면 요청을 종료합니다.
        이를 통해 시스템이 느린 요청에 의해 차단되는 것을 방지합니다.
        """)
        
        deadline_enabled = st.checkbox("데드라인 패턴 활성화", value=pattern_status.get("deadline", True), key="deadline_checkbox")
        if st.button("데드라인 설정 적용"):
            result = api.set_pattern_status("deadline", deadline_enabled)
            if "error" not in result:
                st.success(f"데드라인 패턴이 {'활성화' if deadline_enabled else '비활성화'} 되었습니다.")
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"설정 적용 실패: {result.get('error')}")
    
    with col2:
        st.subheader("서킷 브레이커 패턴")
        st.write("""
        서킷 브레이커 패턴은 연속된 오류가 발생하면 일시적으로 요청을 차단합니다.
        이를 통해 이미 문제가 있는 시스템에 추가 부하가 가는 것을 방지하고, 자가 복구 시간을 제공합니다.
        """)
        
        circuit_enabled = st.checkbox("서킷 브레이커 패턴 활성화", value=pattern_status.get("circuit_breaker", True), key="circuit_checkbox")
        if st.button("서킷 브레이커 설정 적용"):
            result = api.set_pattern_status("circuit_breaker", circuit_enabled)
            if "error" not in result:
                st.success(f"서킷 브레이커 패턴이 {'활성화' if circuit_enabled else '비활성화'} 되었습니다.")
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"설정 적용 실패: {result.get('error')}")
    
    with col3:
        st.subheader("백프레셔 패턴")
        st.write("""
        백프레셔 패턴은 시스템이 처리할 수 있는 요청 수를 제한합니다.
        이를 통해 과도한 동시 요청으로 인한 시스템 과부하를 방지하고, 안정적인 서비스를 유지합니다.
        """)
        
        backpressure_enabled = st.checkbox("백프레셔 패턴 활성화", value=pattern_status.get("backpressure", True), key="backpressure_checkbox")
        if st.button("백프레셔 설정 적용"):
            result = api.set_pattern_status("backpressure", backpressure_enabled)
            if "error" not in result:
                st.success(f"백프레셔 패턴이 {'활성화' if backpressure_enabled else '비활성화'} 되었습니다.")
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"설정 적용 실패: {result.get('error')}")
    
    # 서킷 브레이커 상태 확인
    st.subheader("서킷 브레이커 상태")
    cb_status = api.get_circuit_breaker_status()
    
    if "error" not in cb_status:
        # 상태에 따른 표시
        state = cb_status.get("state", "")
        
        if state == "OPEN":
            st.error(f"서킷 브레이커 상태: {state}")
            st.write(f"실패 카운트: {cb_status.get('failure_count', 0)}")
            
            remaining = cb_status.get('remaining_recovery_time', 0)
            if remaining > 0:
                st.write(f"자동 복구까지 남은 시간: {remaining:.1f}초")
                st.progress(1 - (remaining / cb_status.get('reset_timeout', 10)))
                
            if st.button("서킷 브레이커 수동 초기화"):
                result = api.reset_circuit_breaker()
                if "error" not in result:
                    st.success("서킷 브레이커가 초기화되었습니다.")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(f"서킷 브레이커 초기화 실패: {result.get('error')}")
        else:
            st.success(f"서킷 브레이커 상태: {state}")
            st.write(f"실패 카운트: {cb_status.get('failure_count', 0)}")
    else:
        st.error(f"서킷 브레이커 상태 조회 실패: {cb_status.get('error')}")
    
    # 백프레셔 초기화 옵션
    st.subheader("백프레셔 초기화")
    st.write("백프레셔 메커니즘이 요청을 거부하는 경우, 여기서 세마포어를 수동으로 초기화할 수 있습니다.")
    
    if st.button("백프레셔 초기화"):
        result = api.reset_backpressure()
        if "error" not in result:
            st.success("백프레셔가 초기화되었습니다.")
            time.sleep(1)
            st.rerun()
        else:
            st.error(f"백프레셔 초기화 실패: {result.get('error')}")
    
    # 에러율 설정
    st.subheader("백엔드 에러율 설정")
    st.write("백엔드 서비스의 에러 발생률을 설정합니다. 서킷 브레이커 테스트에 유용합니다.")
    
    error_rate = st.slider("에러 발생률 (%)", 0, 100, 0)
    if st.button("에러율 설정"):
        result = api.set_error_rate(error_rate)
        if "error" not in result:
            st.success(f"에러율이 {error_rate}%로 설정되었습니다.")
            time.sleep(1)
            st.rerun()
        else:
            st.error(f"에러율 설정 실패: {result.get('error')}")
    
    # 시스템 초기화 버튼
    st.subheader("시스템 초기화")
    st.write("모든 설정과 상태를 초기 상태로 되돌립니다.")
    
    if st.button("시스템 전체 초기화", key="reset_system_patterns"):
        result = api.reset_system()
        if "error" not in result:
            st.success("시스템이 초기화되었습니다.")
            time.sleep(1)
            st.rerun()
        else:
            st.error(f"초기화 실패: {result.get('error', '알 수 없는 오류')}")