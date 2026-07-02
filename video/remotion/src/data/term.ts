/* 실제 실행 출력에서 발췌 (사내 서버 주소는 마스킹). 씬 길이에 맞게 트리밍만 수행. */

export const PARSE_OUT = `{
  "screen_id": "AC250400",
  "code": "0878-AC250400",
  "title": "지점계좌서비스약정등록내역",
  "screen_no": "0878",
  "source_url": "http://<사내-매뉴얼-서버>/ST/AC250400.html",
  "summary": "지점별, 계좌별, 서비스종류별 부가서비스 약정 등록 내역을 조회하는 화면...",
  "breadcrumbs": [ ... ]
}
screen=AC250400 title=지점계좌서비스약정등록내역 no=0878
breadcrumbs=62 glossary=3 related=4 qa=1`;

export const CHUNKS_OUT = `AC110100.html: 17 chunks
AC110200.html: 16 chunks
AC110500.html: 2 chunks
  ⋮  (356개 파일 처리)
OF726200.html: 23 chunks
SL203000.html: 3 chunks
wrote data/chunks.jsonl (4443 chunks from 356 file(s))`;

export const INDEX_OUT = `[rag] loading embedder: jhgan/ko-sroberta-multitask (cpu)
[build_index] indexed 4443 chunks  dim=768  model=jhgan/ko-sroberta-multitask
[build_index] wrote data/index/ (dense.faiss, bm25.pkl, chunks.json, meta.json)`;

export const TEST_OUT = `PASS test_counts
PASS test_hierarchy
PASS test_metadata
PASS test_qa_content
PASS test_split_term

5/5 passed`;

export const CLI_Q = 'SMS 일괄 발송은 어디서 하나요?';
export const CLI_OUT = `(로컬 LLM 미연결 — 관련 매뉴얼 근거를 제시합니다.)

[S1] SMS서비스 신청(해지)내역 조회[2401] · 질문보기
     > SMS 일괄 발송은 어디서 하나요?
    SMS발송[2797] 화면에서 최대 50건까지 발송 가능합니다.

[S2] 월간거래내역발송대상 SMS 일괄발송[2755] · 관련화면
    계좌우편물발송내역[2056] — 우편물 발송 내역을 조회하는 화면

[S3] 월간거래내역발송대상 SMS 일괄발송[2755] · 화면설명 > 조건입력
    처리할 조건을 입력하는 창입니다.`;
