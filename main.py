# -*- coding: utf-8 -*-
"""
네트워크 설정 생성기 v3
=================================
변경사항:
  - 시작 시 프로젝트 선택 다이얼로그 (기존 열기 / 신규 생성)
  - 신규 프로젝트 생성 시 폴더 + 빈 CSV 7종 자동 생성
  - 입력값 검증 (IP/서브넷/VLAN/키 일치 등) - 저장 전 및 TXT 생성 전 실행
  - 더블클릭으로 수정 모드 진입
  - 컬럼 헤더 클릭으로 정렬 (오름차/내림차 토글)
  - 텍스트 검색/필터 (실시간 필터)
  - 입력 폼 Enter → 선택 행 수정 / 선택 없으면 추가
  - GUI 컬럼명 한글화 (CSV 파일 자체는 영문 그대로)
  - 프로젝트 선택 다이얼로그 디자인을 메인 화면과 통일
"""

import os
import csv
import platform
import tkinter as tk
from tkinter import ttk, font as tkfont, messagebox, simpledialog
import tkinter.scrolledtext as scrolledtext

import pandas as pd

from config_generator import generate_all_configs
from column_labels import get_label
from validator import validate_all
from topology import TopologyFrame

try:
    import winreg
except ImportError:
    winreg = None

try:
    import ipaddress as _ipaddress
except ImportError:
    _ipaddress = None

# -----------------------------
# 경로 설정
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECTS_DIR = os.path.join(BASE_DIR, "projects")

# VS_Code(venv + model)는 현재 폴더 또는 부모 폴더에서 탐색
def _find_vs_code_dir() -> str:
    for candidate in (BASE_DIR, os.path.dirname(BASE_DIR)):
        if os.path.isdir(os.path.join(candidate, "VS_Code")):
            return os.path.join(candidate, "VS_Code")
    return os.path.join(BASE_DIR, "VS_Code")  # 없으면 기본값 유지

VS_CODE_DIR = _find_vs_code_dir()

CSV_FILES = [
    ("장비정보 (devices)", "devices.csv"),
    ("연결관계 (links)", "links.csv"),
    ("VLAN (vlans)", "vlans.csv"),
    ("포트설정 (interfaces)", "interfaces.csv"),
    ("L3설정 (l3_config)", "l3_config.csv"),
    ("방화벽정책 (fw_policy)", "fw_policy.csv"),
    ("OSPF설정 (ospf_config)", "ospf_config.csv"),
]

CSV_HEADERS = {
    "devices.csv":     "device_name,device_type,vendor,model,mgmt_ip,mgmt_subnet_mask,mgmt_vlan,site,role,description",
    "links.csv":       "link_id,device_a,port_a,device_b,port_b,link_type,speed,description",
    "vlans.csv":       "vlan_id,vlan_name,purpose,site,description",
    "interfaces.csv":  "device_name,port_name,mode,access_vlan,trunk_allowed_vlans,native_vlan,port_status,description",
    "l3_config.csv":   "device_name,config_type,vlan_id,interface_name,ip_address,subnet_mask,gateway_redundancy_mode,hsrp_vrrp_vip,priority,routing_protocol,destination_network,next_hop,description",
    "fw_policy.csv":   "policy_id,device_name,policy_name,src_intf,dst_intf,src_subnet,dst_subnet,service,action,nat_enable,nat_type,description",
    "ospf_config.csv": "device_name,ospf_process_id,router_id,interface_name,area_id,network_type,priority,cost,passive_interface,description",
}


# -----------------------------
# 테마 / 폰트
# -----------------------------
def is_windows_dark_mode() -> bool:
    if winreg is None or platform.system() != "Windows":
        return False
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
    except Exception:
        return False


def build_theme_palette() -> dict:
    if is_windows_dark_mode():
        return {
            "bg": "#1e1e1e", "fg": "#e6e6e6",
            "field_bg": "#2d2d2d", "field_fg": "#ffffff",
            "select_bg": "#3a6ea5", "select_fg": "#ffffff",
            "border": "#3c3c3c", "heading_bg": "#2d2d2d",
            "heading_fg": "#ffffff", "button_bg": "#333333",
            "warn_bg": "#5a3a1a",
        }
    return {
        "bg": "#f3f3f3", "fg": "#1a1a1a",
        "field_bg": "#ffffff", "field_fg": "#000000",
        "select_bg": "#cfe4ff", "select_fg": "#000000",
        "border": "#d0d0d0", "heading_bg": "#e8e8e8",
        "heading_fg": "#1a1a1a", "button_bg": "#e1e1e1",
        "warn_bg": "#fff3cd",
    }


