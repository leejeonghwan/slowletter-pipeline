#!/usr/bin/env python3
"""
오피니언 칼럼 리포트를 HTML로 변환
"""
import re
import sys
from pathlib import Path


def convert_opinion_columns_to_html(md_path: str) -> str:
    """MD 리포트를 HTML로 변환"""
    md_path = Path(md_path)
    html_path = md_path.with_suffix('.html')
    
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # HTML 템플릿
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>오피니언 칼럼 분석 - {md_path.stem}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #007bff;
            padding-bottom: 10px;
        }}
        .meta {{
            color: #666;
            margin: 20px 0;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 5px;
        }}
        .article {{
            margin: 25px 0;
            padding: 20px;
            border-left: 4px solid #007bff;
            background: #f8f9fa;
        }}
        .article-title {{
            font-weight: bold;
            color: #007bff;
            margin-bottom: 10px;
        }}
        .claim {{
            margin: 10px 0;
            padding-left: 15px;
        }}
        .quote {{
            margin: 10px 0;
            padding: 10px;
            background: #fff;
            border-left: 3px solid #28a745;
            font-style: italic;
        }}
        .number {{
            margin: 10px 0;
            padding: 10px;
            background: #fff;
            border-left: 3px solid #ffc107;
        }}
        .link {{
            margin-top: 10px;
        }}
        .link a {{
            color: #007bff;
            text-decoration: none;
        }}
        .link a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
"""
    
    # 헤더 파싱
    lines = content.split('\n')
    header_lines = []
    articles = []
    current_article = []
    
    in_header = True
    for line in lines:
        if line.strip() == '---' and in_header:
            in_header = False
            continue
        
        if in_header:
            header_lines.append(line)
        else:
            if line.startswith('- ') and ' | ' in line:
                if current_article:
                    articles.append('\n'.join(current_article))
                current_article = [line]
            else:
                current_article.append(line)
    
    if current_article:
        articles.append('\n'.join(current_article))
    
    # 헤더 추가
    html += "<h1>오피니언 칼럼 분석</h1>\n"
    html += '<div class="meta">\n'
    for line in header_lines:
        if line.strip():
            html += f"<div>{line}</div>\n"
    html += '</div>\n'
    
    # 기사별 파싱
    for article_text in articles:
        lines = article_text.split('\n')
        
        html += '<div class="article">\n'
        
        # 제목 라인
        title_line = lines[0]
        match = re.match(r'- (.+?) \| (.+)', title_line)
        if match:
            press = match.group(1)
            title = match.group(2)
            html += f'<div class="article-title">[{press}] {title}</div>\n'
        
        # 본문 파싱
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            
            # URL 체크 (링크로 시작하는 줄)
            if line.startswith('http'):
                html += f'<div class="link"><a href="{line}" target="_blank">기사 원문 보기</a></div>\n'
            # 인용문 (따옴표로 시작)
            elif line.startswith('- "') or line.startswith('- "'):
                quote = line[2:].strip()
                html += f'<div class="quote">{quote}</div>\n'
            # 숫자/항목 (- 로 시작, 콜론 포함)
            elif line.startswith('- ') and ':' in line:
                html += f'<div class="number">{line[2:]}</div>\n'
            # 기타 항목
            elif line.startswith('- '):
                html += f'<div class="claim">{line[2:]}</div>\n'
            # 일반 텍스트
            else:
                html += f'<div class="claim">{line}</div>\n'
        
        html += '</div>\n'
    
    html += """
    </div>
</body>
</html>
"""
    
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    return str(html_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python convert_opinion_columns_to_html.py <md_file>")
        sys.exit(1)
    
    md_file = sys.argv[1]
    html_file = convert_opinion_columns_to_html(md_file)
    print(f"✅ HTML 생성: {html_file}")
