# Kindle Book Processor

Kindle 전자책 또는 PDF 파일을 자동으로 캡처, OCR, 요약 및 번역하는 도구입니다.

## 주요 기능

- **Kindle 화면 자동 캡처**: Kindle 앱의 페이지를 자동으로 캡처
- **OCR 처리**: 캡처한 이미지에서 텍스트 추출
- **PDF 파싱**: PDF 파일을 직접 파싱하여 텍스트 추출
- **LLM 기반 처리**: OpenAI API를 사용하여 요약 및 번역
- **챕터별 그룹화**: 책의 챕터별로 컨텐츠 정리
- **다양한 출력 형식**: Markdown 및 HTML 형식으로 결과 저장

## 요구 사항

- Python 3.10 이상
- Tesseract OCR (pytesseract)
- OpenAI API 키 또는 Anthropic Claude API 키

## 설치

1. 저장소 클론

```bash
git clone <repository-url>
cd kindle
```

2. 필요한 패키지 설치

```bash
pip install -r requirements.txt
```

3. 환경 변수 설정

`.env` 파일을 생성하고 사용할 LLM 제공자의 API 키를 설정합니다.

**OpenAI를 사용하는 경우:**
```bash
OPENAI_API_KEY=your_openai_api_key_here
```

**Claude를 사용하는 경우:**
```bash
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

두 API를 모두 설정할 수도 있으며, 책 설정 파일에서 어떤 것을 사용할지 선택할 수 있습니다.

## 사용법

### 1. 책 설정 파일 생성

`src/config/` 디렉토리에 책 정보를 담은 JSON 파일을 생성합니다.

```json
{
    "type": "kindle",
    "total_page": 652,
    "top_crop": 250,
    "bottom_crop": 250,
    "types": ["long_summary", "short_summary", "translated"],
    "lang": "eng",
    "llm_provider": "openai",
    "llm_model": "gpt-4o-mini",
    "groups": [
        {
            "start_page": 1,
            "end_page": 27,
            "name": "Chapter 1 From Data as a Byproduct to Data as a Product"
        },
        {
            "start_page": 28,
            "end_page": 68,
            "name": "Chapter 2 Data Products"
        }
    ]
}
```

설정 파일 필드 설명:
- `type`: 책 유형 ("kindle" 또는 "pdf")
- `total_page`: 전체 페이지 수
- `top_crop`: 이미지 상단 자르기 픽셀 수
- `bottom_crop`: 이미지 하단 자르기 픽셀 수
- `types`: 생성할 컨텐츠 유형 (long_summary, short_summary, translated)
- `lang`: 원본 언어
- `llm_provider`: LLM 제공자 ("openai" 또는 "claude", 기본값: "openai")
- `llm_model`: 사용할 모델 이름 (선택사항)
  - OpenAI 기본값: "gpt-4o-mini"
  - Claude 기본값: "claude-3-5-sonnet-20241022"
- `groups`: 챕터별 페이지 범위

#### LLM 제공자 선택 예제

**OpenAI 사용 (기본):**
```json
{
    "llm_provider": "openai",
    "llm_model": "gpt-4o-mini"
}
```

**Claude 사용:**
```json
{
    "llm_provider": "claude",
    "llm_model": "claude-3-5-sonnet-20241022"
}
```

다른 모델 옵션:
- OpenAI: `gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo` 등
- Claude: `claude-3-5-sonnet-20241022`, `claude-3-opus-20240229`, `claude-3-sonnet-20240229` 등

### 2. Jupyter Notebook 실행

[src/main.ipynb](src/main.ipynb)를 열어 단계별로 실행합니다.

#### Kindle 전자책 처리

```python
# 1. 책 ID 설정
book_id = "managing-data-as-a-product"

# 2. 클래스 초기화
from functions import get_config, get_output_dir
from kindle import Kindle
from llm import LLMProcessor
from group import Groupper
from view import View

book_type = get_config(book_id, "type")
book_types = get_config(book_id, "types")

kindle = Kindle(book_id=book_id)
groupper = Groupper(book_id=book_id)
llm_processor = LLMProcessor(book_id=book_id, types=book_types, update_types=[])
view = View(book_id=book_id)

# 3. Kindle 화면 캡처 (Kindle 앱이 실행 중이어야 함)
if book_type == "kindle":
    kindle.collect_images()

