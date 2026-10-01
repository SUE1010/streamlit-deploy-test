# -*- coding: utf-8 -*-
"""
공무직 초과근무수당 엑셀 자동 입력 프로그램
=========================================

기능
----
1) 인사관리시스템에서 받은 `초과근무목록_YYYYMM.xls` (구형 xls) 파일을 읽어
2) `부서연번_N월_공무직_시간외근무수당_부서명_일반부서.xlsx` 보고 양식의
   `자료입력` 시트 A2:S5000 영역에 값만 자동으로 채워 넣고
3) 각 사람 이름 시트 하단의 "1주~5주" 표(소정근로시간/연장근로시간/휴일근무)를
   실제 근무일자를 기준으로 한 일~토 주차 구분에 맞춰 자동 계산해서 채웁니다.
4) `시간입력` 시트 D열(7행부터)의 성명을 읽어, 같은 행 K열/M열에 각각
   "=[성명]!S4" / "=[성명]!U4" 참조 수식을 채웁니다. D열이 비어있는 행을
   만나면 그 시트의 데이터가 끝난 것으로 보고 멈춥니다.
   - 결재상태가 "미처리"인 건은 이 주별 합계에서는 제외합니다(자료입력 시트의
     원본 데이터에는 그대로 남아있어 확인은 가능합니다).
   - 연장근로시간/휴일근무는 결재상태가 "처리"인 수당시간(분)을 주별로 합산한 뒤,
     "15분 이하→0시간, 15분초과45분미만→0.5시간, 45분이상→1시간" 규칙으로
     0.5시간 단위로 반올림합니다. 이때 1~N주 합계가 그 달 전체 총합(분→시간,
     소수점 버림)과 어긋나면, 반올림 경계에 가장 애매하게 걸쳐 있던 주부터
     0.5시간씩 자동으로 보정해서 정확히 맞춥니다.
   - 소정근로시간은 (이번 달의 N주차에 속하는 일~토 주의 평일 수 × 8시간) 에서
     공휴일(사용자가 매번 직접 입력)과, 선택적으로 입력하는 "연가내역" 파일에 있는
     연가/육아시간 등을 뺀 값으로 계산합니다. 연가내역 파일을 넣지 않으면
     공휴일만 반영해서 계산합니다.
     ※ 그 주가 이번 달과 다른 달에 걸쳐 있어도(예: 7월 1주차 = 6월 28일(일)~
       7월 4일(토)), 평일 수는 그 주 전체(다른 달 날짜 포함) 기준으로 계산합니다.
       단, 연장근로시간/휴일근무(초과근무수당)는 원본 파일 자체가 해당 월 실적만
       담고 있으므로 다른 달과 합산되지 않습니다.

절대 건드리지 않는 것
----------------------
- `자료입력` 시트의 T~W열 (매칭용 수식: VALUE / CONCAT / COUNTIFS 등)
- 이름 시트의 1~36행(일별 데이터, 수식 그대로 유지)과 41~45행의 B열(주차 라벨), M열(합계 수식)
- `부서연번`, `고정임금` 등 나머지 시트
- `시간입력` 시트의 K열/M열(7행부터)을 제외한 나머지 부분
- 셀 서식(글꼴, 테두리, 배경색 등) — 값만 덮어씀

필요 라이브러리 (최초 1회 설치)
--------------------------------
    pip install xlrd==2.0.2 openpyxl

xlrd 2.x는 .xlsx 지원이 빠졌지만 .xls는 계속 지원하므로 본 용도에는 문제없습니다.

실행 방법
---------
    python 초과근무_자동입력.py

GUI에서 파일을 선택하고 [실행] 버튼을 누르면 됩니다.
"""

import os
import re
import shutil
import tempfile
import zipfile
import datetime
import calendar
from collections import defaultdict
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

try:
    import xlrd
except ImportError:
    raise SystemExit("xlrd가 설치되어 있지 않습니다. 터미널에서 'pip install xlrd' 실행 후 다시 실행하세요.")

try:
    import openpyxl
except ImportError:
    raise SystemExit("openpyxl이 설치되어 있지 않습니다. 터미널에서 'pip install openpyxl' 실행 후 다시 실행하세요.")







TARGET_HEADERS = [
    "No.", "근무일자", "부서", "고유식별번호", "성명", "생년월일",
    "근무형태", "휴일구분", "자료구분", "결재상태",
    "출근(기본)", "퇴근(기본)", "출근(신청)", "퇴근(신청)", "출근(실제)", "퇴근(실제)",
    "총초과(분)", "수당제외(분)", "수당시간(분)",
]
NUM_COLS = len(TARGET_HEADERS)

DATA_SHEET_NAME = "자료입력"
MAX_ROWS = 5000
MAX_DATA_ROWS = MAX_ROWS - 1


TIME_INPUT_SHEET_NAME = "시간입력"
TIME_INPUT_START_ROW = 7
TIME_INPUT_COL_D = 4
TIME_INPUT_COL_K = 11
TIME_INPUT_COL_M = 13


WEEK_ROWS = [41, 42, 43, 44, 45]
COL_C = 3
COL_E = 5
COL_H = 8


LEAVE_KINDS = {"연가", "육아시간"}


NON_NAME_SHEETS = {
    "작성참고자료", "부서연번", "고정임금", "공무직(99.1.1이후 입사자)",
    "고정임금(2)", "시간입력", DATA_SHEET_NAME,
}






def find_header_col(sheet):
    """'No.' 헤더가 있는 열 인덱스를 찾는다. (원본 파일은 A열이 비어있고
    B열부터 헤더가 시작하는 구조지만, 혹시 다른 달 파일은 배치가 다를 수
    있으므로 방어적으로 탐색한다.)"""
    for row in range(0, min(3, sheet.nrows)):
        for col in range(0, min(5, sheet.ncols)):
            val = str(sheet.cell_value(row, col)).strip()
            if val in ("No.", "No", "번호"):
                return row, col

    return 0, 1


def cell_to_text(cell, workbook_datemode):
    """xls 셀 값을 '있는 그대로'의 텍스트로 변환한다.
    생년월일(mm/dd) 등 텍스트 컬럼이 datetime/숫자로 둔갑하지 않도록
    이미 텍스트인 경우는 그대로 반환하고, 혹시 숫자/날짜 타입으로 들어온
    경우에만 안전하게 문자열로 변환한다."""
    ctype = cell.ctype
    value = cell.value

    if ctype == xlrd.XL_CELL_EMPTY or ctype == xlrd.XL_CELL_BLANK:
        return ""
    if ctype == xlrd.XL_CELL_TEXT:
        return value
    if ctype == xlrd.XL_CELL_NUMBER:

        if float(value).is_integer():
            return str(int(value))
        return str(value)
    if ctype == xlrd.XL_CELL_DATE:
        dt = xlrd.xldate_as_datetime(value, workbook_datemode)
        if dt.time() == datetime.time(0, 0, 0):
            return dt.strftime("%Y-%m-%d")
        return dt.strftime("%Y-%m-%d %H:%M")
    if ctype == xlrd.XL_CELL_BOOLEAN:
        return "TRUE" if value else "FALSE"
    return str(value)


