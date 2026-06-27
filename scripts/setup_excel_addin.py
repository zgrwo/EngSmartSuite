"""Setup SmartExcel custom ribbon in Excel -- injects ribbon XML and VBA callbacks.

Usage:
    python scripts/setup_excel_addin.py

Creates smartexcel_addin/SmartExcel_Addin.xlam with custom ribbon tab "工艺分析".
"""
import os, sys, shutil, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDIN_DIR = os.path.join(ROOT, 'smartexcel_addin')
XLAM_NAME = 'SmartExcel_Addin.xlam'

RIBBON_XML = r"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<customUI xmlns="http://schemas.microsoft.com/office/2006/01/customui">
  <ribbon>
    <tabs>
      <tab id="smartexcel_tab" label="工艺分析">
        <group id="root_cause_group" label="要因分析">
          <button id="btn_correlation" label="相关性分析" onAction="ribbon_correlation"
                  imageMso="TableAnalyze" size="large"
                  screentip="找出与目标变量最相关的工艺参数" />
          <button id="btn_anova" label="ANOVA方差分析" onAction="ribbon_anova"
                  imageMso="ShowReportFilterPage" size="large"
                  screentip="判断因子对质量指标是否有显著影响" />
          <button id="btn_hypothesis" label="假设检验" onAction="ribbon_hypothesis"
                  imageMso="CreateQueryFromWizard" size="large"
                  screentip="对比两组工艺是否有真实差异" />
        </group>
        <group id="doe_group" label="DOE/优化">
          <button id="btn_regression" label="回归建模" onAction="ribbon_regression"
                  imageMso="ChartTrendline" size="large"
                  screentip="建立Y=f(X)预测模型" />
          <button id="btn_rsm" label="响应面分析" onAction="ribbon_rsm"
                  imageMso="Chart3DSurfaceChart" size="large"
                  screentip="3D可视化最优参数区域" />
          <button id="btn_optimize" label="最优搜索" onAction="ribbon_grid"
                  imageMso="TargetInv" size="large"
                  screentip="自动搜索最优工艺参数组合" />
        </group>
        <group id="spc_group" label="过程监控">
          <button id="btn_spc" label="SPC控制图" onAction="ribbon_spc"
                  imageMso="ChartLine" size="large"
                  screentip="X-bar/R控制图，判断过程是否受控" />
          <button id="btn_capability" label="过程能力" onAction="ribbon_capability"
                  imageMso="PivotChart" size="large"
                  screentip="计算Cp/Cpk，评估过程满足规格的能力" />
        </group>
        <group id="report_group" label="报告">
          <button id="btn_excel_report" label="Excel报告" onAction="ribbon_excel_report"
                  imageMso="FileSave" size="large" />
          <button id="btn_ppt_report" label="PPT报告" onAction="ribbon_ppt_report"
                  imageMso="FilePublishAsPptx" size="large" />
        </group>
      </tab>
    </tabs>
  </ribbon>
