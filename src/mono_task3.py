import AI_analyse_V1 as analyser
import regex_formatting as refmt
import os
import pyperclip
import base64
from playwright.async_api import Page
import json
import threading
import asyncio
import time

class MonoKeypointProcess():
    """单发考点加工"""

    def __init__(self, log_callback, result_callback, input_num_for_AI: str, stop_signal: threading.Event):
        self.log = log_callback
        self.result = result_callback
        self.stop = stop_signal
        self.analyser = analyser.AsyncAnalyser(stop_event=self.stop)
        self._user_input = input_num_for_AI
        self.page_1: Page = None
        self.input_data = {}

        self._fill_requested = threading.Event()
        self._fill_lock = asyncio.Lock()
        self._save_composite_requested = threading.Event()
        self._save_composite_lock = asyncio.Lock()
        self._save_func = [self._submit]
        self._auto_fill_enabled = False

    def request_fill(self):
        if not self._auto_fill_enabled:
            self._fill_requested.set()
            self.log("收到填充指令...")

    def request_save_composite(self):
        self._save_composite_requested.set()
        self.log("收到保存/刷新指令...")

    def set_save_mode(self, mode):
        action_map = {
            0: [self._submit],
            1: [self._save, self._next],
            2: [self._save, self._previous],
            3: [self._save, self._refresh]
        }
        self._save_func = action_map.get(mode, [self._submit])
        mode_names = {0: "仅提交", 1: "保存并下一页", 2: "保存并上一页", 3: "保存并刷新"}
        self.log(f"保存模式已更新: {mode_names.get(mode, '模式设置异常')}")

    def set_auto_fill(self, enabled: bool):
        self._auto_fill_enabled = enabled
        status = "启用" if enabled else "禁用"
        self.log(f"自动填充已{status}")

    def set_selected_forms(self, forms: set):
        pass

    def sys_instruct_AI(self):
        with open("prompts/task3_sys_instruct_mono.txt", 'r', encoding='utf-8') as f:
            return f.read().strip()

    def keypoint_table(self):
        with open("datas/keypoint_table_referencing.md", 'r', encoding='utf-8') as f:
            return f.read().strip()

    async def locate_pages(self, pages):
        for page in pages:
            try:
                if await page.locator(".BUTTONS_SELECTOR:nth-child(1)").is_visible():
                    self.page_1 = page
                    self.log(f"已锁定考点加工页面: {await page.title()}")
            except Exception:
                self.log("页面定位异常。")
        if not self.page_1:
            self.log("!!! 警告: 未找到考点加工页面")

    async def execute(self):
        if self.page_1 is None:
            self.log("页面未定位，非法操作。")
            return

        if not await self.page_1.locator(".BUTTONS_SELECTOR:nth-child(1)").is_visible():
            self.log("非目标页面，请重连。")
            return

        if self.page_1.is_closed():
            self.log("***※目标页面已关闭※***")
            return

        if self.stop.is_set():
            self.log("***※已终止※***")
            return

        while not self.stop.is_set():
            self.log("\n>>> 开始执行单发考点加工...")
            start_time = time.perf_counter()

            problem_sn = await self.page_1.locator("td:nth-child(2) > a:nth-child(2)").first.inner_text()

            if await self.page_1.locator(".tablebar:nth-child(2) > h2 > input").is_visible():
                num = await self.page_1.locator(".tablebar:nth-child(2) > h2 > input").get_attribute("value")
                final_num = await self.page_1.locator(".tablebar:nth-child(2) span").inner_text()
            else:
                num = -1

            # 1. 截图
            choices_locator = self.page_1.locator("table.qanwser")
            if await choices_locator.count() > 0:
                imgs = await self._choices_screenshot()
                if imgs is None:
                    self.log("***※截图失败※***")
                    self.stop.set()
                    return
            else:
                imgs = ''

            self.log(f"1. 本题页码为:{num}, SN：\n{problem_sn}")
            self.log("2. 正在获取题目...")
            problem = refmt.process_text(await self._copy_problem())

            # 2. OCR
            choices_alltext = ''
            if imgs != '':
                choices_pic64 = self._encode_base64(imgs)
            else:
                choices_pic64 = ''
            if choices_pic64 != '':
                self.log("2.2 调用多模态LLM进行题目OCR...")
                content_payload = []
                content_payload.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{choices_pic64}"}})
                choices_alltext = await self._problem_ocr(content_payload)
                if choices_alltext == '' or type(json.loads(choices_alltext)) == list:
                    self.log("请求超时(300s)，或识图失败。")
                    choices_alltext = '{"OCR_Result": "OCR_Failed"}'
                choices_alltext = json.loads(choices_alltext)["OCR_Result"]
                try:
                    if os.path.exists(imgs):
                        os.remove(imgs)
                except Exception as e:
                    self.log(f"清理截图文件失败: {e}")

            self.input_data = {
                "problem": problem,
                "choices_text": choices_alltext
            }

            # 3. AI 考点分析
            self.log("3. 提交 AI 考点分析...")
            ai_output = await self._analyze_keypoint(problem, choices_alltext)

            if ai_output == '':
                self.stop.set()
                self.log("请求返回response超时(300s)")
                return

            self.result(ai_output)

            # 4. 改写表单
            self.log("4. 正在等待改写表单...")
            self.log(f"=" * 20)
            try:
                ai_output_formatted = self._formatize_ai_output2json(ai_output)
                parsed_json = json.loads(ai_output_formatted)

                if parsed_json["keypoint"]["s"] == '0':
                    self.log("✔️考点表内存在合适考点。")
                elif parsed_json["keypoint"]["s"] == '-1':
                    self.log("❎考点表内未找到合适考点。")

                current_sn = await self.page_1.locator("td:nth-child(2) > a:nth-child(2)").first.inner_text()
                is_filled = False
                while problem_sn == current_sn:
                    if is_filled == False:
                        if self._auto_fill_enabled:
                            await self._fill_forms(parsed_json)
                            is_filled = True

                        if self._fill_requested.is_set():
                            self._fill_requested.clear()
                            async with self._fill_lock:
                                await self._fill_forms(parsed_json)
                                is_filled = True
                    else:
                        if self._fill_requested.is_set():
                            self._fill_requested.clear()
                            self.log(f"内容已填入。")

                    if self._save_composite_requested.is_set():
                        self._save_composite_requested.clear()
                        async with self._save_composite_lock:
                            await self._submit()
                            await asyncio.sleep(1)
                            if await self.page_1.locator("div#_messsage").is_visible(timeout=1000):
                                await self.page_1.locator("div#_messsage").click()
                            if await self.page_1.locator("div#_messsage").is_visible(timeout=1000):
                                await self.page_1.locator("div#_messsage").click()
                        current_sn = await self.page_1.locator("td:nth-child(2) > a:nth-child(2)").first.inner_text()

                    if self.stop.is_set():
                        break

                    await asyncio.sleep(0.2)

            except Exception as e:
                self.log(f"解析 JSON 或改写表单失败: {e}")
                print(f"异常，原始输出: {ai_output}")
                return

            self.log(f"当前页码：{num}，本次任务已完成。")
            end_time = time.perf_counter()
            self.log(f"本次任务耗时：{end_time - start_time:.2f}秒")
            self.log("=" * 30)

            if num != -1 and num == final_num:
                self.stop.set()
                self.log("当前列表处理结束。")
            elif num == -1:
                self.stop.set()
                self.log("单题处理结束。")

            if self.stop.is_set():
                self.log("***※已终止※***")
                return

            await asyncio.sleep(0.2)

    # ── page helpers ──

    async def _choices_screenshot(self):
        script_path = os.path.dirname(os.path.abspath(__file__))
        try:
            problem_sn = await self.page_1.locator("td:nth-child(2) > a:nth-child(2)").first.inner_text()
        except Exception as e:
            self.log(f"***※未能找到题目SN※***: {e}")
            self.stop.set()
            return None

        try:
            choices_locator = self.page_1.locator("table.qanwser")
            if await choices_locator.count() > 0:
                self.log("2.1 正在截图题目...")
                save_path = script_path + f"{problem_sn}_problem_choices.png"
                clone_handle = await choices_locator.evaluate_handle("""original => {
                    const clone = original.cloneNode(true);
                    Object.assign(clone.style, {
                        position: 'absolute', top: '0', left: '0', width: 'auto',
                        height: 'auto', maxHeight: 'none', overflow: 'visible',
                        zIndex: '2147483647', backgroundColor: '#ffffff', padding: '20px'
                    });
                    document.body.appendChild(clone);
                    return clone;
                }""")
                await clone_handle.screenshot(path=save_path)
                await clone_handle.evaluate("el => el.remove()")
                return save_path
            else:
                self.log("※非选择题※")
                return ""
        except Exception as e:
            self.log(f"***※选项截图失败※***: {e}")
            self.stop.set()
            return None

    def _encode_base64(self, img_path: str) -> str:
        if not img_path:
            return ''
        try:
            with open(img_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            self.log(f"文件读取错误: {e}")
            return ''

    async def _problem_ocr(self, content_payload) -> str:
        if os.getenv("QWEN_API_KEY") == '1':
            self.log("请引入QwenAPI。")
            return ""
        text = await self.analyser.call_analyser(content_payload, '99')
        return text

    async def _copy_problem(self) -> str:
        problem_sn = await self.page_1.locator("td:nth-child(2) > a:nth-child(2)").first.inner_text()
        try:
            await self.page_1.locator("div#Content_" + problem_sn).click()
            await self.page_1.wait_for_timeout(200)
            await self.page_1.locator("input.code").click()
            await self.page_1.wait_for_timeout(200)
            iframe = self.page_1.frame_locator("#htmlSourceFrame")
            textarea = iframe.locator("textarea#htmlSource")
            await textarea.click()
            await self.page_1.keyboard.press("Control+A")
            await self.page_1.keyboard.press("Control+C")
            content = pyperclip.paste()
            await self.page_1.locator("input.hclose:nth-child(2)").click()
            await self.page_1.wait_for_timeout(200)
            return content
        except Exception as e:
            self.log(f"搜索复制失败: {e}")
            self.stop.set()
            return ""

    # ── AI ──

    async def _analyze_keypoint(self, problem_text: str, choices_text: str) -> str:
        self.log("正在调用 AI API...")
        instruction = self.sys_instruct_AI()
        combined = f" keypoint_table:{self.keypoint_table()}\n problem：{problem_text}\n {choices_text}\n"
        return await self.analyser.call_analyser(combined, self._user_input, instruction)

    # ── form ──

    def _formatize_ai_output2json(self, ai_output: str) -> str:
        text = ai_output
        text = text.replace("```", "")
        text = text.replace("json\n", "")
        text = text.replace("\\", "\\\\")
        text = text.replace(" ", "")
        text = text.replace("【", "")
        text = text.replace("】", "")
        text = text.replace(">", "＞")
        text = text.replace("<", "＜")
        return text

    async def _fill_forms(self, data: dict):
        problem_sn = await self.page_1.locator("td:nth-child(2) > a:nth-child(2)").first.inner_text()
        try:
            if data["keypoint"]["s"] == "0":
                while(await self.page_1.locator("li:nth-child(1) > i > img").is_visible()):
                    await self.page_1.locator("li:nth-child(1) > i > img").click()
                with open("datas/keypoint_table_referencing.1.md", "r", encoding="utf-8") as f:
                    keypoint_dict_origin = dict(line.strip().split(':', 1) for line in f if line.strip())
                    keypoint_dict_reversed = {key: value for value, key in keypoint_dict_origin.items()}
                    suggested_keypoint_num_list = []
                    try:
                        for suggested_keypoint, weight in data["keypoint"]["msg"]["keypoint_list"].items():
                            if float(weight) >= 0.85:
                                suggested_keypoint_num_list.append(keypoint_dict_reversed[suggested_keypoint])
                        # 按长度降序排序（长串在前）
                        sorted_kp = sorted(suggested_keypoint_num_list, key=len, reverse=True)
                        deparent_result = []
                        for i, s in enumerate(sorted_kp):
                            # 检查当前字符串是否是前面某个更长字符串的前缀
                            is_prefix = any(sorted_kp[j].startswith(s) for j in range(i))
                            if not is_prefix:
                                deparent_result.append(s)                      
                        for keypoint_num in deparent_result:        
                            await self.page_1.locator("input#Point").fill(keypoint_num)
                            await self.page_1.keyboard.down("Enter")
                        await self.page_1.locator("input#Point").fill(keypoint_dict_reversed[data["keypoint"]["msg"]["keypoint_first"]])
                        await self.page_1.keyboard.down("Enter")
                    except Exception as e:
                        self.log(f"{e}")
                        print(e)
        except Exception as e:
            self.log("***※【考点】填表异常※***")
            self.log(str(e))
            self.stop.set()

        self.log("填写完成。")

    async def _submit(self):
        try:
            await self.page_1.get_by_role('button', name='提交').first.click()
        except Exception as e:
            self.log("***※提交异常※***")
            print(e)
            self.stop.set()

    async def _save(self):
        try:
            await self.page_1.get_by_role('button', name='保存').first.click()
        except Exception as e:
            self.log("***※保存异常※***")
            print(e)
            self.stop.set()

    async def _refresh(self):
        try:
            await self.page_1.get_by_role('link', name='刷新页面').first.click()
        except Exception as e:
            self.log("***※刷新异常※***")
            print(e)
            self.stop.set()

    async def _next(self):
        try:
            await self.page_1.get_by_role('link', name='下一页').first.click()
        except Exception as e:
            self.log("***※前进翻页异常※***")
            print(e)
            self.stop.set()

    async def _previous(self):
        try:
            await self.page_1.get_by_role('link', name='上一页').first.click()
        except Exception as e:
            self.log("***※后退翻页异常※***")
            print(e)
            self.stop.set()

