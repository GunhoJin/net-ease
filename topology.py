# -*- coding: utf-8 -*-
"""
GNS3 스타일 아이콘 + 계층형 레이아웃 네트워크 구성도 뷰어
==========================================================
장비 role / device_type 을 기반으로 계층(tier)을 자동 판별하여
정형화된 배치(Perimeter → Core → Distribution → Access/Services)로 그린다.

다중 사이트(건물) 지원:
  - Distribution · Access 계층에 장비가 2개 이상의 site로 분포할 경우
    site별로 수직 컬럼을 나눠 배치하고, 건물 영역 박스를 그린다.
"""

import math
import random
import tkinter as tk
from tkinter import ttk
import pandas as pd


# ---- 계층 상수 ----
TIER_NAMES  = {0: "Perimeter", 1: "Core", 2: "Distribution", 3: "Access / Services"}
_BAND_LIGHT = {0: "#fff2f2", 1: "#f2f5ff", 2: "#f2fff6", 3: "#fffef2"}
_BAND_DARK  = {0: "#2d1a1a", 1: "#1a1a2d", 2: "#1a2d1a", 3: "#2d2d1a"}

# 사이트(건물) 박스 색상 팔레트 (최대 6개 사이트)
_SITE_CLR_LIGHT = ["#cce5ff", "#d4edda", "#fff3cd", "#f8d7da", "#d1ecf1", "#e2d9f3"]
_SITE_CLR_DARK  = ["#1a2a3d", "#1a3d2a", "#3d3a1a", "#3d1a1a", "#1a3a3d", "#2a1a3d"]

TIER_LABEL_W = 100   # 좌측 계층 라벨 열 너비
DEVICE_X0    = 116   # 장비 배치 시작 x
PAD_Y_TOP    = 90    # 최상단 장비 y 여백
PAD_Y_BOT    = 80    # 최하단 장비 y 여백
PAD_X_RIGHT  = 70    # 우측 여백
PAD_SPRING   = 100   # spring 레이아웃 가장자리 여백
LABEL_Y      = 36    # 아이콘 중심 → 이름 라벨 y 오프셋
SITE_BOX_PAD = 28    # 사이트 박스 내부 여백


# =================================================================
# 계층 판별
# =================================================================
def _get_tier(info: dict) -> int:
    dtype = str(info.get("device_type", "")).strip()
    role  = str(info.get("role", "")).strip().lower()

    if dtype == "Firewall":
        return 0
    if any(k in dtype.lower() for k in ("l4", "lb", "ltm", "f5")):
        return 3
    if any(k in role for k in ("edge", "perimeter", "border", "firewall")):
        return 0
    if "core" in role:
        return 1
    if any(k in role for k in ("dist", "distribution")):
        return 2
    if any(k in role for k in ("access", "load", "balancer", "lb", "server", "service")):
        return 3
    if dtype == "Router":
        return 0
    if dtype == "L3 Switch":
        return 1
    if dtype == "L2 Switch":
        return 2
    return 2


