import os
from functions import get_output_dir, get_config
import json
import markdown2


class View:
    def __init__(self, book_id):
        self.book_id = book_id
        self.llm_output_dir = get_output_dir(book_id, "llm")
        self.view_output_dir = get_output_dir(book_id, "view")
        pass
    
    def md_to_html(self, md):
        return markdown2.markdown(md, extras=["footnotes", "tables", "admonitions", "fenced-code-blocks"])

    def save_md(self, groups):

        md = ""
        for index, filename in enumerate(sorted(os.listdir(self.llm_output_dir), key=lambda x: int(x.split(".")[0]))):
            with open(f"{self.llm_output_dir}/{filename}", "r") as fp:
                summary = json.loads(fp.read())

            group = groups[index]
            name = group["name"]
            start_page = group["start_page"]
            end_page = group["end_page"]
            long_summary = summary["long_summary"]
            short_summary = summary["short_summary"]
            md += f"""
# {name}
({start_page}~{end_page})

{short_summary}

<details>
<summary>긴 요약 보기</summary>

{long_summary}

</details>

---

"""         
#             if "translated" in summary:
#                 translated = summary["translated"]
#                 md += f"""
# <details>
# <summary>번역 보기</summary>

# {translated}

# </details>
# """
            md  + """

---
"""
        with open(f"{self.view_output_dir}/view.md", "w") as f:
            f.write(md)


    def save_html(self, groups):
        book_title = get_config(self.book_id, "title", self.book_id.replace("-", " ").title())

        html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{book_title} - Items</title>
    <link rel="icon" type="image/x-icon" href="/static/favicon.ico" />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Noto+Sans+KR:wght@400;500;600;700&family=Noto+Serif+KR:wght@400;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-primary: #ffffff;
            --bg-secondary: #f7f7f7;
            --bg-tertiary: #fafafa;
            --text-primary: #1a1a1a;
            --text-secondary: #4a4a4a;
            --text-tertiary: #737373;
            --border-color: #e5e5e5;
            --accent-color: #0066cc;
            --accent-light: #e6f0ff;
            --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.04);
            --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.05);
            --radius-sm: 6px;
            --radius-md: 12px;
            --radius-lg: 16px;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Inter', 'Noto Sans KR', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-secondary);
            color: var(--text-primary);
            line-height: 1.7;
            min-height: 100vh;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }}

        .container {{
            max-width: 740px;
            margin: 0 auto;
            padding: 60px 24px;
        }}

        .book-header {{
            text-align: center;
            margin-bottom: 48px;
            padding-bottom: 32px;
            border-bottom: 1px solid var(--border-color);
        }}

        .book-header h1 {{
            font-family: 'Noto Serif KR', Georgia, serif;
            font-size: 2.5rem;
            font-weight: 700;
            color: var(--text-primary);
            margin-bottom: 12px;
            letter-spacing: -0.02em;
        }}

        .book-header .subtitle {{
            color: var(--text-tertiary);
            font-size: 0.95rem;
            font-weight: 400;
        }}

        .chapter-card {{
            background: var(--bg-primary);
            border-radius: var(--radius-lg);
            padding: 32px;
            margin-bottom: 24px;
            border: 1px solid var(--border-color);
            box-shadow: var(--shadow-sm);
            transition: box-shadow 0.2s ease;
        }}

        .chapter-card:hover {{
            box-shadow: var(--shadow-md);
        }}

        .chapter-title {{
            font-family: 'Noto Serif KR', Georgia, serif;
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--text-primary);
            margin-bottom: 8px;
            letter-spacing: -0.01em;
            line-height: 1.4;
        }}

        .page-range {{
            display: inline-block;
            color: var(--text-tertiary);
            font-size: 0.85rem;
            font-weight: 500;
            margin-bottom: 20px;
        }}

        .summary-content {{
            font-size: 1rem;
            line-height: 1.8;
            color: var(--text-secondary);
        }}

        .summary-content p {{
            margin-bottom: 1rem;
        }}

        .summary-content p:last-child {{
            margin-bottom: 0;
        }}

        .details-section {{
            margin-top: 24px;
            border-top: 1px solid var(--border-color);
            padding-top: 20px;
        }}

        .details-toggle {{
            display: flex;
            align-items: center;
            gap: 8px;
            background: none;
            border: none;
            padding: 10px 16px;
            margin-left: -16px;
            font-size: 0.9rem;
            font-weight: 500;
            color: var(--accent-color);
            cursor: pointer;
            border-radius: var(--radius-sm);
            transition: background-color 0.15s ease;
        }}

        .details-toggle:hover {{
            background: var(--accent-light);
        }}

        .details-toggle svg {{
            width: 16px;
            height: 16px;
            transition: transform 0.2s ease;
        }}

        .details-toggle.open svg {{
            transform: rotate(90deg);
        }}

        .details-content {{
            display: none;
            padding: 20px 0 0 0;
            animation: fadeIn 0.2s ease;
        }}

        .details-content.show {{
            display: block;
        }}

        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(-4px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        .details-content-inner {{
            background: var(--bg-tertiary);
            border-radius: var(--radius-md);
            padding: 24px;
            font-size: 0.95rem;
            line-height: 1.8;
            color: var(--text-secondary);
        }}

        .details-content-inner h1,
        .details-content-inner h2,
        .details-content-inner h3,
        .details-content-inner h4 {{
            font-family: 'Noto Serif KR', Georgia, serif;
            color: var(--text-primary);
            margin-top: 1.5rem;
            margin-bottom: 0.75rem;
            font-weight: 600;
        }}

        .details-content-inner h1:first-child,
        .details-content-inner h2:first-child,
        .details-content-inner h3:first-child {{
            margin-top: 0;
        }}

        .details-content-inner h2 {{ font-size: 1.25rem; }}
        .details-content-inner h3 {{ font-size: 1.1rem; }}
        .details-content-inner h4 {{ font-size: 1rem; }}

        .details-content-inner p {{
            margin-bottom: 1rem;
        }}

        .details-content-inner ul,
        .details-content-inner ol {{
            padding-left: 1.5rem;
            margin-bottom: 1rem;
        }}

        .details-content-inner li {{
            margin-bottom: 0.5rem;
        }}

        .details-content-inner code {{
            background: rgba(0, 0, 0, 0.05);
            padding: 0.15rem 0.4rem;
            border-radius: 4px;
            font-size: 0.9em;
            font-family: 'SF Mono', 'Consolas', monospace;
        }}

        .details-content-inner blockquote {{
            border-left: 3px solid var(--accent-color);
            padding-left: 16px;
            margin: 1rem 0;
            color: var(--text-tertiary);
            font-style: italic;
        }}

        .section-divider {{
            height: 1px;
            background: var(--border-color);
            margin: 16px 0;
        }}

        .back-to-top {{
            position: fixed;
            bottom: 32px;
            right: 32px;
            width: 48px;
            height: 48px;
            background: var(--bg-primary);
            border: 1px solid var(--border-color);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            box-shadow: var(--shadow-md);
            transition: all 0.2s ease;
            opacity: 0;
            visibility: hidden;
        }}

        .back-to-top.show {{
            opacity: 1;
            visibility: visible;
        }}

        .back-to-top:hover {{
            background: var(--bg-secondary);
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.1);
        }}

        .back-to-top svg {{
            width: 20px;
            height: 20px;
            color: var(--text-secondary);
        }}

        .back-to-list {{
            position: fixed;
            bottom: 32px;
            left: 32px;
            width: 48px;
            height: 48px;
            background: var(--bg-primary);
            border: 1px solid var(--border-color);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            box-shadow: var(--shadow-md);
            transition: all 0.2s ease;
            text-decoration: none;
        }}

        .back-to-list:hover {{
            background: var(--bg-secondary);
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.1);
        }}

        .back-to-list svg {{
            width: 20px;
            height: 20px;
            color: var(--text-secondary);
        }}

        /* Reading progress bar */
        .progress-bar {{
            position: fixed;
            top: 0;
            left: 0;
            height: 3px;
            background: var(--accent-color);
            width: 0%;
            z-index: 1000;
            transition: width 0.1s ease;
        }}

        @media (max-width: 768px) {{
            .container {{
                padding: 40px 20px;
            }}

            .book-header h1 {{
                font-size: 1.875rem;
            }}

            .chapter-card {{
                padding: 24px;
                margin-bottom: 16px;
            }}

            .chapter-title {{
                font-size: 1.25rem;
            }}

            .details-content-inner {{
                padding: 20px;
            }}

            .back-to-top {{
                bottom: 20px;
                right: 20px;
                width: 44px;
                height: 44px;
            }}

            .back-to-list {{
                bottom: 20px;
                left: 20px;
                width: 44px;
                height: 44px;
            }}
        }}

        /* Print styles */
        @media print {{
            .back-to-top,
            .back-to-list,
            .progress-bar,
            .details-toggle {{
                display: none;
            }}

            .details-content {{
                display: block !important;
            }}

            .chapter-card {{
                break-inside: avoid;
                box-shadow: none;
                border: 1px solid #ddd;
            }}
        }}
    </style>
