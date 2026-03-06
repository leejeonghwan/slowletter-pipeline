#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Convert newspaper_clusters_materials markdown to clean HTML.

v2: Data structure first, then HTML rendering.
"""

import re
import sys
from pathlib import Path
from typing import List, Dict, Any


def parse_markdown(content: str) -> Dict[str, Any]:
    """Parse markdown into structured data."""
    data = {
        'meta': {},
        'keywords': [],
        'details': [],
        'issues': [],
        'clusters': [],
        'observations': [],
        'minor': []
    }
    
    # Extract meta
    meta_pattern = r'^(기준일|생성 시각|원칙):\s*(.+)$'
    for match in re.finditer(meta_pattern, content, re.MULTILINE):
        key, value = match.groups()
        data['meta'][key] = value.strip()
    
    # Split by main sections
    sections = re.split(r'\n\[([^\]]+)\]\n', content)
    
    current_section = None
    for i in range(1, len(sections), 2):
        section_name = sections[i].strip()
        section_content = sections[i+1] if i+1 < len(sections) else ''
        
        if '핵심' in section_name or '주요 키워드' in section_name:
            data['keywords'] = parse_numbered_items(section_content)
        elif '구석' in section_name or '쓸고퀄' in section_name or '디테일' in section_name:
            data['details'] = parse_detail_items(section_content)
        elif '목록' in section_name or '주요 이슈' in section_name:
            data['issues'] = parse_numbered_items(section_content)
        elif '관찰' in section_name:
            data['observations'] = parse_observation_items(section_content)
        elif '소수지만' in section_name:
            data['minor'] = parse_minor_items(section_content)
    
    # Parse cluster details (### sections)
    cluster_pattern = r'### (.+?)\n(.*?)(?=\n### |\n\[|\Z)'
    for match in re.finditer(cluster_pattern, content, re.DOTALL):
        title = match.group(1).strip()
        cluster_content = match.group(2).strip()
        cluster_data = parse_cluster_detail(title, cluster_content)
        data['clusters'].append(cluster_data)
    
    return data


def parse_numbered_items(content: str) -> List[Dict[str, Any]]:
    """Parse numbered list items (1. ... 2. ...)."""
    items = []
    # Pattern: number, title, papers, conclusion/point, urls
    pattern = r'^\d+\.\s+(.+?)\s+\(([^)]+)\)\s*\n\s*-\s*(?:결론|포인트):\s*(.+?)\s*/\s*([^\n]+)\n((?:\s*-\s*https?://[^\n]+\n?)*)'
    
    for match in re.finditer(pattern, content, re.MULTILINE):
        title = match.group(1).strip()
        papers = [p.strip() for p in match.group(2).split(',')]
        quote = match.group(3).strip()
        source = match.group(4).strip()
        urls_text = match.group(5).strip()
        
        # Extract URLs
        urls = []
        for url_match in re.finditer(r'https?://[^\s]+', urls_text):
            url = url_match.group(0).strip()
            if 'nan' not in url.lower():
                urls.append(url)
        
        items.append({
            'title': title,
            'papers': papers,
            'quote': quote,
            'source': source,
            'urls': urls
        })
    
    return items


def parse_detail_items(content: str) -> List[Dict[str, Any]]:
    """Parse detail items (- paper: title ...)."""
    items = []
    # Pattern: - paper: title\n  포인트: quote / source\n  url
    pattern = r'-\s+([^:]+):\s+(.+?)\n\s+포인트:\s+(.+?)\s*/\s*([^\n]+)\n\s+(https?://[^\s]+)'
    
    for match in re.finditer(pattern, content, re.MULTILINE):
        paper = match.group(1).strip()
        title = match.group(2).strip()
        quote = match.group(3).strip()
        source = match.group(4).strip()
        url = match.group(5).strip()
        
        if 'nan' not in url.lower():
            items.append({
                'paper': paper,
                'title': title,
                'quote': quote,
                'source': source,
                'url': url
            })
    
    return items


def parse_observation_items(content: str) -> List[Dict[str, Any]]:
    """Parse observation items (## date ...)."""
    items = []
    # Split by ## date
    date_sections = re.split(r'\n##\s+(\d{8})\n', content)
    
    for i in range(1, len(date_sections), 2):
        date = date_sections[i].strip()
        section_content = date_sections[i+1] if i+1 < len(date_sections) else ''
        
        # Extract bullet items
        bullet_pattern = r'-\s+([^\n]+)\n\s+포인트:\s+(.+?)(?=\n-|\n##|\Z)'
        for match in re.finditer(bullet_pattern, section_content, re.DOTALL):
            keywords = match.group(1).strip()
            point = match.group(2).strip()
            
            items.append({
                'date': date,
                'keywords': keywords,
                'point': point
            })
    
    return items


def parse_minor_items(content: str) -> List[Dict[str, Any]]:
    """Parse minor but important items."""
    items = []
    # Pattern similar to detail items
    pattern = r'-\s+([^:]+):\s+(.+?)(?:\n\s+숫자/팩트:|\n\s+인용:|\n\s+앵글:|\n-|\Z)'
    
    for match in re.finditer(pattern, content, re.DOTALL):
        paper = match.group(1).strip()
        item_content = match.group(2).strip()
        
        # Extract sub-fields
        facts = []
        quotes = []
        angle = ''
        
        fact_pattern = r'숫자/팩트:\s*\n((?:\s*-\s*[^\n]+\n?)+)'
        quote_pattern = r'인용:\s*(.+?)(?=\n\s+앵글:|\Z)'
        angle_pattern = r'앵글:\s*(.+?)(?=\n-|\Z)'
        
        fact_match = re.search(fact_pattern, item_content, re.DOTALL)
        if fact_match:
            fact_lines = fact_match.group(1).strip().split('\n')
            facts = [line.strip().lstrip('- ') for line in fact_lines if line.strip()]
        
        quote_match = re.search(quote_pattern, item_content, re.DOTALL)
        if quote_match:
            quotes_text = quote_match.group(1).strip()
            # Extract quoted text
            quote_lines = re.findall(r'"([^"]+)"', quotes_text)
            quotes = quote_lines
        
        angle_match = re.search(angle_pattern, item_content, re.DOTALL)
        if angle_match:
            angle = angle_match.group(1).strip()
        
        items.append({
            'paper': paper,
            'facts': facts,
            'quotes': quotes,
            'angle': angle
        })
    
    return items


def parse_cluster_detail(title: str, content: str) -> Dict[str, Any]:
    """Parse detailed cluster section (### ...)."""
    cluster = {
        'title': title,
        'papers': [],
        'summary': '',
        'comments': [],
        'one_liner': '',
        'point': '',
        'facts': [],
        'quotes': []
    }
    
    # Extract papers
    papers_match = re.search(r'언론:\s*([^\n]+)', content)
    if papers_match:
        cluster['papers'] = [p.strip() for p in papers_match.group(1).split(',')]
    
    # Extract summary
    summary_match = re.search(r'\[(?:내용 요약|핵심)\]:\s*([^\n]+)', content)
    if summary_match:
        cluster['summary'] = summary_match.group(1).strip()
    
    # Extract comments
    comments_pattern = r'\d+\.\s+"([^"]+)"\s*/\s*([^\(]+)\s*\(([^)]+)\)\s*\n\s*→\s*(https?://[^\s]+)'
    for match in re.finditer(comments_pattern, content):
        quote = match.group(1).strip()
        source = match.group(2).strip()
        paper = match.group(3).strip()
        url = match.group(4).strip()
        
        cluster['comments'].append({
            'quote': f'"{quote}"',
            'source': source,
            'paper': paper,
            'url': url
        })
    
    # Extract one-liner
    oneliner_match = re.search(r'한줄 맥락:\s*([^\n]+)', content)
    if oneliner_match:
        cluster['one_liner'] = oneliner_match.group(1).strip()
    
    # Extract point
    point_match = re.search(r'포인트:\s*"([^"]+)"\s*/\s*([^\n]+)', content)
    if point_match:
        cluster['point'] = f'"{point_match.group(1).strip()}" / {point_match.group(2).strip()}'
    
    # Extract facts
    facts_section = re.search(r'숫자/팩트.*?:\s*\n((?:\s*-[^\n]+\n(?:\s+https?://[^\n]+\n)?)+)', content, re.DOTALL)
    if facts_section:
        fact_lines = facts_section.group(1).strip().split('\n')
        current_fact = ''
        current_url = ''
        
        for line in fact_lines:
            line = line.strip()
            if line.startswith('-'):
                if current_fact:
                    cluster['facts'].append({'text': current_fact, 'url': current_url})
                current_fact = line.lstrip('- ')
                current_url = ''
            elif line.startswith('http'):
                current_url = line
        
        if current_fact:
            cluster['facts'].append({'text': current_fact, 'url': current_url})
    
    # Extract quotes
    quotes_section = re.search(r'발언/인용.*?:\s*\n((?:\s*-[^\n]+\n(?:\s+https?://[^\n]+\n)?)+)', content, re.DOTALL)
    if quotes_section:
        quote_lines = quotes_section.group(1).strip().split('\n')
        current_quote = ''
        current_url = ''
        
        for line in quote_lines:
            line = line.strip()
            if line.startswith('-'):
                if current_quote:
                    cluster['quotes'].append({'text': current_quote, 'url': current_url})
                current_quote = line.lstrip('- ')
                current_url = ''
            elif line.startswith('http'):
                current_url = line
        
        if current_quote:
            cluster['quotes'].append({'text': current_quote, 'url': current_url})
    
    return cluster


def url_to_link(url: str, paper: str = None) -> str:
    """Convert URL to <a> tag."""
    if not url or 'nan' in url.lower():
        return ''
    
    if not paper:
        # Detect paper from URL
        if 'chosun' in url:
            paper = '조선일보'
        elif 'joongang' in url:
            paper = '중앙일보'
        elif 'donga' in url:
            paper = '동아일보'
        elif 'khan' in url or 'kyunghyang' in url:
            paper = '경향신문'
        elif 'hani' in url:
            paper = '한겨레'
        elif 'hankookilbo' in url:
            paper = '한국일보'
        else:
            paper = '링크'
    
    return f'<a href="{url}" target="_blank">[{paper}]</a>'


def render_html(data: Dict[str, Any]) -> str:
    """Render data structure to HTML."""
    parts = []
    
    # Header
    parts.append('''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>지면 분석 기초자료</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", sans-serif;
            max-width: 900px;
            margin: 40px auto;
            padding: 0 20px;
            line-height: 1.7;
            color: #222;
            background: #fdad00;
        }
        h1, h2, h3, h4 {
            margin-top: 0;
            margin-bottom: 15px;
        }
        h2 {
            font-size: 20px;
            color: #0066cc;
            border-left: 4px solid #0066cc;
            padding-left: 10px;
        }
        h3 {
            font-size: 18px;
            color: #333;
        }
        h4 {
            font-size: 16px;
            color: #555;
            margin-top: 20px;
        }
        .meta {
            color: #666;
            font-size: 14px;
            margin-bottom: 15px;
        }
        .section {
            background: white;
            padding: 20px;
            margin: 20px 0;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        .cluster-item {
            background: #f9f9f9;
            padding: 15px;
            margin: 15px 0;
            border-left: 3px solid #0066cc;
            border-radius: 4px;
        }
        .point {
            background: #fff3cd;
            padding: 10px;
            margin: 10px 0;
            border-radius: 4px;
            font-weight: 500;
        }
        .press-list {
            color: #666;
            font-size: 14px;
            margin: 8px 0;
        }
        .press-links {
            margin: 10px 0;
        }
        .press-links a {
            display: inline-block;
            margin-right: 10px;
            margin-bottom: 5px;
        }
        a {
            color: #0066cc;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        ul, ol {
            margin: 10px 0;
            padding-left: 25px;
        }
        li {
            margin: 5px 0;
        }
        p {
            margin: 8px 0;
        }
        hr {
            border: none;
            border-top: 1px solid #ddd;
            margin: 30px 0;
        }
    </style>
</head>
<body>
''')
    
    # Meta section
    parts.append('<div class="section">')
    parts.append('<p><strong>슬로우레터 기초 자료</strong></p>')
    for key, value in data['meta'].items():
        parts.append(f'<p class="meta">{key}: {value}</p>')
    parts.append('</div>')
    
    # Keywords section
    if data['keywords']:
        parts.append('<h2>주요 키워드</h2>')
        parts.append('<p class="meta">기준: 4개. 빠르게 핵심 파악용.</p>')
        
        for item in data['keywords']:
            parts.append('<div class="cluster-item">')
            papers_str = ', '.join(item['papers'])
            parts.append(f'<p><strong>{item["title"]}</strong> ({papers_str})</p>')
            parts.append(f'<div class="point">{item["quote"]} / {item["source"]}</div>')
            
            if item['urls']:
                links = [url_to_link(url) for url in item['urls']]
                parts.append(f'<p class="press-links">{" ".join(links)}</p>')
            
            parts.append('</div>')
        
        parts.append('<hr>')
    
    # Details section
    if data['details']:
        parts.append('<h2>쓸고퀄 디테일</h2>')
        parts.append('<p class="meta">기준: 단독/소수에서 공적 가치/직접 인용/숫자 재료가 강한 것 최대 7개.</p>')
        
        for item in data['details']:
            parts.append('<div class="cluster-item">')
            parts.append(f'<p><strong>{item["paper"]}:</strong> {item["title"]}</p>')
            parts.append(f'<div class="point">{item["quote"]} / {item["source"]}</div>')
            
            if item['url']:
                link = url_to_link(item['url'], item['paper'])
                parts.append(f'<p class="press-links">{link}</p>')
            
            parts.append('</div>')
        
        parts.append('<hr>')
    
    # Issues section
    if data['issues']:
        parts.append('<h2>오늘의 주요 이슈</h2>')
        parts.append('<p class="meta">기준: 클러스터 단위로 15개.</p>')
        
        for item in data['issues']:
            parts.append('<div class="cluster-item">')
            papers_str = ', '.join(item['papers'])
            parts.append(f'<p><strong>{item["title"]}</strong> ({papers_str})</p>')
            parts.append(f'<div class="point">{item["quote"]} / {item["source"]}</div>')
            
            if item['urls']:
                links = [url_to_link(url) for url in item['urls']]
                parts.append(f'<p class="press-links">{" ".join(links)}</p>')
            
            parts.append('</div>')
        
        parts.append('<hr>')
    
    # Cluster details
    if data['clusters']:
        for cluster in data['clusters']:
            parts.append('<div class="section">')
            parts.append(f'<h3>{cluster["title"]}</h3>')
            
            if cluster['papers']:
                papers_str = ', '.join(cluster['papers'])
                parts.append(f'<p class="press-list">언론: {papers_str}</p>')
            
            if cluster['summary']:
                parts.append(f'<p><strong>[핵심]</strong> {cluster["summary"]}</p>')
            
            if cluster['comments']:
                parts.append('<h4>중요 코멘트</h4>')
                parts.append('<ul>')
                for comment in cluster['comments']:
                    link = url_to_link(comment['url'], comment['paper'])
                    parts.append(f'<li>{comment["quote"]} / {comment["source"]} — {link}</li>')
                parts.append('</ul>')
            
            if cluster['one_liner']:
                parts.append(f'<p><strong>한줄 맥락:</strong> {cluster["one_liner"]}</p>')
            
            if cluster['point']:
                parts.append(f'<div class="point">{cluster["point"]}</div>')
            
            if cluster['facts']:
                parts.append('<h4>숫자/팩트</h4>')
                parts.append('<ul>')
                for fact in cluster['facts']:
                    link = url_to_link(fact['url']) if fact['url'] else ''
                    parts.append(f'<li>{fact["text"]} {link}</li>')
                parts.append('</ul>')
            
            if cluster['quotes']:
                parts.append('<h4>발언/인용</h4>')
                parts.append('<ul>')
                for quote in cluster['quotes']:
                    link = url_to_link(quote['url']) if quote['url'] else ''
                    parts.append(f'<li>{quote["text"]} {link}</li>')
                parts.append('</ul>')
            
            parts.append('</div>')
    
    # Observations
    if data['observations']:
        parts.append('<div class="section">')
        parts.append('<h2>관찰(누적)</h2>')
        parts.append('<p class="meta">기준: 진행 중 이슈는 매일 누적. 큰 흐름이 잡힐 때만 본문 카드로 승격.</p>')
        
        current_date = None
        for obs in data['observations']:
            if obs['date'] != current_date:
                if current_date:
                    parts.append('</ul>')
                parts.append(f'<h4>{obs["date"]}</h4>')
                parts.append('<ul>')
                current_date = obs['date']
            
            parts.append(f'<li>{obs["keywords"]}<br><div class="point">{obs["point"]}</div></li>')
        
        if current_date:
            parts.append('</ul>')
        
        parts.append('</div>')
        parts.append('<hr>')
    
    # Minor items
    if data['minor']:
        parts.append('<div class="section">')
        parts.append('<h2>소수지만 중요한 항목</h2>')
        parts.append('<p class="meta">기준: 지면 전체 중 \'단독/소수\'로 남았지만 숫자/직접 인용이 강한 항목</p>')
        
        for item in data['minor']:
            parts.append(f'<h4>{item["paper"]}</h4>')
            
            if item['facts']:
                parts.append('<p><strong>숫자/팩트:</strong></p>')
                parts.append('<ul>')
                for fact in item['facts']:
                    parts.append(f'<li>{fact}</li>')
                parts.append('</ul>')
            
            if item['quotes']:
                parts.append('<p><strong>인용:</strong></p>')
                parts.append('<ul>')
                for quote in item['quotes']:
                    parts.append(f'<li>"{quote}"</li>')
                parts.append('</ul>')
            
            if item['angle']:
                parts.append(f'<p><strong>앵글:</strong> {item["angle"]}</p>')
        
        parts.append('</div>')
    
    # Footer
    parts.append('</body>')
    parts.append('</html>')
    
    return '\n'.join(parts)


def md_to_html(md_path: str, html_path: str):
    """Main conversion function."""
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Parse markdown to data structure
    data = parse_markdown(content)
    
    # Render HTML
    html = render_html(data)
    
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"✓ HTML 생성: {html_path}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: convert_materials_to_html.py YYYYMMDD")
        sys.exit(1)
    
    date = sys.argv[1]
    dl = Path.home() / 'Downloads'
    md_path = dl / f'newspaper_clusters_materials_{date}.md'
    html_path = dl / f'newspaper_clusters_materials_{date}.html'
    
    if not md_path.exists():
        print(f"Error: {md_path} not found")
        sys.exit(1)
    
    md_to_html(str(md_path), str(html_path))
