import time
import threading
import json
from functools import wraps
from datetime import datetime

# 성능 측정을 위한 전역 변수
metrics = {
    "deadlines_exceeded": 0,
    "circuit_breaker_trips": 0,
    "backpressure_rejections": 0,
    "total_requests": 0,
    "successful_requests": 0,
    "failed_requests": 0,
    "avg_response_time": 0,
    "response_times": [],
    "history": {
        "timestamps": [],
        "success_counts": [],
        "failed_counts": [],
        "response_times": []
    }
}

# 메트릭 락
metrics_lock = threading.Lock()

# 히스토리 기록 간격 (초)
HISTORY_INTERVAL = 10
last_history_update = time.time()

def track_metrics(func):
    """요청 처리 메트릭을 추적하는 데코레이터"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        global last_history_update
        
        with metrics_lock:
            metrics["total_requests"] += 1
        
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            
            with metrics_lock:
                metrics["successful_requests"] += 1
                elapsed = time.time() - start_time
                metrics["response_times"].append(elapsed)
                # 최대 100개 응답 시간만 유지
                if len(metrics["response_times"]) > 100:
                    metrics["response_times"] = metrics["response_times"][-100:]
                if len(metrics["response_times"]) > 0:
                    metrics["avg_response_time"] = sum(metrics["response_times"]) / len(metrics["response_times"])
                
                # 히스토리 기록
                current_time = time.time()
                if current_time - last_history_update > HISTORY_INTERVAL:
                    update_metrics_history()
                    last_history_update = current_time
            
            return result
        except Exception as e:
            with metrics_lock:
                metrics["failed_requests"] += 1
                if "deadline exceeded" in str(e).lower():
                    metrics["deadlines_exceeded"] += 1
                if "circuit breaker" in str(e).lower():
                    metrics["circuit_breaker_trips"] += 1
                if "resource_exhausted" in str(e).lower() or "백프레셔" in str(e):
                    metrics["backpressure_rejections"] += 1
                
                # 히스토리 기록
                current_time = time.time()
                if current_time - last_history_update > HISTORY_INTERVAL:
                    update_metrics_history()
                    last_history_update = current_time
            raise
    return wrapper

def update_metrics_history():
    """메트릭 히스토리 업데이트"""
    with metrics_lock:
        current_time = datetime.now().strftime('%H:%M:%S')
        metrics["history"]["timestamps"].append(current_time)
        metrics["history"]["success_counts"].append(metrics["successful_requests"])
        metrics["history"]["failed_counts"].append(metrics["failed_requests"])
        metrics["history"]["response_times"].append(metrics["avg_response_time"])
        
        # 최대 30개 포인트만 유지 (5분 동안의 데이터)
        if len(metrics["history"]["timestamps"]) > 30:
            metrics["history"]["timestamps"] = metrics["history"]["timestamps"][-30:]
            metrics["history"]["success_counts"] = metrics["history"]["success_counts"][-30:]
            metrics["history"]["failed_counts"] = metrics["history"]["failed_counts"][-30:]
            metrics["history"]["response_times"] = metrics["history"]["response_times"][-30:]

def get_metrics():
    """현재 메트릭 정보 반환"""
    with metrics_lock:
        return {
            "deadlines_exceeded": metrics["deadlines_exceeded"],
            "circuit_breaker_trips": metrics["circuit_breaker_trips"],
            "backpressure_rejections": metrics["backpressure_rejections"],
            "total_requests": metrics["total_requests"],
            "successful_requests": metrics["successful_requests"],
            "failed_requests": metrics["failed_requests"],
            "avg_response_time": metrics["avg_response_time"],
            "history": metrics["history"]
        }

def reset_metrics():
    """메트릭 초기화"""
    with metrics_lock:
        # 히스토리는 유지하고 카운터만 초기화
        history = metrics["history"]
        metrics.update({
            "deadlines_exceeded": 0,
            "circuit_breaker_trips": 0,
            "backpressure_rejections": 0,
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "avg_response_time": 0,
            "response_times": []
        })
        metrics["history"] = history

# 에러 처리 패턴 상태 변수
pattern_status = {
    "deadline": True,
    "circuit_breaker": True,
    "backpressure": True
}

# 패턴 상태 락
pattern_status_lock = threading.Lock()

def update_pattern_status(pattern, status):
    """패턴 상태 업데이트 및 이벤트 기록"""
    with pattern_status_lock:
        if pattern in pattern_status:
            old_status = pattern_status[pattern]
            pattern_status[pattern] = status
            
            # 상태 변경 시 이벤트 기록
            if old_status != status:
                status_text = "활성화" if status else "비활성화"
                from common.logging_config import add_event
                add_event("pattern_change", f"{pattern} 패턴 {status_text}", status)
            
            return True
    return False

def get_pattern_status():
    """현재 패턴 상태 반환"""
    with pattern_status_lock:
        return pattern_status.copy()

# 이벤트 직렬화 함수
def event_serializer(obj):
    """이벤트 객체 직렬화 함수"""
    # Circuit Breaker의 상태 객체 처리
    if 'CircuitOpenState' in str(type(obj)) or 'CircuitClosedState' in str(type(obj)) or 'CircuitHalfOpenState' in str(type(obj)):
        return str(obj)
    # 기타 직렬화 불가능 객체 처리
    return str(obj)