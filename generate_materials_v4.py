#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
슬로우레터 기초자료 HTML 생성 파이프라인 v4

CSV 원본 → 클러스터링 → 발언자/팩트 추출 → HTML 렌더링
병합: generate_materials.py (데이터 추출 로직) + convert_materials_to_html.py (렌더링 디자인)
OPENCLO_HTML_GUIDE v3.1 준수

사용법:
  python generate_materials_v4.py newspaper_full_press_view_20260304.csv
  python generate_materials_v4.py newspaper_full_press_view_20260304.csv --date 20260304
"""

import csv
import html
import re
import sys
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime
from statistics import mean

# ═══════════════════════════════════════════════════════
# 1. 데이터 로드
# ═══════════════════════════════════════════════════════

def load_csv(path):
    """CSV 파일 로드. utf-8-sig로 BOM 처리."""
    with open(path, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

# ═══════════════════════════════════════════════════════
# 2. 발언자 추출 (generate_materials.py 핵심 로직)
# ═══════════════════════════════════════════════════════

# 직책 패턴 (자주 등장하는 직책)
TITLE_PATTERN = (
    r'(?:대통령|대표|원장|의원|장관|위원장|도지사|시장|군수|구청장|총장|교수|'
    r'대법원장|대법관|판사|검사|검찰총장|CEO|이사장|본부장|차관|비서관|대변인|'
    r'원내대표|사무총장|사무관|국장|실장|팀장|센터장|부장|과장|계장|소장|'
    r'연구원|연구위원|박사|변호사|회장|부회장|사장|부사장|전무|상무|이사|'
    r'감독|코치|선수|해설위원|위원|간사|총재|의장|부의장|청장|처장|'
    r'총리|부총리|대사|영사|특파원|기자|PD|앵커|아나운서|MC|진행자|'
    r'목사|신부|승려|주지|관장|관계자|대표이사|공동대표)'
)

# 불용어: 발언자로 오추출되는 일반 단어
SPEAKER_STOPWORDS = {
    '그러나', '하지만', '한편', '또한', '이에', '이후', '다만', '그래서', '따라서', '결국',
    '이미', '그동안', '이번', '올해', '지난해', '최근',
    '면서', '이라고', '라며', '라고', '밝혔다', '말했다', '지적했다',
    '때문에', '뿐만', '아니라', '가운데', '이날', '당시', '앞서',
    # 익명 출처 (이름이 아닌 일반명사)
    '관계자', '당국자', '소식통', '측근', '핵심', '인사', '수석', '대표',
    '해수부', '국방부', '외교부', '교육부', '환경부',
    '업계', '지도부', '추진위', '기획단', '사무국', '공간',
    # 동사구/조사 오파싱
    '비판하자', '대해서', '대해', '관련해', '따르면', '통해서',
}

# 발언자로 나오면 안 되는 조각형 표현
SPEAKER_BAD_PATTERNS = (
    '이라고 말', '질문에', '보이는 사람', '군사작전에 대해서',
    '찾아 헌화', '만난', '가짜뉴스', '하고 있', '하는 모습', '모습이다'
)

def extract_quotes(text):
    """기사 본문에서 직접 인용문 + 발언자를 추출한다.
    
    절대 규칙: 발언자가 확인되지 않으면 해당 인용문은 버린다.
    "(발언자 미상)"은 절대 사용하지 않는다.
    """
    quotes = []
    if not text:
        return quotes
    
    # 패턴 1: 발언자가 앞에 오는 경우
    # "홍길동 장관은 "인용문"이라고 말했다"
    pat_before = re.findall(
        r'([가-힣]{2,10}(?:\s+[가-힣]+)?(?:\s+' + TITLE_PATTERN + r')?)'
        r'\s*(?:은|는|이|가|도)\s*'
        r'["\u201C\u201D]([^"\u201C\u201D]{10,500})["\u201C\u201D]',
        text
    )
    for speaker, quote in pat_before:
        speaker = clean_speaker(speaker)
        if is_valid_speaker(speaker):
            quotes.append({"speaker": speaker, "quote": quote.strip()})
    
    # 패턴 2: 발언자가 뒤에 오는 경우
    # "인용문"이라고 홍길동이 말했다
    pat_after = re.findall(
        r'["\u201C]([^"\u201C\u201D]{10,500})["\u201D]\s*'
        r'(?:이라고|라고|라며|면서)?\s*'
        r'([가-힣]{2,10}(?:\s+[가-힣]+)?(?:\s+' + TITLE_PATTERN + r')?)'
        r'\s*(?:이|가|은|는)?\s*'
        r'(?:말했다|밝혔다|강조했다|주장했다|설명했다|전했다|덧붙였다|했다|지적했다|언급했다|평가했다|분석했다|말한다)',
        text
    )
    for quote, speaker in pat_after:
        speaker = clean_speaker(speaker)
        if is_valid_speaker(speaker):
            if not any(q['quote'] == quote.strip() for q in quotes):
                quotes.append({"speaker": speaker, "quote": quote.strip()})
    
    # 패턴 3: "인용문" / 발언자 (슬래시 구분)
    pat_slash = re.findall(
        r'["\u201C]([^"\u201C\u201D]{10,500})["\u201D]\s*/\s*'
        r'([가-힣]{2,10}(?:\s+[가-힣A-Za-z]+)*)',
        text
    )
    for quote, speaker in pat_slash:
        speaker = clean_speaker(speaker)
        if is_valid_speaker(speaker):
            if not any(q['quote'] == quote.strip() for q in quotes):
                quotes.append({"speaker": speaker, "quote": quote.strip()})
    
    return quotes

def clean_speaker(speaker):
    """발언자 이름 정제."""
    speaker = speaker.strip()
    # 앞뒤 조사 제거
    speaker = re.sub(r'^(그런데|그래서|그러나|하지만|한편|이에)\s*', '', speaker)
    speaker = re.sub(r'(에게|에서|으로|한테|에는|에도|까지|부터|에의|과는|와는)$', '', speaker)
    return speaker.strip()

def is_valid_speaker(speaker):
    """발언자가 유효한 인명/직함인지 검증."""
    if not speaker or len(speaker) < 2:
        return False
    if speaker in SPEAKER_STOPWORDS:
        return False
    
    # 복합 익명 출처 필터: "~관계자", "~당국자", "~소식통", "~측근", "~인사" 등
    # 예: "업계 관계자", "해수부 관계자", "지도부 핵심 관계자", "당 수석"
    ANON_SUFFIXES = ('관계자', '당국자', '소식통', '측근', '핵심', '인사', '수석', '대변인', '고위급', '고위 관계자')
    for suffix in ANON_SUFFIXES:
        if speaker.endswith(suffix) and speaker != suffix:
            return False
    
    # "A부 B" 패턴 (정부부처 + 직급) — 이름이 아닌 익명 출처
    if re.match(r'^[가-힣]+부\s+[가-힣]+$', speaker) and len(speaker) <= 8:
        return False
    
    # 한글만 포함 (너무 짧은 일반어 필터)
    if len(speaker) == 2 and not re.match(r'^[가-힣]{2}$', speaker):
        return False
    
    # 사진 캡션 관련 단어 필터
    if re.search(r'(사진|촬영|제공|뉴시스|연합뉴스|뉴스1|AP|로이터|AFP)', speaker):
        return False
    
    if any(pat in speaker for pat in SPEAKER_BAD_PATTERNS):
        return False
    
    if re.search(r'(이라고|라고|라며|면서|질문)', speaker):
        return False
    
    return True

def score_quote_confidence(speaker, quote):
    """발언 추출 신뢰도 점수 (0~1)."""
    score = 0.65
    reasons = []
    
    if not speaker or len(speaker) < 2:
        return 0.0, ['발언자 없음']
    
    if speaker in SPEAKER_STOPWORDS or any(p in speaker for p in SPEAKER_BAD_PATTERNS):
        return 0.0, ['발언자 오추출 패턴']
    
    # 직함/실명 패턴 가산
    if re.search(TITLE_PATTERN, speaker):
        score += 0.15
    if re.match(r'^[가-힣]{2,4}$', speaker):
        score += 0.05
    if re.match(r'^[가-힣]{2,4}\s+[가-힣]{2,10}$', speaker):
        score += 0.1
    
    # 저품질 힌트 감점
    if re.search(r'(질문|라고 말|이라고 말|하나|경고|사람)', speaker):
        score -= 0.35
        reasons.append('발언자 형태가 부정확')
    
    if len(quote) < 18:
        score -= 0.2
        reasons.append('인용문이 너무 짧음')
    
    if re.search(r'(사진|제공|기자|연합뉴스|뉴시스)', quote):
        score -= 0.25
        reasons.append('캡션/메타 가능성')
    
    return max(0.0, min(1.0, score)), reasons

def extract_numbers(text):
    """기사 본문에서 숫자/통계 팩트를 추출한다."""
    facts = []
    if not text:
        return facts
    
    sentences = re.split(r'[.。]\s*', text)
    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 15 or len(sent) > 300:
            continue
        
        # 숫자+단위가 포함된 문장
        if re.search(r'\d+(?:\.\d+)?(?:%|조|억|만|원|달러|명|개|건|곳|위|기|발|배|차|호)', sent):
            # 사진 캡션 필터
            if re.match(r'^[가-힣]+\s+[가-힣]+.*(?:사진|촬영|제공|뉴시스|연합뉴스)', sent):
                continue
            # 기사 메타데이터 필터
            if re.search(r'(입력|수정|기자|특파원)\s*\d{4}', sent):
                continue
            facts.append(sent)
    
    return facts[:5]

# ═══════════════════════════════════════════════════════
# 3. 클러스터링 (제목 키워드 기반)
# ═══════════════════════════════════════════════════════

STOPWORDS = set(
    '것 등 위 위해 대해 있다 했다 한다 있는 하는 되는 없는 통해 중인 '
    '대한 관련 따르면 의해 모든 이번 지난 오늘 내일 올해 작년 가장 '
    '더욱 이미 아직 다시 매우 정도 가능 필요 문제 상황'.split()
)

def extract_keywords(title):
    """제목에서 핵심 키워드 추출."""
    # [사설], [단독] 등 태그 제거
    title = re.sub(r'\[.*?\]', '', title)
    words = re.findall(r'[가-힣]{2,}', title)
    return set(w for w in words if w not in STOPWORDS and len(w) >= 2)

def simple_cluster(articles, min_overlap=2, is_column=False):
    """제목 키워드 겹침 기반 간이 클러스터링.
    
    칼럼 모드 (is_column=True)일 때는 클러스터링을 스킵하고
    각 기사를 독립 클러스터로 반환.
    """
    for art in articles:
        art['_keywords'] = extract_keywords(art['title'])
    
    # 칼럼 모드: 각 기사 = 독립 클러스터
    if is_column:
        clusters = []
        for art in articles:
            clusters.append({
                'articles': [art],
                'papers': [art['press']],
                'title': art['title'],
                'keywords': art['_keywords']
            })
        # 칼럼은 전부 "단독"으로 처리
        return [], clusters
    
    # 일반 모드: 기존 클러스터링 로직
    clusters = []
    used = set()
    
    for i, art in enumerate(articles):
        if i in used:
            continue
        
        cluster = [art]
        used.add(i)
        
        for j, other in enumerate(articles):
            if j in used:
                continue
            overlap = art['_keywords'] & other['_keywords']
            if len(overlap) >= min_overlap or (len(overlap) >= 1 and len(art['_keywords']) <= 3):
                cluster.append(other)
                used.add(j)
        
        papers = set(a['press'] for a in cluster)
        clusters.append({
            'articles': cluster,
            'papers': sorted(papers),
            'title': cluster[0]['title'],
            'keywords': art['_keywords']
        })
    
    # 2개 이상 신문 → 주요 클러스터, 1개 → 단독/소수
    multi = [c for c in clusters if len(c['papers']) >= 2]
    single = [c for c in clusters if len(c['papers']) < 2]
    
    # 기사 수 기준 정렬
    multi.sort(key=lambda c: len(c['articles']), reverse=True)
    single.sort(key=lambda c: len(c['articles']), reverse=True)
    
    return multi, single

# ═══════════════════════════════════════════════════════
# 4. 클러스터 분석 데이터 추출
# ═══════════════════════════════════════════════════════

def analyze_cluster(cluster):
    """클러스터에서 가이드 v3.1 기준 데이터 추출.
    
    반환 구조:
    {
        title, papers, summary,
        facts: [{text, paper, url}],             # 숫자/팩트만
        quotes: [{speaker, quote, paper, url}],  # 실제 발언만
        temperature: str,                        # 온도차 (독립)
        per_paper: {press: summary},             # 신문별 한줄 (독립)
        context_keywords: str,                   # 한줄 맥락 (독립)
        comments: [{speaker, quote, paper, url}], # 중요 코멘트
        best_quote: {speaker, quote, paper, url}, # 대표 인용
    }
    """
    articles = cluster['articles']
    papers = cluster['papers']
    
    all_quotes = []
    all_facts = []
    paper_summaries = {}
    article_links = []
    rejected_quotes = 0
    
    for art in articles:
        content = art.get('content', '') or art.get('summary_2sent', '')
        press = art['press']
        url = art.get('url', '') or art.get('origin_url', '')
        
        # 발언자 추출 (CSV 원문에서 직접)
        quotes = extract_quotes(content)
        for q in quotes:
            q_score, q_reasons = score_quote_confidence(q['speaker'], q['quote'])
            if q_score < 0.45:
                rejected_quotes += 1
                continue
            q['paper'] = press
            q['url'] = url
            q['confidence'] = q_score
            q['confidence_reasons'] = q_reasons
            all_quotes.append(q)
        
        # 숫자/팩트 추출
        facts = extract_numbers(content)
        for f in facts:
            all_facts.append({'text': f, 'paper': press, 'url': url})
        
        # 신문별 요약 (캡션 필터 적용)
        if press not in paper_summaries:
            summary = art.get('summary_2sent', '')
            if summary:
                sents = re.split(r'[.。]\s*', summary)
                for sent in sents:
                    sent = sent.strip()
                    if sent and len(sent) > 10 and not is_caption(sent) and '기자' not in sent:
                        paper_summaries[press] = sent
                        break
        
        # 기사 링크 수집
        if url and 'nan' not in url.lower():
            article_links.append({'press': press, 'url': url, 'title': art['title']})
    
    # 중복 제거
    unique_quotes = deduplicate(all_quotes, key=lambda q: (q['speaker'], q['quote']))
    unique_facts = deduplicate(all_facts, key=lambda f: f['text'][:30])
    
    unique_quotes.sort(key=lambda q: q.get('confidence', 0), reverse=True)
    
    # 핵심 요약
    summary = build_summary(articles)
    
    # 온도차
    temperature = build_temperature(articles, papers)
    
    # 신문별 한줄 (모든 신문 포함)
    per_paper = paper_summaries
    
    # 한줄 맥락
    context = build_context(articles, cluster['keywords'])
    
    # 대표 인용 (발언자 확인된 것만)
    best_quote = unique_quotes[0] if unique_quotes else None
    
    # 중요 코멘트 vs 발언/인용 중복 방지
    # comments는 상위 3개, quotes는 comments에 없는 것만 별도 최대 5개
    comments = unique_quotes[:3]
    comment_keys = set(q['quote'][:30] for q in comments)
    remaining_quotes = [q for q in unique_quotes if q['quote'][:30] not in comment_keys]
    
    cluster_confidence = score_cluster_confidence(cluster)
    priority_score = score_priority(
        cluster=cluster,
        quote_count=len(unique_quotes),
        fact_count=len(unique_facts),
        cluster_confidence=cluster_confidence,
    )
    
    return {
        'title': clean_title(cluster['title']),
        'papers': papers,
        'summary': summary,
        'comments': comments,
        'best_quote': best_quote,
        'facts': unique_facts[:5],
        'quotes': remaining_quotes[:5],
        'temperature': temperature,
        'per_paper': per_paper,
        'context_keywords': context,
        'article_links': article_links,
        'cluster_confidence': cluster_confidence,
        'priority_score': priority_score,
        'kept_quotes': len(unique_quotes),
        'rejected_quotes': rejected_quotes,
    }

def deduplicate(items, key):
    """키 함수 기반 중복 제거."""
    seen = set()
    result = []
    for item in items:
        k = key(item)
        if k not in seen:
            seen.add(k)
            result.append(item)
    return result

def clean_title(title):
    """클러스터 제목 정제."""
    title = re.sub(r'\[.*?\]', '', title).strip()
    # 말줄임표 처리
    if len(title) > 60:
        title = title[:57] + '…'
    return title

def is_caption(text):
    """사진 캡션인지 판별.
    
    캡션 특징: ~하고 있다, ~모습, 촬영, 제공, 기자, 기념 촬영 등.
    """
    if not text:
        return True
    text = text.strip()
    
    # 직접적 캡션 키워드
    if re.search(r'(사진[=:]|촬영[=:]|제공[=:]|뉴시스|연합뉴스|뉴스1|AP통신|로이터)', text):
        return True
    
    # "~하고 있다" / "~모습" 패턴 (사진 설명)
    # 단, 인용부호("") 안의 내용은 발언이므로 제외
    text_no_quotes = re.sub(r'["\u201C\u201D][^"\u201C\u201D]*["\u201C\u201D]', '', text)
    if re.search(r'(하고\s*있다|하는\s*모습|모습이다|바라보고\s*있다|촬영하고|기념\s*촬영|자리를\s*함께)', text_no_quotes):
        return True
    
    # "OOO 기자" 로만 구성된 짧은 문장 (기사 바이라인)
    if re.match(r'^[가-힣]{2,4}\s*기자$', text):
        return True
    
    # 너무 짧은 문장 (캡션일 가능성 높음)
    if len(text) < 12:
        return True
    
    return False

def _score_summary_sentence(sent):
    score = 0.0
    
    if 25 <= len(sent) <= 140:
        score += 1.5
    if re.search(r'\d+(?:\.\d+)?(?:%|조|억|만|원|달러|명|건|개)', sent):
        score += 1.2
    if re.search(r'["\u201C\u201D]', sent):
        score += 1.0
    if re.search(r'(정부|대통령|총리|장관|법원|검찰|금리|주가|환율|유가|수출|성장률)', sent):
        score += 0.8
    
    if is_caption(sent):
        score -= 3.0
    if re.search(r'(기자|특파원|연합뉴스|뉴시스)', sent):
        score -= 1.5
    
    return score

def build_summary(articles):
    """핵심 요약: 클러스터 내 문장 후보를 점수화해 1~2문장 선택."""
    candidates = []
    
    for art in articles:
        text = (art.get('summary_2sent', '') or '') + '. ' + (art.get('content', '') or '')[:400]
        for sent in re.split(r'[.。]\s*', text):
            s = sent.strip()
            if not s or len(s) < 12:
                continue
            sc = _score_summary_sentence(s)
            if sc > 0:
                candidates.append((sc, s))
    
    if not candidates:
        return ''
    
    candidates.sort(key=lambda x: x[0], reverse=True)
    picked = []
    seen_prefix = set()
    
    for _, sent in candidates:
        k = sent[:28]
        if k in seen_prefix:
            continue
        seen_prefix.add(k)
        picked.append(sent)
        if len(picked) == 2:
            break
    
    if not picked:
        return ''
    
    out = '. '.join(picked)
    if not out.endswith('.'):
        out += '.'
    return out

def build_temperature(articles, papers):
    """온도차: 신문별 제목 프레임 비교.
    
    주의: LLM 없이는 깊은 분석이 불가. 제목 기반 기계적 비교만 수행.
    """
    if len(papers) < 2:
        return ""
    
    paper_titles = {}
    for art in articles:
        press = art['press']
        if press not in paper_titles:
            paper_titles[press] = art['title']
    
    parts = []
    for press, title in paper_titles.items():
        clean = re.sub(r'\[.*?\]', '', title).strip()
        if len(clean) > 35:
            clean = clean[:32] + '…'
        parts.append(f"{press}는 '{clean}' 프레임")
    
    if len(parts) >= 2:
        return ', '.join(parts) + '으로 다뤘다.'
    return ""

def build_context(articles, keywords):
    """한줄 맥락: 핵심 키워드 기반."""
    kw_list = sorted(keywords)[:5]
    if kw_list:
        return ', '.join(kw_list)
    return clean_title(articles[0]['title'])

def score_cluster_confidence(cluster):
    """클러스터 응집도 기반 신뢰도 (0~100)."""
    arts = cluster['articles']
    if len(arts) < 2:
        return 35
    
    keyword_sets = [a.get('_keywords', set()) for a in arts if a.get('_keywords')]
    
    pair_scores = []
    for i in range(len(keyword_sets)):
        for j in range(i + 1, len(keyword_sets)):
            a, b = keyword_sets[i], keyword_sets[j]
            if not a or not b:
                continue
            inter = len(a & b)
            union = len(a | b)
            if union:
                pair_scores.append(inter / union)
    
    avg_jaccard = mean(pair_scores) if pair_scores else 0.0
    
    press_count = len(cluster['papers'])
    size_score = min(len(arts), 10) / 10.0
    press_score = min(press_count, 4) / 4.0
    
    conf = (avg_jaccard * 0.55 + size_score * 0.2 + press_score * 0.25) * 100
    return int(max(0, min(100, round(conf))))

def score_priority(cluster, quote_count, fact_count, cluster_confidence):
    """편집 우선순위 점수 (0~100)."""
    article_count = len(cluster['articles'])
    press_count = len(cluster['papers'])
    
    score = 0.0
    score += min(article_count, 12) * 2.8
    score += min(press_count, 6) * 8.0
    score += min(quote_count, 8) * 1.8
    score += min(fact_count, 8) * 1.4
    score += cluster_confidence * 0.22
    
    return int(max(0, min(100, round(score))))

def _pick_fact_points(data, limit=3):
    picked = []
    for f in data.get('facts', []):
        text = f.get('text', '').strip()
        if len(text) < 20:
            continue
        if not re.search(r'\d', text):
            continue
        picked.append(f)
        if len(picked) >= limit:
            break
    return picked

def _pick_quote_points(data, limit=2):
    pool = []
    if data.get('best_quote'):
        pool.append(data['best_quote'])
    pool.extend(data.get('comments', []))
    pool.extend(data.get('quotes', []))
    
    out = []
    seen = set()
    for q in pool:
        key = (q.get('speaker', ''), q.get('quote', ''))
        if key in seen:
            continue
        seen.add(key)
        if len(q.get('quote', '').strip()) < 18:
            continue
        out.append(q)
        if len(out) >= limit:
            break
    return out

def build_why_important(data):
    """편집용 '왜 중요한가' 1문장 생성."""
    reasons = []
    
    if len(data.get('papers', [])) >= 3:
        reasons.append('여러 신문이 동시 보도한 공통 의제')
    if len(data.get('facts', [])) >= 2:
        reasons.append('수치 근거가 확인되는 이슈')
    if len(data.get('quotes', [])) + len(data.get('comments', [])) >= 2:
        reasons.append('직접 인용으로 갈등 축을 잡을 수 있음')
    if data.get('cluster_confidence', 0) < 45:
        reasons.append('다만 클러스터 응집도가 낮아 교차 검증 필요')
    
    if not reasons:
        return '단일 기사 요약보다 맥락 비교에 유리한 재료이므로 우선 검토 가치가 있다.'
    
    return '이 이슈는 ' + '·'.join(reasons[:3]) + '.'

# ═══════════════════════════════════════════════════════
# 5. HTML 렌더링 (openclaw 디자인 기반, 구조는 가이드 v3.1)
# ═══════════════════════════════════════════════════════

def url_to_link(url, paper=None):
    """URL → <a> 태그. 신문사 자동 감지."""
    if not url or 'nan' in url.lower():
        return ''
    
    if not paper:
        if 'chosun' in url:
            paper = '조선'
        elif 'joongang' in url:
            paper = '중앙'
        elif 'donga' in url:
            paper = '동아'
        elif 'khan' in url or 'kyunghyang' in url:
            paper = '경향'
        elif 'hani' in url:
            paper = '한겨레'
        elif 'hankookilbo' in url:
            paper = '한국'
        else:
            paper = '링크'
    
    return f'<a href="{url}" target="_blank">[{paper}]</a>'

CSS = """
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", sans-serif;
    max-width: 900px;
    margin: 40px auto;
    padding: 0 20px;
    line-height: 1.7;
    color: #222;
    background: #fdad00;
}

