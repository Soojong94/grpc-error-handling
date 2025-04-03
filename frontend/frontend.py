import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import threading
import time
from datetime import datetime

# 컴포넌트 모듈 import
from components.dashboard import render_dashboard
from components.error_patterns import render_error_patterns
from components.tests import render_tests
from components.logs import render_logs

# 한글 폰트 설정
plt.rcParams['font.family'] = 'Malgun Gothic'  # Windows 기본 한글 폰트
plt.rcParams['axes.unicode_minus'] = False  # 마이너스 기호 깨짐 방지

# 페이지 설정
st.set_page_config(
    page_title="gRPC 에러 처리 패턴 모니터링",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 세션 상태 초기화
if 'last_update' not in st.session_state:
    st.session_state.last_update = time.time()

# 앱 제목
st.title("gRPC 에러 처리 패턴 모니터링")
st.write("""
이 애플리케이션은 gRPC 기반 시스템에서 발생할 수 있는 슬로우 쿼리 문제를 다양한 에러 처리 패턴으로 
해결하는 방법을 테스트하고 모니터링합니다. 데드라인, 서킷 브레이커, 백프레셔 패턴의 효과를 비교해보세요.
""")

# 탭 생성
tab1, tab2, tab3, tab4 = st.tabs(["대시보드", "에러 처리 패턴", "테스트", "로그 및 이벤트"])

# 탭 1: 대시보드
with tab1:
    render_dashboard()

# 탭 2: 에러 처리 패턴
with tab2:
    render_error_patterns()

# 탭 3: 테스트
with tab3:
    render_tests()

# 탭 4: 로그 확인
with tab4:
    render_logs()

# 자동 새로고침 비활성화 (불필요한 API 호출 방지)
# current_time = time.time()
# if current_time - st.session_state.last_update > 20:  # 10초마다 새로고침
#     st.session_state.last_update = current_time
#     st.rerun()

# 대신 수동 새로고침 버튼 추가
if st.sidebar.button("수동 새로고침"):
    st.session_state.last_update = time.time()
    st.rerun()

# 푸터
st.markdown("""
---
<div style="text-align: center; color: gray; font-size: 0.8em;">
gRPC 에러 처리 패턴 모니터링 시스템 | 현재 시간: {time}
</div>
""".format(time=datetime.now().strftime('%Y-%m-%d %H:%M:%S')), unsafe_allow_html=True)