# =================================================================
# 레이아웃 함수
# =================================================================
def _hierarchical_layout(nodes: list, device_info: dict,
                          width: int, height: int) -> tuple:
    """
    계층형 + 사이트 컬럼 레이아웃.
    반환: (pos, tier_map, tier_y, site_boxes)
      site_boxes: {site_name: {"x0","y0","x1","y1","color_light","color_dark"}}
                   Distribution 이하에 2개 이상의 site가 있을 때만 채워진다.
    """
    # ── 1. 계층별 분류 ──
    tier_map: dict = {}
    for name in nodes:
        t = _get_tier(device_info.get(name, {}))
        tier_map.setdefault(t, []).append(name)

    # ── 2. site → 컬럼 부여 (Distribution 이하) ──
    site_set: set = set()
    for t, names in tier_map.items():
        if t < 2:
            continue
        for n in names:
            s = str(device_info.get(n, {}).get("site", "")).strip()
            if s:
                site_set.add(s)

    sites_sorted = sorted(site_set)          # 알파벳/가나다 정렬
    multi_site   = len(sites_sorted) > 1

    if multi_site:
        # site → x 컬럼 범위
        n_sites  = len(sites_sorted)
        x0_dev   = DEVICE_X0
        x1_dev   = width - PAD_X_RIGHT
        col_w    = (x1_dev - x0_dev) / n_sites
        site_col = {s: x0_dev + col_w * (i + 0.5) for i, s in enumerate(sites_sorted)}
    else:
        site_col = {}

    # ── 3. 계층 y 좌표 ──
    tier_nums = sorted(tier_map.keys())
    n_tiers   = len(tier_nums)
    y_top, y_bot = PAD_Y_TOP, height - PAD_Y_BOT
    tier_y: dict = {}
    for i, t in enumerate(tier_nums):
        if n_tiers == 1:
            tier_y[t] = (y_top + y_bot) / 2
        else:
            tier_y[t] = y_top + (y_bot - y_top) * i / (n_tiers - 1)

    # ── 4. 장비 x 좌표 ──
    # 계층 내 정렬: (site, name)
    for t in tier_map:
        tier_map[t].sort(key=lambda n: (
            str(device_info.get(n, {}).get("site", "")), n))

    pos: dict = {}
    x0_dev = DEVICE_X0
    x1_dev = width - PAD_X_RIGHT

    for t, names in tier_map.items():
        y = tier_y[t]

        if t < 2 or not multi_site:
            # Perimeter·Core 혹은 단일 site: 전체 너비에 균등 배치
            n = len(names)
            for j, name in enumerate(names):
                x = (x0_dev + x1_dev) / 2 if n == 1 \
                    else x0_dev + (x1_dev - x0_dev) * j / (n - 1)
                pos[name] = (x, y)
        else:
            # Distribution 이하: site 컬럼별 배치
            site_groups: dict = {}
            for name in names:
                s = str(device_info.get(name, {}).get("site", "")).strip()
                site_groups.setdefault(s if s in site_col else "__other__", []).append(name)

            for s, group in site_groups.items():
                cx_col = site_col.get(s, (x0_dev + x1_dev) / 2)
                n      = len(group)
                spread = min(col_w * 0.75 if multi_site else x1_dev - x0_dev, 300)
                for j, name in enumerate(group):
                    x = cx_col if n == 1 else cx_col - spread/2 + spread * j / (n-1)
                    pos[name] = (x, y)

    # ── 5. 사이트 박스 계산 (multi-site 한정) ──
    site_boxes: dict = {}
    if multi_site:
        for i, s in enumerate(sites_sorted):
            pts = [pos[n] for t in tier_map for n in tier_map[t]
                   if t >= 2 and
                   str(device_info.get(n, {}).get("site", "")).strip() == s
                   and n in pos]
            if not pts:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            site_boxes[s] = {
                "x0": min(xs) - 58 - SITE_BOX_PAD,
                "y0": min(ys) - 28 - SITE_BOX_PAD,
                "x1": max(xs) + 58 + SITE_BOX_PAD,
                "y1": max(ys) + LABEL_Y + SITE_BOX_PAD,
                "color_light": _SITE_CLR_LIGHT[i % len(_SITE_CLR_LIGHT)],
                "color_dark":  _SITE_CLR_DARK [i % len(_SITE_CLR_DARK)],
            }

    return pos, tier_map, tier_y, site_boxes


def _spring_layout(nodes: list, edges: list, w: int, h: int,
                   iterations: int = 200, seed: int = 0) -> dict:
    """Fruchterman-Reingold spring 레이아웃."""
    if not nodes:
        return {}
    if len(nodes) == 1:
        return {nodes[0]: (w / 2, h / 2)}
    random.seed(seed)
    n = len(nodes)
    cx0, cy0 = w / 2, h / 2
    r0 = min(w-2*PAD_SPRING, h-2*PAD_SPRING) / 2 * 0.8
    pos = {node: (cx0 + r0*math.cos(2*math.pi*i/n) + random.uniform(-8,8),
                  cy0 + r0*math.sin(2*math.pi*i/n) + random.uniform(-8,8))
           for i, node in enumerate(nodes)}
    k = math.sqrt((w-2*PAD_SPRING)*(h-2*PAD_SPRING)/n)
    temp, dt = min(w,h)/6, min(w,h)/6/iterations
    for _ in range(iterations):
        disp = {v: [0.0, 0.0] for v in nodes}
        for i2, v in enumerate(nodes):
            for u in nodes[i2+1:]:
                dx, dy = pos[v][0]-pos[u][0], pos[v][1]-pos[u][1]
                d = max(math.hypot(dx, dy), 0.5)
                f = k*k/d; nx_, ny_ = dx/d, dy/d
                disp[v][0]+=f*nx_; disp[v][1]+=f*ny_
                disp[u][0]-=f*nx_; disp[u][1]-=f*ny_
        for (a, b) in edges:
            if a not in pos or b not in pos: continue
            dx, dy = pos[a][0]-pos[b][0], pos[a][1]-pos[b][1]
            d = max(math.hypot(dx, dy), 0.5)
            f = d*d/k; nx_, ny_ = dx/d, dy/d
            disp[a][0]-=f*nx_; disp[a][1]-=f*ny_
            disp[b][0]+=f*nx_; disp[b][1]+=f*ny_
        for v in nodes:
            dx, dy = disp[v]
            d = max(math.hypot(dx, dy), 0.5); s = min(d, temp)/d
            pos[v] = (max(PAD_SPRING, min(w-PAD_SPRING, pos[v][0]+dx*s)),
                      max(PAD_SPRING, min(h-PAD_SPRING, pos[v][1]+dy*s)))
        temp = max(temp-dt, 0.5)
    return pos


