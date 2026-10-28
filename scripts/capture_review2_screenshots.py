import os
import time
from playwright.sync_api import sync_playwright

CHROME_PATH = r"C:\Users\Srikiran\AppData\Local\ms-playwright\chromium-1247\chrome-win64\chrome.exe"
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "review2_screenshots")
os.makedirs(OUT_DIR, exist_ok=True)

CMD_INJECTION_CODE = """// expect: 1 finding, rule command_execution, HIGH, category command-injection
// Untrusted standard input is concatenated into a shell command.
string build_command(string user_input) {
  return "ls " + user_input;
}

int main() {
  string name = input();
  string command = build_command(name);
  system(command);
  return 0;
}"""

MISSING_SEMI_CODE = """int main() {
  string name = input()
  system(name);
  return 0;
}"""

def capture_all():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME_PATH)
        context = browser.new_context(viewport={"width": 1366, "height": 840}, device_scale_factor=1.5)
        page = context.new_page()

        # 1. Overview Dashboard
        print("1. Capturing Overview...")
        page.goto("http://127.0.0.1:8000/#/overview")
        page.wait_for_selector(".nav")
        time.sleep(1)
        page.screenshot(path=os.path.join(OUT_DIR, "01_overview_dashboard.png"))

        # 2. Analyze Code
        print("2. Capturing Analyze Code...")
        page.goto("http://127.0.0.1:8000/#/analyze")
        page.wait_for_selector("#source-input")
        page.fill("#filename-input", "command_injection.ctc")
        page.fill("#source-input", CMD_INJECTION_CODE)
        page.click("#analyze-button")
        time.sleep(1.5)
        page.screenshot(path=os.path.join(OUT_DIR, "02_analyze_code_workbench.png"))

        # 3. Live Dirty Editor Alert
        print("3. Capturing Live Dirty Editor Alert...")
        page.type("#source-input", "\n// live modification detected")
        time.sleep(0.8)
        page.screenshot(path=os.path.join(OUT_DIR, "03_live_dirty_editor_alert.png"))

        # 4. Located Diagnostics
        print("4. Capturing Located Syntax Diagnostics...")
        page.fill("#filename-input", "missing_semicolon.ctc")
        page.fill("#source-input", MISSING_SEMI_CODE)
        page.click("#analyze-button")
        time.sleep(1.5)
        page.screenshot(path=os.path.join(OUT_DIR, "04_located_syntax_diagnostics.png"))

        # Re-run command injection for complete downstream artifacts
        page.fill("#filename-input", "command_injection.ctc")
        page.fill("#source-input", CMD_INJECTION_CODE)
        page.click("#analyze-button")
        time.sleep(1.5)

        # 5. Findings & Evidence
        print("5. Capturing Findings View...")
        page.goto("http://127.0.0.1:8000/#/findings")
        time.sleep(1)
        # Click on the first finding if present
        finding_item = page.locator(".card, .finding-row, li:has-text('command_execution')")
        if finding_item.count() > 0:
            finding_item.first.click()
            time.sleep(0.5)
        page.screenshot(path=os.path.join(OUT_DIR, "05_findings_and_evidence_path.png"))

        # 6. Program Graph
        print("6. Capturing Program Graph...")
        page.goto("http://127.0.0.1:8000/#/graph")
        time.sleep(1.5)
        page.screenshot(path=os.path.join(OUT_DIR, "06_interactive_program_graph.png"))

        # 7. Data-Flow Analysis
        print("7. Capturing Data-Flow Analysis...")
        page.goto("http://127.0.0.1:8000/#/dataflow")
        time.sleep(1.2)
        # Click a statement to show per-statement details
        stmt_row = page.locator("tr:has-text('system(command)')")
        if stmt_row.count() > 0:
            stmt_row.first.click()
            time.sleep(0.5)
        page.screenshot(path=os.path.join(OUT_DIR, "07_dataflow_analysis_inspector.png"))

        # 8. Program Slicing
        print("8. Capturing Program Slicing...")
        page.goto("http://127.0.0.1:8000/#/slicing")
        time.sleep(1.2)
        page.screenshot(path=os.path.join(OUT_DIR, "08_program_slicing_evidence.png"))

        # 9. Declarative Rule Editor
        print("9. Capturing Rule Editor...")
        page.goto("http://127.0.0.1:8000/#/rules")
        time.sleep(1.2)
        page.screenshot(path=os.path.join(OUT_DIR, "09_declarative_rule_editor.png"))

        # 10. Reports
        print("10. Capturing Reports...")
        page.goto("http://127.0.0.1:8000/#/reports")
        time.sleep(1.2)
        page.screenshot(path=os.path.join(OUT_DIR, "10_audit_reports_export.png"))

        # 11. Compiler Documentation
        print("11. Capturing Documentation...")
        page.goto("http://127.0.0.1:8000/#/documentation")
        time.sleep(1.2)
        page.screenshot(path=os.path.join(OUT_DIR, "11_compiler_documentation.png"))

        # 12. Dark Theme Workbench
        print("12. Capturing Dark Theme Workbench...")
        page.goto("http://127.0.0.1:8000/#/overview")
        time.sleep(0.5)
        theme_toggle = page.locator("#theme-toggle")
        if theme_toggle.count() > 0:
            theme_toggle.click()
            # Click again if needed to cycle to dark
            time.sleep(0.2)
            theme_text = theme_toggle.inner_text().lower()
            if "dark" not in theme_text:
                theme_toggle.click()
        else:
            page.evaluate("document.body.classList.add('dark')")
        time.sleep(0.8)
        page.screenshot(path=os.path.join(OUT_DIR, "12_dark_theme_workbench.png"))

        browser.close()
        print("All 12 screenshots captured successfully!")

if __name__ == "__main__":
    capture_all()
