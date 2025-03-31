FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# proto 파일 컴파일
RUN mkdir -p /app/proto
COPY ../proto/service.proto /app/proto/
RUN python -m grpc_tools.protoc -I/app/proto --python_out=/app --grpc_python_out=/app /app/proto/service.proto

EXPOSE 50051

CMD ["python", "server.py"]