# =================================================================
# GNS3 스타일 아이콘 (canvas item ID 리스트 반환, tags="node")
# =================================================================
def _ring_oval(c, cx, cy, r):
    return c.create_oval(cx-r-5,cy-r-5,cx+r+5,cy+r+5,fill="",outline="#ffcc00",width=3,tags="node")
def _ring_rect(c,x0,y0,x1,y1):
    return c.create_rectangle(x0-5,y0-5,x1+5,y1+5,fill="",outline="#ffcc00",width=3,tags="node")

def icon_router(canvas, cx, cy, sel):
    r=22; ids=[]
    if sel: ids.append(_ring_oval(canvas,cx,cy,r))
    ids.append(canvas.create_oval(cx-r,cy-r,cx+r,cy+r,fill="#3a6fa8",outline="#1e3d6e",width=2,tags="node"))
    ids.append(canvas.create_arc(cx-r+4,cy-r+4,cx+r-4,cy+r-4,start=110,extent=70,outline="#6a9fd8",width=1.5,style="arc",tags="node"))
    inner,outer=r*.40,r*.78
    for ddx,ddy in[(0,-1),(1,0),(0,1),(-1,0)]:
        ids.append(canvas.create_line(cx+ddx*inner,cy+ddy*inner,cx+ddx*outer,cy+ddy*outer,
                                       fill="#ffffff",width=2,arrow="last",arrowshape=(6,8,3),tags="node"))
    return ids

def icon_l2switch(canvas, cx, cy, sel):
    w,h=52,34; x0,y0=cx-w//2,cy-h//2; x1,y1=cx+w//2,cy+h//2; ids=[]
    if sel: ids.append(_ring_rect(canvas,x0,y0,x1,y1))
    ids.append(canvas.create_rectangle(x0,y0,x1,y1,fill="#2e7d4f",outline="#1a5032",width=2,tags="node"))
    n,pw,ph=5,5,4
    for i in range(n):
        px=x0+w*(i+0.75)/(n+0.5)-pw/2
        ids.append(canvas.create_rectangle(px,y0+4,px+pw,y0+4+ph,fill="#90ee90",outline="",tags="node"))
        ids.append(canvas.create_rectangle(px,y1-4-ph,px+pw,y1-4,fill="#90ee90",outline="",tags="node"))
    ids.append(canvas.create_line(x0+6,cy,x1-6,cy,fill="#90ee90",width=1,tags="node"))
    return ids

def icon_l3switch(canvas, cx, cy, sel):
    w,h=52,34; x0,y0=cx-w//2,cy-h//2; x1,y1=cx+w//2,cy+h//2; ids=[]
    if sel: ids.append(_ring_rect(canvas,x0,y0,x1,y1))
    ids.append(canvas.create_rectangle(x0,y0,x1,y1,fill="#1d7a8a",outline="#0e4d5a",width=2,tags="node"))
    n,pw,ph=5,5,4
    for i in range(n):
        px=x0+w*(i+0.75)/(n+0.5)-pw/2
        ids.append(canvas.create_rectangle(px,y0+4,px+pw,y0+4+ph,fill="#80d8e8",outline="",tags="node"))
        ids.append(canvas.create_rectangle(px,y1-4-ph,px+pw,y1-4,fill="#80d8e8",outline="",tags="node"))
    ids.append(canvas.create_line(x0+6,cy,x1-6,cy,fill="#80d8e8",width=1,tags="node"))
    ids.append(canvas.create_line(cx-8,cy+4,cx+8,cy+4,fill="#ffffff",width=1.5,arrow="last",arrowshape=(4,5,2),tags="node"))
    return ids

