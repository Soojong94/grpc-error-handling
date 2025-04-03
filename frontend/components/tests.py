import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import time
import sys
import os

# 상위 디렉토리를 경로에 추가하여 모듈 import 가능하게 설정
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.api import ApiClient
from utils.charts import create_pattern_comparison_chart, create_error_comparison_chart

def render_tests():
    """테스트 페이지 렌더링"""
    st.header("에러 처리 패턴 테스트")
    
    # API 클라이언트 생성
    api = ApiClient()
    
    # 탭 생성
    test_tab1, test_tab2 = st.tabs(["슬로우 쿼리 테스트", "패턴 비교 테스트"])
    
    # 슬로우 쿼리 테스트 탭
    with test_tab1:
        st.subheader("슬로우 쿼리 테스트")
        st.write("""
        슬로우 쿼리는 실제 환경에서 가장 흔하게 발생하는 문제 중 하나입니다.
        각 에러 처리 패턴이 슬로우 쿼리에 어떻게 대응하는지 확인해보세요.
        """)
        
        # 경고 메시지 추가
        st.warning("⚠️ 테스트 실행 시 고의적으로 지연이 발생합니다. 테스트를 실행하지 않을 때는 시스템이 빠르게 응답합니다.")
        
        col1, col2 = st.columns(2)
        
        with col1:
            query_delay = st.slider("쿼리 지연 시간 (초)", 1, 10, 5)
            concurrent_requests = st.slider("동시 요청 수", 3, 15, 5)  # 기본값을 5로 낮춤
        
        with col2:
            timeout = st.slider("타임아웃 설정 (초, 데드라인 패턴용)", 1, 5, 3)
            
            # 활성화된 패턴 표시
            pattern_status = api.get_pattern_status()
            if "error" not in pattern_status:
                active_patterns = []
                if pattern_status.get("deadline", False):
                    active_patterns.append("데드라인")
                if pattern_status.get("circuit_breaker", False):
                    active_patterns.append("서킷 브레이커")
                if pattern_status.get("backpressure", False):
                    active_patterns.append("백프레셔")
                    
                if active_patterns:
                    st.write(f"활성화된 패턴: {', '.join(active_patterns)}")
                else:
                    st.warning("활성화된 패턴이 없습니다!")
            else:
                st.error(f"패턴 상태 조회 실패: {pattern_status.get('error')}")
        
        # 테스트 실행 버튼
        if st.button("슬로우 쿼리 테스트 실행"):
            with st.spinner("테스트 실행 중... (이 작업은 시간이 걸릴 수 있습니다)"):
                # 테스트 시작 전 캐시 초기화
                api.clear_cache()
                
                result = api.run_slow_query_test(query_delay, concurrent_requests, timeout)
                
                if result and "error" not in result:
                    st.success("테스트 완료!")
                    
                    # 테스트 결과 요약
                    st.subheader("테스트 결과 요약")
                    st.text(result["summary"])
                    
                    # 그래프로 결과 시각화
                    st.subheader("요청 처리 결과")
                    results = result["results"]
                    
                    # 파이 차트 - 요청 결과 분포
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
                        fig1, ax1 = plt.subplots(figsize=(6, 6))
                        ax1.pie(non_zero_sizes, labels=non_zero_labels, colors=non_zero_colors,
                                autopct='%1.1f%%', startangle=90)
                        ax1.axis('equal')
                        st.pyplot(fig1)
                    
                    # 패턴별 효과 분석
                    if "pattern_effects" in result and result["pattern_effects"]:
                        st.subheader("패턴별 효과 분석")
                        for pattern, effect in result["pattern_effects"].items():
                            if pattern in ["deadline", "circuit_breaker", "backpressure"]:
                                effectiveness = float(effect['effectiveness'])
                                st.write(f"**{effect['name']}**: {effect['comment']}")
                                st.progress(effectiveness)
                    
                    # 상세 요청 결과 테이블
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
                    df = pd.DataFrame(table_data)
                    st.dataframe(df, use_container_width=True)
                    
                else:
                    st.error(f"테스트 실패: {result.get('error', '알 수 없는 오류')}")
    
    # 패턴 비교 테스트 탭
    with test_tab2:
        st.subheader("패턴 비교 테스트")
        st.write("""
        다양한 에러 처리 패턴의 효과를 자동으로 비교하고 가장 효율적인 패턴 조합을 찾아보세요.
        이 테스트는 각 패턴 조합에 대해 동일한 조건에서 성능을 측정합니다.
        """)
        
        # 경고 메시지 추가
        st.warning("⚠️ 이 테스트는 모든 패턴 조합을 순차적으로 실행하므로 시간이 오래 걸릴 수 있습니다.")
        
        # 테스트 설정
        col1, col2 = st.columns(2)
        
        with col1:
            comparison_delay = st.slider("쿼리 지연 시간 (초)", 1, 10, 3, key="comparison_delay")  # 기본값을 3으로 낮춤
            requests_per_test = st.slider("각 패턴당 요청 수", 3, 15, 5, key="requests_per_test")  # 기본값을 5로 낮춤
        
        with col2:
            comparison_timeout = st.slider("타임아웃 설정 (초)", 1, 5, 2, key="comparison_timeout")  # 기본값을 2로 낮춤
            st.info("각 패턴 조합이 순차적으로 테스트됩니다. 총 5개의 패턴 조합이 테스트됩니다.")
        
        # 테스트 실행 버튼
        if st.button("패턴 비교 테스트 실행"):
            with st.spinner("패턴 비교 테스트 실행 중... (이 작업은 시간이 오래 걸릴 수 있습니다)"):
                # 테스트 시작 전 캐시 초기화
                api.clear_cache()
                
                result = api.run_pattern_comparison_test(
                    comparison_delay, 
                    requests_per_test, 
                    comparison_timeout
                )
                
                if result and "error" not in result:
                    st.success("패턴 비교 테스트 완료!")
                    
                    # 최적의 패턴 추천 표시
                    best_pattern = result.get("best_pattern", {})
                    if best_pattern:
                        st.subheader("🏆 추천 패턴")
                        
                        pattern_name = best_pattern.get("name", "")
                        score = best_pattern.get("score", 0) * 100  # 점수를 퍼센트로 변환
                        reason = best_pattern.get("reason", "")
                        
                        st.markdown(f"""
                        <div style="padding: 20px; background-color: #E3F2FD; border-radius: 10px; margin-bottom: 20px;">
                            <h3 style="margin-top: 0;">추천 패턴: {pattern_name}</h3>
                            <p><b>점수:</b> {score:.1f}%</p>
                            <p><b>이유:</b> {reason}</p>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    # 패턴별 성공률 및 응답 시간 비교 차트
                    st.subheader("패턴 성능 비교")
                    comparison_chart = create_pattern_comparison_chart(result.get("comparison_results", {}))
                    if comparison_chart:
                        st.pyplot(comparison_chart)
                    
                    # 패턴별 에러 유형 비교 차트
                    st.subheader("패턴별 에러 유형 비교")
                    error_chart = create_error_comparison_chart(result.get("comparison_results", {}))
                    if error_chart:
                        st.pyplot(error_chart)
                    
                    # 상세 결과 표 (접을 수 있게)
                    with st.expander("상세 결과 데이터"):
                        st.json(result.get("comparison_results", {}))
                        
                else:
                    st.error(f"패턴 비교 테스트 실패: {result.get('error', '알 수 없는 오류')}")
        
        # 결과 후 추천 사항
        st.info("""
        💡 **팁**: 패턴 비교 테스트 후 추천된 패턴 조합을 '에러 처리 패턴 설정' 탭에서 설정해 보세요.
        그런 다음 슬로우 쿼리 테스트를 실행하여 개선 효과를 확인할 수 있습니다.
        """)