import asyncio
import threading
import os
import subprocess
from PyQt6.QtCore import QThread, pyqtSignal, QEventLoop
from AI_analyse_V1 import AsyncAnalyser
from broswer_manager import BrowserManager
from dotenv import load_dotenv

import task1, task2
import mono_task1, mono_task2, mono_task2_concurrent
import mono_task3, mono_task3_concurrent

load_dotenv(override = True)

class AutomationWorker(QThread):
    
    log_signal = pyqtSignal(str)
    result_signal = pyqtSignal(str)
    input_signal = pyqtSignal(str)
    critical_signal = pyqtSignal(str)
    status_signal = pyqtSignal(list)
    chooseAI_signal = pyqtSignal(bool)
    busy_signal = pyqtSignal(bool)
    batch_input_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = True
        
        # 标志位
        self._request_restart = False
        self._task_requested = False   
        self._reinit_requested = False 
        self._rechooseAPI_requested = False
        self._requested_change_to_task1 = False
        self._requested_change_to_task2 = False
        self._requested_change_to_mono1 = False
        self._requested_change_to_mono2 = False
        self._requested_change_to_mono2c = False
        self._requested_change_to_mono3 = False
        self._requested_change_to_mono3c = False
        self._task1_flag = False
        self._task2_flag = False
        self._savenext_requested = False
        self._fill_requested = False
        self._auto_fill_enabled = False
        self._save_mode = 0
        self._selected_forms = {"problem", "keypoint", "keypoint_plus", "analysis", "discuss", "difficulty", "answer"}
        self._connected = False
        self._dialog_listeners_registered = set()
        
        # Playwright
        self.browser_manager = BrowserManager(self.log_signal.emit)
        self.pages = None
        self.browser_path = None
        self.browser_process = None
        
        # 当前执行的策略与线程控制
        self.current_strategy = None
        self.method_thread = None
        self.stop_signal = threading.Event()
        self.status = [0,0,0] # 状态列表，元素1对应基底进程运行中，元素2对应任务1，元素3对应任务2.
        self.analyser = AsyncAnalyser(stop_event=self.stop_signal)


    @property
    def is_busy(self):
        return any(self.status)

    @property
    def is_task2_family(self):
        """当前策略是否为复审类 (Task2 / Mono2 / Mono2C)"""
        return isinstance(self.current_strategy, (
            task2.QualityCheckStep2,
            mono_task2.MonoQualityCheckStep2,
            mono_task2_concurrent.MonoQualityCheckStep2Concurrent,
        ))

    @property
    def is_task3_family(self):
        """当前策略是否为考点加工类 (Mono3 / Mono3C)"""
        return isinstance(self.current_strategy, (
            mono_task3.MonoKeypointProcess,
            mono_task3_concurrent.MonoKeypointProcessConcurrent,
        ))

    def _set_busy(self, task_index=0):
        if not self.status[task_index]:
            self.status[task_index] = 1
            self.status_signal.emit(self.status)
            self.busy_signal.emit(True)
        
    def _set_idle(self):
        if any(self.status):
            self.status = [0, 0, 0]
            self.status_signal.emit(self.status)
            self.busy_signal.emit(False)
            # 非请求更换模型，则禁用选用
            self.chooseAI_signal.emit(False)

    def _current_task_index(self):
        if isinstance(self.current_strategy, (task1.QualityCheckStep1, mono_task1.MonoQualityCheckStep1)):
            return 1
        elif isinstance(self.current_strategy, (task2.QualityCheckStep2, mono_task2.MonoQualityCheckStep2, mono_task2_concurrent.MonoQualityCheckStep2Concurrent,
                                                 mono_task3.MonoKeypointProcess, mono_task3_concurrent.MonoKeypointProcessConcurrent)):
            return 2
        return 0

    async def _cleanup_current_strategy(self):
        """关闭当前策略的 AsyncAnalyser，释放 httpx 连接"""
        if self.current_strategy and hasattr(self.current_strategy, 'analyser'):
            try:
                await self.current_strategy.analyser.close()
            except Exception:
                pass

    def request_change_strategy_to_task1(self):
        self._requested_change_to_task1 = True
        self.log_signal.emit(f"请等待...")

    def request_change_strategy_to_task2(self):
        self._requested_change_to_task2 = True
        self.log_signal.emit(f"请等待...")

    def request_change_strategy_to_mono1(self):
        self._requested_change_to_mono1 = True
        self.log_signal.emit(f"请等待...")

    def request_change_strategy_to_mono2(self):
        self._requested_change_to_mono2 = True
        self.log_signal.emit(f"请等待...")

    def request_change_strategy_to_mono2c(self):
        self._requested_change_to_mono2c = True
        self.log_signal.emit(f"请等待...")

    def request_change_strategy_to_mono3(self):
        self._requested_change_to_mono3 = True
        self.log_signal.emit(f"请等待...")

    def request_change_strategy_to_mono3c(self):
        self._requested_change_to_mono3c = True
        self.log_signal.emit(f"请等待...")

    def request_reinit(self):
        self._reinit_requested = True
        self.log_signal.emit(">>> 已收到重置指令，等待线程调度...")

    def request_taskrun(self):
        self._task_requested = True
        self.log_signal.emit(f"请等待...")

    # 处理终止
    def request_halt(self):
        self.log_signal.emit(f"已发出终止指令。")
        self.stop_signal.set()

    def request_rechooseAPI(self):
        self._rechooseAPI_requested = True
        self.log_signal.emit(f"请等待...")

    def request_restart(self):
        self._request_restart = True
        self.log_signal.emit(f"请等待...")

    def request_fill(self):
        if self.current_strategy and hasattr(self.current_strategy, 'request_fill'):
            self.current_strategy.request_fill()
        else:
            self.log_signal.emit(f"未设置策略，或当前策略无此函数。")

    def request_save_composite(self):
        if self.current_strategy and hasattr(self.current_strategy, 'request_save_composite'):
            self.current_strategy.request_save_composite()
        else:
            self.log_signal.emit(f"未设置策略，或当前策略无此函数。")

    def set_save_mode(self, mode: int):
        self._save_mode = mode
        if self.current_strategy and hasattr(self.current_strategy, 'set_save_mode'):
            self.current_strategy.set_save_mode(mode)
        else:
            self.log_signal.emit(f"未设置策略，或当前策略无此函数。")

    def set_auto_fill(self, enabled: bool):
        self._auto_fill_enabled = enabled
        if self.current_strategy and hasattr(self.current_strategy, 'set_auto_fill'):
            self.current_strategy.set_auto_fill(enabled)
        else:
            self.log_signal.emit(f"未设置策略，或当前策略无此函数。")

    def set_selected_forms(self, forms: set):
        self._selected_forms = forms
        if self.current_strategy and hasattr(self.current_strategy, 'set_selected_forms'):
            self.current_strategy.set_selected_forms(forms)
        else:
            self.log_signal.emit(f"未设置策略，或当前策略无此函数。")


    def run(self):
        """重写同步的 run 方法"""
        # 在当前线程创建一个新的 asyncio 事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # 运行主异步逻辑
        loop.run_until_complete(self.main_loop())
        loop.close()

    async def main_loop(self):
        """真正的异步主循环"""
        self.log_signal.emit(f"TASK#1: {task1.QualityCheckStep1.__doc__}")
        self.log_signal.emit(f"TASK#2: {task2.QualityCheckStep2.__doc__}")

        self._rechooseAPI_requested = True

        while self.running:
            # 1. 重置逻辑
            if self._reinit_requested:
                self._set_busy(0)
                self._reinit_requested = False
                await self._do_reinit()
                self._set_idle()

            # 2. 执行任务
            if self._task_requested:
                self._set_busy(self._current_task_index())
                self._task_requested = False
                await self.task_run()
                self._set_idle()

            # 3. 处理重选API
            if self._rechooseAPI_requested:
                self.chooseAI_signal.emit(True)
                self._rechooseAPI_requested = False
                await self._cleanup_current_strategy()
                self.client_select_request()
                self.chooseAI_signal.emit(False)
                self._set_idle()

            # 4. 切换策略
            if self._requested_change_to_task1:
                self._set_busy(0)
                self._requested_change_to_task1 = False
                await self.change_strategy_to_task1()
                self._set_idle()

            if self._requested_change_to_task2:
                self._set_busy(0)
                self._requested_change_to_task2 = False
                await self.change_strategy_to_task2()
                self._set_idle()

            if self._requested_change_to_mono1:
                self._set_busy(0)
                self._requested_change_to_mono1 = False
                await self.change_strategy_to_mono1()
                self._set_idle()

            if self._requested_change_to_mono2:
                self._set_busy(0)
                self._requested_change_to_mono2 = False
                await self.change_strategy_to_mono2()
                self._set_idle()

            if self._requested_change_to_mono2c:
                self._set_busy(0)
                self._requested_change_to_mono2c = False
                await self.change_strategy_to_mono2c()
                self._set_idle()

            if self._requested_change_to_mono3:
                self._set_busy(0)
                self._requested_change_to_mono3 = False
                await self.change_strategy_to_mono3()
                self._set_idle()

            if self._requested_change_to_mono3c:
                self._set_busy(0)
                self._requested_change_to_mono3c = False
                await self.change_strategy_to_mono3c()
                self._set_idle()

            # 5. 检查弹窗
            await self.refresh_n_check_pages_ondialog()

            # 6. 处理重启动
            if self._request_restart:
                self._set_busy(0)
                self._request_restart = False
                await self.reboot()
                self._set_idle()

            # 异步睡
            await asyncio.sleep(0.1)
            
        # 退出时清理
        await self._cleanup_current_strategy()
        try:
            await self.analyser.close()
        except Exception:
            pass
        await self.browser_manager.close()