def icon_firewall(canvas, cx, cy, sel):
    w,h=46,46; x0,y0=cx-w//2,cy-h//2; x1,y1=cx+w//2,cy+h//2; ids=[]
    if sel: ids.append(_ring_rect(canvas,x0,y0,x1,y1))
    ids.append(canvas.create_rectangle(x0,y0,x1,y1,fill="#c0392b",outline="#8e1a10",width=2,tags="node"))
    bh,bw,mo=8,10,2
    for ri,by in enumerate(range(int(y0)+mo,int(y1)-mo,bh+mo)):
        offset=(ri%2)*(bw//2+mo//2)
        for bx in range(int(x0)+mo-offset,int(x1),bw+mo):
            bx0=max(bx,int(x0)+mo); bx1=min(bx+bw,int(x1)-mo)
            if bx1-bx0>2:
                ids.append(canvas.create_rectangle(bx0,by,bx1,min(by+bh,int(y1)-mo),
                                                    fill="#d45a50",outline="#b02a20",width=1,tags="node"))
    return ids

def icon_f5ltm(canvas, cx, cy, sel):
    w,h=52,40; x0,y0=cx-w//2,cy-h//2; x1,y1=cx+w//2,cy+h//2; ids=[]
    if sel: ids.append(_ring_rect(canvas,x0,y0,x1,y1))
    ids.append(canvas.create_rectangle(x0,y0,x1,y1,fill="#7b3fa0",outline="#4e2470",width=2,tags="node"))
    for by in(cy-9,cy,cy+9):
        ids.append(canvas.create_line(x0+8,by,x1-8,by,fill="#d8b0f0",width=3,tags="node"))
    return ids

def icon_generic(canvas, cx, cy, sel):
    w,h=46,36; x0,y0=cx-w//2,cy-h//2; x1,y1=cx+w//2,cy+h//2; ids=[]
    if sel: ids.append(_ring_rect(canvas,x0,y0,x1,y1))
    ids.append(canvas.create_rectangle(x0,y0,x1,y1,fill="#6c757d",outline="#495057",width=2,tags="node"))
    for ddx in(-9,0,9):
        ids.append(canvas.create_oval(cx+ddx-3,cy-3,cx+ddx+3,cy+3,fill="#aaaaaa",outline="",tags="node"))
    return ids

_ICON_FN = {
    "Router":    icon_router,
    "L2 Switch": icon_l2switch,
    "L3 Switch": icon_l3switch,
    "Firewall":  icon_firewall,
    "F5 LTM":   icon_f5ltm,
    "L4 LB":    icon_f5ltm,
}
def _draw_icon(canvas, cx, cy, device_type, sel):
    return _ICON_FN.get(device_type, icon_generic)(canvas, cx, cy, sel)

LEGEND = [
    ("Router","#3a6fa8"),("L2 Switch","#2e7d4f"),("L3 Switch","#1d7a8a"),
    ("Firewall","#c0392b"),("LB / F5","#7b3fa0"),("기타","#6c757d"),
]


# =================================================================
# TopologyFrame
# =================================================================
class TopologyFrame(ttk.Frame):

    def __init__(self, parent, get_dfs_fn, fonts, palette):
        super().__init__(parent)
        self._get_dfs     = get_dfs_fn
        self._fonts       = fonts
        self._palette     = palette

        self._device_names: list = []
        self._device_info:  dict = {}
        self._edges:        list = []
        self._edge_labels:  dict = {}

        self._node_pos:     dict = {}
        self._node_ids:     dict = {}
        self._item_to_node: dict = {}
        self._tier_map:     dict = {}
        self._tier_y:       dict = {}
        self._site_boxes:   dict = {}   # {site: {x0,y0,x1,y1,color_light,color_dark}}

        self._layout_mode = "hierarchical"
        self._drag_node = None
        self._drag_ox = self._drag_oy = 0
        self._selected = None
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        tb = ttk.Frame(self)
        tb.pack(fill="x", padx=8, pady=(6,2))

        self._btn_hier   = ttk.Button(tb, text="▦ 계층형 레이아웃",   command=self._set_hierarchical)
        self._btn_spring = ttk.Button(tb, text="◎ Spring 자동 배치",  command=self._set_spring)
        self._btn_hier.pack(side="left", padx=4)
        self._btn_spring.pack(side="left", padx=4)
        ttk.Separator(tb, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(tb, text="새로고침", command=self.refresh).pack(side="left", padx=4)
        self._stat = ttk.Label(tb, text="장비 탭 데이터 입력 후 새로고침 하세요.")
        self._stat.pack(side="left", padx=10)

        leg = ttk.LabelFrame(tb, text="범례")
        leg.pack(side="right", padx=6)
        for label, color in LEGEND:
            tk.Label(leg, text=f"  {label}  ", bg=color, fg="#ffffff",
                     font=(self._fonts["base"][0], 8), padx=2,
                     ).pack(side="left", padx=2, pady=2)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=8, pady=(0,8))

        detail_pane = ttk.LabelFrame(body, text="장비 상세", width=200)
        detail_pane.pack(side="right", fill="y", padx=(4,0))
        detail_pane.pack_propagate(False)
        self._detail = tk.Text(detail_pane, state="disabled", wrap="word",
                               font=(self._fonts["base"][0], 9),
                               bg=self._palette["field_bg"], fg=self._palette["field_fg"],
                               relief="flat", borderwidth=0)
        self._detail.pack(fill="both", expand=True, padx=6, pady=6)

        cf = ttk.Frame(body)
        cf.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(cf, bg=self._palette["field_bg"],
                                highlightthickness=1,
                                highlightbackground=self._palette["border"])
        ys = ttk.Scrollbar(cf, orient="vertical",   command=self.canvas.yview)
        xs = ttk.Scrollbar(cf, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        cf.rowconfigure(0, weight=1); cf.columnconfigure(0, weight=1)

        self.canvas.bind("<ButtonPress-1>",   self._on_press)
        self.canvas.bind("<B1-Motion>",       self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self._update_btn_state()

    # ------------------------------------------------------------------
    def _set_hierarchical(self):
        self._layout_mode = "hierarchical"
        self._update_btn_state()
        if self._device_names: self._do_layout()

    def _set_spring(self):
        self._layout_mode = "spring"
        self._update_btn_state()
        if self._device_names: self._do_layout(seed=random.randint(0, 99999))

    def _update_btn_state(self):
        if self._layout_mode == "hierarchical":
            self._btn_hier.state(["pressed"]); self._btn_spring.state(["!pressed"])
        else:
            self._btn_hier.state(["!pressed"]); self._btn_spring.state(["pressed"])

    # ------------------------------------------------------------------
    def refresh(self):
        dfs    = self._get_dfs()
        dev_df = dfs.get("devices", pd.DataFrame())
        lnk_df = dfs.get("links",   pd.DataFrame())

        if dev_df.empty or "device_name" not in dev_df.columns:
            self._stat.config(text="장비(devices) 데이터가 없습니다."); return

        self._device_names = dev_df["device_name"].str.strip().tolist()
        self._device_info  = {r["device_name"].strip(): r.to_dict()
                               for _, r in dev_df.iterrows()}
        self._edges = []; self._edge_labels = {}

        if not lnk_df.empty and "device_a" in lnk_df.columns:
            for _, row in lnk_df.iterrows():
                a = str(row.get("device_a","")).strip()
                b = str(row.get("device_b","")).strip()
                if not (a and b): continue
                if a not in self._device_info or b not in self._device_info: continue
                self._edges.append((a, b))
                pa  = str(row.get("port_a","")).strip()
                pb  = str(row.get("port_b","")).strip()
                spd = str(row.get("speed", "")).strip()
                parts = []
                if pa and pb: parts.append(f"{pa}↔{pb}")
                if spd:       parts.append(spd)
                lbl = "\n".join(parts)
                self._edge_labels[(a,b)] = lbl
                self._edge_labels[(b,a)] = lbl

        self._do_layout()

    def _do_layout(self, seed=0):
        self.canvas.update_idletasks()
        w = max(self.canvas.winfo_width(),  700)
        h = max(self.canvas.winfo_height(), 500)

        if self._layout_mode == "hierarchical":
            self._node_pos, self._tier_map, self._tier_y, self._site_boxes = \
                _hierarchical_layout(self._device_names, self._device_info, w, h)
        else:
            self._node_pos  = _spring_layout(self._device_names, self._edges, w, h, seed=seed)
            self._tier_map  = {}
            self._tier_y    = {}
            self._site_boxes = {}

        self._draw(w, h)
        n, e = len(self._device_names), len(self._edges)
        mode = "계층형" if self._layout_mode == "hierarchical" else "Spring"
        self._stat.config(text=f"[{mode}]  장비 {n}대  /  링크 {e}개   (노드 드래그로 위치 조정 가능)")

    # ------------------------------------------------------------------
    def _is_dark(self):
        try: return int(self._palette.get("bg","#f3f3f3")[1:3],16) < 80
        except: return False

    def _draw(self, cw, ch):
        self.canvas.delete("all")
        self._node_ids.clear()
        self._item_to_node.clear()

        # ① 계층 밴드
        if self._tier_map and self._tier_y:
            self._draw_tier_bg(cw, ch)

        # ② 사이트(건물) 박스 — 계층 밴드 위, 엣지 아래
        if self._site_boxes:
            self._draw_site_boxes()

        # ③ 엣지
        for (a, b) in self._edges:
            if a not in self._node_pos or b not in self._node_pos: continue
            x1,y1 = self._node_pos[a]; x2,y2 = self._node_pos[b]
            self.canvas.create_line(x1,y1,x2,y2,fill="#aaaaaa",width=2,tags="edge")
            lbl = self._edge_labels.get((a,b),"")
            if lbl:
                self.canvas.create_text((x1+x2)/2,(y1+y2)/2,text=lbl,
                                         font=(self._fonts["base"][0],7),
                                         fill="#888888",tags="edge")

        # ④ 노드
        for name in self._device_names:
            if name in self._node_pos:
                self._draw_node(name)

        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _draw_tier_bg(self, cw, ch):
        dark      = self._is_dark()
        band_map  = _BAND_DARK if dark else _BAND_LIGHT
        fg        = self._palette["fg"]
        sep_color = self._palette["border"]
        tier_nums = sorted(self._tier_y.keys())
        n         = len(tier_nums)

        def bounds(i):
            t  = tier_nums[i]; cy = self._tier_y[t]
            top = 0 if i==0 else (self._tier_y[tier_nums[i-1]]+cy)/2
            bot = ch if i==n-1 else (cy+self._tier_y[tier_nums[i+1]])/2
            return top, bot

        for i, t in enumerate(tier_nums):
            top, bot = bounds(i)
            self.canvas.create_rectangle(0, top, cw, bot,
                                          fill=band_map.get(t,band_map[2]),
                                          outline="", tags="tier_bg")
            self.canvas.create_text(TIER_LABEL_W//2, (top+bot)/2,
                                     text=TIER_NAMES.get(t,f"Tier {t}"),
                                     font=(self._fonts["base"][0],9,"bold"),
                                     fill=fg, anchor="center", tags="tier_label")
            if i < n-1:
                self.canvas.create_line(0, bot, cw, bot,
                                         fill=sep_color, width=1, dash=(6,3), tags="tier_sep")
        self.canvas.create_line(TIER_LABEL_W+6, 0, TIER_LABEL_W+6, ch,
                                 fill=sep_color, width=1, tags="tier_sep")

    def _draw_site_boxes(self):
        """건물 영역 박스 그리기 (Distribution·Access 계층 장비를 site별로 묶음)."""
        dark = self._is_dark()
        fg   = self._palette["fg"]
        for site, b in self._site_boxes.items():
            color = b["color_dark"] if dark else b["color_light"]
            # 배경
            self.canvas.create_rectangle(
                b["x0"], b["y0"], b["x1"], b["y1"],
                fill=color, outline=self._palette["border"],
                width=1.5, dash=(8, 4), tags="site_box")
            # 건물명 라벨 (박스 상단 중앙)
            cx_mid = (b["x0"] + b["x1"]) / 2
            self.canvas.create_rectangle(
                cx_mid - 36, b["y0"] - 1,
                cx_mid + 36, b["y0"] + 18,
                fill=color, outline=self._palette["border"], width=1,
                tags="site_box")
            self.canvas.create_text(
                cx_mid, b["y0"] + 8,
                text=f"  {site}  ",
                font=(self._fonts["base"][0], 9, "bold"),
                fill=fg, anchor="center", tags="site_box")

    def _draw_node(self, name):
        cx, cy = self._node_pos[name]
        dtype  = str(self._device_info.get(name,{}).get("device_type","")).strip()
        sel    = (name == self._selected)
        icon_ids = _draw_icon(self.canvas, cx, cy, dtype, sel)
        lbl_id   = self.canvas.create_text(
            cx, cy+LABEL_Y, text=name,
            font=(self._fonts["base"][0],9,"bold"),
            fill=self._palette["fg"], tags="node_label")
        all_ids = icon_ids + [lbl_id]
        self._node_ids[name] = all_ids
        for iid in all_ids:
            self._item_to_node[iid] = name

    # ------------------------------------------------------------------
    def _node_at(self, x, y):
        for item in self.canvas.find_overlapping(x-3,y-3,x+3,y+3):
            if item in self._item_to_node: return self._item_to_node[item]
        return None

    def _on_press(self, event):
        x = self.canvas.canvasx(event.x); y = self.canvas.canvasy(event.y)
        node = self._node_at(x, y)
        self._drag_node = node
        if node:
            cx,cy = self._node_pos[node]
            self._drag_ox = cx-x; self._drag_oy = cy-y
            self._select(node)
        else: self._select(None)

    def _on_drag(self, event):
        if not self._drag_node: return
        x = self.canvas.canvasx(event.x); y = self.canvas.canvasy(event.y)
        ncx, ncy = x+self._drag_ox, y+self._drag_oy
        ocx, ocy = self._node_pos[self._drag_node]
        dx, dy   = ncx-ocx, ncy-ocy
        self._node_pos[self._drag_node] = (ncx, ncy)
        for iid in self._node_ids.get(self._drag_node,[]): self.canvas.move(iid,dx,dy)
        self._redraw_edges()

    def _on_release(self, event): self._drag_node = None

    def _redraw_edges(self):
        self.canvas.delete("edge")
        for (a,b) in self._edges:
            if a not in self._node_pos or b not in self._node_pos: continue
            x1,y1=self._node_pos[a]; x2,y2=self._node_pos[b]
            self.canvas.create_line(x1,y1,x2,y2,fill="#aaaaaa",width=2,tags="edge")
            lbl=self._edge_labels.get((a,b),"")
            if lbl:
                self.canvas.create_text((x1+x2)/2,(y1+y2)/2,text=lbl,
                                         font=(self._fonts["base"][0],7),
                                         fill="#888888",tags="edge")
        self.canvas.tag_raise("node"); self.canvas.tag_raise("node_label")

    def _select(self, name):
        prev = self._selected; self._selected = name
        if prev and prev in self._node_ids: self._redraw_node_inplace(prev)
        if name and name in self._node_ids: self._redraw_node_inplace(name)
        self._update_detail(name)

    def _redraw_node_inplace(self, name):
        for iid in self._node_ids.get(name,[]):
            self.canvas.delete(iid); self._item_to_node.pop(iid,None)
        self._node_ids.pop(name,None); self._draw_node(name)

    def _update_detail(self, name):
        self._detail.config(state="normal"); self._detail.delete("1.0","end")
        if name:
            info = self._device_info.get(name,{})
            for label,key in [("장비명","device_name"),("유형","device_type"),
                               ("제조사","vendor"),("모델","model"),
                               ("관리IP","mgmt_ip"),("관리VLAN","mgmt_vlan"),
                               ("사이트","site"),("역할","role"),("설명","description")]:
                val=str(info.get(key,"")).strip()
                if val: self._detail.insert("end",f"{label}:\n  {val}\n\n")
            neighbors=([b for a,b in self._edges if a==name]+
                        [a for a,b in self._edges if b==name])
            if neighbors:
                self._detail.insert("end","─"*20+"\n연결 장비:\n")
                for nb in neighbors: self._detail.insert("end",f"  • {nb}\n")
        self._detail.config(state="disabled")
