import time
import threading
import json
from functools import wraps

# 성능 측정을 위한 전역 변수
metrics = {
    "deadlines_exceeded": 0,
    "circuit_breaker_trips": 0,
    "backpressure_rejections": 0,
    "total_requests": 0,
    "successful_requests": 0,
    "failed_requests": 0,
    "avg_response_time": 0,
    "response_times": []
}

# 메트릭 락
metrics_lock = threading.Lock()

def track_metrics(func):
    """요청 처리 메트릭을 추적하는 데코레이터"""
    @wraps(func)
    def wrapper(*args, **kwargs):
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
            raise
    return wrapper

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
            "avg_response_time": metrics["avg_response_time"]
        }

# 에러 처리 패턴 상태 변수
pattern_status = {
    "deadline": True,
    "circuit_breaker": True,
    "backpressure": True
}

# 상태 변경 이벤트 저장 리스트
events = []
events_lock = threading.Lock()
MAX_EVENTS = 50

def add_event(event_type, description, status=None):
    """시스템 이벤트 추가"""
    event = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "type": event_type,
        "description": description,
        "status": status
    }
    
    with events_lock:
        events.append(event)
        if len(events) > MAX_EVENTS:
            events.pop(0)
    
    return event

def get_events(limit=MAX_EVENTS):
    """저장된 이벤트 조회"""
    with events_lock:
        return events[-limit:]

def update_pattern_status(pattern, status):
    """패턴 상태 업데이트 및 이벤트 기록"""
    if pattern in pattern_status:
        old_status = pattern_status[pattern]
        pattern_status[pattern] = status
        
        # 상태 변경 시 이벤트 기록
        if old_status != status:
            status_text = "활성화" if status else "비활성화"
            add_event("pattern_change", f"{pattern} 패턴 {status_text}", status)
        
        return True
    return False

def get_pattern_status():
    """현재 패턴 상태 반환"""
    return pattern_status.copy()