def pick_gothic_font_family() -> str:
    preferred = ["맑은 고딕", "Malgun Gothic", "Segoe UI", "Noto Sans KR", "Arial"]
    available = set(tkfont.families())
    for name in preferred:
        if name in available:
            return name
    return "TkDefaultFont"


BASE_FONT_SIZE = 11
TITLE_FONT_SIZE = 12
HEADING_FONT_SIZE = 11


def apply_theme_and_fonts(root, palette, font_family):
    root.configure(bg=palette["bg"])
    base_font = (font_family, BASE_FONT_SIZE)
    title_font = (font_family, TITLE_FONT_SIZE, "bold")
    heading_font = (font_family, HEADING_FONT_SIZE, "bold")

    for name in ["TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"]:
        try:
            tkfont.nametofont(name).configure(family=font_family, size=BASE_FONT_SIZE)
        except tk.TclError:
            pass

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", font=base_font, background=palette["bg"], foreground=palette["fg"])
    style.configure("TFrame", background=palette["bg"])
    style.configure("TLabel", background=palette["bg"], foreground=palette["fg"], font=base_font)
    style.configure("TLabelframe", background=palette["bg"], foreground=palette["fg"], bordercolor=palette["border"])
    style.configure("TLabelframe.Label", background=palette["bg"], foreground=palette["fg"], font=title_font)
    style.configure("TButton", background=palette["button_bg"], foreground=palette["fg"], font=base_font, padding=6)
    style.map("TButton", background=[("active", palette["select_bg"])])
    style.configure("TEntry", fieldbackground=palette["field_bg"], foreground=palette["field_fg"],
                    font=base_font, insertcolor=palette["field_fg"])
    style.configure("TNotebook", background=palette["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background=palette["button_bg"], foreground=palette["fg"],
                    font=title_font, padding=(8, 5))
    style.map("TNotebook.Tab",
              background=[("selected", palette["select_bg"])],
              foreground=[("selected", palette["select_fg"])])
    style.configure("Treeview", background=palette["field_bg"], fieldbackground=palette["field_bg"],
                    foreground=palette["field_fg"], font=base_font,
                    rowheight=int(BASE_FONT_SIZE * 2.2))
    style.configure("Treeview.Heading", background=palette["heading_bg"],
                    foreground=palette["heading_fg"], font=heading_font)
    style.map("Treeview",
              background=[("selected", palette["select_bg"])],
              foreground=[("selected", palette["select_fg"])])
    style.configure("TScrollbar", background=palette["button_bg"])

    return base_font, title_font, heading_font


# -----------------------------
# 프로젝트 선택 다이얼로그
# -----------------------------
class ProjectDialog(tk.Toplevel):

    def __init__(self, parent, palette: dict, fonts: dict):
        super().__init__(parent)
        self.title("네트워크 설정 생성기 — 프로젝트 선택")
        self.resizable(False, False)
        self.result = None
        self.palette = palette
        self.fonts = fonts
        self.grab_set()
        self.configure(bg=palette["bg"])

        self._build_ui()
        self._load_project_list()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self.update_idletasks()
        w, h = 480, 420
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        ttk.Label(self,
                  text="프로젝트를 선택하거나 새로 만드세요.",
                  font=self.fonts["title"],
                  padding=(16, 14, 16, 6)).pack(anchor="w")

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=16)

        list_frame = ttk.Frame(self)
        list_frame.pack(fill="both", expand=True, padx=16, pady=10)

        vsb = ttk.Scrollbar(list_frame, orient="vertical")
        self.tree = ttk.Treeview(list_frame, columns=("name",), show="headings",
                                 selectmode="browse", yscrollcommand=vsb.set)
        self.tree.heading("name", text="프로젝트명")
        self.tree.column("name", anchor="w", stretch=True)
        vsb.configure(command=self.tree.yview)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Double-Button-1>", lambda e: self._on_open())

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=16)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=16, pady=12)
        ttk.Button(btn_frame, text="열기", command=self._on_open).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="신규 프로젝트", command=self._on_new).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="취소", command=self._on_cancel).pack(side="right", padx=4)

    def _load_project_list(self):
        self.tree.delete(*self.tree.get_children())
        os.makedirs(PROJECTS_DIR, exist_ok=True)
        projects = sorted([
            d for d in os.listdir(PROJECTS_DIR)
            if os.path.isdir(os.path.join(PROJECTS_DIR, d))
        ])
        for p in projects:
            self.tree.insert("", "end", iid=p, values=(p,))
        if projects:
            self.tree.selection_set(projects[0])
            self.tree.see(projects[0])

    def _on_open(self):
        if self.result is not None:
            return
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("알림", "프로젝트를 선택하세요.", parent=self)
            return
        self.result = os.path.join(PROJECTS_DIR, sel[0])
        self._close()

    def _on_new(self):
        name = simpledialog.askstring("신규 프로젝트", "프로젝트 이름을 입력하세요:", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()

        if any(c in set(r'\/:*?"<>|') for c in name):
            messagebox.showerror("오류", "프로젝트 이름에 사용할 수 없는 문자가 포함돼 있습니다.", parent=self)
            return

        project_path = os.path.join(PROJECTS_DIR, name)
        if os.path.exists(project_path):
            messagebox.showerror("오류", f"'{name}' 프로젝트가 이미 존재합니다.", parent=self)
            return

        os.makedirs(os.path.join(project_path, "dataset"), exist_ok=True)
        os.makedirs(os.path.join(project_path, "output"), exist_ok=True)

        for fname, header in CSV_HEADERS.items():
            with open(os.path.join(project_path, "dataset", fname),
                      "w", encoding="utf-8", newline="") as f:
                f.write(header + "\n")

        messagebox.showinfo("완료", f"프로젝트 '{name}'이 생성됐습니다.", parent=self)
        self._load_project_list()
        self.tree.selection_set(name)
        self.tree.see(name)

    def _on_cancel(self):
        self.result = None
        self._close()

    def _close(self):
        try:
            self.tree.unbind("<Double-Button-1>")
            self.tree.unbind_class("Treeview", "<Double-Button-1>")
        except Exception:
            pass
        self.after(10, self.destroy)


# -----------------------------
# 자동 채우기 다이얼로그
# -----------------------------
class AutoFillDialog(tk.Toplevel):
    """VLAN / 서브넷 입력 후 장비 타입·IP·interfaces·l3_config 자동 생성."""

    _DEFAULTS = [
        ("100", "Management", "192.168.100.0/24", True),
        ("200", "Data",       "10.0.0.0/24",      False),
    ]

    def __init__(self, parent, palette: dict, fonts: dict):
        super().__init__(parent)
        self.title("자동 채우기 — VLAN / 네트워크 설정")
        self.resizable(False, False)
        self.result = None
        self._palette = palette
        self._fonts = fonts
        self._rows: list = []   # list of (vid_var, name_var, sub_var, mgmt_var)
        self.grab_set()
        self.configure(bg=palette["bg"])
        self._build_ui()
        for vid, name, sub, mgmt in self._DEFAULTS:
            self._add_row(vid, name, sub, mgmt)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.update_idletasks()
        w, h = 620, 380
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        ttk.Label(
            self,
            text="VLAN과 서브넷을 지정하면 장비 타입·IP·인터페이스·L3 설정을 자동으로 생성합니다.",
            padding=(16, 12, 16, 4),
        ).pack(anchor="w")
        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=16)

        # 컬럼 헤더
        hdr = ttk.Frame(self)
        hdr.pack(fill="x", padx=20, pady=(8, 2))
        for col, w, text in [
            (0, 8,  "VLAN ID"),
            (1, 20, "VLAN 이름"),
            (2, 22, "서브넷 (CIDR)"),
            (3, 7,  "관리용"),
        ]:
            ttk.Label(hdr, text=text, width=w, anchor="center").grid(
                row=0, column=col, padx=4)

        # 스크롤 가능한 입력 테이블
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True, padx=16, pady=2)
        self._canvas = tk.Canvas(
            outer, bg=palette_bg(self._palette), highlightthickness=0, height=140)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._tbl = ttk.Frame(self._canvas)
        self._tbl.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.create_window((0, 0), window=self._tbl, anchor="nw")
        self._canvas.configure(yscrollcommand=vsb.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # 행 추가/삭제 버튼
        row_btn = ttk.Frame(self)
        row_btn.pack(fill="x", padx=16, pady=(2, 4))
        ttk.Button(row_btn, text="+ VLAN 추가",
                   command=lambda: self._add_row()).pack(side="left", padx=4)
        ttk.Button(row_btn, text="마지막 삭제",
                   command=self._del_last).pack(side="left", padx=4)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=16)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=16, pady=10)
        ttk.Button(btns, text="자동 채우기 실행",
                   command=self._on_ok).pack(side="right", padx=4)
        ttk.Button(btns, text="취소",
                   command=self._on_cancel).pack(side="right", padx=4)

    def _add_row(self, vid="", name="", subnet="", is_mgmt=False):
        idx = len(self._rows)
        vid_v  = tk.StringVar(value=str(vid))
        nam_v  = tk.StringVar(value=name)
        sub_v  = tk.StringVar(value=subnet)
        mgmt_v = tk.BooleanVar(value=is_mgmt)
        ttk.Entry(self._tbl, textvariable=vid_v,  width=9).grid(
            row=idx, column=0, padx=4, pady=3)
        ttk.Entry(self._tbl, textvariable=nam_v,  width=20).grid(
            row=idx, column=1, padx=4, pady=3)
        ttk.Entry(self._tbl, textvariable=sub_v,  width=24).grid(
            row=idx, column=2, padx=4, pady=3)
        ttk.Checkbutton(self._tbl, variable=mgmt_v).grid(
            row=idx, column=3, padx=8, pady=3)
        self._rows.append((vid_v, nam_v, sub_v, mgmt_v))

    def _del_last(self):
        if len(self._rows) <= 1:
            return
        saved = [(v.get(), n.get(), s.get(), m.get())
                 for v, n, s, m in self._rows[:-1]]
        self._rows.clear()
        for w in self._tbl.winfo_children():
            w.destroy()
        for vid, name, sub, mgmt in saved:
            self._add_row(vid, name, sub, mgmt)

    def _on_ok(self):
        configs = []
        for vid_v, nam_v, sub_v, mgmt_v in self._rows:
            vid = vid_v.get().strip()
            sub = sub_v.get().strip()
            if not vid or not sub:
                continue
            try:
                int(vid)
                if _ipaddress:
                    _ipaddress.IPv4Network(sub, strict=False)
            except ValueError as e:
                messagebox.showerror("입력 오류", f"VLAN {vid}: {e}", parent=self)
                return
            configs.append({
                "vlan_id":   int(vid),
                "vlan_name": nam_v.get().strip() or f"VLAN{vid}",
                "subnet":    sub,
                "is_mgmt":   mgmt_v.get(),
            })
        if not configs:
            messagebox.showwarning("알림", "VLAN을 최소 1개 입력하세요.", parent=self)
            return
        if not any(c["is_mgmt"] for c in configs):
            configs[0]["is_mgmt"] = True
        self.result = configs
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()


