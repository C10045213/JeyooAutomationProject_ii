import os
import sys
import markdown

# PyQt6 导入
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,  QPushButton,
                            QTextEdit, QSplitter, QLabel, QInputDialog, QMessageBox, QCheckBox, QComboBox, QMenu, QDialog)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtGui import QColor, QAction

from automation_worker import AutomationWorker

# ==========================================
# GUI 主窗口
# ==========================================

os.environ["QT_OPENGL"] = "software"  
os.environ["QT_XCB_FORCE_SOFTWARE_OPENGL"] = "1"
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"


class LogRedirector(QObject):
    """捕获 stdout 并发送信号"""
    text_written = pyqtSignal(str)
    def write(self, text):
        self.text_written.emit(str(text))
    def flush(self):
        pass

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()     

        # 关联后台线程
        self.worker = AutomationWorker()
        self.worker.log_signal.connect(self.update_log)
        self.worker.result_signal.connect(self.render_markdown)
        self.worker.input_signal.connect(self.receive_input)
        self.worker.critical_signal.connect(self.msg_critical)
        self.worker.status_signal.connect(self.update_status)
        self.worker.chooseAI_signal.connect(self.on_worker_busy_API)
        self.worker.busy_signal.connect(self.on_worker_busy)
        self.worker.batch_input_signal.connect(self.on_batch_size_request)
        self.worker.start()

        self.statusls = []

        # 窗口设置
        self.setWindowTitle("Auto-Check HUD")
        self.resize(450, 800)
        
        # 始终置顶
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)

        # 样式表 (Dark Mode)
        self.setStyleSheet("""
            QMainWindow, QDialog, QMessageBox { 
                background-color: #2b2b2b; 
                color: white; 
            }

            QLabel { 
                color: #ffffff; 
                font-weight: bold; 
            }

            QTextEdit { 
                background-color: #1e1e1e; 
                color: #00ff00; 
                font-family: 'Consolas', 'Courier New', monospace; 
                font-size: 10pt;
                border: 1px solid #444;
                padding: 5px;
            }
            
            QMenuBar {
                background-color: #1e1e1e; 
                color: #ffffff;
                border-bottom: 1px solid #444; 
            }

            QMenuBar::item {
                background-color: transparent;
                padding: 5px 10px;
                margin: 2px;
            }

            QMenuBar::item:selected { 
                background-color: #444; 
                color: #00ff00;        
                border-radius: 3px;
            }

            QMenu {
                background-color: #2b2b2b;
                color: white;
                border: 1px solid #00ff00; 
                margin: 2px;
            }

            QMenu::item {
                padding: 5px 25px 5px 20px;
                border: 1px solid transparent;
            }

            QMenu::item:selected {
                background-color: #1e1e1e; 
                color: #00ff00;             
            }
            QMenu::item:disabled {
                background-color: #2b2b2b;
                color: #666;
            }

            QMenu::separator {
                height: 1px;
                background: #444;
                margin: 5px 10px;
            }

            QMenu::indicator {
                width: 14px;
                height: 14px;
                margin-left: 4px;
            }

            QMenu::indicator:checked {
                background-color: #00ff00;
                border: 1px solid #00ff00;
                border-radius: 2px;
            }

            QMenu::indicator:unchecked {
                background-color: #1e1e1e;
                border: 1px solid #666;
                border-radius: 2px;
            }

            QCheckBox {
                color: #ffffff;
                spacing: 8px;      
                font-size: 10pt;
            }

            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                background-color: #1e1e1e;
                border: 1px solid #666;
                border-radius: 3px; 
            }

            QCheckBox::indicator:hover {
                border: 1px solid #00ff00; 
            }

            QCheckBox::indicator:checked {
                background-color: #00ff00; 
                border: 1px solid #00ff00;
            }

            QCheckBox::indicator:checked:hover {
                background-color: #00cc00; 
            }

            QCheckBox::indicator:unchecked {
                background-color: #1e1e1e;
            }

            QCheckBox:disabled {
                color: #666;
            }
            QCheckBox:disabled {
                color: #666;
            }
            QCheckBox::indicator:disabled {
                border: 1px solid #333;
                background-color: #2b2b2b;
            }

            QPushButton {
                background-color: #444;
                color: white;
                border: 1px solid #666;
                padding: 5px 15px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #555;
                border: 1px solid #00ff00; 
            }
            QPushButton:pressed {
                background-color: #222;
            }
            QPushButton:disabled {
                background-color: #333;
                color: #666;
                border: 1px solid #444;
            }

            QInputDialog {
                background-color: #2b2b2b;
            }
            QLineEdit {
                background-color: #1e1e1e;
                color: white;
                border: 1px solid #444;
                padding: 3px;
            }
            QComboBox {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #444;
                padding: 3px 8px;
                border-radius: 3px;
                min-width: 160px;
                font-size: 10pt;
            }
            QComboBox:hover {
                border: 1px solid #00ff00;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left: 1px solid #444;
            }
            QComboBox QAbstractItemView {
                background-color: #2b2b2b;
                color: #ffffff;
                selection-background-color: #444;
                selection-color: #00ff00;
                border: 1px solid #00ff00;
                outline: none;
            }
            QComboBox:disabled {
                color: #666;
                border: 1px solid #333;
                background-color: #2b2b2b;
            }
        """)

        # 主布局
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        menubar = self.menuBar()
        menubar.setNativeMenuBar(False) 

        # --- 菜单栏 ---
        general_menu = menubar.addMenu("General")
        self.restarter = QAction("浏览器9222启动/重启动", self)
        self.restarter.triggered.connect(self.worker.request_restart)
        self.re_connxion = QAction("重置Playwright连接", self)
        self.re_connxion.triggered.connect(self.worker.request_reinit)
        self.re_choose_api = QAction("重选API", self)
        self.re_choose_api.triggered.connect(self.worker.request_rechooseAPI)

        general_menu.addAction(self.restarter)
        general_menu.addSeparator()
        general_menu.addAction(self.re_connxion)
        general_menu.addAction(self.re_choose_api)

        mono_menu = menubar.addMenu("Mono")
        self.change_to_mono1 = QAction("单发审题 Mono#1", self)
        self.change_to_mono1.triggered.connect(self.worker.request_change_strategy_to_mono1)
        self.change_to_mono2 = QAction("单发复审 Mono#2", self)
        self.change_to_mono2.triggered.connect(self.worker.request_change_strategy_to_mono2)
        self.change_to_mono3 = QAction("单发考点加工 Mono#3", self)
        self.change_to_mono3.triggered.connect(self.worker.request_change_strategy_to_mono3)

        mono_menu.addAction(self.change_to_mono1)
        mono_menu.addAction(self.change_to_mono2)
        mono_menu.addSeparator()
        mono_menu.addAction(self.change_to_mono3)
        
        monoc_menu = menubar.addMenu("Mono.C")
        self.change_to_mono1c = QAction("并发审题 Mono#1C", self)
        self.change_to_mono1c.triggered.connect(self.worker.request_change_strategy_to_task1)
        self.change_to_mono2c = QAction("并发复审 Mono#2C", self)
        self.change_to_mono2c.triggered.connect(self.worker.request_change_strategy_to_mono2c)
        self.change_to_mono3c = QAction("并发考点加工 Mono#3C", self)
        self.change_to_mono3c.triggered.connect(self.worker.request_change_strategy_to_mono3c)
        monoc_menu.addAction(self.change_to_mono1c)
        monoc_menu.addAction(self.change_to_mono2c)
        monoc_menu.addSeparator()
        monoc_menu.addAction(self.change_to_mono3c)

        help_menu = menubar.addMenu("help")
        self.about = QAction("关于.", self)
        self.about.triggered.connect(self.show_about_dialog)
        help_menu.addAction(self.about)

        # --- 主显示区域 ---
        # 分割器 (上下拖动)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # 上半部分：日志控制台
        log_container = QWidget()
        log_layout = QVBoxLayout(log_container)
        log_layout.addWidget(QLabel("运行日志 (Console)"))
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        log_layout.addWidget(self.console_output)
        
        # 中间部分：填入与翻页保存控制、下半部分的标题
        result_container = QWidget()
        result_layout = QVBoxLayout(result_container)

        title_widget = QWidget()
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_label = QLabel("AI 返回结果")
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        self.btn_fill = QPushButton("填入")
        self.btn_save_n_refresh = QPushButton("保存")
        self.toggle_autofill = QCheckBox("AUTO")

        # 表单选择下拉按钮
        self.form_select_btn = QPushButton("表单 ▾")
        self.form_menu = QMenu(self.form_select_btn)
        self.form_actions = {}
        form_options = {"problem": "题目", "keypoint": "考点", "keypoint_plus": "考点+", "analysis": "分析", "discuss": "点评", "difficulty": "难度", "answer": "解答"}
        for key, label in form_options.items():
            action = self.form_menu.addAction(label)
            action.setCheckable(True)
            # # 默认选项
            # if key == "keypoint_plus":
            #     action.setChecked(False)
            # else:
            action.setChecked(True)
            action.toggled.connect(self._on_form_selection_changed)
            self.form_actions[key] = action
        self.form_select_btn.clicked.connect(self._show_form_menu)

        title_layout.addWidget(self.form_select_btn)
        title_layout.addWidget(self.btn_fill)
        title_layout.addWidget(self.btn_save_n_refresh)
        title_layout.addWidget(self.toggle_autofill)

        result_layout.addWidget(title_widget)
        
        # 下半部分：输出与渲染
        self.browser = QWebEngineView()
        self.browser.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        page0 = self.browser.page()
        if page0:
            page0.setBackgroundColor(QColor("#2b2b2b"))
        result_layout.addWidget(self.browser)

        result_layout.setStretch(0, 0) # 标签不拉伸，保持最小高度
        result_layout.setStretch(1, 1) # 浏览器拉伸，占用剩余空间

        splitter.addWidget(log_container)
        splitter.addWidget(result_container)
        splitter.setSizes([200,600]) # 默认高度比例

        layout.addWidget(splitter)

        # --- 底部按钮区域 ---
        button_layout = QHBoxLayout()

        ai_label = QLabel("AI:")
        button_layout.addWidget(ai_label)

        self.api_selector = QComboBox()
        self.api_selector.setMaxVisibleItems(6)
        self._populate_api_selector()
        self.api_selector.currentIndexChanged.connect(self.on_api_selected)
        button_layout.addWidget(self.api_selector)

        button_layout.addStretch()

        self.btn1 = QPushButton("启动")
        self.btn0 = QPushButton("终止")

        button_layout.addWidget(self.btn1)
        button_layout.addWidget(self.btn0)
        layout.addLayout(button_layout)

        self.btn1.clicked.connect(self.on_start_clicked)
        self.btn0.clicked.connect(self.worker.request_halt)

        self.btn_fill.clicked.connect(self.worker.request_fill)
        self.btn_save_n_refresh.clicked.connect(self.worker.request_save_refresh)
        self.toggle_autofill.stateChanged.connect(self.on_auto_fill_changed)
    

    # ========== GUI相关函数区 ==========
    def show_about_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("关于")
        dlg.setFixedSize(380, 200)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(8)

        emoji = QLabel("🍵")
        emoji.setAlignment(Qt.AlignmentFlag.AlignLeft)
        emoji.setStyleSheet("font-size: 32px;")
        layout.addWidget(emoji)

        info = QLabel("项目地址：")
        info.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(info)

        url = QLabel('<a href="https://github.com/C10045213/JeyooAutomationProject_ii" style="color: #58a6ff;">https://github.com/C10045213/JeyooAutomationProject_ii</a>')
        url.setAlignment(Qt.AlignmentFlag.AlignLeft)
        url.setOpenExternalLinks(True)
        url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse)
        url.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(url)

        layout.addStretch()
        dlg.exec()

    def on_start_clicked(self):
        self.browser.setHtml("")
        self.worker.request_taskrun()

    def update_status(self, bool_list: list):
        self.statusls = bool_list
    
    def on_auto_fill_changed(self, state):
        ifenabled = state == Qt.CheckState.Checked.value
        self.worker.set_auto_fill(ifenabled)

    def _show_form_menu(self):
        self.form_menu.exec(self.form_select_btn.mapToGlobal(
            self.form_select_btn.rect().bottomLeft()))

    def _on_form_selection_changed(self):
        selected = {key for key, action in self.form_actions.items() if action.isChecked()}
        self.worker.set_selected_forms(selected)

    def _compute_form_enabled(self):
        """表单按钮启用状态——由 current_strategy 类型决定，维护操作中强制禁用"""
        if self.worker.current_strategy is None:
            return False
        if self.worker.is_busy and not any(self.worker.status[1:]):
            return False
        return self.worker.is_task2_family or self.worker.is_task3_family

    def _compute_form_dropdown_enabled(self):
        """表单下拉框启用状态——考点加工模式下禁用"""
        if self.worker.current_strategy is None:
            return False
        if self.worker.is_task3_family:
            return False
        return self._compute_form_enabled()

    def _apply_form_buttons(self, enabled: bool):
        self.form_select_btn.setEnabled(enabled and not self.worker.is_task3_family)
        self.btn_fill.setEnabled(enabled)
        self.btn_save_n_refresh.setEnabled(enabled)
        self.toggle_autofill.setEnabled(enabled)

    def on_worker_busy_API(self, triggered: bool):
        """重选API时封锁其他操作按钮，否则被封锁"""
        enabled = not triggered
        has_strategy = self.worker.current_strategy is not None

        self.btn1.setEnabled(enabled and has_strategy)
        self.btn0.setEnabled(enabled and has_strategy)
        self.btn_fill.setEnabled(enabled)
        self.btn_save_n_refresh.setEnabled(enabled)
        self.restarter.setEnabled(enabled)
        self.re_connxion.setEnabled(enabled)
        self.re_choose_api.setEnabled(enabled)
        self.change_to_mono1.setEnabled(enabled)
        self.change_to_mono2.setEnabled(enabled)
        self.change_to_mono1c.setEnabled(enabled)
        self.change_to_mono2c.setEnabled(enabled)
        self.change_to_mono3.setEnabled(enabled)
        self.change_to_mono3c.setEnabled(enabled)
        self.toggle_autofill.setEnabled(enabled)
        self.form_select_btn.setEnabled(enabled)
        self.api_selector.setEnabled(triggered)

        if not triggered:
            self._apply_form_buttons(self._compute_form_enabled())

    def on_worker_busy(self, busy: bool):
        """Worker 忙碌时封锁操作按钮，防止重复操作。"""
        enabled = not busy
        has_strategy = self.worker.current_strategy is not None

        self.btn1.setEnabled(enabled and has_strategy)
        self.btn0.setEnabled(any(self.worker.status[1:]) and has_strategy)
        self.restarter.setEnabled(enabled)
        self.re_connxion.setEnabled(enabled)
        self.re_choose_api.setEnabled(enabled)
        self.change_to_mono1.setEnabled(enabled)
        self.change_to_mono2.setEnabled(enabled)
        self.change_to_mono1c.setEnabled(enabled)
        self.change_to_mono2c.setEnabled(enabled)
        self.change_to_mono3.setEnabled(enabled)
        self.change_to_mono3c.setEnabled(enabled)
        self.api_selector.setEnabled(enabled)

        self._apply_form_buttons(self._compute_form_enabled())


    def on_batch_size_request(self, prompt: str):
        size, ok = QInputDialog.getInt(self, "批次数量设置", prompt, value=5, min=1, max=9999, step=1)
        if ok:
            self.worker.client_receive_batch_size(size)
        else:
            self.worker.client_receive_batch_size(-1)

    # ========== AI 选择下拉列表 ==========
    def _populate_api_selector(self):
        """从 worker 的 model_map 填充 AI 选择下拉列表。"""
        self.api_selector.blockSignals(True)
        self.api_selector.clear()
        self.api_selector.addItem("请选择AI模型...", None)
        for num, (name, _) in self.worker.analyser.model_map.items():
            if num != '99':
                self.api_selector.addItem(f"{num}. {name}", num)
        self.api_selector.setCurrentIndex(0)
        self.api_selector.blockSignals(False)

    def on_api_selected(self, index):
        """下拉列表选择变更时通知 worker。"""
        if index <= 0:
            return
        key = self.api_selector.itemData(index)
        if key:
            self.worker.client_receive_input(str(key))

    def receive_input(self, prompt):
        """提示用户从下拉列表中选择 AI 模型。"""
        self.update_log(prompt)
        self.api_selector.setCurrentIndex(0)
        self.api_selector.setFocus()

    def update_log(self, text):
        self.console_output.append(text.strip())

    def msg_critical(self, text):
        QMessageBox.critical(self, "终止", text)

    def render_markdown(self, markdown_text):
        def texreplace(text):
            # 双反斜杠与单星转义、单下划线紧随大括号转义
            # text = text.replace('\\', '\\\\')
            # text = re.sub(r'(?<!\*)\^\*(?!\*)', r'^\\*', text)
            # text = text.replace('_{', '\\_{')
            text = text.replace('\\u200b', '')
            print(repr(text))
            return text
        
        markdown_text = texreplace(markdown_text) 
        
        md_extensions = [
            'fenced_code', 
            'tables', 
        ]
        
        try:
            rendered_md = markdown.markdown(
                markdown_text,
                extensions=md_extensions,
            )
        except Exception as e:
            rendered_md = f"<p>Markdown 解析失败: {e}</p><pre>{markdown_text}</pre>"
        
        html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                
                <!-- 1. 定义配置 (必须在加载库之前) -->
                <script>
                window.MathJax = {{
                    tex: {{
                        inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
                        displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
                        processEscapes: true
                    }},
                    startup: {{
                        // 2. 关键修复：使用 pageReady 回调
                        // 这个函数会在 MathJax 库加载完成且 DOM 准备好后自动调用
                        pageReady: () => {{
                            console.log('MathJax 开始渲染...');
                            return MathJax.startup.defaultPageReady().then(() => {{
                                console.log('MathJax 渲染完成');
                            }});
                        }}
                    }}
                }};
                </script>
                
                <!-- 3. 加载库 (移除 polyfill，只留 MathJax) -->
                <script id="MathJax-script" src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
                
                <style>
                    body {{
                        background-color: #2b2b2b;
                        color: #e0e0e0;
                        font-family: "Segoe UI", sans-serif;
                        padding: 15px;
                        line-height: 1.6;
                    }}
                    code {{
                        background-color: #444;
                        padding: 2px 5px;
                        border-radius: 3px;
                    }}
                    pre {{
                        background-color: #111;
                        padding: 10px;
                        border-radius: 5px;
                        overflow-x: auto;
                        white-space: pre-wrap !important;
                        word-wrap: break-word !important;
                        word-break: break-all !important;
                    }}
                    /* 强制公式颜色适配深色模式 */
                    mjx-container {{ color: #e0e0e0 !important; }}
                </style>
            </head>
            <body>
                {rendered_md}
                
                <!-- 4. 底部不再需要手动触发脚本，配置里的 pageReady 会自动处理 -->
            </body>
            </html>
        """
        self.browser.setHtml(html_content)

    def closeEvent(self, event):
        self.worker.running = False
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())