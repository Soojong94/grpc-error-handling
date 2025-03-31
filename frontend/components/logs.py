import streamlit as st
import pandas as pd
import sys
import os

# 상위 디렉토리를 경로에 추가하여 모듈 import 가능하게 설정
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.api import ApiClient

def render_logs():
    """로그 페이지 렌더링"""
    st.header("시스템 로그 및 이벤트")
    
    # API 클라이언트 생성
    api = ApiClient()
    
    # 탭 생성
    log_tab, event_tab = st.tabs(["로그", "이벤트"])
    
    # 로그 탭
    with log_tab:
        st.subheader("시스템 로그")
        
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
        
        # 로그 데이터 가져오기
        logs = api.get_logs(limit=200)
        
        if "error" in logs:
            st.error(f"로그 조회 실패: {logs.get('error')}")
        else:
            # 로그 필터링
            filtered_logs = []
            
            for log in logs:
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
                   (pattern == "일반" and not show_deadline and not show_circuit and not show_backpressure):
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
                df = pd.DataFrame(table_data)
                st.dataframe(
                    df,
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
    
    # 이벤트 탭
    with event_tab:
        st.subheader("시스템 이벤트")
        
        # 이벤트 새로고침 버튼
        if st.button("이벤트 새로고침", key="refresh_events"):
            st.rerun()
        
        # 이벤트 유형 필터링
        st.write("이벤트 유형 필터링:")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            show_system = st.checkbox("시스템", value=True)
            show_error = st.checkbox("에러", value=True, key="show_error_events")
        
        with col2:
            show_circuit_breaker = st.checkbox("서킷 브레이커", value=True)
            show_deadline = st.checkbox("데드라인", value=True, key="show_deadline_events")
        
        with col3:
            show_backpressure = st.checkbox("백프레셔", value=True, key="show_backpressure_events")
            show_test = st.checkbox("테스트", value=True)
        
        with col4:
            show_settings = st.checkbox("설정", value=True)
            show_pattern_change = st.checkbox("패턴 변경", value=True)
        
        # 이벤트 데이터 가져오기
        events = api.get_events()
        
        if "error" in events:
            st.error(f"이벤트 조회 실패: {events.get('error')}")
        else:
            # 이벤트 필터링
            filtered_events = []
            
            for event in events:
                event_type = event.get('type', '')
                
                # 유형 필터링
                if (event_type == "system" and show_system) or \
                   (event_type == "circuit_breaker" and show_circuit_breaker) or \
                   (event_type == "deadline" and show_deadline) or \
                   (event_type == "backpressure" and show_backpressure) or \
                   (event_type == "error" and show_error) or \
                   (event_type == "test" and show_test) or \
                   (event_type == "settings" and show_settings) or \
                   (event_type == "pattern_change" and show_pattern_change):
                    filtered_events.append(event)
            
            # 이벤트 타임라인 표시
            if filtered_events:
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
                
                # 최신 이벤트가 위로 오도록 역순 정렬
                filtered_events.reverse()
                
                # 이벤트 타임라인 표시
                for event in filtered_events:
                    event_type = event.get("type", "unknown")
                    timestamp = event.get("timestamp", "")
                    description = event.get("description", "")
                    
                    icon = event_icons.get(event_type, "ℹ️")
                    color = event_colors.get(event_type, "black")
                    
                    st.markdown(f"""
                    <div style="margin-bottom: 15px; border-left: 3px solid {color}; padding-left: 15px; padding-top: 5px; padding-bottom: 5px;">
                        <span style="color: gray; font-size: 0.8em;">{timestamp}</span><br>
                        <span style="font-size: 1.1em;">{icon} <span style="color: {color}; font-weight: bold;">{event_type.upper()}</span>: {description}</span>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("조건에 맞는 이벤트가 없습니다.")