</customUI>
"""

VBA_CODE = r'''Attribute VB_Name = "SmartExcelRibbon"

Public Sub ribbon_correlation(control As IRibbonControl)
    RunPython ("import smartexcel_addin; smartexcel_addin.run_correlation()")
End Sub

Public Sub ribbon_anova(control As IRibbonControl)
    RunPython ("import smartexcel_addin; smartexcel_addin.run_anova()")
End Sub

Public Sub ribbon_hypothesis(control As IRibbonControl)
    RunPython ("import smartexcel_addin; smartexcel_addin.run_hypothesis_test()")
End Sub

Public Sub ribbon_regression(control As IRibbonControl)
    RunPython ("import smartexcel_addin; smartexcel_addin.run_regression()")
End Sub

Public Sub ribbon_rsm(control As IRibbonControl)
    RunPython ("import smartexcel_addin; smartexcel_addin.run_response_surface()")
End Sub

Public Sub ribbon_grid(control As IRibbonControl)
    RunPython ("import smartexcel_addin; smartexcel_addin.run_grid_search()")
End Sub

Public Sub ribbon_spc(control As IRibbonControl)
    RunPython ("import smartexcel_addin; smartexcel_addin.run_spc()")
End Sub

Public Sub ribbon_capability(control As IRibbonControl)
    RunPython ("import smartexcel_addin; smartexcel_addin.run_process_capability()")
End Sub

Public Sub ribbon_excel_report(control As IRibbonControl)
    RunPython ("import smartexcel_addin; smartexcel_addin.run_report_excel()")
End Sub

Public Sub ribbon_ppt_report(control As IRibbonControl)
    RunPython ("import smartexcel_addin; smartexcel_addin.run_report_ppt()")
End Sub
'''


def inject_customui(xlam_path):
    """Inject customUI ribbon XML into .xlam file ZIP structure."""
    tmp = xlam_path + '.tmp'
    with zipfile.ZipFile(xlam_path, 'r') as zin:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                zout.writestr(item, zin.read(item.filename))
            zout.writestr('customUI/customUI.xml', RIBBON_XML)
            ct = zin.read('[Content_Types].xml').decode('utf-8')
            if 'customUI' not in ct:
                ct = ct.replace('</Types>',
                    '<Override PartName="/customUI/customUI.xml" '
                    'ContentType="application/xml"/></Types>')
                zout.writestr('[Content_Types].xml', ct.encode('utf-8'))
            rels = zin.read('_rels/.rels').decode('utf-8')
            if 'customUI' not in rels:
                rels = rels.replace('</Relationships>',
                    '<Relationship Id="customUIRel" '
                    'Type="http://schemas.microsoft.com/office/2006/relationships/ui/extensibility" '
                    'Target="/customUI/customUI.xml"/></Relationships>')
                zout.writestr('_rels/.rels', rels.encode('utf-8'))
    os.replace(tmp, xlam_path)
    return xlam_path


def main():
    print("=" * 60)
    print("SmartExcel Suite -- Excel Add-in Setup")
    print("=" * 60)

    source = os.path.join(ADDIN_DIR, 'smartexcel_addin.xlsm')
    if not os.path.exists(source):
        print(f"ERROR: {source} not found.")
        print("Run: xlwings quickstart smartexcel_addin")
        sys.exit(1)

    xlam = os.path.join(ADDIN_DIR, XLAM_NAME)
    shutil.copy(source, xlam)
    print(f"Created: {xlam}")

    try:
        inject_customui(xlam)
        print("Custom ribbon '工艺分析' injected into .xlam")
    except Exception as e:
        print(f"WARNING: Ribbon injection failed: {e}")
        ribbon_file = os.path.join(ADDIN_DIR, 'ribbon.xml')
        with open(ribbon_file, 'w', encoding='utf-8') as f:
            f.write(RIBBON_XML)
        print(f"Ribbon XML saved to: {ribbon_file}")

    vba_file = os.path.join(ADDIN_DIR, 'SmartExcelRibbon.bas')
    with open(vba_file, 'w', encoding='utf-8') as f:
        f.write(VBA_CODE)
    print(f"VBA module saved to: {vba_file}")

    print()
    print("=" * 60)
    print("SETUP COMPLETE -- Next Steps:")
    print("=" * 60)
    print(f"""
  1. Open Excel, go to VBA editor (Alt+F11)
  2. File > Import File > select: {vba_file}
  3. Save {XLAM_NAME} (Ctrl+S, keep as .xlam format)
  4. File > Options > Add-ins > Go... > Browse > select {XLAM_NAME}
  5. Restart Excel -- you should see '工艺分析' tab in the ribbon!

  OR (simpler, no add-in install needed):
  Open {source} directly -- it works as a macro-enabled workbook.
  (The ribbon won't appear, but you can still call functions from VBA)
""")


if __name__ == '__main__':
    main()
