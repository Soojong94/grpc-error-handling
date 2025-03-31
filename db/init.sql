CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 초기 데이터 삽입
INSERT INTO users (name, email) VALUES
    ('홍길동', 'hong@example.com'),
    ('김철수', 'kim@example.com'),
    ('이영희', 'lee@example.com'),
    ('박지성', 'park@example.com'),
    ('최민수', 'choi@example.com')
ON CONFLICT DO NOTHING;