h2 {
    font-size: 20px;
    color: #0066cc;
    border-left: 4px solid #0066cc;
    padding-left: 10px;
    margin-top: 40px;
}

h3 {
    font-size: 18px;
    color: #333;
    margin-top: 30px;
}

h4 {
    font-size: 15px;
    color: #555;
    margin-top: 18px;
    margin-bottom: 8px;
}

.meta {
    color: #666;
    font-size: 14px;
    margin-bottom: 15px;
}

.section {
    background: #fff;
    padding: 20px;
    margin: 20px 0;
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
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

.temperature {
    background: #e8f4fd;
    padding: 10px;
    margin: 10px 0;
    border-radius: 4px;
    font-size: 14px;
}

.per-paper {
    font-size: 14px;
    color: #444;
}

.context-kw {
    font-size: 13px;
    color: #888;
    margin-top: 8px;
}
"""

def render_html(date_str, multi_clusters, single_clusters, all_articles, is_column=False):
    """가이드 v4 기준 HTML 생성.
    
    일반 모드 섹션 순서:
    1. 메타 정보
    2. 주요 키워드 (상위 4개 클러스터)
    3. 쓸고퀄 디테일 (단독 기사 중 재료가 강한 것)
    4. 오늘의 주요 이슈 (클러스터 목록)
    5. 클러스터 상세 (각 클러스터 풀 분석)
    
    칼럼 모드 섹션 순서:
    1. 메타 정보
    2. 오늘의 칼럼 (전체 칼럼 목록)
    3. 칼럼 상세 (각 칼럼의 논지 + 핵심 문장)
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    press_count = len(set(a['press'] for a in all_articles))
    
    analyzed_multi = []
    for cl in multi_clusters:
        analyzed_multi.append((cl, analyze_cluster(cl)))
    analyzed_multi.sort(key=lambda x: x[1]['priority_score'], reverse=True)
    
    def esc(s):
        return html.escape(str(s), quote=True)
    
    parts = []
    
    # ── HEAD ──
    parts.append(f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>슬로우레터 기초 자료 ({date_str})</title>
<style>
{CSS}
</style>
</head>
<body>
''')
    
    # ── 메타 ──
    parts.append('<div class="section">')
    if is_column:
        parts.append('<p><strong>슬로우레터 칼럼 자료</strong></p>')
    else:
        parts.append('<p><strong>슬로우레터 기초 자료</strong></p>')
    parts.append(f'<p class="meta">기준일: {date_str}</p>')
    parts.append(f'<p class="meta">생성 시각: {now}</p>')
    if is_column:
        parts.append(f'<p class="meta">분석 대상: {press_count}개 신문 {len(all_articles)}개 칼럼</p>')
    else:
        parts.append(f'<p class="meta">분석 대상: {press_count}개 신문 {len(all_articles)}개 기사</p>')
    parts.append(f'<p class="meta">생성 방식: CSV 원본 직접 처리 (generate_materials_v4.py)</p>')
    parts.append('</div>')
    
    # ═════════════════════════════════════════════════════
    # 칼럼 모드: 간소화된 섹션
    # ═════════════════════════════════════════════════════
    if is_column:
        # 칼럼은 전부 single_clusters에 들어있음 (각 칼럼 = 독립 클러스터)
        parts.append('<h2>오늘의 칼럼</h2>')
        parts.append(f'<p class="meta">총 {len(single_clusters)}개 칼럼</p>')
        
        # 신문사별로 그룹화
        by_press = defaultdict(list)
        for cl in single_clusters:
            art = cl['articles'][0]
            by_press[art['press']].append(cl)
        
        for press in sorted(by_press.keys()):
            parts.append(f'<h3>{press} ({len(by_press[press])}개)</h3>')
            for cl in by_press[press]:
                analyzed = analyze_cluster(cl)
                parts.append('<div class="cluster-item">')
                parts.append(f'<p><strong>{esc(analyzed["title"])}</strong></p>')
                
                if analyzed['best_quote']:
                    q = analyzed['best_quote']
                    parts.append(f'<div class="point">"{esc(q["quote"])}" / {esc(q["speaker"])}</div>')
                elif analyzed['summary']:
                    parts.append(f'<div class="point">{esc(analyzed["summary"])}</div>')
                
                if analyzed['article_links']:
                    link = url_to_link(analyzed['article_links'][0]['url'], press)
                    parts.append(f'<p class="press-links">{link}</p>')
                
                parts.append('</div>')
        
        parts.append('<hr>')
        
        # 칼럼 상세
        parts.append('<h2>칼럼 상세</h2>')
        parts.append('<p class="meta">각 칼럼의 논지 + 핵심 문장</p>')
        
        for press in sorted(by_press.keys()):
            for cl in by_press[press]:
                analyzed = analyze_cluster(cl)
                parts.append('<div class="section">')
                parts.append(f'<h3>{esc(analyzed["title"])}</h3>')
                parts.append(f'<p class="press-list">{press}</p>')
                
                if analyzed['summary']:
                    parts.append(f'<p><strong>[논지]</strong> {esc(analyzed["summary"])}</p>')
                
                # 핵심 문장 (인용 or 팩트)
                if analyzed['quotes']:
                    parts.append('<h4>핵심 문장</h4>')
                    parts.append('<ul>')
                    for q in analyzed['quotes'][:3]:
                        parts.append(f'<li>"{esc(q["quote"])}" / {esc(q["speaker"])}</li>')
                    parts.append('</ul>')
                
                if analyzed['facts']:
                    parts.append('<h4>주요 내용</h4>')
                    parts.append('<ul>')
                    for f in analyzed['facts'][:3]:
                        parts.append(f'<li>{esc(f["text"])}</li>')
                    parts.append('</ul>')
                
                if analyzed['article_links']:
                    parts.append(f'<p class="press-links">{url_to_link(analyzed["article_links"][0]["url"], press)}</p>')
                
                parts.append('</div>')
        
        # 칼럼 모드는 여기서 종료
        parts.append(f'<p class="meta" style="margin-top:40px; text-align:center;">생성: generate_materials_v4.py (칼럼 모드) | {now}</p>')
        parts.append('</body>')
        parts.append('</html>')
        return ' '.join(parts)
    
    # ═════════════════════════════════════════════════════
    # 일반 모드: 기존 섹션 (지면 기사)
    # ═════════════════════════════════════════════════════
    
    # ── 1. 주요 키워드 ──
    top4 = analyzed_multi[:4]
    if top4:
        parts.append('<h2>주요 키워드</h2>')
        parts.append('<p class="meta">기준: 우선순위 점수 상위 4개.</p>')
        for _, data in top4:
            parts.append('<div class="cluster-item">')
            papers_str = ', '.join(data['papers'])
            parts.append(
                f'<p><strong>{esc(data["title"])}</strong> ({esc(papers_str)}) '
                f'<span class="meta">우선순위 {data["priority_score"]} / 신뢰도 {data["cluster_confidence"]}</span></p>'
            )
            if data['best_quote']:
                q = data['best_quote']
                parts.append(f'<div class="point">"{esc(q["quote"])}" / {esc(q["speaker"])}</div>')
            elif data['summary']:
                parts.append(f'<div class="point">{esc(data["summary"])}</div>')
            
            # 기사 링크
            if data['article_links']:
                links = [url_to_link(al['url'], al['press']) for al in data['article_links'][:6]]
                parts.append(f'<p class="press-links">{" ".join(links)}</p>')
            
            parts.append('</div>')
        parts.append('<hr>')
    
    # ── 2. 쓸고퀄 디테일 ──
    # 단독 기사 중 인용/숫자가 강한 것
    sogoqual = []
    for cl in single_clusters[:20]:
        art = cl['articles'][0]
        content = art.get('content', '') or art.get('summary_2sent', '')
        quotes = extract_quotes(content)
        facts = extract_numbers(content)
        if quotes or len(facts) >= 2:
            sogoqual.append({
                'article': art,
                'quotes': quotes,
                'facts': facts,
            })
    sogoqual = sogoqual[:7]
    
    if sogoqual:
        parts.append('<h2>쓸고퀄 디테일</h2>')
        parts.append('<p class="meta">기준: 단독/소수에서 공적 가치·직접 인용·숫자 재료가 강한 것 최대 7개.</p>')
        for item in sogoqual:
            art = item['article']
            parts.append('<div class="cluster-item">')
            parts.append(f'<p><strong>{esc(art["press"])}:</strong> {esc(art["title"])}</p>')
            if item['quotes']:
                q = item['quotes'][0]
                parts.append(f'<div class="point">"{esc(q["quote"])}" / {esc(q["speaker"])}</div>')
            elif item['facts']:
                parts.append(f'<div class="point">{esc(item["facts"][0])}</div>')
            
            url = art.get('url', '') or art.get('origin_url', '')
            if url and 'nan' not in url.lower():
                parts.append(f'<p class="press-links">{url_to_link(url, art["press"])}</p>')
            
            parts.append('</div>')
        parts.append('<hr>')
    
    # ── 3. 오늘의 주요 이슈 ──
    issue_clusters = analyzed_multi[:15]
    if issue_clusters:
        parts.append('<h2>오늘의 주요 이슈</h2>')
        parts.append('<p class="meta">기준: 우선순위 상위 15개, 편집 브리프(사실+직접인용+왜 중요한가) 제공.</p>')
        
        for _, data in issue_clusters:
            parts.append('<div class="cluster-item">')
            papers_str = ', '.join(data['papers'])
            parts.append(
                f'<p><strong>{esc(data["title"])}</strong> ({esc(papers_str)}) '
                f'<span class="meta">우선순위 {data["priority_score"]} / 신뢰도 {data["cluster_confidence"]} / '
                f'인용 유지 {data["kept_quotes"]}, 제거 {data["rejected_quotes"]}</span></p>'
            )
            
            if data['best_quote']:
                q = data['best_quote']
                parts.append(f'<div class="point">"{esc(q["quote"])}" / {esc(q["speaker"])}</div>')
            elif data['summary']:
                parts.append(f'<div class="point">{esc(data["summary"])}</div>')
            
            fact_points = _pick_fact_points(data, limit=2)
            quote_points = _pick_quote_points(data, limit=1)
            
            if fact_points:
                parts.append('<p><strong>사실</strong></p><ul>')
                for f in fact_points:
                    parts.append(f'<li>{esc(f["text"])}</li>')
                parts.append('</ul>')
            
            if quote_points:
                q = quote_points[0]
                parts.append(f'<p><strong>직접인용</strong> "{esc(q["quote"])}" / {esc(q["speaker"])}</p>')
            
            parts.append(f'<p><strong>왜 중요한가</strong> {esc(build_why_important(data))}</p>')
            
            if data['article_links']:
                links = [url_to_link(al['url'], al['press']) for al in data['article_links'][:6]]
                parts.append(f'<p class="press-links">{" ".join(links)}</p>')
            
            parts.append('</div>')
        
        parts.append('<hr>')
    
    # ── 4. 클러스터 상세 ──
    # 가이드 v3.1 핵심: 각 섹션 완전 분리
    detail_clusters = analyzed_multi[:15]
    if detail_clusters:
        parts.append('<h2>클러스터 상세</h2>')
        parts.append('<p class="meta">가이드 v4: 편집 브리프 중심(사실 2~3개 + 직접인용 1~2개 + 왜 중요한가) + 근거 섹션</p>')
        
        for _, data in detail_clusters:
            parts.append('<div class="section">')
            parts.append(f'<h3>{esc(data["title"])}</h3>')
            parts.append(
                f'<p class="meta">우선순위 {data["priority_score"]} / 클러스터 신뢰도 {data["cluster_confidence"]} '
                f'/ 인용 유지 {data["kept_quotes"]}, 제거 {data["rejected_quotes"]}</p>'
            )
            
            # 언론사
            papers_str = ', '.join(data['papers'])
            parts.append(f'<p class="press-list">언론: {papers_str}</p>')
            
            # 핵심 요약
            if data['summary']:
                parts.append(f'<p><strong>[핵심]</strong> {esc(data["summary"])}</p>')
            
            # 편집 브리프
            parts.append('<h4>편집 브리프</h4>')
            
            fact_points = _pick_fact_points(data, limit=3)
            quote_points = _pick_quote_points(data, limit=2)
            
            if fact_points:
                parts.append('<p><strong>사실 (2~3개)</strong></p><ul>')
                for f in fact_points:
                    link = url_to_link(f.get('url', ''), f.get('paper', ''))
                    parts.append(f'<li>{esc(f["text"])} {link}</li>')
                parts.append('</ul>')
            
            if quote_points:
                parts.append('<p><strong>직접인용 (1~2개)</strong></p><ul>')
                for q in quote_points:
                    link = url_to_link(q.get('url', ''), q.get('paper', ''))
                    parts.append(f'<li>"{esc(q["quote"])}" / {esc(q["speaker"])} '
                               f'<span class="meta">(신뢰도 {int(q.get("confidence", 0)*100)})</span> {link}</li>')
                parts.append('</ul>')
            
            parts.append(f'<p><strong>왜 중요한가</strong> {esc(build_why_important(data))}</p>')
            
            # ▼ 여기서부터 v3.1 핵심: 각 섹션 완전 분리 ▼
            
            # ── 숫자/팩트 (발언 절대 혼입 금지) ──
            if data['facts']:
                parts.append('<h4>숫자/팩트</h4>')
                parts.append('<ul>')
                for f in data['facts']:
                    link = url_to_link(f.get('url', ''), f.get('paper', ''))
                    parts.append(f'<li>{esc(f["text"])} {link}</li>')
                parts.append('</ul>')
            
            # ── 발언/인용 (숫자 절대 혼입 금지) ──
            if data['quotes']:
                parts.append('<h4>발언/인용</h4>')
                parts.append('<ul>')
                for q in data['quotes']:
                    link = url_to_link(q.get('url', ''), q.get('paper', ''))
                    parts.append(f'<li>"{esc(q["quote"])}" / {esc(q["speaker"])} '
                               f'<span class="meta">(신뢰도 {int(q.get("confidence", 0)*100)})</span> {link}</li>')
                parts.append('</ul>')
            
            # ── 온도차 (독립 섹션) ──
            if data['temperature']:
                parts.append('<h4>온도차</h4>')
                parts.append(f'<div class="temperature">{data["temperature"]}</div>')
            
            # ── 신문별 한줄 (독립 섹션, 모든 신문 포함) ──
            if data['per_paper']:
                parts.append('<h4>신문별 한줄</h4>')
                parts.append('<ul class="per-paper">')
                for press, summ in data['per_paper'].items():
                    parts.append(f'<li><strong>{esc(press)}:</strong> {esc(summ)}</li>')
                parts.append('</ul>')
            
            # ── 한줄 맥락 (독립 섹션) ──
            if data['context_keywords']:
                parts.append(f'<p class="context-kw"><strong>한줄 맥락:</strong> {esc(data["context_keywords"])}</p>')
            
            # 기사 링크
            if data['article_links']:
                parts.append('<h4>관련 기사</h4>')
                parts.append('<p class="press-links">')
                for al in data['article_links'][:8]:
                    parts.append(f'<a href="{al["url"]}" target="_blank">[{esc(al["press"])}] {esc(al["title"][:30])}</a><br>')
                parts.append('</p>')
            
            parts.append('</div>')
    
    # ── FOOTER ──
    parts.append(f'<p class="meta" style="margin-top:40px; text-align:center;">생성: generate_materials_v4.py | {now}</p>')
    parts.append('</body>')
    parts.append('</html>')
    
    return ' '.join(parts)

# ═══════════════════════════════════════════════════════
# 6. 품질 검증
# ═══════════════════════════════════════════════════════

def quality_check(html_text):
    """가이드 v3.1 기준 품질 체크."""
    issues = []
    
    # 1. (발언자 미상) 체크
    count = html_text.count('(발언자 미상)')
    if count > 0:
        issues.append(f'❌ "(발언자 미상)" {count}건 발견')
    else:
        issues.append('✅ "(발언자 미상)" 0건')
    
    # 2. 중복 섹션 체크
    facts_count = html_text.count('<h4>숫자/팩트</h4>')
    quotes_count = html_text.count('<h4>발언/인용</h4>')
    temp_count = html_text.count('<h4>온도차</h4>')
    cluster_count = html_text.count('<h3>')
    
    if cluster_count > 0:
        # 각 클러스터에 최대 1개씩만 있어야 함
        if facts_count <= cluster_count and quotes_count <= cluster_count:
            issues.append(f'✅ 섹션 분리 정상 (클러스터 {cluster_count}개, 팩트 {facts_count}개, 발언 {quotes_count}개)')
        else:
            issues.append(f'❌ 섹션 중복 의심 (클러스터 {cluster_count}개인데 팩트 {facts_count}개, 발언 {quotes_count}개)')
    
    # 3. 사진 캡션 혼입 체크
    caption_patterns = ['사진=', '촬영=', '제공=', '뉴시스', '연합뉴스']
    caption_in_quotes = 0
    for pat in caption_patterns:
        # <h4>발언/인용</h4> 이후 <h4> 이전에 해당 패턴이 있으면
        # (간이 체크: 전체 발언 섹션에서)
        caption_in_quotes += html_text.count(pat)
    
    if caption_in_quotes > 0:
        issues.append(f'⚠️ 발언/인용 섹션 캡션/통신사 키워드 {caption_in_quotes}건')
    
    # 4. 빈 섹션 체크
    empty_sections = len(re.findall(r'<h4>[^<]+</h4>\s*<h4>', html_text))
    if empty_sections > 0:
        issues.append(f'⚠️ 빈 섹션 {empty_sections}개')
    
    # 5. 중요 코멘트 ↔ 발언/인용 중복 체크 (클러스터 단위)
    import re as _re
    sections = _re.split(r'<div class="section">', html_text)
    dup_count = 0
    
    for sec in sections:
        comments = _re.findall(r'<h4>중요 코멘트</h4>(.*?)</ul>', sec, _re.DOTALL)
        quotes = _re.findall(r'<h4>발언/인용</h4>(.*?)</ul>', sec, _re.DOTALL)
        
        if comments and quotes:
            # <li> 안의 인용문만 추출 (URL 제외)
            c_texts = set(_re.findall(r'<li>\s*"([^"]{10,40})', comments[0]))
            q_texts = set(_re.findall(r'<li>\s*"([^"]{10,40})', quotes[0]))
            dup_count += len(c_texts & q_texts)
    
    if dup_count > 0:
        issues.append(f'⚠️ 중요 코멘트↔발언/인용 중복 {dup_count}건')
    else:
        issues.append('✅ 중요 코멘트↔발언/인용 중복 0건')
    
    # 6. 사진 캡션 혼입 체크 ([핵심] 요약 + 신문별 한줄에서만 확인)
    caption_in_content = 0
    
    # [핵심] 요약 텍스트 추출
    summaries = _re.findall(r'\[핵심\]\s*</strong>\s*(.+?)</p>', html_text)
    # 신문별 한줄 텍스트 추출
    per_papers = _re.findall(r'<li><strong>[^<]+:</strong>\s*(.+?)</li>', html_text)
    
    for text in summaries + per_papers:
        for pat in ['하고 있다', '하는 모습', '모습이다', '기념 촬영', '촬영=', '사진=']:
            if pat in text:
                caption_in_content += 1
    
    if caption_in_content > 0:
        issues.append(f'⚠️ [핵심]/신문별 캡션 혼입 {caption_in_content}건')
    else:
        issues.append('✅ 캡션 혼입 0건')
    
    return issues

# ═══════════════════════════════════════════════════════
# 7. 메인 실행
# ═══════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("사용법: python generate_materials_v4.py <CSV파일> [--date YYYYMMDD]")
        sys.exit(1)
    
    csv_path = sys.argv[1]
    
    # 날짜 추출
    date_str = None
    if '--date' in sys.argv:
        idx = sys.argv.index('--date')
        if idx + 1 < len(sys.argv):
            date_str = sys.argv[idx + 1]
    
    if not date_str:
        # 파일명에서 날짜 추출 시도
        m = re.search(r'(\d{8})', csv_path)
        if m:
            date_str = m.group(1)
        else:
            date_str = datetime.now().strftime('%Y%m%d')
    
    print(f"📊 CSV 로드: {csv_path}")
    articles = load_csv(csv_path)
    print(f"   → {len(articles)}개 기사 로드됨")
    
    # 칼럼 모드 자동 감지 (page="column")
    is_column = all(a.get('page', '') == 'column' for a in articles)
    
    if is_column:
        print(f"   ✍️ 칼럼 모드 감지")
    
    # 신문별 통계
    press_counter = Counter(a['press'] for a in articles)
    for press, count in press_counter.most_common():
        print(f"     {press}: {count}개")
    
    if is_column:
        print(f"   📝 칼럼 분석 (클러스터링 스킵)...")
    else:
        print(f"   🔗 클러스터링...")
    
    multi, single = simple_cluster(articles, is_column=is_column)
    
    if is_column:
        print(f"   → 총 {len(single)}개 칼럼")
    else:
        print(f"   → 다수 신문 클러스터: {len(multi)}개")
        print(f"   → 단독/소수: {len(single)}개")
    
    print(f"   📝 HTML 생성...")
    html = render_html(date_str, multi, single, articles, is_column=is_column)
    
    # 출력 경로 (스크립트가 있는 디렉토리에 저장)
    out_dir = Path(__file__).parent
    if is_column:
        out_path = out_dir / f'newspaper_column_materials_{date_str}_v4.html'
    else:
        out_path = out_dir / f'newspaper_clusters_materials_{date_str}_v4.html'
    
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"   → {out_path} ({len(html):,}자)")
    
    # 품질 검증
    print(f"   🔍 품질 검증:")
    issues = quality_check(html)
    for issue in issues:
        print(f"     {issue}")
    
    print(f"   ✅ 완료! (v4)")
    return str(out_path)

if __name__ == '__main__':
    main()
