import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

def create_response_time_chart(metrics):
    """응답 시간 트렌드 차트 생성"""
    if not metrics or "history" not in metrics:
        return None
    
    history = metrics["history"]
    if not history["timestamps"] or len(history["timestamps"]) < 2:
        return None
    
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(history["timestamps"], history["response_times"], marker='o', linestyle='-', color='#1f77b4')
    
    ax.set_title('평균 응답 시간 추이')
    ax.set_xlabel('시간')
    ax.set_ylabel('응답 시간 (초)')
    ax.grid(True, linestyle='--', alpha=0.7)
    
    # X축 레이블 회전
    plt.xticks(rotation=45)
    
    # 여백 조정
    plt.tight_layout()
    
    return fig

def create_request_counts_chart(metrics):
    """요청 수 트렌드 차트 생성"""
    if not metrics or "history" not in metrics:
        return None
    
    history = metrics["history"]
    if not history["timestamps"] or len(history["timestamps"]) < 2:
        return None
    
    fig, ax = plt.subplots(figsize=(10, 4))
    
    # 성공 요청 수
    ax.plot(history["timestamps"], history["success_counts"], marker='o', linestyle='-', color='#2ca02c', label='성공')
    
    # 실패 요청 수
    ax.plot(history["timestamps"], history["failed_counts"], marker='x', linestyle='-', color='#d62728', label='실패')
    
    ax.set_title('요청 처리 추이')
    ax.set_xlabel('시간')
    ax.set_ylabel('누적 요청 수')
    ax.grid(True, linestyle='--', alpha=0.7)
    ax.legend()
    
    # X축 레이블 회전
    plt.xticks(rotation=45)
    
    # 여백 조정
    plt.tight_layout()
    
    return fig

def create_error_distribution_chart(metrics):
    """에러 유형별 분포 차트 생성"""
    if not metrics:
        return None
    
    # 기본값을 0으로 설정
    metrics.setdefault('failed_requests', 0)
    metrics.setdefault('deadlines_exceeded', 0)
    metrics.setdefault('circuit_breaker_trips', 0)
    metrics.setdefault('backpressure_rejections', 0)
    
    error_types = {
        "deadlines_exceeded": "데드라인 초과",
        "circuit_breaker_trips": "서킷 브레이커",
        "backpressure_rejections": "백프레셔 거부",
        "failed_requests": "기타 오류"
    }
    
    # 데이터 준비
    labels = []
    values = []
    colors = ['#ff9800', '#f44336', '#2196f3', '#9c27b0']
    
    # 총 실패 수에서 다른 오류들을 제외한 '기타 오류' 계산
    other_errors = metrics["failed_requests"] - (
        metrics["deadlines_exceeded"] + 
        metrics["circuit_breaker_trips"] + 
        metrics["backpressure_rejections"]
    )
    
    error_counts = {
        "deadlines_exceeded": metrics["deadlines_exceeded"],
        "circuit_breaker_trips": metrics["circuit_breaker_trips"],
        "backpressure_rejections": metrics["backpressure_rejections"],
        "failed_requests": max(0, other_errors)  # 음수가 되지 않도록
    }
    
    # 값이 0보다 큰 항목만 포함
    for key, label in error_types.items():
        if error_counts[key] > 0:
            labels.append(label)
            values.append(error_counts[key])
    
    if not values:  # 에러가 없으면 차트 생성 안함
        return None
    
    # 파이 차트 생성
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.pie(values, labels=labels, autopct='%1.1f%%', startangle=90, colors=colors[:len(values)])
    ax.axis('equal')  # 원형 유지
    
    plt.title('에러 유형별 분포')
    
    return fig

def create_pattern_comparison_chart(comparison_results):
    """패턴 비교 차트 생성"""
    if not comparison_results:
        return None
    
    pattern_names = {
        "no_pattern": "패턴 없음",
        "deadline_only": "데드라인",
        "circuit_only": "서킷 브레이커",
        "backpressure_only": "백프레셔",
        "all_patterns": "모든 패턴"
    }
    
    # 성공률 데이터
    patterns = []
    success_rates = []
    response_times = []
    
    for pattern, result in comparison_results.items():
        if pattern in pattern_names:
            patterns.append(pattern_names[pattern])
            success_rates.append(result["success_rate"] * 100)  # 퍼센트로 변환
            response_times.append(result["avg_response_time"])
    
    # 두 개의 서브플롯 생성
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    
    # 성공률 차트
    bars1 = ax1.bar(patterns, success_rates, color='#4CAF50')
    ax1.set_title('패턴별 성공률')
    ax1.set_ylabel('성공률 (%)')
    ax1.set_ylim(0, 100)
    ax1.grid(axis='y', linestyle='--', alpha=0.7)
    
    # 응답 시간 차트
    bars2 = ax2.bar(patterns, response_times, color='#2196F3')
    ax2.set_title('패턴별 평균 응답 시간')
    ax2.set_ylabel('응답 시간 (초)')
    ax2.grid(axis='y', linestyle='--', alpha=0.7)
    
    # 데이터 레이블 추가
    for bar in bars1:
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height + 1,
                f'{height:.1f}%', ha='center', va='bottom')
    
    for bar in bars2:
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                f'{height:.2f}s', ha='center', va='bottom')
    
    # X축 레이블 회전
    plt.setp(ax1.get_xticklabels(), rotation=45, ha='right')
    plt.setp(ax2.get_xticklabels(), rotation=45, ha='right')
    
    plt.tight_layout()
    
    return fig

def create_error_comparison_chart(comparison_results):
    """패턴별 에러 유형 비교 차트"""
    if not comparison_results:
        return None
    
    pattern_names = {
        "no_pattern": "패턴 없음",
        "deadline_only": "데드라인",
        "circuit_only": "서킷 브레이커",
        "backpressure_only": "백프레셔",
        "all_patterns": "모든 패턴"
    }
    
    # 데이터 준비
    patterns = []
    deadline_exceeded = []
    circuit_broken = []
    backpressure_rejected = []
    other_errors = []
    
    for pattern, result in comparison_results.items():
        if pattern in pattern_names:
            patterns.append(pattern_names[pattern])
            deadline_exceeded.append(result["deadline_exceeded"])
            circuit_broken.append(result["circuit_broken"])
            backpressure_rejected.append(result["backpressure_rejected"])
            other_errors.append(result["other_errors"])
    
    # 그래프 생성
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # 막대 너비
    width = 0.2
    
    # 각 유형별 막대 위치 계산
    x = np.arange(len(patterns))
    
    # 각 유형별 막대 그래프
    ax.bar(x - width*1.5, deadline_exceeded, width, label='데드라인 초과', color='#FF9800')
    ax.bar(x - width/2, circuit_broken, width, label='서킷 브레이커', color='#F44336')
    ax.bar(x + width/2, backpressure_rejected, width, label='백프레셔 거부', color='#2196F3')
    ax.bar(x + width*1.5, other_errors, width, label='기타 오류', color='#9C27B0')
    
    # 그래프 설정
    ax.set_title('패턴별 에러 유형 비교')
    ax.set_xticks(x)
    ax.set_xticklabels(patterns)
    ax.set_ylabel('오류 수')
    ax.legend()
    ax.grid(axis='y', linestyle='--', alpha=0.7)
    
    # X축 레이블 회전
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    
    plt.tight_layout()
    
    return fig