# 4. 캡처한 이미지 자르기
if book_type == "kindle":
    kindle.crop_images()

# 5. OCR로 텍스트 추출
if book_type == "kindle":
    kindle.ocr_images()
```

#### PDF 파일 처리

```python
# 1. 책 ID 설정
book_id = "your-pdf-book-id"

# 2. PDF 파서 초기화
from pdf import PDFParser
pdf_parser = PDFParser(book_id=book_id)

# 3. PDF 변환
if book_type == "pdf":
    pdf_parser.convert()

# 4. 결과 분할
if book_type == "pdf":
    groups = pdf_parser.split_result()
```

#### 공통 처리 단계

```python
# 1. 챕터별 그룹화
if groups is None:
    groups = get_config(book_id, "groups")
groupper.group(groups)

# 2. LLM 처리 (요약 및 번역)
llm_processor.process(groups, max_workers=1)

# 3. 결과 저장
view.save_md(groups)    # Markdown 형식
view.save_html(groups)  # HTML 형식
```

### 3. 명령줄 인터페이스

Jupyter Notebook의 첫 번째 셀에서 명령줄 인수를 사용할 수 있습니다.

```bash
jupyter nbconvert --to notebook --execute src/main.ipynb --ExecutePreprocessor.kernel_name=python3 --book-id=managing-data-as-a-product
```

## 처리 흐름

1. **이미지 수집** (Kindle만 해당)
   - Kindle 앱 창을 자동으로 찾아 페이지별 스크린샷 캡처
   - 자동으로 다음 페이지로 이동

2. **이미지 전처리**
   - 상단/하단 여백 제거
   - OCR에 최적화된 형식으로 저장

3. **텍스트 추출**
   - Tesseract OCR을 사용하여 이미지에서 텍스트 추출

4. **그룹화**
   - 설정 파일의 챕터 정보에 따라 페이지를 그룹화

5. **LLM 처리**
   - OpenAI API를 사용하여 긴 요약, 짧은 요약, 번역 생성

6. **결과 저장**
   - `output/<book_id>/` 디렉토리에 Markdown 및 HTML 형식으로 저장

## 출력 구조

```
output/
└── <book_id>/
    ├── images/          # 원본 캡처 이미지
    ├── cropped/         # 자른 이미지
    ├── ocr/             # OCR 텍스트
    ├── long_summary/    # 긴 요약
    ├── short_summary/   # 짧은 요약
    ├── translated/      # 번역 결과
    ├── <book_id>.md     # 최종 Markdown
    └── <book_id>.html   # 최종 HTML
```

## 주의 사항

- Kindle 캡처 시 Kindle 앱이 활성화되어 있어야 합니다
- 캡처 시작 전 10초의 대기 시간이 있으므로 Kindle 창을 준비하세요
- OpenAI 또는 Claude API 사용에 따른 비용이 발생할 수 있습니다
- LLM 처리는 페이지 수에 따라 시간이 오래 걸릴 수 있습니다
- Claude API는 OpenAI보다 더 나은 한국어 번역 품질을 제공할 수 있습니다

## 문제 해결

### Kindle 캡처가 작동하지 않을 때
- Kindle 앱이 실행 중인지 확인
- 10초 카운트다운 중 Kindle 창을 활성화했는지 확인
- macOS의 경우 접근성 권한 확인

### OCR 품질이 낮을 때
- `top_crop`과 `bottom_crop` 값 조정
- Kindle 앱의 글꼴 크기 조정

### LLM 처리 중 오류 발생 시
- API 키가 올바르게 설정되었는지 확인 (`.env` 파일)
- 선택한 LLM 제공자의 API 사용량 및 한도 확인
- `max_workers` 값을 줄여서 재시도
- 설정 파일의 `llm_provider`와 `llm_model`이 올바른지 확인

### LLM 제공자 변경 시
- `.env` 파일에 새로운 제공자의 API 키 추가
- 책 설정 파일의 `llm_provider` 및 `llm_model` 수정
- 노트북 커널을 재시작하여 환경 변수 다시 로드

## 라이선스

이 프로젝트는 개인적인 용도로만 사용하세요. 저작권이 있는 책의 내용을 무단으로 배포하지 마세요.