def read_source_xls(path, log):
    """초과근무목록_YYYYMM.xls 를 읽어 19개 컬럼 데이터 리스트를 반환한다.
    결재상태와 무관하게 전체 행을 포함한다."""
    wb = xlrd.open_workbook(path)

    sheet = None
    if "초과근무목록" in wb.sheet_names():
        sheet = wb.sheet_by_name("초과근무목록")
    else:
        sheet = wb.sheet_by_index(0)
        log(f"⚠ '초과근무목록' 시트를 찾지 못해 첫 번째 시트('{sheet.name}')를 사용합니다.")

    header_row, start_col = find_header_col(sheet)
    log(f"원본 헤더 위치 확인: {header_row + 1}행, {start_col + 1}번째 열부터 시작")


    for i, expected in enumerate(TARGET_HEADERS):
        actual = str(sheet.cell_value(header_row, start_col + i)).strip()
        if actual != expected:
            log(f"⚠ 헤더 불일치 가능성: 예상 '{expected}' / 실제 '{actual}' (열 위치 확인 필요)")

    rows = []
    status_counts = {}
    for r in range(header_row + 1, sheet.nrows):
        row_values = []
        empty_row = True
        for c in range(start_col, start_col + NUM_COLS):
            cell = sheet.cell(r, c)
            text = cell_to_text(cell, wb.datemode)
            if text != "":
                empty_row = False
            row_values.append(text)
        if empty_row:
            continue
        rows.append(row_values)

        status = row_values[9]
        status_counts[status] = status_counts.get(status, 0) + 1

    log(f"원본에서 총 {len(rows)}건의 데이터 행을 읽었습니다. (결재상태별: {status_counts})")
    log("→ 결재상태와 무관하게 전체 행을 그대로 포함합니다 (미처리 포함).")
    return rows






def parse_date(value):
    """'2026-06-01' / '2026.06.01' / '2026/06/01' 등을 date로 변환. 실패 시 None."""
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def sunday_of_week(d):
    """d가 속한 주(일요일 시작)의 일요일 날짜를 반환한다."""

    return d - datetime.timedelta(days=(d.weekday() + 1) % 7)


def month_weeks(year, month):
    """해당 연/월이 걸쳐 있는 일~토 주들의 '일요일 날짜' 리스트를 순서대로 반환한다.
    리스트의 n번째(0-index) 항목이 '(n+1)주'에 해당한다."""
    first_day = datetime.date(year, month, 1)
    last_day = datetime.date(year, month, calendar.monthrange(year, month)[1])
    start = sunday_of_week(first_day)
    end = sunday_of_week(last_day)
    weeks = []
    cur = start
    while cur <= end:
        weeks.append(cur)
        cur += datetime.timedelta(days=7)
    return weeks


def parse_holidays(text):
    """'2026-06-03, 2026-06-06' 같은 텍스트를 날짜 집합으로 변환."""
    holidays = set()
    for tok in re.split(r"[,\s]+", (text or "").strip()):
        if not tok:
            continue
        d = parse_date(tok)
        if d:
            holidays.add(d)
    return holidays


_LEAVE_DURATION_RE = re.compile(r"(\d+)\s*일|(\d+)\s*시간|(\d+)\s*분")


def parse_leave_hours(text):
    """'3시간 40분' / '2시간' / '1일' 등의 텍스트를 시간(소수)으로 변환한다."""
    if not text:
        return 0.0
    total_minutes = 0
    for m in _LEAVE_DURATION_RE.finditer(str(text)):
        day, hour, minute = m.groups()
        if day:
            total_minutes += int(day) * 8 * 60
        if hour:
            total_minutes += int(hour) * 60
        if minute:
            total_minutes += int(minute)
    return total_minutes / 60.0


def read_leave_xls(path, log):
    """개인별근무상황내역(연가내역) .xls를 읽어
    {고유식별번호 또는 성명: [{"date":.., "kind":.., "hours":..}, ...]} 로 반환한다."""
    wb = xlrd.open_workbook(path)
    sheet = wb.sheet_by_index(0)
    header_row = 0
    headers = [str(sheet.cell_value(header_row, c)).strip() for c in range(sheet.ncols)]

    def col(name):
        return headers.index(name) if name in headers else None

    c_name, c_id, c_kind = col("성명"), col("고유식별번호"), col("종별")
    c_period, c_dur = col("기간"), col("일/시간")
    if c_name is None or c_period is None or c_dur is None:
        raise ValueError(f"연가내역 파일 헤더를 인식하지 못했습니다: {headers}")

    records = defaultdict(list)
    kinds_seen = set()
    period_re = re.compile(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})")
    for r in range(header_row + 1, sheet.nrows):
        name = str(sheet.cell_value(r, c_name)).strip() if c_name is not None else ""
        if not name:
            continue
        emp_id = str(sheet.cell_value(r, c_id)).strip() if c_id is not None else ""
        kind = str(sheet.cell_value(r, c_kind)).strip() if c_kind is not None else ""
        period = str(sheet.cell_value(r, c_period)).strip()
        dur_text = str(sheet.cell_value(r, c_dur)).strip()
        kinds_seen.add(kind)

        m = period_re.match(period)
        if not m:
            continue
        d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        key = emp_id if emp_id else name
        records[key].append({
            "date": d, "name": name, "emp_id": emp_id,
            "kind": kind, "hours": parse_leave_hours(dur_text),
        })

    log(f"연가내역에서 발견한 '종별' 목록: {sorted(kinds_seen)} (소정근로시간 차감 대상: "
        f"{sorted(LEAVE_KINDS)} — 필요시 코드 상단 LEAVE_KINDS 수정)")
    return records