</head>
<body>
    <div class="progress-bar" id="progressBar"></div>
    <div class="container">
        <div class="book-header">
            <h1>{book_title}</h1>
            <p class="subtitle">AI 기반 요약</p>
        </div>
"""

        for index, filename in enumerate(sorted(os.listdir(self.llm_output_dir), key=lambda x: int(x.split(".")[0]))):
            with open(f"{self.llm_output_dir}/{filename}", "r") as fp:
                summary = json.loads(fp.read())

            group = groups[index]
            name = group["name"]
            start_page = group["start_page"]
            end_page = group["end_page"]

            # Get available fields
            long_summary = summary.get("long_summary", "")
            translated = summary.get("translated", "")
            short_summary = summary.get("short_summary", "")

            html += f"""
        <div class="chapter-card">
            <h2 class="chapter-title">{name}</h2>
            <span class="page-range">p. {start_page} - {end_page}</span>
"""

            # Show short summary if available
            if short_summary:
                html += f"""
            <div class="summary-content">
                {self.md_to_html(short_summary)}
            </div>
"""

            # Build details sections
            details_sections = []

            if long_summary:
                details_sections.append(("long", "자세히 보기", long_summary))

            if translated:
                details_sections.append(("translated", "전체 번역 보기", translated))

            # Only show details if there are sections
            if details_sections:
                html += """
            <div class="details-section">