# ========== 线程基础逻辑 ==========
    async def _do_reinit(self):
        """线程内部执行的重置逻辑"""
        self._dialog_listeners_registered.clear()
        self.connected = await self.browser_manager.connect()
        if self.connected and self.current_strategy:
            self.pages = await self.browser_manager.get_all_pages()
            await self.current_strategy.locate_pages(self.pages) # 各Task的locate_pages函数名需统一
        elif self.current_strategy == None:
            self.log_signal.emit(f"错误：尚未连接或未选择任务")


    async def task_run(self):
        if self.current_strategy:
            try:
                self.stop_signal.clear()
                if isinstance(self.current_strategy, (task2.QualityCheckStep2, mono_task2_concurrent.MonoQualityCheckStep2Concurrent,
                                                       mono_task3_concurrent.MonoKeypointProcessConcurrent)):
                    batch_size = self.request_batch_size()
                    if batch_size == -1:
                        self.log_signal.emit(f"已取消。")
                        return
                    self.current_strategy.set_taskcounts(batch_size)
                await self.current_strategy.execute()
            except Exception as e:
                error_msg = str(e)
                if "closed" in error_msg.lower():
                    self.log_signal.emit(f"检测到浏览器页面已关闭，需要重连...")
                else:
                    self.log_signal.emit(f"任务执行其他异常: {e}")
        else:
            self.log_signal.emit(f"未设置任务策略！")


    def client_select_request(self):
        """重选 AI 审核客户端"""
        self.current_strategy = None
        self.log_signal.emit(f"*" * 20)
        self.log_signal.emit("请预先确认 VPN 已正确配置")
        self.log_signal.emit(f"原任务策略已退出")
        self.log_signal.emit(f"*" * 20)

        self._loop = QEventLoop()
        self.input_signal.emit("请从下方下拉列表中选择 AI 模型")
        self._loop.exec()

    def client_receive_input(self, data):
        if data != None:
            self._user_input = data
            self.log_signal.emit(f"#{data} Choosen")
            try:
                print(self.analyser.model_map.get(data))
            except Exception as e:
                self.log_signal.emit(f"选择API出现错误，{e}")
        else:
            self.log_signal.emit(f"操作已取消。")
            self._user_input = ""
        if self._loop:
            self._loop.quit()

    def request_batch_size(self):
        self._batch_loop = QEventLoop()
        self.batch_input_signal.emit("请输入当前批次需要处理的数据数目:")
        self._batch_loop.exec()
        return self._batch_size

    def client_receive_batch_size(self, size: int):
        self._batch_size = size
        if size != -1:
            self.log_signal.emit(f"当前批次处理数量: {size}")
        if hasattr(self, '_batch_loop'):
            self._batch_loop.quit()


    # 应对各页面中需要手动处置的弹窗，并刷新当前打开所有页面确保处理所有弹窗
    def manual_check(self, dialog):
        try:
            dialog.accept()
        # 跳过异常（重要）
        except:
            return
             
    async def refresh_n_check_pages_ondialog(self):
        if self.pages is None:
            return

        try:
            self.pages = await self.browser_manager.get_all_pages()
            for p in self.pages:
                if p.is_closed():
                    continue
                if p not in self._dialog_listeners_registered:
                    p.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
                    self._dialog_listeners_registered.add(p)
        except Exception as e:
            if "closed" not in str(e).lower():
                self.log_signal.emit(f"检查页面异常: {e}")


    # 切换任务
    async def change_strategy_to_task1(self):
        if self._user_input == '':
            self.log_signal.emit(f"未选择API！")
            return
        await self._cleanup_current_strategy()
        self.current_strategy = task1.QualityCheckStep1(self.log_signal.emit,self.result_signal.emit,self._user_input, self.stop_signal)
        if hasattr(self.current_strategy, 'set_auto_fill'):
            self.current_strategy.set_auto_fill(self._auto_fill_enabled)
        self.log_signal.emit(f"正在切换工作模式: {task1.QualityCheckStep1.__doc__}")
        await self._do_reinit()

    async def change_strategy_to_task2(self):
        if self._user_input == '':
            self.log_signal.emit(f"未选择API！")
            return
        await self._cleanup_current_strategy()
        self.current_strategy = task2.QualityCheckStep2(self.log_signal.emit,self.result_signal.emit,self._user_input, self.stop_signal)
        if hasattr(self.current_strategy, 'set_auto_fill'):
            self.current_strategy.set_auto_fill(self._auto_fill_enabled)
        if hasattr(self.current_strategy, 'set_selected_forms'):
            self.current_strategy.set_selected_forms(self._selected_forms)
        if hasattr(self.current_strategy, 'set_save_mode'):
            self.current_strategy.set_save_mode(self._save_mode)
        self.log_signal.emit(f"正在换工作模式: {task2.QualityCheckStep2.__doc__}")
        await self._do_reinit()

    async def change_strategy_to_mono1(self):
        if self._user_input == '':
            self.log_signal.emit(f"未选择API！")
            return
        await self._cleanup_current_strategy()
        self.current_strategy = mono_task1.MonoQualityCheckStep1(self.log_signal.emit, self.result_signal.emit, self._user_input, self.stop_signal)
        self.log_signal.emit(f"正在切换工作模式: {mono_task1.MonoQualityCheckStep1.__doc__}")
        await self._do_reinit()

    async def change_strategy_to_mono2(self):
        if self._user_input == '':
            self.log_signal.emit(f"未选择API！")
            return
        await self._cleanup_current_strategy()
        self.current_strategy = mono_task2.MonoQualityCheckStep2(self.log_signal.emit, self.result_signal.emit, self._user_input, self.stop_signal)
        if hasattr(self.current_strategy, 'set_auto_fill'):
            self.current_strategy.set_auto_fill(self._auto_fill_enabled)
        if hasattr(self.current_strategy, 'set_selected_forms'):
            self.current_strategy.set_selected_forms(self._selected_forms)
        if hasattr(self.current_strategy, 'set_save_mode'):
            self.current_strategy.set_save_mode(self._save_mode)
        self.log_signal.emit(f"正在切换工作模式: {mono_task2.MonoQualityCheckStep2.__doc__}")
        await self._do_reinit()

    async def change_strategy_to_mono2c(self):
        if self._user_input == '':
            self.log_signal.emit(f"未选择API！")
            return
        await self._cleanup_current_strategy()
        self.current_strategy = mono_task2_concurrent.MonoQualityCheckStep2Concurrent(self.log_signal.emit, self.result_signal.emit, self._user_input, self.stop_signal)
        if hasattr(self.current_strategy, 'set_auto_fill'):
            self.current_strategy.set_auto_fill(self._auto_fill_enabled)
        if hasattr(self.current_strategy, 'set_selected_forms'):
            self.current_strategy.set_selected_forms(self._selected_forms)
        if hasattr(self.current_strategy, 'set_save_mode'):
            self.current_strategy.set_save_mode(self._save_mode)
        self.log_signal.emit(f"正在切换工作模式: {mono_task2_concurrent.MonoQualityCheckStep2Concurrent.__doc__}")
        await self._do_reinit()

    async def change_strategy_to_mono3(self):
        if self._user_input == '':
            self.log_signal.emit(f"未选择API！")
            return
        await self._cleanup_current_strategy()
        self.current_strategy = mono_task3.MonoKeypointProcess(self.log_signal.emit, self.result_signal.emit, self._user_input, self.stop_signal)
        if hasattr(self.current_strategy, 'set_auto_fill'):
            self.current_strategy.set_auto_fill(self._auto_fill_enabled)
        if hasattr(self.current_strategy, 'set_save_mode'):
            self.current_strategy.set_save_mode(self._save_mode)
        self.log_signal.emit(f"正在切换工作模式: {mono_task3.MonoKeypointProcess.__doc__}")
        await self._do_reinit()

    async def change_strategy_to_mono3c(self):
        if self._user_input == '':
            self.log_signal.emit(f"未选择API！")
            return
        await self._cleanup_current_strategy()
        self.current_strategy = mono_task3_concurrent.MonoKeypointProcessConcurrent(self.log_signal.emit, self.result_signal.emit, self._user_input, self.stop_signal)
        if hasattr(self.current_strategy, 'set_auto_fill'):
            self.current_strategy.set_auto_fill(self._auto_fill_enabled)
        if hasattr(self.current_strategy, 'set_save_mode'):
            self.current_strategy.set_save_mode(self._save_mode)
        self.log_signal.emit(f"正在切换工作模式: {mono_task3_concurrent.MonoKeypointProcessConcurrent.__doc__}")
        await self._do_reinit()


    # 重启动
    async def reboot(self):
        """重启浏览器进程"""
        try:
            browser_process = os.getenv("BROWSER_PROCESS", "msedge.exe")
            browser_path = os.getenv("BROWSER_PATH")

            self.log_signal.emit("正在关闭现有浏览器...")
            await self.browser_manager.close()
            
            subprocess.run(f"taskkill /F /IM {browser_process}", shell=True, capture_output=True)
            await asyncio.sleep(1)

            self.log_signal.emit("正在启动新浏览器...")
            subprocess.Popen([browser_path, "--remote-debugging-port=9222", "--user-data-dir=C:\\EdgeDebugProfile"], shell=False)
            
            await asyncio.sleep(2) # 等待启动
        except Exception as e:
            self.log_signal.emit(f"重启失败: {e}")


