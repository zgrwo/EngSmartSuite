Attribute VB_Name = "SmartSuiteRibbon"

Public Sub ribbon_correlation(control As IRibbonControl)
    RunPython ("import smartsuite_addin; smartsuite_addin.run_correlation()")
End Sub

Public Sub ribbon_anova(control As IRibbonControl)
    RunPython ("import smartsuite_addin; smartsuite_addin.run_anova()")
End Sub

Public Sub ribbon_hypothesis(control As IRibbonControl)
    RunPython ("import smartsuite_addin; smartsuite_addin.run_hypothesis_test()")
End Sub

Public Sub ribbon_regression(control As IRibbonControl)
    RunPython ("import smartsuite_addin; smartsuite_addin.run_regression()")
End Sub

Public Sub ribbon_rsm(control As IRibbonControl)
    RunPython ("import smartsuite_addin; smartsuite_addin.run_response_surface()")
End Sub

Public Sub ribbon_grid(control As IRibbonControl)
    RunPython ("import smartsuite_addin; smartsuite_addin.run_grid_search()")
End Sub

Public Sub ribbon_spc(control As IRibbonControl)
    RunPython ("import smartsuite_addin; smartsuite_addin.run_spc()")
End Sub

Public Sub ribbon_capability(control As IRibbonControl)
    RunPython ("import smartsuite_addin; smartsuite_addin.run_process_capability()")
End Sub

Public Sub ribbon_excel_report(control As IRibbonControl)
    RunPython ("import smartsuite_addin; smartsuite_addin.run_report_excel()")
End Sub

Public Sub ribbon_ppt_report(control As IRibbonControl)
    RunPython ("import smartsuite_addin; smartsuite_addin.run_report_ppt()")
End Sub
