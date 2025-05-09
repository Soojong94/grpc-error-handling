FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 50057

# 환경변수 기본값 설정
ENV SLOW_QUERY_DELAY=2.0

# 헬스체크 엔드포인트 추가를 위한 패키지 설정
RUN pip install --no-cache-dir grpcio-health-checking

CMD ["python", "db/db_service.py"]