# -*- coding: utf-8 -*-
"""
네트워크 설정 생성기 - 1단계
=================================
./dataset 폴더의 CSV 5종(devices, links, vlans, interfaces, l3_config)을 읽어와
GUI 테이블로 표시하고, 사용자가 행을 추가/수정/삭제할 수 있게 한다.

다음 단계 확장 지점:
  - 장비 간 링크를 GUI에서 직접 연결(드래그 등)하는 토폴로지 화면
  - Jinja2 템플릿 기반 컨피그(.txt) 생성 버튼
  - 입력값 검증(IP 포맷, VLAN 중복 등)

현재 단계 범위:
  - CSV 로드
  - 테이블 표시
  - 행 추가 / 수정 / 삭제
  - ./output 에 CSV로 저장
"""

import os
import csv
import tkinter as tk
from tkinter import ttk, messagebox

import pandas as pd

# -----------------------------
# 경로 설정
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(BASE_DIR, "..", "dataset")
OUTPUT_DIR = os.path.join(BASE_DIR, "..", "output")

# 다룰 CSV 파일 목록 (탭 이름, 파일명)
CSV_FILES = [
    ("장비정보 (devices)", "devices.csv"),
    ("연결관계 (links)", "links.csv"),
    ("VLAN (vlans)", "vlans.csv"),
    ("포트설정 (interfaces)", "interfaces.csv"),
    ("L3설정 (l3_config)", "l3_config.csv"),
]