"""
                for section_id, section_title, section_content in details_sections:
                    html += f"""
                <button class="details-toggle" onclick="toggleDetails(this, 'details-{index}-{section_id}')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="9 18 15 12 9 6"></polyline>
                    </svg>
                    {section_title}
                </button>
                <div class="details-content" id="details-{index}-{section_id}">
                    <div class="details-content-inner">
                        {self.md_to_html(section_content)}
                    </div>
                </div>
"""
                html += """
            </div>
"""

            html += """
        </div>
"""

        html += """
    </div>

    <a href="/" class="back-to-list" title="목록으로 돌아가기">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="15 18 9 12 15 6"></polyline>
        </svg>
    </a>

    <div class="back-to-top" id="backToTop">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="18 15 12 9 6 15"></polyline>
        </svg>
    </div>

    <script>
        // Toggle details section
        function toggleDetails(button, contentId) {
            const content = document.getElementById(contentId);
            const isOpen = content.classList.contains('show');

            if (isOpen) {
                content.classList.remove('show');
                button.classList.remove('open');
            } else {
                content.classList.add('show');
                button.classList.add('open');
            }
        }

        // Back to top button
        const backToTop = document.getElementById('backToTop');
        const progressBar = document.getElementById('progressBar');

        window.addEventListener('scroll', () => {
            // Back to top visibility
            if (window.pageYOffset > 300) {
                backToTop.classList.add('show');
            } else {
                backToTop.classList.remove('show');
            }

            // Progress bar
            const winScroll = document.body.scrollTop || document.documentElement.scrollTop;
            const height = document.documentElement.scrollHeight - document.documentElement.clientHeight;
            const scrolled = (winScroll / height) * 100;
            progressBar.style.width = scrolled + '%';
        });

        backToTop.addEventListener('click', () => {
            window.scrollTo({
                top: 0,
                behavior: 'smooth'
            });
        });
    </script>
</body>
</html>
"""
        with open(f"{self.view_output_dir}/view.html", "w") as f:
            f.write(html)
