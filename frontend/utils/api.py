import requests
import logging
import time

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [FRONTEND-API] %(message)s',
)
logger = logging.getLogger(__name__)

# 기본 API URL
BFF_URL = "http://localhost:8000"

class ApiClient:
    """BFF API 호출을 담당하는 클라이언트"""
    
    def __init__(self, base_url=BFF_URL):
        self.base_url = base_url
        self.last_error = None
    
    def make_request(self, method, endpoint, params=None, json_data=None, max_retries=3, retry_delay=1):
        """API 요청 수행"""
        url = f"{self.base_url}{endpoint}"
        self.last_error = None
        
        retries = 0
        while retries < max_retries:
            try:
                logger.info(f"API 요청: {method} {url}")
                if method.lower() == "get":
                    response = requests.get(url, params=params, timeout=10)
                elif method.lower() == "post":
                    response = requests.post(url, json=json_data, timeout=10)
                else:
                    logger.error(f"지원되지 않는 HTTP 메서드: {method}")
                    self.last_error = f"지원되지 않는 HTTP 메서드: {method}"
                    return None
                
                # 응답 상태 코드 확인
                if response.status_code == 200:
                    logger.info(f"API 요청 성공: {url}")
                    return response.json() if response.content else {}
                else:
                    logger.warning(f"API 요청 실패 (상태 코드: {response.status_code}): {url}")
                    self.last_error = f"요청 실패 (상태 코드: {response.status_code})"
                    
                    # 서버 내부 오류면 재시도
                    if 500 <= response.status_code < 600:
                        retries += 1
                        if retries < max_retries:
                            logger.info(f"{retry_delay}초 후 재시도 ({retries}/{max_retries})...")
                            time.sleep(retry_delay)
                            continue
                    
                    # 클라이언트 오류는 재시도 없이 결과 반환
                    return response.json() if response.content else {"error": self.last_error}
                    
            except requests.exceptions.Timeout:
                logger.warning(f"요청 타임아웃: {url}")
                self.last_error = "요청 타임아웃"
                retries += 1
                if retries < max_retries:
                    logger.info(f"{retry_delay}초 후 재시도 ({retries}/{max_retries})...")
                    time.sleep(retry_delay)
                else:
                    return {"error": self.last_error}
                    
            except requests.exceptions.ConnectionError:
                logger.error(f"연결 오류: {url}")
                self.last_error = "서버에 연결할 수 없습니다"
                retries += 1
                if retries < max_retries:
                    logger.info(f"{retry_delay}초 후 재시도 ({retries}/{max_retries})...")
                    time.sleep(retry_delay)
                else:
                    return {"error": self.last_error}
                    
            except Exception as e:
                logger.error(f"API 요청 중 예상치 못한 오류: {str(e)}")
                self.last_error = f"오류: {str(e)}"
                return {"error": self.last_error}
        
        return {"error": self.last_error or "요청 실패"}
    
    def get_health(self):
        """서비스 상태 확인"""
        return self.make_request("get", "/health")
    
    def get_logs(self, limit=100, pattern=None, level=None):
        """로그 조회"""
        params = {"limit": limit}
        if pattern:
            params["pattern"] = pattern
        if level:
            params["level"] = level
        return self.make_request("get", "/logs", params=params)
    
    def get_events(self, limit=50):
        """이벤트 조회"""
        return self.make_request("get", "/events", params={"limit": limit})
    
    def get_metrics(self):
        """메트릭 조회"""
        return self.make_request("get", "/metrics")
    
    def get_pattern_status(self):
        """에러 처리 패턴 상태 조회"""
        return self.make_request("get", "/patterns/status")
    
    def set_pattern_status(self, pattern, status):
        """에러 처리 패턴 상태 설정"""
        return self.make_request("post", f"/patterns/{pattern}", json_data={"status": status})
    
    def get_circuit_breaker_status(self):
        """서킷 브레이커 상태 조회"""
        return self.make_request("get", "/circuit-breaker/status")
    
    def reset_circuit_breaker(self):
        """서킷 브레이커 초기화"""
        return self.make_request("post", "/circuit-breaker/reset")
    
    def set_error_rate(self, error_rate):
        """백엔드 에러율 설정"""
        return self.make_request("post", "/backend/error-rate", json_data={"error_rate": error_rate})
    
    def reset_backpressure(self):
        """백프레셔 초기화"""
        return self.make_request("post", "/backend/reset-backpressure")
    
    def reset_system(self):
        """전체 시스템 초기화"""
        return self.make_request("post", "/system/reset")
    
    def run_slow_query_test(self, delay, requests, timeout):
        """슬로우 쿼리 테스트 실행"""
        params = {
            "delay": delay,
            "requests": requests,
            "timeout": timeout
        }
        return self.make_request("get", "/test/slow-query", params=params)
    
    def run_pattern_comparison_test(self, delay=5, requests_per_test=10, timeout=3):
        """패턴 비교 테스트 실행"""
        json_data = {
            "delay": delay,
            "requests_per_test": requests_per_test,
            "timeout": timeout
        }
        return self.make_request("post", "/test/comparison", json_data=json_data)