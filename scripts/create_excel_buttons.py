"""Create Excel workbook with embedded SmartSuite analysis buttons.

Usage: python scripts/create_excel_buttons.py
Output: tests/SmartSuite_Analyzer.xlsm

This creates a macro-enabled workbook with Form Control buttons directly
on a worksheet. No ribbon XML, no Custom UI Editor needed.
Just open the file, enable macros, and click.
"""
import os
import xlwings as xw
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(ROOT, 'tests', 'SmartSuite_Analyzer.xlsm')

np.random.seed(42)

# Create workbook
wb = xw.Book()
wb.save(OUTPUT)

# Sheet 1: Analysis Panel with buttons
sheet = wb.sheets[0]
sheet.name = "SmartSuite"

# Header
sheet.range("A1").value = "SmartSuite 工艺分析工具箱"
sheet.range("A1").font.size = 18
sheet.range("A1").font.bold = True
sheet.range("A1:B1").color = (30, 60, 120)
sheet.range("A1:B1").font.color = (255, 255, 255)

sheet.range("A2").value = "使用: 在下方设置参数, 选中数据区域, 然后点击分析按钮。结果写入新工作表。"
sheet.range("A2").font.size = 10

# Input area
row = 4
sheet.range(f"A{row}").value = "目标列名 (Y) :"
sheet.range(f"B{row}").value = "不良率"
sheet.range(f"B{row}").color = (255, 255, 200)
row += 1
sheet.range(f"A{row}").value = "因子列名 (X) :"
sheet.range(f"B{row}").value = "熔体温度, 模具温度, 注射压力, 保压时间"
sheet.range(f"B{row}").color = (255, 255, 200)
row += 1
sheet.range(f"A{row}").value = "数据范围 :"
sheet.range(f"B{row}").value = "A1:F31 (或点击'示例数据'工作表)"
sheet.range(f"B{row}").color = (255, 255, 200)

# Button panel
row = 9
sheet.range(f"A{row}").value = "=== 要因分析 ==="
sheet.range(f"A{row}").font.bold = True
row += 1

button_config = [
    # (label, name, col_offset, section)
    ("相关性分析", "btn_corr", 0, "要因分析"),
    ("ANOVA方差分析", "btn_anova", 1, "要因分析"),
    ("假设检验", "btn_ttest", 2, "要因分析"),
    ("决策树归因", "btn_tree", 3, "要因分析"),
]

for label, name, col, section in button_config:
    x_pos = 10 + col * 160
    y_pos = row * 16
    btn = sheet.shapes.api.AddFormControl(0, x_pos, y_pos, 145, 28)
    btn.Text = label
    btn.Name = name

row += 3
sheet.range(f"A{row}").value = "=== DOE / 优化 ==="
sheet.range(f"A{row}").font.bold = True
row += 1

doe_buttons = [
    ("回归建模", "btn_reg", 0),
    ("响应面分析", "btn_rsm", 1),
    ("最优搜索", "btn_grid", 2),
    ("多目标优化", "btn_multi", 3),
]
for label, name, col in doe_buttons:
    x_pos = 10 + col * 160
    y_pos = row * 16
    btn = sheet.shapes.api.AddFormControl(0, x_pos, y_pos, 145, 28)
    btn.Text = label
    btn.Name = name

row += 3
sheet.range(f"A{row}").value = "=== 过程监控 ==="
sheet.range(f"A{row}").font.bold = True
row += 1

spc_buttons = [
    ("SPC控制图", "btn_spc", 0),
    ("过程能力Cp/Cpk", "btn_cpk", 1),
    ("趋势预测", "btn_trend", 2),
    ("异常检测", "btn_anom", 3),
]
for label, name, col in spc_buttons:
    x_pos = 10 + col * 160
    y_pos = row * 16
    btn = sheet.shapes.api.AddFormControl(0, x_pos, y_pos, 145, 28)
    btn.Text = label
    btn.Name = name

# Sheet 2: Sample data
sheet2 = wb.sheets.add("示例数据")
n = 30
data_df = pd.DataFrame({
    '熔体温度': np.round(np.random.uniform(180, 220, n), 1),
    '模具温度': np.round(np.random.uniform(40, 80, n), 1),
    '注射压力': np.round(np.random.uniform(60, 100, n), 1),
    '保压时间': np.round(np.random.uniform(5, 15, n), 1),
    '不良率': np.round(np.random.beta(2, 98, n) * 10, 3),
    '强度': np.round(35 + 0.15*np.random.uniform(180,220,n) + np.random.normal(0,2,n), 2),
})
sheet2.range("A1").value = data_df

# Sheet 3: Full test data
sheet3 = wb.sheets.add("完整测试数据")
test_path = os.path.join(ROOT, 'tests', 'test_data.xlsx')
if os.path.exists(test_path):
    full_df = pd.read_excel(test_path)
    sheet3.range("A1").value = full_df.head(200)
    sheet3.range("A202").value = f"(仅显示前 200 行，共 {len(full_df)} 行。完整数据见 tests/test_data.xlsx)"

wb.sheets[0].activate()
wb.save()
print(f"Created: {OUTPUT}")
print()
print("TO USE:")
print(f"  1. Open {OUTPUT} in Excel")
print("  2. Click 'Enable Content' if macro warning appears")
print("  3. Go to '示例数据' sheet, select the data range (A1:F31)")
print("  4. Go to 'SmartSuite' sheet, set target/feature column names")
print("  5. Click any analysis button")
