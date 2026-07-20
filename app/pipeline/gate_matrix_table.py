"""Stage B(gate_matrix) 6칸 확정 매핑표. 룰_추출_기준_최종확정본.md §Stage B(v1.1/v1.2), db_구축_설계서.md §3.2 §4.2.
data_type 2분류(라이프스타일/생체지표) × function_type 3분류 = 6칸 전부 확정된 닫힌 표라, LLM은
data_type/function_type만 판단하고 verdict/exemption_note는 이 표에서 조회해서 채운다.
"""

DATA_TYPE_ENUM = {"라이프스타일", "생체지표"}
FUNCTION_TYPE_ENUM = {"단순기록", "비교·추이분석", "수치예측·진단"}
MATRIX_VERDICT_ENUM = {"PASS", "CONDITIONAL", "FAIL"}

# 복수 조합 시 우선순위(FAIL > CONDITIONAL > PASS, db_구축_설계서.md §3.2)
VERDICT_PRIORITY = {"FAIL": 3, "CONDITIONAL": 2, "PASS": 1}

GATE_MATRIX_TABLE: dict[tuple[str, str], dict] = {
    ("생체지표", "단순기록"): {"verdict": "PASS", "exemption_note": None},
    ("생체지표", "비교·추이분석"): {"verdict": "CONDITIONAL", "exemption_note": None},
    ("생체지표", "수치예측·진단"): {"verdict": "FAIL", "exemption_note": None},
    ("라이프스타일", "단순기록"): {"verdict": "PASS", "exemption_note": None},
    ("라이프스타일", "비교·추이분석"): {"verdict": "PASS", "exemption_note": None},
    ("라이프스타일", "수치예측·진단"): {"verdict": "CONDITIONAL", "exemption_note": None},
}