def palette_bg(palette: dict) -> str:
    return palette.get("bg", "#1e1e1e")


# -----------------------------
# CSV 탭 프레임
# -----------------------------
class CsvTableFrame(ttk.Frame):

    def __init__(self, parent, file_path: str, fonts: dict, palette: dict):
        super().__init__(parent)
        self.file_path = file_path
        self.fonts = fonts
        self.palette = palette
        self.columns = []
        self.df = pd.DataFrame()
        self.df_full = pd.DataFrame()
        self.entry_widgets = {}
        self.selected_item_id = None
        self._sort_col = None
        self._sort_asc = True

        self._load_csv()
        self._build_ui()
        self._refresh_table()

    def _load_csv(self):
        if os.path.exists(self.file_path):
            self.df = pd.read_csv(self.file_path, dtype=str, keep_default_na=False)
        else:
            self.df = pd.DataFrame()
        self.df_full = self.df.copy()
        self.columns = list(self.df.columns)

    def _apply_column_widths(self):
        heading_font = tkfont.Font(font=self.fonts["heading"])
        body_font = tkfont.Font(font=self.fonts["base"])
        MIN_WIDTH, MAX_WIDTH, PADDING = 80, 300, 24

        for col in self.columns:
            label = get_label(col)
            self.tree.heading(col, text=label,
                              command=lambda c=col: self._sort_by_column(c))
            heading_width = heading_font.measure(label)
            if len(self.df_full) > 0:
                values = self.df_full[col].astype(str)
                longest_value = values.loc[values.str.len().idxmax()]
                data_width = body_font.measure(longest_value)
            else:
                data_width = 0
            width = max(heading_width, data_width) + PADDING
            width = max(MIN_WIDTH, min(width, MAX_WIDTH))
            self.tree.column(col, width=width, anchor="w", stretch=True)

    def _sort_by_column(self, col: str):
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        self.df = self.df.sort_values(by=col, ascending=self._sort_asc,
                                      key=lambda s: s.str.lower()).reset_index(drop=True)
        self._refresh_table()

    def _build_ui(self):
        # 검색 바
        search_frame = ttk.Frame(self)
        search_frame.pack(fill="x", padx=8, pady=(6, 0))

        ttk.Label(search_frame, text="검색:").pack(side="left")
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(search_frame, textvariable=self._search_var, width=30,
                  font=self.fonts["base"]).pack(side="left", padx=6)
        ttk.Button(search_frame, text="초기화", command=self._clear_filter).pack(side="left")
        self._filter_label = ttk.Label(search_frame, text="")
        self._filter_label.pack(side="left", padx=10)

        # 테이블
        table_frame = ttk.Frame(self)
        table_frame.pack(fill="both", expand=True, padx=8, pady=(4, 4))

        self.tree = ttk.Treeview(table_frame, columns=self.columns,
                                 show="headings", selectmode="browse")
        self._apply_column_widths()

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)
        self.tree.bind("<Double-Button-1>", self._on_row_double_click)

        # 입력 폼
        form_outer = ttk.LabelFrame(self, text="행 입력 / 수정  (Enter: 수정 적용 / 선택 없으면 추가)")
        form_outer.pack(fill="x", padx=8, pady=4)

        form_canvas = tk.Canvas(form_outer, height=220, highlightthickness=0,
                                bg=self.palette["bg"])
        form_scrollbar = ttk.Scrollbar(form_outer, orient="vertical",
                                       command=form_canvas.yview)
        self.form_inner = ttk.Frame(form_canvas)
        self.form_inner.bind("<Configure>",
                             lambda e: form_canvas.configure(
                                 scrollregion=form_canvas.bbox("all")))
        form_canvas.create_window((0, 0), window=self.form_inner, anchor="nw")
        form_canvas.configure(yscrollcommand=form_scrollbar.set)
        form_canvas.pack(side="left", fill="both", expand=True)
        form_scrollbar.pack(side="right", fill="y")

        self.entry_widgets = {}
        cols_per_row = 4
        for idx, col in enumerate(self.columns):
            r = idx // cols_per_row
            c = (idx % cols_per_row) * 2
            ttk.Label(self.form_inner, text=get_label(col), width=18,
                      anchor="e", font=self.fonts["base"]).grid(
                row=r, column=c, padx=4, pady=5, sticky="e")
            entry = ttk.Entry(self.form_inner, width=28, font=self.fonts["base"])
            entry.grid(row=r, column=c + 1, padx=4, pady=5, sticky="w")
            entry.bind("<Return>",
                       lambda e: self._update_row() if self.selected_item_id else self._add_row())
            self.entry_widgets[col] = entry

        # 버튼
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=8, pady=(0, 8))

        ttk.Button(btn_frame, text="행 추가", command=self._add_row).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="선택 행 수정", command=self._update_row).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="선택 행 삭제", command=self._delete_row).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="입력칸 비우기", command=self._clear_form).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="CSV로 저장", command=self._save_csv).pack(side="right", padx=4)

    def _apply_filter(self):
        query = self._search_var.get().strip().lower()
        if not query:
            self.df = self.df_full.copy()
            self._filter_label.config(text="")
        else:
            mask = self.df_full.apply(
                lambda row: row.astype(str).str.lower().str.contains(query).any(), axis=1)
            self.df = self.df_full[mask].reset_index(drop=True)
            self._filter_label.config(text=f"{len(self.df)}개 검색됨")
        self._refresh_table()

    def _clear_filter(self):
        self._search_var.set("")

    def _refresh_table(self):
        self.tree.delete(*self.tree.get_children())
        for idx, row in self.df.iterrows():
            values = [row[col] for col in self.columns]
            self.tree.insert("", "end", iid=str(idx), values=values)

    def _on_row_select(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        self.selected_item_id = selected[0]
        values = self.tree.item(selected[0], "values")
        for col, val in zip(self.columns, values):
            self.entry_widgets[col].delete(0, "end")
            self.entry_widgets[col].insert(0, val)

    def _on_row_double_click(self, event):
        selected = self.tree.selection()
        if not selected or not self.columns:
            return
        first_entry = self.entry_widgets[self.columns[0]]
        first_entry.focus_set()
        first_entry.icursor("end")

    def _get_form_values(self) -> dict:
        return {col: self.entry_widgets[col].get() for col in self.columns}

    def _clear_form(self):
        for col in self.columns:
            self.entry_widgets[col].delete(0, "end")
        self.selected_item_id = None
        self.tree.selection_remove(self.tree.selection())

    def _add_row(self):
        values = self._get_form_values()
        new_idx = len(self.df_full)
        self.df_full.loc[new_idx] = values
        self.df = self.df_full.copy()
        self._search_var.set("")
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
            self.df_full.at[idx, col] = values[col]
        self._refresh_table()
        self.tree.selection_set(str(idx))
        self.tree.see(str(idx))
        for col in self.columns:
            self.entry_widgets[col].delete(0, "end")

    def _delete_row(self):
        if self.selected_item_id is None:
            messagebox.showwarning("알림", "삭제할 행을 먼저 테이블에서 선택하세요.")
            return
        idx = int(self.selected_item_id)
        self.df = self.df.drop(index=idx).reset_index(drop=True)
        self.df_full = self.df.copy()
        self._refresh_table()
        self._clear_form()

    def _save_csv(self):
        key = os.path.basename(self.file_path).replace(".csv", "")
        from validator import validate_devices, validate_vlans
        fn_map = {
            "devices": lambda: validate_devices(self.df_full),
            "vlans": lambda: validate_vlans(self.df_full),
        }
        issues = fn_map[key]() if key in fn_map else []
        if issues:
            msg = "\n".join(issues[:10])
            if len(issues) > 10:
                msg += f"\n... 외 {len(issues)-10}건"
            if not messagebox.askyesno("검증 경고",
                                       f"아래 문제가 있습니다. 그래도 저장하시겠어요?\n\n{msg}"):
                return
        self.df_full.to_csv(self.file_path, index=False, quoting=csv.QUOTE_MINIMAL)
        messagebox.showinfo("저장 완료", f"저장됐습니다:\n{self.file_path}")


# -----------------------------
# 메인 애플리케이션
# -----------------------------
class NetConfigApp(tk.Tk):

    def __init__(self, project_path: str):
        super().__init__()
        self.project_path = project_path
        self.dataset_dir = os.path.join(project_path, "dataset")
        self.output_dir = os.path.join(project_path, "output")
        os.makedirs(self.output_dir, exist_ok=True)

        project_name = os.path.basename(project_path)
        self.title(f"네트워크 설정 생성기 v3  —  {project_name}")
        self.geometry("1600x820")

        palette = build_theme_palette()
        font_family = pick_gothic_font_family()
        base_font, title_font, heading_font = apply_theme_and_fonts(self, palette, font_family)
        fonts = {"base": base_font, "title": title_font, "heading": heading_font}
        self._palette = palette
        self._fonts = fonts

        # 상단 툴바
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=8, pady=(8, 0))

        ttk.Button(toolbar, text="전체 장비 TXT 컨피그 생성",
                   command=self._generate_all_txt_configs).pack(side="right", padx=4)
        ttk.Button(toolbar, text="전체 데이터 검증",
                   command=self._validate_all).pack(side="right", padx=4)
        ttk.Button(toolbar, text="프로젝트 전환",
                   command=self._switch_project).pack(side="left", padx=4)
        ttk.Button(toolbar, text="이미지 가져오기",
                   command=self._import_from_image).pack(side="left", padx=4)
        ttk.Button(toolbar, text="자동 채우기",
                   command=self._auto_fill).pack(side="left", padx=4)
        ttk.Label(toolbar, text=f"프로젝트: {project_name}",
                  font=(font_family, BASE_FONT_SIZE, "bold")).pack(side="left", padx=12)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_frames = {}
        missing_files = []
        for tab_name, filename in CSV_FILES:
            file_path = os.path.join(self.dataset_dir, filename)
            if not os.path.exists(file_path):
                missing_files.append(filename)
                continue
            frame = CsvTableFrame(notebook, file_path, fonts, palette)
            notebook.add(frame, text=tab_name)
            self.tab_frames[filename.replace(".csv", "")] = frame

        if missing_files:
            messagebox.showwarning("파일 누락",
                                   "다음 CSV 파일을 dataset 폴더에서 찾지 못했습니다:\n"
                                   + "\n".join(missing_files))

        # 구성도 탭
        topo_frame = TopologyFrame(
            notebook,
            lambda: {k: f.df_full for k, f in self.tab_frames.items()},
            fonts,
            palette,
        )
        notebook.add(topo_frame, text="구성도 (Topology)")

        def _on_tab_change(event):
            if notebook.nametowidget(notebook.select()) is topo_frame:
                topo_frame.after(80, topo_frame.refresh)

        notebook.bind("<<NotebookTabChanged>>", _on_tab_change)

    def _validate_all(self):
        dfs = {key: frame.df_full for key, frame in self.tab_frames.items()}
        issues = validate_all(dfs)

        win = tk.Toplevel(self)
        win.title("데이터 검증 결과")
        win.geometry("700x450")

        header = f"⚠  {len(issues)}개 문제가 발견됐습니다." if issues else "✓  검증 통과 — 오류 없음"
        ttk.Label(win, text=header,
                  font=(pick_gothic_font_family(), 12, "bold"),
                  padding=10).pack(anchor="w", padx=10)

        st = scrolledtext.ScrolledText(win, font=(pick_gothic_font_family(), 10),
                                       wrap="word")
        st.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        st.insert("end", "\n".join(issues) if issues else "모든 데이터가 유효합니다.")
        st.config(state="disabled")

        ttk.Button(win, text="닫기", command=win.destroy).pack(pady=(0, 10))

    def _generate_all_txt_configs(self):
        required = ["devices", "vlans", "interfaces", "l3_config", "fw_policy", "ospf_config"]
        missing = [k for k in required if k not in self.tab_frames]
        if missing:
            messagebox.showerror("생성 불가", f"다음 탭 데이터가 없습니다:\n{missing}")
            return

        dfs = {key: frame.df_full for key, frame in self.tab_frames.items()}
        issues = validate_all(dfs)
        if issues:
            msg = "\n".join(issues[:15])
            if len(issues) > 15:
                msg += f"\n... 외 {len(issues)-15}건"
            if not messagebox.askyesno("검증 경고",
                                       f"{len(issues)}개 문제가 있습니다. 그래도 생성하시겠어요?\n\n{msg}"):
                return

        try:
            paths = generate_all_configs(
                dfs["devices"], dfs["vlans"], dfs["interfaces"],
                dfs["l3_config"], dfs["fw_policy"], dfs["ospf_config"],
                self.output_dir
            )
        except Exception as e:
            messagebox.showerror("생성 실패", f"오류가 발생했습니다:\n{e}")
            return

        file_list = "\n".join(os.path.basename(p) for p in paths)
        messagebox.showinfo("TXT 생성 완료",
                            f"{len(paths)}개 장비 컨피그를 생성했습니다.\n"
                            f"위치: {os.path.join(self.output_dir, 'configs')}\n\n{file_list}")

    def _auto_fill(self):
        import csv as _csv
        from auto_fill import auto_fill as _do_fill

        if "devices" not in self.tab_frames:
            messagebox.showwarning("알림",
                "장비 데이터가 없습니다.\n"
                "먼저 이미지에서 가져오거나 devices.csv에 장비를 입력하세요.",
                parent=self)
            return

        dev_df = self.tab_frames["devices"].df_full
        if dev_df.empty or "device_name" not in dev_df.columns:
            messagebox.showwarning("알림", "devices.csv에 장비가 없습니다.", parent=self)
            return

        lnk_df = (self.tab_frames["links"].df_full
                  if "links" in self.tab_frames else pd.DataFrame())

        dialog = AutoFillDialog(self, self._palette, self._fonts)
        self.wait_window(dialog)
        if dialog.result is None:
            return

        try:
            result = _do_fill(dev_df, lnk_df, dialog.result)
        except Exception as exc:
            messagebox.showerror("자동 채우기 실패", str(exc), parent=self)
            return

        _CSV_MAP = {
            "devices":    "devices.csv",
            "vlans":      "vlans.csv",
            "interfaces": "interfaces.csv",
            "l3_config":  "l3_config.csv",
        }
        for key, fname in _CSV_MAP.items():
            df = result.get(key)
            if df is not None and not df.empty:
                df.to_csv(os.path.join(self.dataset_dir, fname),
                          index=False, quoting=_csv.QUOTE_MINIMAL)

        for frame in self.tab_frames.values():
            frame._load_csv()
            frame._refresh_table()

        vlan_cnt = len(dialog.result)
        messagebox.showinfo(
            "자동 채우기 완료",
            f"다음 CSV가 업데이트됐습니다:\n\n"
            f"  • devices.csv  — 장비 타입 · IP 할당\n"
            f"  • vlans.csv    — {vlan_cnt}개 VLAN\n"
            f"  • interfaces.csv — 포트 trunk 설정\n"
            f"  • l3_config.csv  — SVI · 기본 라우팅\n\n"
            f"'전체 장비 TXT 컨피그 생성' 버튼으로 CLI 설정을 뽑을 수 있습니다.",
            parent=self,
        )

    def _import_from_image(self):
        import threading
        import subprocess
        import queue as _queue
        from tkinter import filedialog

        img_path = filedialog.askopenfilename(
            title="GNS3 스크린샷 선택",
            filetypes=[("이미지 파일", "*.png *.jpg *.jpeg *.bmp"), ("모든 파일", "*.*")],
            parent=self,
        )
        if not img_path:
            return

        venv_py = os.path.join(VS_CODE_DIR, ".venv", "Scripts", "python.exe")
        runner  = os.path.join(BASE_DIR, "topology_pipeline", "runner.py")
        model   = os.path.join(VS_CODE_DIR, "best.pt")

        if not os.path.exists(venv_py):
            messagebox.showerror(
                "환경 없음",
                f"VS_Code/.venv 가 없습니다.\n{venv_py}\n\n"
                "VS_Code/setup_venv.ps1 을 먼저 실행하세요.",
                parent=self,
            )
            return
        if not os.path.exists(model):
            messagebox.showerror(
                "모델 없음",
                f"YOLO 모델 파일이 없습니다.\n{model}",
                parent=self,
            )
            return

        # --- 진행 상황 창 ---
        prog = tk.Toplevel(self)
        prog.title("이미지 분석 중...")
        prog.geometry("500x300")
        prog.resizable(False, False)
        prog.grab_set()
        prog.configure(bg=self._palette["bg"])

        ttk.Label(prog, text="GNS3 이미지에서 토폴로지를 추출하고 있습니다.",
                  padding=(12, 10)).pack(anchor="w")

        log_text = scrolledtext.ScrolledText(
            prog, height=10,
            font=(pick_gothic_font_family(), 9),
            state="disabled", wrap="word",
        )
        log_text.pack(fill="both", expand=True, padx=12, pady=4)

        pbar = ttk.Progressbar(prog, mode="indeterminate")
        pbar.pack(fill="x", padx=12, pady=(0, 8))
        pbar.start(12)

        def _append_log(msg: str):
            log_text.configure(state="normal")
            log_text.insert("end", msg + "\n")
            log_text.see("end")
            log_text.configure(state="disabled")

        result_holder: dict = {}
        q: _queue.Queue = _queue.Queue()

        def _run_proc():
            try:
                env = dict(os.environ)
                env["PYTHONIOENCODING"] = "utf-8"
                env["PYTHONUNBUFFERED"] = "1"
                proc = subprocess.Popen(
                    [venv_py, runner, img_path, self.dataset_dir, model],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                )
                for raw in proc.stdout:
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    if line.startswith("LOG:"):
                        q.put(("log", line[4:]))
                    elif line.startswith("RESULT:"):
                        import json
                        q.put(("result", json.loads(line[7:])))
                    elif line.startswith("ERROR:"):
                        q.put(("error", line[6:]))
                proc.wait()
                if proc.returncode != 0 and "result" not in {t for t, _ in list(q.queue)}:
                    stderr_raw = proc.stderr.read()
                    stderr_out = stderr_raw.decode("utf-8", errors="replace")
                    q.put(("error", f"종료 코드 {proc.returncode}\n{stderr_out[:500]}"))
            except Exception as exc:
                q.put(("error", str(exc)))
            finally:
                q.put(("done", None))

        def _poll():
            try:
                while True:
                    tag, val = q.get_nowait()
                    if tag == "log":
                        _append_log(val)
                    elif tag == "result":
                        result_holder["ok"] = val
                    elif tag == "error":
                        result_holder.setdefault("err", val)
                    elif tag == "done":
                        pbar.stop()
                        prog.destroy()
                        return
            except _queue.Empty:
                pass
            prog.after(100, _poll)

        threading.Thread(target=_run_proc, daemon=True).start()
        prog.after(100, _poll)
        self.wait_window(prog)

        if "err" in result_holder:
            messagebox.showerror("분석 실패", result_holder["err"], parent=self)
            return

        if "ok" not in result_holder:
            return

        res = result_holder["ok"]

        for key in ("devices", "links"):
            if key in self.tab_frames:
                self.tab_frames[key]._load_csv()
                self.tab_frames[key]._refresh_table()

        messagebox.showinfo(
            "가져오기 완료",
            f"토폴로지 감지 완료!\n\n"
            f"  장비: {res.get('nodes', 0)}개\n"
            f"  연결: {res.get('links', 0)}개\n\n"
            f"devices.csv 와 links.csv 가 업데이트됐습니다.\n"
            f"나머지 CSV(vlans, interfaces 등)는 직접 입력해 주세요.",
            parent=self,
        )

    def _switch_project(self):
        self.withdraw()
        dialog = ProjectDialog(self, self._palette, self._fonts)
        self.wait_window(dialog)

        if dialog.result:
            self.destroy()
            app = NetConfigApp(dialog.result)
            app.mainloop()
        else:
            self.deiconify()


# -----------------------------
# 진입점
# -----------------------------
def main():
    os.makedirs(PROJECTS_DIR, exist_ok=True)

    root = tk.Tk()
    root.withdraw()

    palette = build_theme_palette()
    font_family = pick_gothic_font_family()
    base_font, title_font, heading_font = apply_theme_and_fonts(root, palette, font_family)
    fonts = {"base": base_font, "title": title_font, "heading": heading_font}

    dialog = ProjectDialog(root, palette, fonts)
    root.wait_window(dialog)
    root.destroy()

    if dialog.result is None:
        return

    app = NetConfigApp(dialog.result)
    app.mainloop()


if __name__ == "__main__":
    main()