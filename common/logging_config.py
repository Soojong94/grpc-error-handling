import logging
import json
import time
import threading
from datetime import datetime

# 로그 저장용 전역 변수
logs = []
log_lock = threading.Lock()  # 스레드 안전성을 위한 락

# 이벤트 저장용 전역 변수
events = []
events_lock = threading.Lock()
MAX_EVENTS = 100

# 로그 레벨 상수
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL
}

def setup_logger(service_name, log_level="INFO"):
    """로거 설정 함수"""
    logger = logging.getLogger(service_name)
    logger.setLevel(LOG_LEVELS.get(log_level, logging.INFO))
    
    # 기존 핸들러 제거
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 콘솔 핸들러 추가
    console_handler = logging.StreamHandler()
    console_handler.setLevel(LOG_LEVELS.get(log_level, logging.INFO))
    
    # 로그 포맷 설정 - 패턴 정보 포함
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] [%(service)s] [Thread-%(thread)d] %(message)s'
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 커스텀 핸들러 추가 (로그 저장용)
    logger.addHandler(LogCollectorHandler())
    
    return logger

class LogCollectorHandler(logging.Handler):
    """로그를 메모리에 저장하는 핸들러"""
    def emit(self, record):
        """로그 레코드 처리"""
        # 로그 메시지를 파싱
        try:
            msg = self.format(record)
            
            # 패턴 정보 추출
            pattern = "일반"
            if "데드라인" in msg or "deadline" in msg.lower():
                pattern = "데드라인"
            elif "서킷" in msg or "circuit" in msg.lower():
                pattern = "서킷브레이커"
            elif "백프레셔" in msg or "세마포어" in msg.lower() or "backpressure" in msg.lower():
                pattern = "백프레셔"
            
            # 로그 항목 생성
            log_entry = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created)),
                "level": record.levelname,
                "service": getattr(record, 'service', record.name),
                "thread": record.thread,
                "message": record.getMessage(),
                "pattern": pattern
            }
            
            # 스레드 안전하게 로그 저장
            with log_lock:
                logs.append(log_entry)
                # 로그 크기 제한 (최대 1000개)
                if len(logs) > 1000:
                    logs.pop(0)
                    
            # 에러 로그일 경우 이벤트에도 추가
            if record.levelname in ["ERROR", "WARNING"] and "test" not in record.getMessage().lower():
                add_event("error", f"{pattern}: {record.getMessage()}")
                
        except Exception as e:
            print(f"로그 처리 오류: {e}")

def get_logs(pattern=None, level=None, limit=100):
    """저장된 로그를 조회"""
    with log_lock:
        filtered_logs = logs.copy()
    
    # 패턴으로 필터링
    if pattern:
        filtered_logs = [log for log in filtered_logs if log["pattern"] == pattern]
    
    # 레벨로 필터링
    if level:
        filtered_logs = [log for log in filtered_logs if log["level"] == level]
    
    # 최신 로그 순으로 정렬
    filtered_logs.sort(key=lambda x: x["timestamp"], reverse=True)
    
    # 제한된 수만큼 반환
    return filtered_logs[:limit]

def log_event(logger, level, message, pattern=None, service=None):
    """패턴 정보를 포함한 로그 기록"""
    extra = {'service': service or logger.name}
    
    # 패턴 정보 메시지에 추가
    if pattern:
        message = f"[{pattern}] {message}"
    
    # 로그 레벨에 따라 로깅
    if level == "DEBUG":
        logger.debug(message, extra=extra)
    elif level == "INFO":
        logger.info(message, extra=extra)
    elif level == "WARNING":
        logger.warning(message, extra=extra)
    elif level == "ERROR":
        logger.error(message, extra=extra)
    elif level == "CRITICAL":
        logger.critical(message, extra=extra)

# 이벤트 관련 함수
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