def round_half_hour(minutes):
    """분(minute)을 '15분 이하->0, 15분초과45분미만->0.5, 45분이상->1시간(올림)' 규칙으로
    0.5시간 단위로 반올림한다."""
    whole = int(minutes // 60)
    rem = minutes % 60
    if rem <= 15:
        frac = 0.0
    elif rem < 45:
        frac = 0.5
    else:
        frac = 1.0
    return whole + frac


def reconcile_weekly_hours(minutes_list, target_hours):
    """각 주를 round_half_hour로 반올림하되, 합계가 target_hours(정수 시간)와
    정확히 같아지도록 가장 애매하게 반올림된 주부터 0.5시간씩 조정한다."""
    n = len(minutes_list)
    if n == 0:
        return []
    raw_hours = [m / 60.0 for m in minutes_list]
    rounded = [round_half_hour(m) for m in minutes_list]
    residual = [raw_hours[i] - rounded[i] for i in range(n)]
    steps = round((target_hours - sum(rounded)) / 0.5)

    order_up = sorted(range(n), key=lambda i: -residual[i])
    order_down = sorted(range(n), key=lambda i: residual[i])
    i = 0
    while steps > 0 and i < n * 20:
        idx = order_up[i % n]
        rounded[idx] += 0.5
        steps -= 1
        i += 1
    i = 0
    while steps < 0 and i < n * 20:
        idx = order_down[i % n]
        if rounded[idx] - 0.5 >= 0:
            rounded[idx] -= 0.5
            steps += 1
        i += 1
    return rounded


def _time_to_minutes(t):
    """'HH:MM' 문자열을 자정 기준 분으로 변환한다. 파싱 실패 시 None."""
    try:
        h, m = str(t).strip().split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def calc_ao_minutes(신청출근, 퇴근기본, 신청퇴근, 실제출근, 실제퇴근, is_holiday):
    """이름 시트의 AF6/AG6/U6/AO6 수식을 재현해서 '초과근무 원시 분'을 계산한다.
    - 시작시각: 신청출근과 실제출근 중 더 늦은 시각
    - 종료시각: 신청퇴근이 실제퇴근보다 빠르거나 같으면 신청퇴근, 아니면
                max(퇴근기본, 실제퇴근)
    - 평일은 9시간(기본 근무시간)을 뺀 나머지를 초과근무로 본다.
    """
    af = max(str(신청출근), str(실제출근))
    ag = str(신청퇴근) if str(신청퇴근) <= str(실제퇴근) else max(str(퇴근기본), str(실제퇴근))
    start, end = _time_to_minutes(af), _time_to_minutes(ag)
    if start is None or end is None:
        return None
    baseline = 0 if is_holiday else 540
    return end - start - baseline


def calc_z_ab_minutes(ao_minutes, is_holiday):
    """이름 시트의 Z6/AB6 수식(구간별 식사시간 공제)을 재현한다.
    반환: (평일가산 분, 휴일가산 분, 9시간 이상이라 근사치를 썼는지 여부)
    * 원본 수식의 AO>=540(9시간 이상) 구간은 Z6가 자기 자신을 참조하는
      순환식이라 정확히 재현할 수 없어 근사치(-90분)로 처리한다."""
    if ao_minutes is None:
        return 0, 0, False

    def tiered(ao):
        if ao >= 540:
            return ao - 90, True
        if ao >= 480:
            return 480, False
        if ao >= 270:
            return ao - 30, False
        if ao > 240:
            return 240, False

        return ao, False

    if is_holiday:
        val, approx = tiered(ao_minutes)
        z_extra = max(ao_minutes - 540, 0)
        return z_extra, val, approx
    else:
        val, approx = tiered(ao_minutes)
        return val, 0, approx


def build_weekly_summary(rows, leave_records, holidays, log, extra_names=None):
    """자료입력용 rows(원본 전체 행)에서 사람별 · 주별 요약을 계산한다.
    extra_names: 이번 달 초과근무 기록이 아예 없어도 이름 시트가 존재하는
                 사람 이름 목록. 이 사람들도 소정근로시간은 계산하고
                 연장/휴일근무는 0으로 채운다 (그렇지 않으면 이전 달의
                 낡은 값이 표에 그대로 남아있게 된다).
    반환: (employees, weeks)
      employees: {성명: {"emp_id":.., "weeks":[{"C":..,"E":..,"H":..}, ...]}}
      weeks: 이번 달의 일~토 주 시작일(일요일) 리스트 (1주부터 순서대로)
    """
    ym_counts = {}
    for row in rows:
        d = parse_date(row[1])
        if not d: continue
        ym_counts[(d.year, d.month)] = ym_counts.get((d.year, d.month), 0) + 1
    if not ym_counts:
        log("⚠ 근무일자를 인식하지 못해 주별 합계를 계산할 수 없습니다.")
        return {}, []

    year, month = max(ym_counts, key=ym_counts.get)
    weeks = month_weeks(year, month)
    if len(weeks) > len(WEEK_ROWS):
        log(f"⚠ {year}-{month:02d}은 {len(weeks)}개 주로 나뉘는데 서식에는 "
            f"{len(WEEK_ROWS)}주 칸만 있습니다. 마지막 주는 표에 반영되지 않습니다.")
    week_index = {ws: i for i, ws in enumerate(weeks)}

    employees = {}
    for name in (extra_names or []):
        employees.setdefault(name, {
            "emp_id": "",
            "weeks": [{"C": 0.0, "E": 0.0, "H": 0.0} for _ in weeks],
            "_e_min": [0.0 for _ in weeks],
            "_h_min": [0.0 for _ in weeks],
        })

    approx_warned = set()
    night_warned = set()

    for row in rows:
        (No_, 근무일자, 부서, 고유id, 성명, 생년월일, 근무형태, 휴일구분,
         자료구분, 결재상태, 출근기본, 퇴근기본, 출근신청, 퇴근신청,
         출근실제, 퇴근실제) = row[:16]
        emp = employees.setdefault(성명, {
            "emp_id": 고유id,
            "weeks": [{"C": 0.0, "E": 0.0, "H": 0.0} for _ in weeks],
            "_e_min": [0.0 for _ in weeks],
            "_h_min": [0.0 for _ in weeks],
        })
        if not emp.get("emp_id"):
            emp["emp_id"] = 고유id
        d = parse_date(근무일자)
        if not d or 결재상태 != "처리":
            continue
        idx = week_index.get(sunday_of_week(d))
        if idx is None or idx >= len(WEEK_ROWS):
            continue

        is_holiday = (휴일구분 == "휴일")
        ao = calc_ao_minutes(출근신청, 퇴근기본, 퇴근신청, 출근실제, 퇴근실제, is_holiday)
        if ao is None:
            continue
        z_min, ab_min, approx = calc_z_ab_minutes(ao, is_holiday)
        if approx and 성명 not in approx_warned:
            log(f"⚠ {성명}: 하루 초과근무가 9시간을 넘는 날이 있어 근사치로 계산했습니다 (원본 서식 수식이 자기참조라 정확히 재현이 안 됨). 이름 시트에서 그 날짜만 직접 한 번 더 확인해 주세요.")


            approx_warned.add(성명)
        start_min = _time_to_minutes(str(출근실제))
        end_min = _time_to_minutes(str(퇴근실제))
        if 성명 not in night_warned and (
            (start_min is not None and start_min < 6 * 60) or
            (end_min is not None and end_min > 22 * 60)
        ):
            log(f"⚠ {성명}: 06시 이전 또는 22시 이후 근무가 있어 야간가산 부분은 이 프로그램 계산에 반영되지 않았습니다(이름 시트에서 별도 확인 필요).")

            night_warned.add(성명)

        emp["_e_min"][idx] += z_min
        emp["_h_min"][idx] += ab_min



    for name, emp in employees.items():
        e_min, h_min = emp["_e_min"], emp["_h_min"]
        total_h_min = sum(h_min)
        total_e_min = sum(e_min)
        target_h = int(total_h_min // 60)
        target_e = int((total_e_min + total_h_min % 60) // 60)
        e_rounded = reconcile_weekly_hours(e_min, target_e)
        h_rounded = reconcile_weekly_hours(h_min, target_h)
        for i in range(len(weeks)):
            if i >= len(WEEK_ROWS):
                break
            emp["weeks"][i]["E"] = e_rounded[i]
            emp["weeks"][i]["H"] = h_rounded[i]
        del emp["_e_min"], emp["_h_min"]






    for name, emp in employees.items():
        leave_list = leave_records.get(emp["emp_id"]) or leave_records.get(name) or []
        for i, ws in enumerate(weeks):
            if i >= len(WEEK_ROWS):
                break
            days_in_week = [ws + datetime.timedelta(days=off) for off in range(7)]
            weekdays_in_week = [
                d for d in days_in_week
                if d.weekday() < 5
            ]
            hours = len(weekdays_in_week) * 8.0
            hours -= 8.0 * sum(1 for d in weekdays_in_week if d in holidays)
            leave_hours = sum(
                rec["hours"] for rec in leave_list
                if rec["kind"] in LEAVE_KINDS and rec["date"] in weekdays_in_week
            )
            hours -= leave_hours
            emp["weeks"][i]["C"] = round(max(hours, 0.0), 2)
            emp["weeks"][i]["E"] = round(emp["weeks"][i]["E"], 2)
            emp["weeks"][i]["H"] = round(emp["weeks"][i]["H"], 2)



    unprocessed_minutes = defaultdict(lambda: [0.0, 0.0])
    for row in rows:
        성명, 휴일구분, 결재상태 = row[4], row[7], row[9]
        if 결재상태 == "처리":
            continue
        try:
            분 = float(row[18]) if row[18] not in ("", None) else 0.0
        except ValueError:
            분 = 0.0
        if 휴일구분 == "휴일":
            unprocessed_minutes[성명][1] += 분
        else:
            unprocessed_minutes[성명][0] += 분
    for name, (e_min, h_min) in unprocessed_minutes.items():
        if not (e_min or h_min): continue
        log(f"⚠ {name}: 미처리 건이 남아있어 1주~5주 표 합계에서 제외됨 (미처리 연장 "
            f"{e_min / 60:.1f}시간, 미처리 휴일 {h_min / 60:.1f}시간 — 이 건들이 자료입력 시트에는 그대로 남아있으니 확인 후 승인되면 다시 실행하세요. 이 때문에 시트 상단 S4/U4(전체 합계)와 1주~5주 표 합계가 다를 수 있습니다.)")



    return employees, weeks, year, month


def write_weekly_summary_to_name_sheets(wb, employees, log):
    """계산된 주별 요약을 각 사람 이름 시트의 41~45행(C/E/H열)에 기록한다."""
    written, skipped = [], []
    for name, emp in employees.items():
        if name not in wb.sheetnames or name in NON_NAME_SHEETS:
            skipped.append(name)
            continue
        ws = wb[name]
        for i, row_num in enumerate(WEEK_ROWS):
            if i < len(emp['weeks']):
                w = emp['weeks'][i]
                ws.cell(row=row_num, column=COL_C).value = w['C']
                ws.cell(row=row_num, column=COL_E).value = w['E']
                ws.cell(row=row_num, column=COL_H).value = w['H']
            else:
                ws.cell(row=row_num, column=COL_C).value = None
                ws.cell(row=row_num, column=COL_E).value = None
                ws.cell(row=row_num, column=COL_H).value = None
        written.append(name)
    if written:
        log(f"이름 시트 '1주~5주' 표 자동 입력 완료: {', '.join(written)}")
    if skipped:
        log(f"⚠ 다음 이름은 서식에 해당 시트가 없어 주별 합계 입력을 건너뛰었습니다: {', '.join(skipped)}")


def mark_no_overtime_sheets(wb, log):
    """자료입력 시트의 E열(성명)에 없는 사람의 시트를 찾아,
D11~N13을 병합하고 '초과근무내역 없음' 문구를 입력한다."""
    if DATA_SHEET_NAME not in wb.sheetnames:
        return


    data_sheet = wb[DATA_SHEET_NAME]
    names_in_data = set()
    for row in range(2, MAX_ROWS + 1):
        cell = data_sheet.cell(row=row, column=5)
        if cell.value and str(cell.value).strip():
            names_in_data.add(str(cell.value).strip())
        else:
            break


    marked = []
    for sheet_name in wb.sheetnames:
        if sheet_name in NON_NAME_SHEETS:
            continue
        if sheet_name not in names_in_data:
            try:
                ws = wb[sheet_name]

                ws.merge_cells('D11:N13')

                ws['D11'].value = '초과근무내역 없음'
                marked.append(sheet_name)
            except Exception as e:
                log(f"⚠ '{sheet_name}' 시트 병합 처리 중 오류: {e}")

    if marked:
        log(f"초과근무 내역 없음: {', '.join(marked)} (D11~N13 병합, 문구 입력)")


def fill_time_input_sheet_formulas(wb, log):
    """'시간입력' 시트 D열(7행부터)의 성명을 읽어, 같은 행의 K열/M열에
각각 '=[성명]!S4', '=[성명]!U4' 참조 수식을 채운다. D열이 비어있는
행을 만나면 그 시트의 데이터가 끝난 것으로 보고 멈춘다."""
    if TIME_INPUT_SHEET_NAME not in wb.sheetnames:
        log(f"⚠ '{TIME_INPUT_SHEET_NAME}' 시트를 찾을 수 없어 K/M열 수식 입력을 건너뜁니다.")
        return

    ws = wb[TIME_INPUT_SHEET_NAME]
    row = TIME_INPUT_START_ROW
    filled, missing_sheet = [], []
    while True:
        name = ws.cell(row=row, column=TIME_INPUT_COL_D).value
        if name is None or str(name).strip() == '':
            break
        name = str(name).strip()
        if name not in wb.sheetnames:
            missing_sheet.append(f'{name}({row}행)')
        ws.cell(row=row, column=TIME_INPUT_COL_K).value = f"='{name}'!S4"
        ws.cell(row=row, column=TIME_INPUT_COL_M).value = f"='{name}'!U4"
        filled.append(name)
        row += 1

    if filled:
        log(f"'{TIME_INPUT_SHEET_NAME}' 시트 K/M열 수식 입력 완료: {', '.join(filled)}")
    else:
        log(f"⚠ '{TIME_INPUT_SHEET_NAME}' 시트 D열({TIME_INPUT_START_ROW}행부터)에서 성명을 찾지 못했습니다.")
    if missing_sheet:
        log(f'⚠ 다음 성명은 통합 문서에 같은 이름의 시트가 없어 수식이 참조 오류가 날 수 있습니다: '
            f"{', '.join(missing_sheet)}")


def fill_time_input_sheet_month(wb, month, log):
    """'시간입력' 시트의 B1 셀에 월(month) 값을 자동으로 입력한다.
이 값은 제목행의 '2026년 _월 공무직 시간외근무수당' 텍스트에서 _부분에 표시된다."""
    if TIME_INPUT_SHEET_NAME not in wb.sheetnames:
        log(f"⚠ '{TIME_INPUT_SHEET_NAME}' 시트를 찾을 수 없어 B1 월 입력을 건너뜁니다.")
        return

    ws = wb[TIME_INPUT_SHEET_NAME]
    ws.cell(row=1, column=2).value = month
    log(f"'{TIME_INPUT_SHEET_NAME}' 시트 B1에 월 자동 입력: {month}월")














_ALT_CONTENT_RE = re.compile(
    r"<mc:AlternateContent\b[^>]*>.*?<mc:Fallback>(.*?)</mc:Fallback>\s*</mc:AlternateContent>",
    re.DOTALL,
)


def sanitize_hancom_styles(xlsx_path, log):
    """styles.xml에 한컴 전용 mc:AlternateContent가 있으면 정리한 임시
사본 경로를 반환하고, 없으면 원본 경로를 그대로 반환한다."""
    try:
        with zipfile.ZipFile(xlsx_path, 'r') as zin:
            if 'xl/styles.xml' not in zin.namelist():
                return xlsx_path
            styles_xml = zin.read('xl/styles.xml').decode('utf-8')
    except zipfile.BadZipFile:


        return xlsx_path

    if 'mc:AlternateContent' not in styles_xml:
        return xlsx_path

    fixed_xml, n = _ALT_CONTENT_RE.subn(r'\1', styles_xml)
    if n == 0 or 'mc:AlternateContent' in fixed_xml:
        log('⚠ 한컴 전용 서식 구조를 자동으로 정리하지 못했습니다. 원본으로 계속 시도합니다.')
        return xlsx_path

    log(f'한컴오피스 전용 서식 확장 {n}건을 표준 서식으로 자동 정리했습니다 (내용에는 영향 없음).')

    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.xlsx', prefix='hs_fixed_')
    os.close(tmp_fd)
    with zipfile.ZipFile(xlsx_path, 'r') as zin, zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == 'xl/styles.xml':
                data = fixed_xml.encode('utf-8')
            zout.writestr(item, data)
    return tmp_path






def load_target_workbook(xlsx_path, log):
    """대상 xlsx를 (필요시 한컴 서식 정리 후) 열어서 workbook 객체를 반환한다."""
    load_path = sanitize_hancom_styles(xlsx_path, log)
    try:
        wb = openpyxl.load_workbook(load_path)
    finally:
        if load_path != xlsx_path and os.path.exists(load_path):
            os.remove(load_path)
    return wb


def fill_data_sheet(wb, rows, log):
    """자료입력 시트 A2:S5000 영역을 지우고 rows로 다시 채운다. (저장은 하지 않음)"""
    if DATA_SHEET_NAME not in wb.sheetnames:
        raise ValueError(f"'{DATA_SHEET_NAME}' 시트를 찾을 수 없습니다. 시트 목록: {wb.sheetnames}")

    ws = wb[DATA_SHEET_NAME]


    for i, expected in enumerate(TARGET_HEADERS):
        actual = ws.cell(row=1, column=i + 1).value
        if actual != expected:
            log(f"⚠ 대상 헤더 불일치: {i + 1}번째 열 예상 '{expected}' / 실제 '{actual}'")


    log(f'기존 데이터 삭제 중: A2:S{MAX_ROWS} ...')
    for r in range(2, MAX_ROWS + 1):
        for c in range(1, NUM_COLS + 1):
            ws.cell(row=r, column=c).value = None


    log(f'새 데이터 {len(rows)}건 입력 중...')
    for r_idx, row_values in enumerate(rows):
        target_row = r_idx + 2
        for c_idx, value in enumerate(row_values):
            cell = ws.cell(row=target_row, column=c_idx + 1)
            cell.value = str(value) if value != '' else None






class App:

    C_BG = '#f4f6fb'
    C_CARD = '#ffffff'
    C_BORDER = '#e4e8f1'
    C_TEXT = '#1f2937'
    C_SUBTEXT = '#7a8299'
    C_PRIMARY = '#4356e8'
    C_PRIMARY_DK = '#3346c9'
    C_PRIMARY_SOFT = '#eef0fd'
    C_BADGE_FG = '#ffffff'
    C_LOG_BG = '#1e2333'
    C_LOG_FG = '#d7ddf0'


    C_PREP_BG = '#fff8ec'
    C_PREP_BORDER = '#f3ddb0'
    C_PREP_ACCENT = '#c8790a'
    C_PREP_BADGE_BG = '#ffffff'

    F_TITLE = ('맑은 고딕', 16, 'bold')
    F_SUB = ('맑은 고딕', 10)
    F_SECTION = ('맑은 고딕', 11, 'bold')
    F_STEP_DESC = ('맑은 고딕', 10)
    F_BODY = ('맑은 고딕', 10)
    F_BUTTON = ('맑은 고딕', 10)
    F_RUN = ('맑은 고딕', 12, 'bold')
    F_LOG = ('Consolas', 10)
    F_BADGE = ('맑은 고딕', 12, 'bold')
    F_PREP_TITLE = ('맑은 고딕', 11, 'bold')


    BADGE_SIZE = 26
    BADGE_COL_W = 38
    CARD_PAD_X = 18

    def __init__(self, root):
        self.root = root
        root.title('공무직 초과근무수당 자동 입력')
        root.configure(bg=self.C_BG)


        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w = min(820, max(660, sw - 80))
        h = min(860, max(480, sh - 140))
        root.geometry(f'{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2 - 20)}')
        root.minsize(640, 420)
        root.resizable(True, True)

        self._wrap_labels = []
        self._setup_style()


        self._build_action_bar(root)


        body = self._build_scroll_area(root)

        self._build_header(body)
        self._build_prep_card(body)
        self._build_input_card(body)
        self._build_option_card(body)
        self._build_log_card(body)




    def _build_action_bar(self, root):
        bar = tk.Frame(root, bg=self.C_BG, highlightthickness=1,
                       highlightbackground=self.C_BORDER, highlightcolor=self.C_BORDER)
        bar.pack(side='bottom', fill='x')
        inner = tk.Frame(bar, bg=self.C_BG)
        inner.pack(fill='x', padx=16, pady=12)

        self.run_btn = tk.Button(
            inner, text='▶  실행', font=self.F_RUN, command=self.run,
            bg=self.C_PRIMARY, fg='white', activebackground=self.C_PRIMARY_DK,
            activeforeground='white', relief='flat', cursor='hand2',
            padx=20, pady=11, bd=0, highlightthickness=0)

        self.run_btn.pack(fill='x')
        self.run_btn.bind('<Enter>', lambda e: self.run_btn.config(bg=self.C_PRIMARY_DK))
        self.run_btn.bind('<Leave>', lambda e: self.run_btn.config(bg=self.C_PRIMARY))

    def _build_scroll_area(self, root):
        """세로 스크롤이 되는 본문 프레임을 만들어 반환한다."""
        wrap = tk.Frame(root, bg=self.C_BG)
        wrap.pack(side='top', fill='both', expand=True)

        self.canvas = tk.Canvas(wrap, bg=self.C_BG, highlightthickness=0, bd=0)
        self.vbar = ttk.Scrollbar(wrap, orient='vertical', command=self.canvas.yview,
                                  style='App.Vertical.TScrollbar')
        self._vbar_shown = False
        self.canvas.configure(yscrollcommand=self._on_scroll_set)
        self.canvas.pack(side='left', fill='both', expand=True)

        body = tk.Frame(self.canvas, bg=self.C_BG)
        self._body_id = self.canvas.create_window((0, 0), window=body, anchor='nw')

        def on_body_configure(_e=None):
            self.canvas.configure(scrollregion=self.canvas.bbox('all'))

        def on_canvas_configure(e):

            self.canvas.itemconfigure(self._body_id, width=e.width)
            self._refresh_wraplength(e.width)

        body.bind('<Configure>', on_body_configure)
        self.canvas.bind('<Configure>', on_canvas_configure)
        self.canvas.bind_all('<MouseWheel>', self._on_mousewheel)
        self.canvas.bind_all('<Button-4>', self._on_mousewheel)
        self.canvas.bind_all('<Button-5>', self._on_mousewheel)

        self.body_pad = tk.Frame(body, bg=self.C_BG)
        self.body_pad.pack(fill='both', expand=True, padx=16, pady=16)
        self.body_pad.columnconfigure(0, weight=1)
        return self.body_pad

    def _on_scroll_set(self, first, last):
        """내용이 창보다 길 때만 스크롤바를 보여준다."""
        need = not (float(first) <= 0.0 and float(last) >= 1.0)
        if need != self._vbar_shown:
            if need:
                self.vbar.pack(side='right', fill='y', before=self.canvas)
            else:
                self.vbar.pack_forget()
            self._vbar_shown = need
        self.vbar.set(first, last)

    def _on_mousewheel(self, event):

        w = self.root.winfo_containing(event.x_root, event.y_root)
        box = getattr(self, 'log_box', None)
        while w is not None:
            if box is not None and w is box:
                return
            w = getattr(w, 'master', None)
        if event.num == 4:
            self.canvas.yview_scroll(-1, 'units')
        elif event.num == 5:
            self.canvas.yview_scroll(1, 'units')
        else:
            self.canvas.yview_scroll(int(-event.delta / 120), 'units')

    def _refresh_wraplength(self, canvas_width):
        """창 폭이 바뀌면 설명글 줄바꿈 폭을 다시 계산한다."""

        usable = canvas_width - 18
        for widget, reserved in self._wrap_labels:
            try:
                widget.configure(wraplength=max(220, usable - reserved))
            except tk.TclError:
                pass




    def _build_header(self, parent):
        header = tk.Frame(parent, bg=self.C_BG)
        header.pack(fill='x', pady=(0, 12))
        tk.Label(header, text='🗂  공무직 초과근무수당 자동 입력', font=self.F_TITLE,
                 bg=self.C_BG, fg=self.C_TEXT).pack(anchor='w')
        sub = tk.Label(header, text='초과근무목록과 보고 양식을 넣으면 자료입력·주차별 표를 자동으로 채워줍니다.',
                       font=self.F_SUB, bg=self.C_BG, fg=self.C_SUBTEXT, justify='left')
        sub.pack(anchor='w', pady=(2, 0))
        self._wrap_labels.append((sub, 40))

    def _build_prep_card(self, parent):
        card = tk.Frame(parent, bg=self.C_PREP_BG, highlightthickness=1,
                        highlightbackground=self.C_PREP_BORDER, highlightcolor=self.C_PREP_BORDER)
        card.pack(fill='x', pady=(0, 12))
        inner = tk.Frame(card, bg=self.C_PREP_BG)
        inner.pack(fill='both', expand=True, padx=self.CARD_PAD_X, pady=(14, 16))
        inner.columnconfigure(0, weight=0, minsize=self.BADGE_COL_W)
        inner.columnconfigure(1, weight=1)

        tk.Label(inner, text="📋 사전 작업 (서식파일 '부서연번.N월 공무직_시간외근무수당_부서명.xlsx')", font=self.F_PREP_TITLE,
                 bg=self.C_PREP_BG, fg=self.C_PREP_ACCENT).grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 10))

        items = [
            ('시간입력 시트 입력',
             '시간입력 시트의 소속, 등급, 성명, 생년월일, 근속년수를 입력해야 합니다'),
            ('공무직 이름별 시트 생성',
             "공무직 이름별 시트를 생성하고(서식의 홍길동과 같은 형식), 부서명(H3), 이름(I3), 생일(J3, 'mm/dd 형식)을 입력해야 합니다"),
        ]

        for i, (title, desc) in enumerate(items, start=1):
            self._add_prep_item(inner, row=i, num=str(i), title=title, desc=desc)

    def _build_input_card(self, parent):
        card = tk.Frame(parent, bg=self.C_CARD, highlightthickness=1,
                        highlightbackground=self.C_BORDER, highlightcolor=self.C_BORDER)
        card.pack(fill='x')
        inner = tk.Frame(card, bg=self.C_CARD)
        inner.pack(fill='both', expand=True, padx=self.CARD_PAD_X, pady=16)
        inner.columnconfigure(0, weight=0, minsize=self.BADGE_COL_W)
        inner.columnconfigure(1, weight=1)

        self.src_var = tk.StringVar()
        self.tgt_var = tk.StringVar()
        self.leave_var = tk.StringVar()
        self.holidays_var = tk.StringVar()

        self._add_step(
            inner, row=0, num='1',
            title='초과근무목록.xls',
            desc='인사랑에서 받은 원본 파일',
            var=self.src_var, command=self.browse_src)

        self._add_step(
            inner, row=1, num='2',
            title='부서연번.N월 공무직_시간외근무수당_부서명.xlsx',
            desc="총무과 서식 파일 ※개별 시트 생일 형식('mm/dd) 확인",
            var=self.tgt_var, command=self.browse_tgt)

        self._add_step(
            inner, row=2, num='3',
            title='개인별근무상황내역.xls',
            desc='인사랑에서 받은 원본 파일',
            var=self.leave_var, command=self.browse_leave, optional=False)

        self._add_step(
            inner, row=3, num='4',
            title='이번 달 공휴일(대체공휴일 포함) 날짜',
            desc='쉼표로 구분, 예: 2026-06-03, 2026-06-06',
            var=self.holidays_var, command=None, optional=True)


    def _build_option_card(self, parent):
        card = tk.Frame(parent, bg=self.C_CARD, highlightthickness=1,
                        highlightbackground=self.C_BORDER, highlightcolor=self.C_BORDER)
        card.pack(fill='x', pady=(12, 0))
        inner = tk.Frame(card, bg=self.C_CARD)
        inner.pack(fill='both', expand=True, padx=self.CARD_PAD_X, pady=14)

        tk.Label(inner, text='저장 방식', font=self.F_SECTION,
                 bg=self.C_CARD, fg=self.C_TEXT).pack(anchor='w', pady=(0, 6))

        self.overwrite_var = tk.BooleanVar(value=False)
        ttk.Radiobutton(
            inner, text='별도 파일로 저장 (원본 보존, 권장)',
            variable=self.overwrite_var, value=False, style='App.TRadiobutton'
        ).pack(anchor='w', pady=2)
        ttk.Radiobutton(
            inner, text='원본 파일에 덮어쓰기 (저장 전 자동 백업 생성)',
            variable=self.overwrite_var, value=True, style='App.TRadiobutton'
        ).pack(anchor='w', pady=2)

    def _build_log_card(self, parent):
        card = tk.Frame(parent, bg=self.C_CARD, highlightthickness=1,
                        highlightbackground=self.C_BORDER, highlightcolor=self.C_BORDER)
        card.pack(fill='x', pady=(12, 0))
        inner = tk.Frame(card, bg=self.C_CARD)
        inner.pack(fill='both', expand=True, padx=self.CARD_PAD_X, pady=(14, 16))

        tk.Label(inner, text='처리 로그', font=self.F_SECTION,
                 bg=self.C_CARD, fg=self.C_TEXT).pack(anchor='w', pady=(0, 6))
        self.log_box = scrolledtext.ScrolledText(
            inner, height=9, font=self.F_LOG, wrap='word',
            bg=self.C_LOG_BG, fg=self.C_LOG_FG, insertbackground=self.C_LOG_FG,
            relief='flat', borderwidth=0, padx=10, pady=8)

        self.log_box.pack(fill='both', expand=True)


    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        style.configure('App.TEntry', fieldbackground='#ffffff', bordercolor=self.C_BORDER,
                        lightcolor=self.C_BORDER, darkcolor=self.C_BORDER, padding=6, relief='solid')
        style.map('App.TEntry', bordercolor=[('focus', self.C_PRIMARY)])

        style.configure('App.TButton', background='#ffffff', foreground=self.C_TEXT,
                        font=self.F_BUTTON, padding=(12, 6), borderwidth=1,
                        bordercolor=self.C_BORDER, relief='solid')
        style.map('App.TButton', background=[('active', self.C_PRIMARY_SOFT)],
                  bordercolor=[('active', self.C_PRIMARY)])

        style.configure('App.TRadiobutton', background=self.C_CARD, foreground=self.C_TEXT,
                        font=self.F_BODY)
        style.map('App.TRadiobutton', background=[('active', self.C_CARD)])

        style.configure('App.Vertical.TScrollbar', background=self.C_BORDER,
                        troughcolor=self.C_BG, bordercolor=self.C_BG,
                        arrowcolor=self.C_SUBTEXT, relief='flat')

    def _make_badge(self, parent, num, bg, fg, border=None):
        """항상 같은 픽셀 크기의 정사각 번호 배지를 만든다(카드가 달라도 열이 어긋나지 않음)."""
        edge = 1 if border else 0
        side = self.BADGE_SIZE - 2 * edge
        box = tk.Frame(parent, bg=bg, width=side, height=side,
                       highlightthickness=edge,
                       highlightbackground=border or bg, highlightcolor=border or bg)
        box.pack_propagate(False)
        tk.Label(box, text=num, font=self.F_BADGE, bg=bg, fg=fg).place(relx=0.5, rely=0.5, anchor="center")
        return box

    def _add_prep_item(self, parent, row, num, title, desc):
        """사전 작업 카드 안의 체크리스트 한 줄(번호 배지 + 제목/설명)을 배치한다."""
        top_pad = 0 if row == 1 else 10
        badge = self._make_badge(parent, num, self.C_PREP_BADGE_BG, self.C_PREP_ACCENT,
                                 border=self.C_PREP_ACCENT)
        badge.grid(row=row, column=0, sticky="nw", pady=(top_pad + 1, 0))

        text_frame = tk.Frame(parent, bg=self.C_PREP_BG)
        text_frame.grid(row=row, column=1, sticky="we", pady=(top_pad, 0))
        text_frame.columnconfigure(0, weight=1)

        tk.Label(text_frame, text=title, font=self.F_PREP_TITLE,
                 bg=self.C_PREP_BG, fg=self.C_TEXT).grid(row=0, column=0, sticky="w")
        lbl = tk.Label(text_frame, text=desc, font=self.F_STEP_DESC, bg=self.C_PREP_BG,
                       fg=self.C_SUBTEXT, justify="left", anchor="w")
        lbl.grid(row=1, column=0, sticky="we", pady=(2, 0))

        self._wrap_labels.append((lbl, 32 + 2 * self.CARD_PAD_X + self.BADGE_COL_W + 8))

    def _add_step(self, parent, row, num, title, desc, var, command, optional=False):
        """번호 배지 + 라벨/입력창/찾아보기 버튼 한 세트를 카드 안에 배치한다."""
        top_pad = 0 if row == 0 else 16
        badge = self._make_badge(parent, num, self.C_PRIMARY, self.C_BADGE_FG)
        badge.grid(row=row, column=0, sticky="nw", pady=(top_pad + 1, 0))

        text_frame = tk.Frame(parent, bg=self.C_CARD)
        text_frame.grid(row=row, column=1, sticky="we", pady=(top_pad, 0))
        text_frame.columnconfigure(0, weight=1)

        title_text = title + ("  (선택)" if optional else "")
        t = tk.Label(text_frame, text=title_text, font=self.F_SECTION,
                     bg=self.C_CARD, fg=self.C_TEXT, justify="left", anchor="w")
        t.grid(row=0, column=0, sticky="we")
        self._wrap_labels.append((t, 32 + 2 * self.CARD_PAD_X + self.BADGE_COL_W + 8))

        d = tk.Label(text_frame, text=desc, font=self.F_STEP_DESC,
                     bg=self.C_CARD, fg=self.C_SUBTEXT, justify="left", anchor="w")
        d.grid(row=1, column=0, sticky="we", pady=(0, 5))
        self._wrap_labels.append((d, 32 + 2 * self.CARD_PAD_X + self.BADGE_COL_W + 8))

        entry_row = tk.Frame(text_frame, bg=self.C_CARD)
        entry_row.grid(row=2, column=0, sticky="we")
        entry_row.columnconfigure(0, weight=1)
        ttk.Entry(entry_row, textvariable=var, font=self.F_BODY,
                  style="App.TEntry").grid(row=0, column=0, sticky="we")
        if command is not None:
            ttk.Button(entry_row, text="찾아보기", style="App.TButton",
                       command=command).grid(row=0, column=1, padx=(8, 0))

    def _scroll_to_log(self):
        """실행 직후 처리 로그가 보이도록 본문을 아래로 내린다."""
        try:
            self.canvas.update_idletasks()
            self.canvas.yview_moveto(1.0)
        except tk.TclError:
            pass

    def log(self, msg):
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.root.update_idletasks()

    def browse_src(self):
        path = filedialog.askopenfilename(
            title="초과근무목록_YYYYMM.xls 선택",
            filetypes=[("Excel 97-2003 (*.xls)", "*.xls"), ("모든 파일", "*.*")],
        )
        if path:
            self.src_var.set(path)

    def browse_tgt(self):
        path = filedialog.askopenfilename(
            title="부서연번_..._일반부서.xlsx 선택",
            filetypes=[("Excel (*.xlsx)", "*.xlsx"), ("모든 파일", "*.*")],
        )
        if path:
            self.tgt_var.set(path)

    def browse_leave(self):
        path = filedialog.askopenfilename(
            title="개인별근무상황내역(연가내역)_YYYYMM.xls 선택 (선택 사항)",
            filetypes=[("Excel 97-2003 (*.xls)", "*.xls"), ("모든 파일", "*.*")],
        )
        if path:
            self.leave_var.set(path)

    def run(self):
        src = self.src_var.get().strip()
        tgt = self.tgt_var.get().strip()
        leave_path = self.leave_var.get().strip()

        if not src or not os.path.isfile(src):
            messagebox.showerror("오류", "1번 초과근무목록.xls 파일을 올바르게 선택하세요.")
            return
        if not tgt or not os.path.isfile(tgt):
            messagebox.showerror("오류", "2번 부서연번...xlsx 파일을 올바르게 선택하세요.")
            return
        if leave_path and not os.path.isfile(leave_path):
            messagebox.showerror("오류", "3번 연가내역 파일 경로가 올바르지 않습니다.")
            return

        self.log_box.delete("1.0", "end")
        self._scroll_to_log()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base, ext = os.path.splitext(tgt)

        try:
            self.log(f"[1/4] 원본 파일 읽는 중: {src}")
            rows = read_source_xls(src, self.log)

            if len(rows) == 0:
                messagebox.showwarning("경고", "원본 파일에서 읽은 데이터가 없습니다. 처리를 중단합니다.")
                return

            if len(rows) > MAX_DATA_ROWS:
                messagebox.showerror(
                    "오류",
                    f"원본 데이터가 {len(rows)}건으로, 자료입력 시트가 지원하는 최대 "
                    f"{MAX_DATA_ROWS}건을 초과합니다. 서식 파일의 행 범위를 확인하세요.",
                )
                return

            holidays = parse_holidays(self.holidays_var.get())
            self.log(f"이번 달 공휴일로 입력된 날짜: {sorted(str(d) for d in holidays) or '(없음)'}")

            leave_records = {}
            if leave_path:
                self.log(f"연가내역 파일 읽는 중: {leave_path}")
                leave_records = read_leave_xls(leave_path, self.log)
            else:
                self.log("연가내역 파일 없음 — 소정근로시간 계산에는 공휴일만 반영됩니다.")

            if self.overwrite_var.get():
                backup_path = f"{base}_백업_{timestamp}{ext}"
                shutil.copy2(tgt, backup_path)
                self.log(f"[2/4] 원본 백업 생성: {backup_path}")
                output_path = tgt
            else:
                output_path = f"{base}_자동입력_{timestamp}{ext}"
                self.log(f"[2/4] 별도 파일로 저장 예정: {output_path}")

            self.log("[3/4] 워크북을 열어 자료입력 시트에 값 입력 중...")
            wb = load_target_workbook(tgt, self.log)
            fill_data_sheet(wb, rows, self.log)

            self.log("[4/4] 처리 건만 합산해서 이름 시트 '1주~5주' 표 계산 중... (연장·휴일근무는 0.5시간 단위로 반올림 후 월 총합에 맞춰 보정)")

            name_sheets = [n for n in wb.sheetnames if n not in NON_NAME_SHEETS]
            employees, weeks, year, month = build_weekly_summary(
                rows, leave_records, holidays, self.log, extra_names=name_sheets
            )
            if weeks:
                self.log(f"이번 달 주차 구성(일요일 시작): {[str(w) for w in weeks]}")
            write_weekly_summary_to_name_sheets(wb, employees, self.log)

            mark_no_overtime_sheets(wb, self.log)

            fill_time_input_sheet_formulas(wb, self.log)
            fill_time_input_sheet_month(wb, month, self.log)

            wb.save(output_path)
            self.log(f"저장 완료: {output_path}")

            messagebox.showinfo(
                "완료",
                f"총 {len(rows)}건을 '{DATA_SHEET_NAME}' 시트에 입력하고,\n이름 시트 '1주~5주' 표도 자동으로 계산해서 채웠습니다.\n\n결과 파일:\n"
                f"{output_path}",
            )

        except PermissionError:
            messagebox.showerror(
                "오류",
                "파일에 쓸 수 없습니다. 대상 엑셀 파일이 이미 열려 있다면 닫고 다시 시도하세요.",
            )
        except zipfile.BadZipFile:
            messagebox.showerror(
                "오류",
                "대상 xlsx 파일을 열 수 없습니다. 회사 보안 프로그램(DRM)으로 암호화된 파일일 수 있습니다.\n해당 파일을 엑셀로 정상적으로 열 수 있는지 확인 후, 필요하다면 암호를 해제하거나\n'다른 이름으로 저장'으로 새 파일을 만든 뒤 다시 시도해 주세요.",
            )


        except Exception as e:
            self.log(f"❌ 오류 발생: {e}")
            messagebox.showerror("오류", f"처리 중 오류가 발생했습니다:\n{e}")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