class CsvTableFrame(ttk.Frame):
    """
    CSV 한 개를 표시/편집하는 탭 프레임.
    - 위쪽: Treeview 테이블 (스크롤바 포함)
    - 아래쪽: 선택한 행을 편집하는 입력 폼 + 추가/수정/삭제/저장 버튼
    """

    def __init__(self, parent, file_path: str):
        super().__init__(parent)
        self.file_path = file_path
        self.columns = []
        self.df = pd.DataFrame()
        self.entry_widgets = {}  # 컬럼명 -> Entry 위젯
        self.selected_item_id = None  # 현재 Treeview에서 선택된 row id

        self._load_csv()
        self._build_ui()
        self._refresh_table()

    # -----------------------------
    # 데이터 로드
    # -----------------------------
    def _load_csv(self):
        if os.path.exists(self.file_path):
            # 빈 문자열을 NaN으로 바꾸지 않도록 keep_default_na=False 사용
            # (네트워크 설정값 중 빈 칸이 의미를 가지는 경우가 많음)
            self.df = pd.read_csv(self.file_path, dtype=str, keep_default_na=False)
        else:
            self.df = pd.DataFrame()
        self.columns = list(self.df.columns)

    # -----------------------------
    # UI 구성
    # -----------------------------
    def _build_ui(self):
        # ---- 상단: 테이블 영역 ----
        table_frame = ttk.Frame(self)
        table_frame.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        self.tree = ttk.Treeview(
            table_frame, columns=self.columns, show="headings", selectmode="browse"
        )
        for col in self.columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=120, anchor="w", stretch=True)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)

        # ---- 중단: 입력 폼 영역 (스크롤 가능하게 캔버스로 감쌈) ----
        form_outer = ttk.LabelFrame(self, text="행 입력 / 수정")
        form_outer.pack(fill="x", padx=8, pady=4)

        form_canvas = tk.Canvas(form_outer, height=140, highlightthickness=0)
        form_scrollbar = ttk.Scrollbar(
            form_outer, orient="vertical", command=form_canvas.yview
        )
        self.form_inner = ttk.Frame(form_canvas)

        self.form_inner.bind(
            "<Configure>",
            lambda e: form_canvas.configure(scrollregion=form_canvas.bbox("all")),
        )
        form_canvas.create_window((0, 0), window=self.form_inner, anchor="nw")
        form_canvas.configure(yscrollcommand=form_scrollbar.set)

        form_canvas.pack(side="left", fill="both", expand=True)
        form_scrollbar.pack(side="right", fill="y")

        # 컬럼마다 라벨 + 입력칸을 격자로 배치 (한 줄에 3쌍씩)
        self.entry_widgets = {}
        cols_per_row = 3
        for idx, col in enumerate(self.columns):
            r = idx // cols_per_row
            c = (idx % cols_per_row) * 2
            ttk.Label(self.form_inner, text=col, width=18, anchor="e").grid(
                row=r, column=c, padx=4, pady=4, sticky="e"
            )
            entry = ttk.Entry(self.form_inner, width=22)
            entry.grid(row=r, column=c + 1, padx=4, pady=4, sticky="w")
            self.entry_widgets[col] = entry

        # ---- 하단: 버튼 영역 ----
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=8, pady=(0, 8))

        ttk.Button(btn_frame, text="행 추가", command=self._add_row).pack(
            side="left", padx=4
        )
        ttk.Button(btn_frame, text="선택 행 수정", command=self._update_row).pack(
            side="left", padx=4
        )
        ttk.Button(btn_frame, text="선택 행 삭제", command=self._delete_row).pack(
            side="left", padx=4
        )
        ttk.Button(btn_frame, text="입력칸 비우기", command=self._clear_form).pack(
            side="left", padx=4
        )
        ttk.Button(
            btn_frame, text="CSV로 저장 (output)", command=self._save_csv
        ).pack(side="right", padx=4)

    # -----------------------------
    # 테이블 갱신
    # -----------------------------
    def _refresh_table(self):
        self.tree.delete(*self.tree.get_children())
        for idx, row in self.df.iterrows():
            values = [row[col] for col in self.columns]
            self.tree.insert("", "end", iid=str(idx), values=values)

    # -----------------------------
    # 이벤트 핸들러
    # -----------------------------
    def _on_row_select(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        item_id = selected[0]
        self.selected_item_id = item_id
        values = self.tree.item(item_id, "values")
        for col, val in zip(self.columns, values):
            self.entry_widgets[col].delete(0, "end")
            self.entry_widgets[col].insert(0, val)

    def _get_form_values(self) -> dict:
        return {col: self.entry_widgets[col].get() for col in self.columns}

    def _clear_form(self):
        for col in self.columns:
            self.entry_widgets[col].delete(0, "end")
        self.selected_item_id = None
        self.tree.selection_remove(self.tree.selection())

    def _add_row(self):
        values = self._get_form_values()
        new_idx = len(self.df)
        self.df.loc[new_idx] = values
        self._refresh_table()
        self._clear_form()

    def _update_row(self):
        if self.selected_item_id is None:
            messagebox.showwarning("알림", "수정할 행을 먼저 테이블에서 선택하세요.")
            return
        idx = int(self.selected_item_id)
        values = self._get_form_values()
        for col in self.columns:
            self.df.at[idx, col] = values[col]
        self._refresh_table()
        self._clear_form()

    def _delete_row(self):
        if self.selected_item_id is None:
            messagebox.showwarning("알림", "삭제할 행을 먼저 테이블에서 선택하세요.")
            return
        idx = int(self.selected_item_id)
        self.df = self.df.drop(index=idx).reset_index(drop=True)
        self._refresh_table()
        self._clear_form()

    def _save_csv(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        filename = os.path.basename(self.file_path)
        save_path = os.path.join(OUTPUT_DIR, filename)
        self.df.to_csv(save_path, index=False, quoting=csv.QUOTE_MINIMAL)
        messagebox.showinfo("저장 완료", f"저장되었습니다:\n{save_path}")


class NetConfigApp(tk.Tk):
    """메인 애플리케이션 윈도우. CSV 파일별로 탭을 구성한다."""

    def __init__(self):
        super().__init__()
        self.title("네트워크 설정 생성기 - 1단계 (CSV 입력/편집)")
        self.geometry("1100x650")

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        missing_files = []
        for tab_name, filename in CSV_FILES:
            file_path = os.path.join(DATASET_DIR, filename)
            if not os.path.exists(file_path):
                missing_files.append(filename)
                continue
            frame = CsvTableFrame(notebook, file_path)
            notebook.add(frame, text=tab_name)

        if missing_files:
            messagebox.showwarning(
                "파일 누락",
                "다음 CSV 파일을 ./dataset 폴더에서 찾지 못했습니다:\n"
                + "\n".join(missing_files),
            )


if __name__ == "__main__":
    app = NetConfigApp()
    app.mainloop()
