import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface MarkdownProps {
  children: string
  className?: string
  /** 단일 줄바꿈을 hard break로 보존 (comments·실시간 입력 등). 기본은 CommonMark(false). */
  breaks?: boolean
}

export function Markdown({ children, className = '', breaks = true }: MarkdownProps) {
  // breaks=true면 단독 \n을 두 칸 + \n으로 바꿔 hard line break로 만듦.
  // 기존 paragraph 구분(\n\n)은 유지.
  const source = breaks
    ? children.replace(/([^\n])\n(?!\n)/g, '$1  \n')
    : children
  return (
    <div className={`markdown-body prose-custom ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          a({ href, children: kids }: any) {
            if (typeof href === 'string' && !/^https?:\/\//.test(href)) {
              return <span className="text-text-secondary">{kids}</span>
            }
            return (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {kids}
              </a>
            )
          },
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  )
}
