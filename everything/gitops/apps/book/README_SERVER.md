# Kindle Book Viewer Server

FastAPI 기반 Kindle 도서 뷰어 서버입니다.

## 설치

```bash
pip install -r requirements.txt
```

## 실행

```bash
cd src
python3 server.py
```

서버가 `http://localhost:3200`에서 실행됩니다.

## 엔드포인트

- `GET /` - 모든 도서 목록 페이지
- `GET /book/{book_name}` - 개별 도서 뷰어
- `GET /health` - 헬스 체크

## 디렉토리 구조

```
src/
├── server.py           # FastAPI 서버
├── templates/          # HTML 템플릿
│   └── index.html     # 도서 목록 페이지
└── output/            # 처리된 도서 파일
    └── {책_이름}/
        └── view/
            └── view.html
```

## 사용 방법

1. Kindle 도서를 처리하여 `src/output/{책_이름}/view/view.html` 형식으로 저장
2. 서버 실행: `python3 server.py`
3. 브라우저에서 `http://localhost:3200` 접속
4. 도서 목록에서 원하는 책 클릭하여 뷰어로 이동

## 프로덕션 배포

### Uvicorn으로 직접 실행

```bash
cd src
uvicorn server:app --host 0.0.0.0 --port 3200
```

### 백그라운드 실행

```bash
nohup uvicorn server:app --host 0.0.0.0 --port 3200 > server.log 2>&1 &
```

### systemd 서비스 (Linux)

`/etc/systemd/system/kindle-viewer.service` 파일 생성:

```ini
[Unit]
Description=Kindle Book Viewer
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/kindle/src
ExecStart=/usr/bin/uvicorn server:app --host 0.0.0.0 --port 3200
Restart=always

[Install]
WantedBy=multi-user.target
```

서비스 시작:

```bash
sudo systemctl daemon-reload
sudo systemctl start kindle-viewer
sudo systemctl enable kindle-viewer
```

## 환경 변수

필요한 경우 `.env` 파일을 생성하여 설정:

```env
PORT=3200
HOST=0.0.0.0
```
