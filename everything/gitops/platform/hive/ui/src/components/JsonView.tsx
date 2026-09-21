import type { ReactNode } from 'react'

// VSCode dark+ 유사 팔레트. 별도 CSS 변수 도입 없이 Tailwind 컬러로 매핑한다.
type TokenType = 'key' | 'string' | 'number' | 'boolean' | 'null' | 'punct'
const TOKEN_CLASS: Record<TokenType, string> = {
  key:     'text-sky-300',
  string:  'text-amber-300',
  number:  'text-emerald-300',
  boolean: 'text-purple-300',
  null:    'text-text-tertiary italic',
  punct:   'text-text-tertiary',
}

// src 는 `JSON.stringify(.., null, 2)` 결과(=well-formed JSON) 라고 가정. 그
// 가정 하에선 정규식 토크나이저로 충분 — 정식 parser 불필요.
function tokenize(src: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /("(?:\\.|[^"\\])*")(\s*:)?|true|false|null|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g
  let last = 0
  let key = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(src)) !== null) {
    if (m.index > last) {
      out.push(<span key={key++} className={TOKEN_CLASS.punct}>{src.slice(last, m.index)}</span>)
    }
    const [full, str, colon] = m
    if (str !== undefined) {
      if (colon !== undefined) {
        out.push(<span key={key++} className={TOKEN_CLASS.key}>{str}</span>)
        out.push(<span key={key++} className={TOKEN_CLASS.punct}>{colon}</span>)
      } else {
        out.push(<span key={key++} className={TOKEN_CLASS.string}>{str}</span>)
      }
    } else if (full === 'true' || full === 'false') {
      out.push(<span key={key++} className={TOKEN_CLASS.boolean}>{full}</span>)
    } else if (full === 'null') {
      out.push(<span key={key++} className={TOKEN_CLASS.null}>{full}</span>)
    } else {
      out.push(<span key={key++} className={TOKEN_CLASS.number}>{full}</span>)
    }
    last = m.index + full.length
  }
  if (last < src.length) {
    out.push(<span key={key++} className={TOKEN_CLASS.punct}>{src.slice(last)}</span>)
  }
  return out
}

interface JsonViewProps {
  /** 원문. 파싱돼 object/array 면 indent=2 + 신택스 컬러, 그 외엔 원문 그대로. */
  raw: string
  /** <pre> 에 그대로 전달 (bg·padding·font 등 부모 톤). wrap 규칙은 분기별로 자체 결정. */
  className?: string
}

export function JsonView({ raw, className = '' }: JsonViewProps) {
  let pretty: string | null = null
  try {
    const parsed: unknown = JSON.parse(raw)
    // primitive(문자열·숫자·불·null) 는 JSON 뷰로 꾸미지 않는다 — 원문 plain 이 더 자연.
    if (parsed !== null && typeof parsed === 'object') {
      pretty = JSON.stringify(parsed, null, 2)
    }
  } catch {
    pretty = null
  }
  if (pretty === null) {
    // 평문(혹은 truncate 로 깨진 JSON): 줄바꿈·단어 단위 wrap 으로 가독 우선.
    return <pre className={`whitespace-pre-wrap break-words ${className}`}>{raw}</pre>
  }
  // 잘 형성된 JSON: 들여쓰기 보존(no-wrap) + 가로 스크롤 — 구조가 깨지지 않게.
  return <pre className={`whitespace-pre overflow-x-auto ${className}`}>{tokenize(pretty)}</pre>
}
