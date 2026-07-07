# 교육자료 인용 소스 큐레이션

> 서브에이전트 3개 병렬 리서치로 수집, **전 URL 접속 검증(2026-07-02)** 통과분만 수록.
> 리다이렉트된 구 URL은 최종 URL로 표기. 슬라이드 각주가 이 목록을 인용한다.

## A. RAG 개념 (Part 1)

| # | 주제 | 제목 | 발행처 | URL |
|---|---|---|---|---|
| A1 | RAG 필요성(한국어) | 검색 증강 생성(RAG)이란 무엇인가요? | Google Cloud | https://cloud.google.com/use-cases/retrieval-augmented-generation?hl=ko |
| A2 | 할루시네이션 억제 | Reduce hallucinations | Anthropic | https://platform.claude.com/docs/en/docs/test-and-evaluate/strengthen-guardrails/reduce-hallucinations |
| A3 | RAG 파이프라인(한국어) | RAG(검색 증강 생성)란 무엇인가요? | AWS | https://aws.amazon.com/ko/what-is/retrieval-augmented-generation/ |
| A4 | RAG 개념 스토리텔링(한국어) | 검색 증강 생성(RAG)이란? | NVIDIA 블로그 코리아 | https://blogs.nvidia.co.kr/blog/what-is-retrieval-augmented-generation/ |
| A5 | 임베딩 시각화 교육 | The Illustrated Word2vec | Jay Alammar | https://jalammar.github.io/illustrated-word2vec/ |
| A6 | RAG 원 논문 | Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks (Lewis et al., NeurIPS 2020) | arXiv | https://arxiv.org/abs/2005.11401 |
| A7 | 청킹 전략 | Chunking Strategies for LLM Applications | Pinecone | https://www.pinecone.io/learn/chunking-strategies/ |
| A8 | 문맥 보존 청킹·하이브리드 효과 수치 | Introducing Contextual Retrieval | Anthropic | https://www.anthropic.com/news/contextual-retrieval |
| A9 | 출처 인용 응답 | Citations | Anthropic | https://platform.claude.com/docs/en/docs/build-with-claude/citations |

## B. 검색·리랭킹 (Part 1 후반 · Part 4)

| # | 주제 | 제목 | 발행처 | URL |
|---|---|---|---|---|
| B1 | BM25 수식 분해 | Practical BM25 — Part 2 | Elastic | https://www.elastic.co/blog/practical-bm25-part-2-the-bm25-algorithm-and-its-variables |
| B2 | 정규화 내적=코사인 | MetricType and distances | Meta·FAISS 공식 위키 | https://github.com/facebookresearch/faiss/wiki/MetricType-and-distances |
| B3 | 시맨틱 검색 개념 | Semantic Search | Sentence Transformers | https://sbert.net/examples/applications/semantic-search/README.html |
| B4 | 하이브리드 융합 방식 | Hybrid Search Explained | Weaviate | https://weaviate.io/blog/hybrid-search-explained |
| B5 | α 가중합 하이브리드 | Getting Started with Hybrid Search | Pinecone | https://www.pinecone.io/learn/hybrid-search-intro/ |
| B6 | bi vs cross-encoder | Cross-Encoders | Sentence Transformers | https://sbert.net/examples/applications/cross-encoder/README.html |
| B7 | 사용 리랭커 모델 카드 | BAAI/bge-reranker-v2-m3 | BAAI·Hugging Face | https://huggingface.co/BAAI/bge-reranker-v2-m3 |
| B8 | 한국어 토크나이제이션 | Nori: Korean Language Analysis | Elastic | https://www.elastic.co/blog/nori-the-official-elasticsearch-plugin-for-korean-language-analysis |

## C. Claude Code (Part 2 · 3)

| # | 주제 | 제목 | URL |
|---|---|---|---|
| C1 | 설치·시작 | Quickstart | https://code.claude.com/docs/en/quickstart |
| C2 | CLAUDE.md·메모리 | How Claude remembers your project | https://code.claude.com/docs/en/memory |
| C3 | 플랜 모드 | Permission modes | https://code.claude.com/docs/en/permission-modes |
| C4 | 서브에이전트 | Create custom subagents | https://code.claude.com/docs/en/sub-agents |
| C5 | 베스트 프랙티스 | Best practices for Claude Code | https://code.claude.com/docs/en/best-practices |
| C6 | 훅 | Hooks reference | https://code.claude.com/docs/en/hooks |
| C7 | 설정 | Claude Code settings | https://code.claude.com/docs/en/settings |
| C8 | 프롬프트 엔지니어링 | Prompt engineering overview | https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview |
| C9 | 공통 워크플로 | Common workflows | https://code.claude.com/docs/en/common-workflows |

## D. 업무매뉴얼 확장 — 도식 텍스트화 (2026-07-07, 저장소 내부 소스)

> 외부 URL이 아니라 이 저장소의 실제 구현 파일. "업무매뉴얼 확장 — 이원 매뉴얼과 도식 텍스트화" 슬라이드의 근거.

| # | 주제 | 파일 / 문서 | 비고 |
|---|---|---|---|
| D1 | PM 템플릿 전용 파서 | `src/parse_pm.py` | 업무매뉴얼(PM) HTML → 구조화 트리, 골든 `tests/test_parse_pm.py` 3종 |
| D2 | 이미지 도식 텍스트화 | `src/extract_pm_images.py` | 2패스 — EasyOCR(ko/en) 전량 추출 → VLM(ollama qwen2.5vl / claude CLI 비전)이 OCR 텍스트 주입받아 흐름도 단계 재구성, sha1 캐시 |
| D3 | 확장 계획·실측 | `업무매뉴얼확장_계획.md` | 이원 매뉴얼 체계·매뉴얼 레벨 스코프·통합 44,340청크·τ 0.5641·품질 실측(Recall@5 100%·부문 top1 94.7%·모호성 감지 90%) |

## 발췌 메모 (슬라이드 반영 근거)

- **A8 Contextual Retrieval**: 청크에 문맥 보존 시 검색 실패율 35%↓, +BM25 하이브리드 49%↓, +리랭킹 67%↓ — 우리 "브레드크럼 경로를 embed_text에 보존" 설계의 정량 근거
- **B7 bge-reranker-v2-m3**: "질문+문서 쌍을 입력받아 임베딩이 아닌 유사도 점수를 직접 출력, sigmoid로 [0,1]" — 관련도 게이트 τ 설계 근거
- **C5 Best practices** 3원칙: ① 검증 수단을 함께 제공 ② 탐색→계획→구현 분리 ③ 구체적 맥락·제약 명시 — Part 2 프롬프트 패턴 슬라이드의 골자
