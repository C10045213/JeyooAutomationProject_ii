import AI_analyse_V1 as analyser
import regex_formatting as refmt
import os
import pyperclip
import base64
import re
from playwright.async_api import Page
import json
import threading
import asyncio
import time


class MonoQualityCheckStep2Concurrent():
    """分别复审并发版"""

    def __init__(self, log_callback, result_callback, input_num_for_AI: str, stop_signal: threading.Event):
        self.log = log_callback
        self.result = result_callback
        self.stop = stop_signal
        self.analyser = analyser.AsyncAnalyser(stop_event=self.stop)
        self._user_input = input_num_for_AI
        self.page_1: Page = None

        self.input_dataset: dict = {}
        self.taskcounts = 5
        self.output_dataset: dict = {}
        self._ordered_sns: list = []

        self._fill_requested = threading.Event()
        self._fill_lock = asyncio.Lock()
        self._save_composite_requested = threading.Event()
        self._save_composite_lock = asyncio.Lock()
        self._save_func = [self._save]
        self._auto_fill_enabled = False
        self._selected_forms = {"problem", "keypoint", "keypoint_plus", "analysis", "discuss", "difficulty", "answer"}

    # ── 外部调用接口 ──

    def request_fill(self):
        if not self._auto_fill_enabled:
            self._fill_requested.set()
            self.log("收到填充指令...")

    def request_save_composite(self):
        self._save_composite_requested.set()
        self.log("收到保存指令...")

    def set_save_mode(self, mode):
        action_map = {
            0: [self._save],
            1: [self._save, self._next],
            2: [self._save, self._previous],
            3: [self._save, self._refresh]
        }
        self._save_func = action_map.get(mode, [self._save])
        mode_names = {0: "仅保存", 1: "保存并下一页", 2: "保存并上一页", 3: "保存并刷新"}
        self.log(f"保存模式已更新: {mode_names.get(mode, '模式设置异常')}")

    def set_auto_fill(self, enabled: bool):
        self._auto_fill_enabled = enabled
        status = "启用" if enabled else "禁用"
        self.log(f"自动填充已{status}")

    def set_selected_forms(self, forms: set):
        self._selected_forms = forms
        self.log(f"表单选择已更新: {forms}")

    def set_taskcounts(self, n: int):
        self.taskcounts = n
        self.log(f"当前批次处理数量已设置为: {n}")

    def sys_instruct_AI(self):
        with open("prompts/task2_sys_instruct_mono.txt", 'r', encoding='utf-8') as f:
            return f.read().strip()

    def keypoint_table(self):
        with open("datas/keypoint_table_referencing.md", 'r', encoding = 'utf-8') as f:
            return f.read().strip()

    async def locate_pages(self, pages):
        for page in pages:
            try:
                if await page.locator("input#SStatus_3").is_visible():
                    self.page_1 = page
                    self.log(f"已锁定题目全修改页面: {await page.title()}")
            except Exception:
                self.log("页面定位异常。")
        if not self.page_1:
            self.log("!!! 警告: 未找到题目全修改页面")

    # ── 数据采集（借鉴 task2 的批量采集模式） ──

    async def _get_current_sn(self):
        try:
            await asyncio.sleep(0.5)
            return await self.page_1.locator("td:nth-child(2) > a:nth-child(2)").first.inner_text(timeout=2000)
        except Exception:
            return ""

    async def collect_onepage_data(self):
        if self.page_1 is None:
            self.log("页面未定位，非法操作。")
            return ("", "")

        if not await self.page_1.locator("input#SStatus_3").is_visible():
            self.log("非目标页面，请重连。")
            return ("", "")

        if self.page_1.is_closed():
            self.log("***※目标页面已关闭※***")
            return ("", "")

        if await self.page_1.locator("div#_messsage").is_visible():
            await self.page_1.locator("div#_messsage").click()

        sn = await self._get_current_sn()
        if not sn:
            self.log("***※未能获取SN※***")
            return ("", "")

        self.log(f"当前题目SN: {sn}")
        self.log(".../正在获取题目信息")

        choices_img = await self._choices_screenshot()
        if choices_img is not None and choices_img != '':
            self.log("../正在对题目选项进行OCR...")
            choices_pic64 = self._encode_base64(choices_img)
            content_payload = []
            content_payload.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{choices_pic64}"}})
            choices_text = await self._problem_ocr(content_payload)
            if choices_text == '' or type(json.loads(choices_text)) == list:
                self.log("请求超时(300s)，或识图失败。")
                choices_text = '{"OCR_Result": "OCR_Failed"}'
            choices_text = json.loads(choices_text)["OCR_Result"]
            try:
                if os.path.exists(choices_img):
                    os.remove(choices_img)
            except Exception as e:
                self.log(f"清理截图文件失败: {e}")
        else:
            choices_text = ''

        problem_text = refmt.process_text(await self._copy_problem())
        keypoint_text = refmt.process_text(await self._copy_keypoint())
        answer_text = refmt.process_text(await self._copy_answer())
        analysis_text = refmt.process_text(await self._copy_analyse())
        discuss_text = refmt.process_text(await self._copy_discuss())

        self.log(f"✔️本页题目信息获取完成")
        return (sn, {
            "problem": problem_text,
            "choices_text": choices_text,
            "answer": answer_text,
            "keypoint": keypoint_text,
            "analysis": analysis_text,
            "discuss": discuss_text
        })

    async def gather_alldata(self, totalnum):
        self.input_dataset = {}
        self.output_dataset = {}
        self._ordered_sns = []

        if self.page_1 is None:
            self.log("页面未定位，非法操作。")
            return ""

        if not await self.page_1.locator("input#SStatus_3").is_visible():
            self.log("非目标页面，请重连。")
            return ""

        if self.page_1.is_closed():
            self.log("***※目标页面已关闭※***")
            return ""

        try:
            init_num_str = await self.page_1.locator(".tablebar:nth-child(2) > h2 > input").input_value()
            num_limit_str = await self.page_1.locator(".tablebar:nth-child(2) span").inner_text()
            init_num = int(init_num_str)
            num_limit = int(num_limit_str)
            final_num = min(num_limit, init_num + totalnum - 1)
            self.log(f"批次尾页页码为{final_num}")
            self.log(f"即将处理{final_num - init_num + 1}条数据，期间请勿对页面进行操作")
        except Exception as e:
            self.log("***确认页码范围错误***")
            self.log(f"{e}")
            return ""

        index = init_num
        for _ in range(init_num, final_num + 2):
            if self.stop.is_set():
                self.log("***※采集已终止※***")
                return ""

            await asyncio.sleep(0.5)

            if index <= final_num:
                sn, data = await self.collect_onepage_data()
                await self._next()
                index = index + 1
            else:
                self.log("当前序列采集完成。")
                await self.page_1.locator(".tablebar:nth-child(2) > h2 > input").fill(init_num_str)
                await asyncio.sleep(0.1)
                await self.page_1.press(".tablebar:nth-child(2) > h2 > input", "Enter")
                await asyncio.sleep(0.1)
                break

            if data == "":
                self.log("***获取题目数据出现异常，任务终止***")
                return ""

            self.input_dataset[sn] = data
            self._ordered_sns.append(sn)

        return 1

    # ── 并发 AI 分析（monoTask2 单次调用方式，并发执行） ──

    async def single_analyse(self, sn, data: dict):
        if data["problem"] == "":
            return "本题略过。"

        ai_output = await self._analyze_answer(
            data["problem"],
            data["choices_text"],
            data["analysis"],
            data["answer"],
            data["discuss"],
            data["keypoint"]
        )

        if ai_output == '':
            return "AI分析失败"

        try:
            formatted = self._formatize_ai_output2json(ai_output)
            parsed = json.loads(formatted)
            return parsed
        except Exception as e:
            self.log(f"SN={sn} 解析AI输出失败: {e}")
            print(f"异常，原始输出: {ai_output}")
            return "解析失败"

    async def total_analyse(self):
        if not self.input_dataset:
            self.log("***采集数据过程异常，请联系调试***")
            return ""

        try:
            self.log(".../开始并发AI分析.../")
            async_tasks = [self.single_analyse(sn, self.input_dataset[sn]) for sn in self._ordered_sns]
            raw_results = await asyncio.gather(*async_tasks, return_exceptions=True)

            for sn, r in zip(self._ordered_sns, raw_results):
                self.output_dataset[sn] = r if not isinstance(r, Exception) else "本题处理异常"

            failed = sum(1 for r in raw_results if isinstance(r, Exception))
            if failed:
                self.log(f"***※ {failed}/{len(raw_results)} 条并发处理失败 ※***")
            return 1
        except Exception as e:
            self.log("***并发调用API出现错误***")
            self.log(f"{e}")
            return ""

    # ── 主执行流程 ──

    async def execute(self):
        if self.page_1 is None:
            self.log("页面未定位，非法操作。")
            return

        if not await self.page_1.locator("input#SStatus_3").is_visible():
            self.log("非目标页面，请重连。")
            return

        if self.page_1.is_closed():
            self.log("***※目标页面已关闭※***")
            return

        if self.stop.is_set():
            self.log("***※已终止※***")
            return

        if await self.page_1.locator(".tablebar:nth-child(2) > h2 > input").is_visible():
            pagenum_lowerlimit_str = await self.page_1.locator(".tablebar:nth-child(2) > h2 > input").input_value()
            pagenum_lowerlimit = int(pagenum_lowerlimit_str)
            pagenum_outer_truelimit = int(await self.page_1.locator(".tablebar:nth-child(2) span").inner_text())
            pagenum_upperlimit = min(pagenum_outer_truelimit, pagenum_lowerlimit + self.taskcounts - 1)
        else:
            self.log("***※并发模式不支持仅一题※***")
            return

        # Phase 1: 批量采集
        time_origin = time.perf_counter()
        info_gathered = await self.gather_alldata(self.taskcounts)
        if info_gathered != 1:
            self.log("***采集信息失败***")
            return

        # Phase 2: 并发 AI 分析
        info_processed = await self.total_analyse()
        if info_processed != 1:
            self.log("***处理信息失败***")
            return

        time_ender = time.perf_counter()
        self.log(f"本批次处理耗时：{time_ender - time_origin:.2f}秒")

        # Phase 3: 逐页展示结果
        previous_sn = ""
        tobefilled: dict = {}

        while not self.stop.is_set():
            if self.stop.is_set():
                self.log("***※已终止※***")
                return
            
            current_sn = await self._get_current_sn()

            # 检查页码范围
            try:
                current_pagenum = int(await self.page_1.locator(".tablebar:nth-child(2) > h2 > input").input_value())
            except Exception:
                current_pagenum = pagenum_lowerlimit

            if current_pagenum < pagenum_lowerlimit or current_pagenum > pagenum_upperlimit:
                self.result("当前页面超范围")
                previous_sn = current_sn
                await asyncio.sleep(0.1)
                continue

            # 展示当前题目的 AI 结果
            if current_sn in self.output_dataset:
                output_data = self.output_dataset[current_sn]
                self.result(f"```json\n" + json.dumps(output_data, indent=2, ensure_ascii=False) + "\n```")
                input_data = self.input_dataset.get(current_sn, {})

                if isinstance(output_data, str):
                    self.result(f"当前SN：{current_sn}\n{output_data}")
                    tobefilled = {}
                else:
                    output: str = ""
                    output += f"当前SN：{current_sn}\n"

                    if "problem" in self._selected_forms and output_data.get("problem", {}).get("s") == '0':
                        output += "**题目**有误, 请参照msg修改或检查ocr。\n"

                    if "keypoint" in self._selected_forms and output_data.get("keypoint", {}).get("s") == '0':
                        output += "**考点**有误, 请参照msg修改。\n"
                        combined = input_data.get("problem", "") + "\n" + input_data.get("choices_text", "")
                        pyperclip.copy(combined + "\n")
                        output += "※" * 14 + "\n"
                        output += "※※※已复制至剪切板。※※※\n"
                        output += "※" * 14 + "\n"

                    if "answer" in self._selected_forms and output_data.get("answer", {}).get("s") == '0':
                        output += "**解答**有误, 请参照msg自行或复制与AI修改。\n"
                        output += "*" * 20 + "\n"
                        combined = input_data.get("problem", "") + "\n" + input_data.get("choices_text", "") + "\n" + input_data.get("answer", "")
                        output += combined + "\n"
                        pyperclip.copy(combined + "\n" + "审阅此解答")
                        output += "※" * 14 + "\n"
                        output += "※※※已复制至剪切板。※※※\n"
                        output += "※" * 14 + "\n"

                    if ("analysis" in self._selected_forms or "discuss" in self._selected_forms) and (output_data.get("analysis",{}).get("s") == '0' or output_data.get("discuss",{}).get("s") == '0'):
                        output += (f"**分析或点评**为略或有误，请参考msg修改。")

                    self.log(output)
                    tobefilled = output_data
            else:
                self.result("当前题目不在本批次中")
                tobefilled = {}

            # 等待填写
            is_filled = False

            previous_sn = current_sn
            while tobefilled != {} and current_sn == previous_sn:
                if self._auto_fill_enabled and tobefilled:
                    if not is_filled:
                        await self._fill_forms(tobefilled)
                        is_filled = True

                if self._fill_requested.is_set():
                    self._fill_requested.clear()
                    if not is_filled and tobefilled:
                        async with self._fill_lock:
                            await self._fill_forms(tobefilled)
                            is_filled = True
                    elif is_filled:
                        self.log("内容已填入。")

                if self._save_composite_requested.is_set():
                    self._save_composite_requested.clear()
                    async with self._save_composite_lock:
                        for save_related_func in self._save_func:
                            await save_related_func()
                            await asyncio.sleep(1)
                        
                        if await self.page_1.locator("div#_messsage").is_visible(timeout=1000):
                            await self.page_1.locator("div#_messsage").click()
                        if await self.page_1.locator("div#_messsage").is_visible(timeout=1000):
                            await self.page_1.locator("div#_messsage").click()
                
                await asyncio.sleep(0.5)
                current_sn = await self._get_current_sn()
                continue
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

    async def _copy_answer(self) -> str:
        problem_sn = await self.page_1.locator("td:nth-child(2) > a:nth-child(2)").first.inner_text()
        try:
            await self.page_1.locator("div#Method_" + problem_sn).click()
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

    async def _copy_discuss(self) -> str:
        problem_sn = await self.page_1.locator("td:nth-child(2) > a:nth-child(2)").first.inner_text()
        try:
            return await self.page_1.locator("div#Discuss_" + problem_sn).first.inner_text()
        except Exception as e:
            self.log(f"搜索复制失败: {e}")
            self.stop.set()
            return ""
    
    async def _copy_analyse(self) -> str:
        problem_sn = await self.page_1.locator("td:nth-child(2) > a:nth-child(2)").first.inner_text()
        try:
            return await self.page_1.locator("div#Analyse_" + problem_sn).first.inner_text()
        except Exception as e:
            self.log(f"搜索复制失败: {e}")
            self.stop.set()
            return ""

    async def _copy_keypoint(self) -> str:
        unformatted = await self.page_1.locator("tbody:nth-child(2) > tr:nth-child(3) > td:nth-child(2)").first.inner_text()
        formatted = re.sub(r'\d+：', '', unformatted).strip()
        formatted = re.sub(r'\n+', ',', formatted)
        return formatted

    # ── AI ──

    async def _analyze_answer(self, problem_text: str, choices_text: str, analysis_text: str, answer_text: str, discuss_text: str, keypoint_text: str) -> str:
        self.log("正在调用 AI API...")
        instruction = self.sys_instruct_AI()
        if self._selected_forms == ["keypoint", "keypoint_plus"]:
            combined = f" keypoint_table:{self.keypoint_table()}\n keypoint：{keypoint_text}\n problem：{problem_text}\n"
        elif "keypoint_plus" in self._selected_forms:
            combined = f" keypoint_table:{self.keypoint_table()}\n keypoint：{keypoint_text}\n problem：{problem_text}\n {choices_text}\n analysis：{analysis_text}\n answer：{answer_text}\n discuss：{discuss_text}"
        elif "keypoint" in self._selected_forms:
            combined = f" problem：{problem_text}\n {choices_text}\n keypoint：{keypoint_text}\n analysis：{analysis_text}\n answer：{answer_text}\n discuss：{discuss_text}\n"
        else:
            combined = f" problem：{problem_text}\n {choices_text}\n analysis：{analysis_text}\n answer：{answer_text}\n discuss：{discuss_text}\n"
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
            if "analysis" in self._selected_forms and data["analysis"]["s"] == '0':
                analysis_text = data["analysis"]["msg"].replace("。", "。\n")
                analysis_text = analysis_text.replace("\\\\", "\\")
                await self.page_1.locator("div#Analyse_" + problem_sn).click()
                await self.page_1.wait_for_timeout(200)
                await self.page_1.locator("input.code").click()
                await self.page_1.wait_for_timeout(200)
                iframe = self.page_1.frame_locator("#htmlSourceFrame")
                textarea = iframe.locator("textarea#htmlSource")
                await textarea.fill(analysis_text)
                await iframe.locator("div:nth-child(3) > input:nth-child(3)").click()
                await self.page_1.wait_for_timeout(200)
        except Exception as e:
            self.log("***※【分析】填表异常※***")
            self.log(str(e))
            self.stop.set()

            # 填写点评与难度
        try:
            if "discuss" in self._selected_forms and data["discuss"]["s"] == '0':
                discuss_text = data["discuss"]["msg"].replace("。", "。\n")
                discuss_text = discuss_text.replace("\\\\", "\\")
                await self.page_1.locator("div#Discuss_" + problem_sn).fill(discuss_text)
                await self.page_1.wait_for_timeout(200)
        except Exception as e:
            self.log("***※【点评】填表异常※***")
            self.log(str(e))
            self.stop.set()

        try:
            if "difficulty" in self._selected_forms:
                await self.page_1.locator("input#Degree_" + problem_sn + "_" + str(data["difficulty"])).click()
        except Exception as e:
            self.log("***※【难度】填表异常※***")
            self.log(str(e))
            self.stop.set()
        
        try:
            if "answer" in self._selected_forms and data["answer"]["s"] == '0':
                await self.page_1.locator("div#Method_" + problem_sn).click()
                await self.page_1.wait_for_timeout(200)
                await self.page_1.locator("input.code").click()
                await self.page_1.wait_for_timeout(200)
                iframe = self.page_1.frame_locator("#htmlSourceFrame")
                textarea = iframe.locator("textarea#htmlSource")
                method_text = self.input_dataset[problem_sn]["answer"]

                if data["answer"]["msg"]["type"] == "简单错误":
                    msg = data["answer"]["msg"]
                    temp_replacing = dict(zip(msg["locator"].values(), msg["correction"].values()))
                    for loc, corr in temp_replacing.items():
                        loc = loc.replace("\\\\", "\\")
                        corr = corr.replace("\\\\", "\\")
                        method_text = method_text.replace(loc, corr)
                    await textarea.fill(method_text)
                elif data["answer"]["msg"]["type"] == "严重错误":
                    pass

                await iframe.locator("div:nth-child(3) > input:nth-child(3)").click()
                await self.page_1.wait_for_timeout(200)
        except Exception as e:
            self.log("***※【解答】填表异常※***")
            self.log(str(e))
            self.stop.set()

        try:
            # 修改考点
            if "keypoint_plus" in self._selected_forms and data["keypoint"]["s"] == "0":
                while(await self.page_1.locator("li:nth-child(1) > i > img").is_visible()):
                    await self.page_1.locator("li:nth-child(1) > i > img").click()
                with open("datas/keypoint_table_referencing.1.md", "r", encoding="utf-8") as f:
                    keypoint_dict_origin = dict(line.strip().split(':', 1) for line in f if line.strip())
                    keypoint_dict_reversed = {key : value for value, key in keypoint_dict_origin.items()}
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

    async def _save(self):
        try:
            await self.page_1.get_by_role('button', name='保存').first.click()
        except Exception as e:
            self.log("***※保存异常※***")
            print(e)
            self.stop.set()

    async def _refresh(self):
        try:
            await self.page_1.get_by_role('link', name='刷新数据').first.click()
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
