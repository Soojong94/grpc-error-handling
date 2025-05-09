import logging
import sys
import os  # 추가 필요
from datetime import datetime  # 추가 필요

def setup_logging(service_name):
    """각 서비스의 로깅 설정"""
    
    # 로그 디렉토리 생성
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    # 로거 설정
    logger = logging.getLogger(service_name)
    logger.setLevel(logging.DEBUG)
    
    # 콘솔 핸들러
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    
    # 파일 핸들러 - 인코딩 설정 추가
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    file_handler = logging.FileHandler(
        os.path.join(log_dir, f"{service_name}_{timestamp}.log"),
        encoding='utf-8'  # 인코딩 설정 추가
    )
    file_handler.setLevel(logging.DEBUG)
    
    # 포맷터
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    )
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)
    
    # 핸들러 추가
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger