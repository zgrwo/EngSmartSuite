"""SmartSuite GUI v2 — redesigned with proper workflow, Y/X/Category selectors.

Three column checkboxes: Y (target), X (feature), Cat (categorical).
Workflow: Step1 Filter -> Step2 Model -> Step3 Optimize + Monitor.
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pandas as pd
import numpy as np
import os, sys, threading, io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from smartexcel.core.contracts import AnalysisRequest
from smartexcel.services.orchestrator import orchestrate, TASK_REGISTRY
from smartexcel.services.reporter import to_ppt

CATEGORICAL_KEYWORDS = ['日期','班次','车间','机台','模具','编号','操作','检验',
    '原料','类型','批号','冷却','循环','模式','分区','保养','环境',
    '产品代码','色母','嵌件','首件','外观','尺寸','需返工','报警','换料',
    'operator','machine','mold','material','batch','shift','workshop',
    'inspector','date','type','code','alarm','mode','check']

STEP1_METHODS = ["correlation", "anova", "hypothesis_test"]
STEP2_METHODS = ["vif", "regression", "decision_tree"]
STEP3_METHODS = ["response_surface", "multi_objective", "grid_search", "doe_analysis"]
MONITOR_METHODS = ["spc_xbar", "process_capability", "trend_forecast", "anomaly_detect"]

METHOD_LABELS = {
    "correlation": "相关性分析", "anova": "ANOVA方差分析",
    "hypothesis_test": "假设检验",
    "vif": "VIF共线性诊断", "regression": "回归建模",
    "decision_tree": "决策树建模",
    "response_surface": "响应面分析", "multi_objective": "多目标优化",
    "grid_search": "最优参数搜索", "doe_analysis": "DOE效应估计",
    "spc_xbar": "SPC控制图", "process_capability": "过程能力Cp/Cpk",
    "trend_forecast": "趋势预测", "anomaly_detect": "异常检测",
}

METHOD_HINTS = {
    "correlation": "扫描全部因子与目标的线性相关性，快速了解'谁最重要'",
    "anova": "判断类别因子(如原料类型)对目标是否有显著影响",
    "hypothesis_test": "对比两组数据(如新旧工艺)是否存在真实差异",
    "vif": "诊断因子之间是否存在多重共线性(建模前必做)",
    "regression": "建立 Y=f(X1,X2...) 线性预测方程",
    "decision_tree": "用决策树拟合非线性关系，输出特征重要性排名",
    "response_surface": "生成3D曲面图，可视化两因子交互效应和最优区域",
    "multi_objective": "同时优化多个目标(如强度↑+成本↓)的权衡解",
    "grid_search": "在参数空间内自动搜索使目标最优的参数组合",
    "doe_analysis": "计算试验设计中各因子的主效应大小",
    "spc_xbar": "X-bar/R控制图，判断过程是否统计受控",
    "process_capability": "计算Cp/Cpk，评估过程满足规格限的能力",
    "trend_forecast": "基于历史趋势预测未来N步的走向",
    "anomaly_detect": "用IQR/Z-score方法识别数据中的离群异常点",
}


class ColumnRow(ttk.Frame):
    """One row: col_name | [类] [X] [Y] — grid with fixed column widths."""
    COL_NAME = 0; COL_CAT = 1; COL_X = 2; COL_Y = 3

    def __init__(self, parent, name, on_change, is_header=False):
        super().__init__(parent)
        self.name = name

        for c, w in [(self.COL_NAME, 150), (self.COL_CAT, 44), (self.COL_X, 36), (self.COL_Y, 36)]:
            self.grid_columnconfigure(c, minsize=w)

        if is_header:
            ttk.Label(self, text="列名", font=("Microsoft YaHei", 8, "bold")).grid(
                row=0, column=self.COL_NAME, sticky=tk.W)
            ttk.Label(self, text="类", font=("Microsoft YaHei", 8, "bold"), width=2).grid(
                row=0, column=self.COL_CAT, padx=1, sticky="")
            ttk.Label(self, text="X", font=("Microsoft YaHei", 8, "bold"), width=2).grid(
                row=0, column=self.COL_X, padx=1, sticky="")
            ttk.Label(self, text="Y", font=("Microsoft YaHei", 8, "bold"), width=2).grid(
                row=0, column=self.COL_Y, padx=1, sticky="")
        else:
            self.var_y = tk.BooleanVar(); self.var_x = tk.BooleanVar(); self.var_cat = tk.BooleanVar()
            ttk.Label(self, text=name, anchor=tk.W).grid(
                row=0, column=self.COL_NAME, sticky=tk.W)
            ttk.Checkbutton(self, variable=self.var_cat,
                command=lambda n=name: on_change(n, 'cat', self.var_cat.get())).grid(
                row=0, column=self.COL_CAT, padx=1)
            ttk.Checkbutton(self, variable=self.var_x,
                command=lambda n=name: on_change(n, 'X', self.var_x.get())).grid(
                row=0, column=self.COL_X, padx=1)
            ttk.Checkbutton(self, variable=self.var_y,
                command=lambda n=name: on_change(n, 'Y', self.var_y.get())).grid(
                row=0, column=self.COL_Y, padx=1)


class SmartSuiteGUI:
    def __init__(self, initial_file=None):
        self.root = tk.Tk()
        self.root.title("SmartSuite — 工艺数据分析工具箱")
        self.root.geometry("1200x800")
        self.df = None
        self._df_encoded = None
        self.last_result = None
        self._file_path = None
        self._col_rows = {}
        self._targets = set()
        self._features = set()
        self._categoricals = set()
        self._build_ui()
        if initial_file:
            self._load_file(os.path.abspath(initial_file))

    # ============================================================
    # UI CONSTRUCTION
    # ============================================================
    def _build_ui(self):
        # Title
        tk.Label(self.root, text="SmartSuite 工艺数据分析工具箱",
                 font=("Microsoft YaHei", 16, "bold")).pack(pady=4)

        # ---- Top bar ----
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=10, pady=2)
        ttk.Button(top, text="打开 Excel 文件", command=self._open_file).pack(side=tk.LEFT)
        self.file_lbl = ttk.Label(top, text="未选择文件", foreground="gray")
        self.file_lbl.pack(side=tk.LEFT, padx=8)
        ttk.Label(top, text="Sheet:").pack(side=tk.LEFT, padx=(10,0))
        self.sheet_cb = ttk.Combobox(top, width=14, state="disabled")
        self.sheet_cb.pack(side=tk.LEFT, padx=2)
        self.sheet_cb.bind("<<ComboboxSelected>>", lambda e: self._load_sheet())
        self._status_lbl = tk.StringVar(value="就绪")
        ttk.Label(top, textvariable=self._status_lbl, foreground="blue").pack(
            side=tk.RIGHT, padx=10)

        # ---- Main area: Left(cols) + Center(workflow) + Right(chart) ----
        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # LEFT: Column selector
        col_frm = ttk.LabelFrame(main, text="列定义", padding=4)
        col_frm.pack(side=tk.LEFT, fill=tk.BOTH)

        # ---- Toolbar (top of column panel) ----
        qf = ttk.Frame(col_frm); qf.pack(fill=tk.X, pady=(0,4))
        ttk.Button(qf, text="智能识别", command=self._auto_detect, width=9).pack(side=tk.LEFT, padx=1)
        ttk.Button(qf, text="全选数值X", command=lambda: self._set_all('X', 'numeric'), width=8).pack(side=tk.LEFT, padx=1)
        ttk.Button(qf, text="全选响应Y", command=lambda: self._set_all('Y', 'response'), width=8).pack(side=tk.LEFT, padx=1)
        ttk.Button(qf, text="清空全部", command=self._clear_all, width=7).pack(side=tk.LEFT, padx=1)

        # ---- Scrollable table with header and rows together ----
        canvas = tk.Canvas(col_frm, width=270, height=300, highlightthickness=0)
        scrollbar = ttk.Scrollbar(col_frm, orient=tk.VERTICAL, command=canvas.yview)
        self._col_container = ttk.Frame(canvas)
        self._col_container.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._col_container, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(-1 * (event.delta // 120), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # CENTER: Workflow + Bottom results
        center = ttk.Frame(main)
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8,0))

        # Workflow steps
        wf = ttk.LabelFrame(center, text="分析流程", padding=4)
        wf.pack(fill=tk.X)

        steps = [
            ("Step 1  要因筛选", STEP1_METHODS, "#e8f5e9"),
            ("Step 2  建模诊断", STEP2_METHODS, "#e3f2fd"),
            ("Step 3  寻优预测", STEP3_METHODS, "#fff3e0"),
            ("过程监控", MONITOR_METHODS, "#fce4ec"),
        ]

        self._hint_lbl = tk.StringVar(value="选择分析方法查看说明")
        for title, methods, color in steps:
            sf = tk.Frame(wf, bg=color, highlightbackground="#ccc",
                          highlightthickness=1, bd=0)
            sf.pack(fill=tk.X, pady=1)
            tk.Label(sf, text=title, font=("Microsoft YaHei", 9, "bold"),
                     bg=color).pack(side=tk.LEFT, padx=4)
            for m in methods:
                btn = tk.Button(sf, text=METHOD_LABELS[m], font=("Microsoft YaHei", 9),
                                bg="white", relief=tk.RAISED, width=12,
                                command=lambda m=m: self._run(m))
                btn.pack(side=tk.LEFT, padx=1, pady=2)
                btn.bind("<Enter>", lambda e, m=m: self._hint_lbl.set(
                    f"{METHOD_LABELS[m]}: {METHOD_HINTS[m]}"))
                btn.bind("<Leave>", lambda e: self._hint_lbl.set(""))

        tk.Label(center, textvariable=self._hint_lbl, font=("Microsoft YaHei", 8),
                 fg="#666").pack(fill=tk.X, padx=4)

        # ---- Results area (tabbed) ----
        res_frm = ttk.LabelFrame(center, text="分析结果", padding=4)
        res_frm.pack(fill=tk.BOTH, expand=True, pady=(4,0))

        self._result_nb = ttk.Notebook(res_frm)
        self._result_nb.pack(fill=tk.BOTH, expand=True)

        # Tab 1: Summary
        sum_frm = ttk.Frame(self._result_nb)
        self._result_nb.add(sum_frm, text="结论")
        self._summary_text = tk.Text(sum_frm, font=("Microsoft YaHei", 11), wrap=tk.WORD,
                                      height=6, bg="#f0f8e8", relief=tk.FLAT, padx=10, pady=8)
        self._summary_text.pack(fill=tk.BOTH, expand=True)

        # Tab 2: Tables
        tbl_frm = ttk.Frame(self._result_nb)
        self._result_nb.add(tbl_frm, text="表格")
        self._table_tree = ttk.Treeview(tbl_frm, show="headings", height=10)
        tbl_scroll_y = ttk.Scrollbar(tbl_frm, orient=tk.VERTICAL, command=self._table_tree.yview)
        tbl_scroll_x = ttk.Scrollbar(tbl_frm, orient=tk.HORIZONTAL, command=self._table_tree.xview)
        self._table_tree.configure(yscrollcommand=tbl_scroll_y.set, xscrollcommand=tbl_scroll_x.set)
        self._table_tree.grid(row=0, column=0, sticky="nsew")
        tbl_scroll_y.grid(row=0, column=1, sticky="ns")
        tbl_scroll_x.grid(row=1, column=0, sticky="ew")
        tbl_frm.grid_rowconfigure(0, weight=1)
        tbl_frm.grid_columnconfigure(0, weight=1)

        # Tab 3: Log
        log_frm = ttk.Frame(self._result_nb)
        self._result_nb.add(log_frm, text="日志")
        self.out = tk.Text(log_frm, font=("Consolas", 9), wrap=tk.WORD,
                           bg="#1a1a2e", fg="#cdd6f4")
        log_scroll = ttk.Scrollbar(log_frm, command=self.out.yview)
        self.out.configure(yscrollcommand=log_scroll.set)
        self.out.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Export buttons (below results)
        exp = ttk.Frame(center)
        exp.pack(fill=tk.X, pady=(2,0))
        self.ppt_btn = ttk.Button(exp, text="导出 PPT 报告", command=self._export_ppt, state="disabled")
        self.ppt_btn.pack(side=tk.RIGHT, padx=2)
        self.xls_btn = ttk.Button(exp, text="导出 Excel 报告", command=self._export_xls, state="disabled")
        self.xls_btn.pack(side=tk.RIGHT, padx=2)

    # ============================================================
    # COLUMN SELECTION
    # ============================================================
    def _on_col_change(self, name, role, checked):
        if role == 'Y':
            (self._targets.add(name) if checked else self._targets.discard(name))
        elif role == 'X':
            (self._features.add(name) if checked else self._features.discard(name))
        elif role == 'cat':
            (self._categoricals.add(name) if checked else self._categoricals.discard(name))
        self._update_status()

    def _update_status(self):
        self._status_lbl.set(
            f"Y={len(self._targets)}列 X={len(self._features)}列 类别={len(self._categoricals)}列")

    def _auto_detect(self):
        for name, row in self._col_rows.items():
            lo = name.lower()
            dtype = str(self.df[name].dtype) if self.df is not None else ""
            # Category detection
            is_cat = any(kw.lower() in lo for kw in CATEGORICAL_KEYWORDS)
            if is_cat or dtype == 'object':
                row.var_cat.set(True); self._categoricals.add(name)
            # Y detection: keywords that suggest a response/quality metric
            y_kw = ['不良','强度','伸长','冲击','粗糙','偏差','波动','效率',
                    'defect','strength','rough','deviation']
            if any(k in lo for k in y_kw):
                row.var_y.set(True); self._targets.add(name)
            # X detection: numeric columns that aren't Y or Category
            if dtype in ('float64','int64') and name not in self._targets and not is_cat:
                row.var_x.set(True); self._features.add(name)
        self._update_status()
        self._log("智能识别完成: Y=响应指标, X=数值工艺参数, 类别=文本/分类变量")

    def _set_all(self, role, filter_type):
        for name, row in self._col_rows.items():
            dtype = str(self.df[name].dtype) if self.df is not None else ""
            if filter_type == 'numeric' and dtype in ('float64','int64'):
                if role == 'X' and name not in self._targets:
                    row.var_x.set(True); self._features.add(name)
            elif filter_type == 'response' and dtype in ('float64','int64'):
                row.var_y.set(True); self._targets.add(name)
        self._update_status()

    def _clear_all(self):
        for name, row in self._col_rows.items():
            row.var_y.set(False); row.var_x.set(False); row.var_cat.set(False)
        self._targets.clear(); self._features.clear(); self._categoricals.clear()
        self._update_status()

    # ============================================================
    # FILE LOADING
    # ============================================================
    def _open_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("Excel files", "*.xlsx *.xls *.xlsm"), ("All", "*.*")])
        if path:
            self._load_file(path)

    def _load_file(self, path):
        self._file_path = path
        self.file_lbl.config(text=os.path.basename(path), foreground="black")
        xl = pd.ExcelFile(path)
        self.sheet_cb.config(values=xl.sheet_names, state="readonly")
        self.sheet_cb.current(0)
        self._load_sheet()

    def _load_sheet(self):
        if not self._file_path: return
        sheet = self.sheet_cb.get()
        self.df = pd.read_excel(self._file_path, sheet_name=sheet)

        # Rebuild column UI (header + rows inside scrollable container)
        for w in self._col_container.winfo_children():
            w.destroy()
        self._col_rows.clear()
        self._targets.clear(); self._features.clear(); self._categoricals.clear()

        # Header row (grid-based, inside scrollable container)
        ColumnRow(self._col_container, "__header__", self._on_col_change, is_header=True).pack(fill=tk.X)
        ttk.Separator(self._col_container, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=1)

        for col in self.df.columns:
            row = ColumnRow(self._col_container, col, self._on_col_change, is_header=False)
            row.pack(fill=tk.X, anchor=tk.W)
            self._col_rows[col] = row

        self._auto_detect()
        self._log(f"已加载: {len(self.df)} 行 x {len(self.df.columns)} 列 [{sheet}]")
        self._log(f"  目标列(Y): {sorted(self._targets)}")
        self._log(f"  因子列(X): {sorted(self._features)}")
        self._log(f"  类别列:    {sorted(self._categoricals)}")

    # ============================================================
    # DATA PREP: encode categoricals for analysis
    # ============================================================
    def _prepare_data(self, targets, features):
        """One-hot encode categorical features, return (df_encoded, feature_cols_encoded)."""
        df = self.df.copy()
        encoded_cols = []
        cat_map = {}

        for col in features:
            if col in self._categoricals or self.df[col].dtype == 'object':
                dummies = pd.get_dummies(df[col], prefix=col, drop_first=True)
                for dc in dummies.columns:
                    df[dc] = dummies[dc].astype(float)
                    encoded_cols.append(dc)
                cat_map[col] = list(dummies.columns)
            else:
                # Numeric: ensure numeric, fill NaN with median
                df[col] = pd.to_numeric(df[col], errors='coerce')
                if df[col].isnull().any():
                    df[col] = df[col].fillna(df[col].median())
                encoded_cols.append(col)

        self._df_encoded = df
        self._cat_map = cat_map
        return df, encoded_cols

    # ============================================================
    # RUN ANALYSIS
    # ============================================================
    def _run(self, task):
        if self.df is None:
            messagebox.showwarning("请先加载数据", "请先选择 Excel 文件并加载")
            return

        targets = sorted(self._targets)
        features = sorted(self._features)

        if not targets:
            messagebox.showwarning("请选择目标列", "请勾选至少一个 Y 列(响应)")
            return
        if not features:
            messagebox.showwarning("请选择因子列", "请勾选至少一个 X 列(因子)")
            return

        # Prepare data with encoding
        df_enc, feature_cols = self._prepare_data(targets, features)
        cat_count = len(self._categoricals & set(features))
        self._log(f"\n{'='*60}")
        self._log(f"  {METHOD_LABELS[task]}")
        self._log(f"  目标(Y): {targets}")
        self._log(f"  因子(X): {feature_cols}")
        if cat_count > 0:
            self._log(f"  (已对 {cat_count} 个类别变量做 One-Hot 编码)")
        self._log(f"{'='*60}")

        self._status_lbl.set(f"运行中: {METHOD_LABELS[task]}...")

        def run_all():
            for target in targets:
                self.root.after(0, lambda t=target: self._log(f"\n--- Y = {t} ---"))
                req = AnalysisRequest(task=task, data=df_enc, target_col=target,
                                      feature_cols=feature_cols)
                result = orchestrate(req)
                self.root.after(0, lambda r=result: self._show(r))
            self.root.after(0, self._done)

        threading.Thread(target=run_all, daemon=True).start()

    def _show(self, result):
        self.last_result = result
        status_icon = "OK" if result.status == 'ok' else ("WARN" if result.status == 'warning' else "ERR")
        self._log(f"[{status_icon}] {result.summary}")
        for msg in result.messages:
            self._log(f"  {msg}")

        # Summary tab
        self._summary_text.configure(state=tk.NORMAL)
        self._summary_text.delete("1.0", tk.END)
        color = "#2e7d32" if result.status == 'ok' else ("#e65100" if result.status == 'warning' else "#c62828")
        self._summary_text.insert(tk.END, f"  {result.summary}\n\n", ("big",))
        self._summary_text.tag_configure("big", font=("Microsoft YaHei", 13, "bold"), foreground=color)
        if result.metadata:
            meta_lines = "\n".join(f"  {k}: {v}" for k, v in list(result.metadata.items())[:8])
            self._summary_text.insert(tk.END, meta_lines, ("meta",))
            self._summary_text.tag_configure("meta", font=("Consolas", 10), foreground="#555")
        self._summary_text.configure(state=tk.DISABLED)

        # Table tab — show the first result table in Treeview
        self._table_tree.delete(*self._table_tree.get_children())
        if result.tables:
            first_name = list(result.tables.keys())[0]
            tbl = result.tables[first_name]
            # Include index as first column
            idx_name = str(tbl.index.name or "")
            display_cols = [idx_name] + list(tbl.columns)
            self._table_tree["columns"] = display_cols
            self._table_tree.heading("#0", text="")
            self._table_tree.column("#0", width=0, stretch=False)
            for i, c in enumerate(display_cols):
                self._table_tree.heading(f"#{i+1}", text=str(c))
                self._table_tree.column(f"#{i+1}", width=84, anchor=tk.CENTER)
            for idx_val, row in tbl.head(50).iterrows():
                vals = []
                for v in [idx_val] + list(row):
                    if isinstance(v, float):
                        vals.append(f"{v:6.4f}")   # 6-char right-aligned numbers
                    else:
                        vals.append(str(v))
                self._table_tree.insert("", tk.END, values=vals)
            self._result_nb.select(1)  # Show table tab
            self._log(f"\n[{first_name}] - {len(tbl)} rows, shown in '表格' tab")

        self._result_nb.select(0)  # Back to summary tab

    def _done(self):
        self._status_lbl.set("分析完成")
        self.ppt_btn.config(state="normal")
        self.xls_btn.config(state="normal")

    # ============================================================
    # EXPORT
    # ============================================================
    def _export_ppt(self):
        if self.last_result is None: return
        path = filedialog.asksaveasfilename(defaultextension=".pptx",
                                             filetypes=[("PowerPoint", "*.pptx")])
        if path:
            to_ppt(self.last_result, path)
            messagebox.showinfo("完成", f"PPT 报告已保存至:\n{path}")

    def _export_xls(self):
        if self.last_result is None: return
        path = filedialog.asksaveasfilename(defaultextension=".xlsx",
                                             filetypes=[("Excel", "*.xlsx")])
        if path:
            with pd.ExcelWriter(path) as w:
                for name, tbl in self.last_result.tables.items():
                    tbl.to_excel(w, sheet_name=name[:31])
            messagebox.showinfo("完成", f"Excel 报告已保存至:\n{path}")

    # ============================================================
    # LOGGING
    # ============================================================
    def _log(self, msg):
        self.out.insert(tk.END, msg + "\n")
        self.out.see(tk.END)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("file", nargs="?", help="Excel file to open directly")
    args = p.parse_args()
    SmartSuiteGUI(initial_file=args.file).run()
