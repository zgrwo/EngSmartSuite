RIBBON_XML = """
<customUI xmlns="http://schemas.microsoft.com/office/2006/01/customui">
  <ribbon>
    <tabs>
      <tab id="smartsuite_tab" label="工艺分析">
        <group id="root_cause_group" label="要因分析">
          <button id="btn_correlation" label="相关性分析"
                  onAction="run_correlation" imageMso="TableAnalyze" size="large" />
          <button id="btn_anova" label="ANOVA方差分析"
                  onAction="run_anova" imageMso="ShowReportFilterPage" size="large" />
          <button id="btn_hypothesis" label="假设检验"
                  onAction="run_hypothesis_test" imageMso="CreateQueryFromWizard" size="large" />
        </group>
        <group id="doe_group" label="DOE/优化">
          <button id="btn_regression" label="回归建模"
                  onAction="run_regression" imageMso="ChartTrendline" size="large" />
          <button id="btn_rsm" label="响应面分析"
                  onAction="run_response_surface" imageMso="Chart3DSurfaceChart" size="large" />
          <button id="btn_optimize" label="最优搜索"
                  onAction="run_grid_search" imageMso="TargetInv" size="large" />
        </group>
        <group id="spc_group" label="过程监控">
          <button id="btn_spc" label="SPC控制图"
                  onAction="run_spc" imageMso="ChartLine" size="large" />
          <button id="btn_capability" label="过程能力"
                  onAction="run_process_capability" imageMso="PivotChart" size="large" />
        </group>
        <group id="report_group" label="报告输出">
          <button id="btn_excel_report" label="Excel报告"
                  onAction="run_report_excel" imageMso="FileSave" size="large" />
          <button id="btn_ppt_report" label="PPT报告"
                  onAction="run_report_ppt" imageMso="FilePublishAsPptx" size="large" />
        </group>
      </tab>
    </tabs>
  </ribbon>
</customUI>
"""
