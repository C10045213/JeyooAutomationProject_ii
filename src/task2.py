import AI_analyse_V1 as analyser
import os
import pyperclip
import base64
import re
from playwright.async_api import Page
import json
import threading
import asyncio
import time

class QualityCheckStep2():
    """全面复审逻辑"""

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

    # 关于填入、保存的外部调用函数
    def request_fill(self):
        if not self._auto_fill_enabled:
            self._fill_requested.set()
            self.log("收到填充指令...")
    
    def request_save_composite(self):
        self._save_composite_requested.set()
        self.log("收到保存/刷新指令...") 

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

    def sys_instruct_AI01(self):
        with open("prompts/01_answer_check.txt", 'r', encoding='utf-8') as f:
            return f.read().strip()
    
    def sys_instruct_AI02(self):
        with open("prompts/02_answer_compare.txt", 'r', encoding='utf-8') as f:
            return f.read().strip()
        
    def sys_instruct_AI03(self):
        with open("prompts/03_keypoint_check.txt", 'r', encoding='utf-8') as f:
            return f.read().strip()
        
    def sys_instruct_AI04(self):
        with open("prompts/04_info_completion.txt", 'r', encoding='utf-8') as f:
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
            except:
                self.log(f"页面定位异常。")
        
        if not self.page_1:
            self.log("!!! 警告: 未找到题目全修改页面")

    async def total_analyse(self):
        '''核心并发调用'''
        if not self.input_dataset:
            self.log(f"***采集数据过程异常，请联系调试***")
            return ""
        try:
            self.log(f".../开始分析.../")
            async_tasks = [self.main_workflow(sn, self.input_dataset[sn]) for sn in self._ordered_sns]
            raw_results = await asyncio.gather(*async_tasks, return_exceptions=True)
            for sn, r in zip(self._ordered_sns, raw_results):
                self.output_dataset[sn] = r if not isinstance(r, Exception) else "本题处理异常"
            failed = sum(1 for r in raw_results if isinstance(r, Exception))
            if failed:
                self.log(f"***※ {failed}/{len(raw_results)} 条并发处理失败 ※***")
            return 1
        except Exception as e:
            self.log(f"***并发调用API出现错误***")
            self.log(str({e}))

    async def main_workflow(self, sn, data: dict):
        check_answer: dict = {
            "problem": {"status": "", "suggestion": ""},
            "answer": {"status": "", "suggestion": ""}
        }
        answer_compare: dict = {"status": "", "formatted_output": "", "anchor": ""}
        info_completion: dict = {"keypoints": "", 
                                 "analysis_status":"", "analysis": "",
                                 "discuss_status":"", "discuss": "",
                                 "difficulty": ""}
        keypoint_check: dict = {"status": "", "suggestion": ""}
        final_output: dict = {
            "problem_status": "", "problem_suggestion": "",
            "answer_status": "", "answer_suggestion": "", "answer_anchor": "",
            "keypoint_status": "", "keypoint_suggestion": "",
            "analysis_status": "", "analysis": "",
            "discuss_status": "", "discuss": "",
            "difficulty": ""
        }

        if data["problem"] == "":
            return "本题略过。"

        # workflow step 1
        step1_payload = "\n problem: " + data["problem"] + "\n answer: " + data["answer"]
        check_answer_json = await self.analyser.call_analyser(step1_payload, self._user_input, self.sys_instruct_AI01())
        check_answer = json.loads(self.formatize_ai_output2json(check_answer_json))

        # workflow step 2
        if check_answer["answer"]["status"] == '0':
            step2_payload = step1_payload + "\n answer_ai: " + check_answer["answer"]["suggestion"]
            answer_compare_json = await self.analyser.call_analyser(step2_payload, self._user_input, self.sys_instruct_AI02())
            answer_compare = json.loads(self.formatize_ai_output2json(answer_compare_json))

        # workflow step 3
        if check_answer["answer"]["status"] == '0':
            step3_payload_0 = "\n problem: " + data["problem"] + "\n answer: " + answer_compare["formatted_output"] + "\n keypoints: " + data["keypoints"]
        else:
            step3_payload_0 = step1_payload + "\n keypoints: " + data["keypoints"]
        if "keypoint_plus" in self._selected_forms:
            step3_payload = step3_payload_0 + "\n keypoint_table: " + self.keypoint_table()
        else:
            step3_payload = step3_payload_0
        keypoint_check_json = await self.analyser.call_analyser(step3_payload, self._user_input, self.sys_instruct_AI03())
        keypoint_check = json.loads(self.formatize_ai_output2json(keypoint_check_json))

        # workflow step 4
        step4_payload = step3_payload_0  + "\n analysis: " + data["analysis"] + "\n discuss: " + data["discuss"] + "\n keypoint_plus: "+ str(keypoint_check["suggestion"])
        info_completion_json = await self.analyser.call_analyser(step4_payload, self._user_input, self.sys_instruct_AI04())
        info_completion = json.loads(self.formatize_ai_output2json(info_completion_json))

        final_output["sn"] = sn
        final_output["problem_status"] = check_answer["problem"]["status"]
        final_output["problem_suggestion"] = check_answer["problem"]["suggestion"]
        if check_answer["answer"]["status"] == "0":
            final_output["answer_status"] = answer_compare["status"] 
        else:
            final_output["answer_status"] = check_answer["answer"]["status"] 
        final_output["answer_suggestion"] = answer_compare["formatted_output"]
        final_output["answer_anchor"] = answer_compare["anchor"]
        final_output["analysis_status"] = info_completion["analysis_status"]
        final_output["analysis"] = info_completion["analysis"]
        final_output["discuss_status"]  = info_completion["discuss_status"]
        final_output["discuss"] = info_completion["discuss"]
        final_output["difficulty"] = info_completion["difficulty"]
        final_output["keypoint_status"] = keypoint_check["status"]
        final_output["keypoint_suggestion"] = keypoint_check["suggestion"]

        return final_output

    async def gather_alldata(self, totalnum):
        '''基于collect_onepage_data()，
        对从当前页面开始之后的所有页面进行信息存储，
        完成存储后，返回整数1。'''

        self.input_dataset = {}
        self.output_dataset = {}
        self._ordered_sns = []

        if self.page_1 == None:
            self.log(f"页面未定位，非法操作。")
            return ""

        if await self.page_1.locator("input#SStatus_3").is_visible() == False:
            self.log(f"非目标页面，请重连。")

        if self.page_1.is_closed():
            self.log(f"***※目标页面已关闭※***")
            return ""

        try:
            init_num_str = await self.page_1.locator(".tablebar:nth-child(2) > h2 > input").input_value(timeout = 500)
            num_limit_str = await self.page_1.locator(".tablebar:nth-child(2) span").inner_text()
            init_num = int(init_num_str)
            num_limit = int(num_limit_str)
            taskcounts = totalnum
            final_num = min(num_limit, init_num + taskcounts - 1)
            self.log(f"批次尾页页码为{final_num}")
            self.log(f"即将处理{final_num - init_num + 1}条数据，期间请勿对页面进行操作")
        except Exception as e:
            self.log(f"***确认页码范围错误***")
            self.log({e})

        index = init_num
        for _ in range(init_num, final_num + 2):
            await asyncio.sleep(0.5)

            if index <= final_num:
                sn, data = await self.collect_onepage_data()
                await self.page_1.locator(".tablebar:nth-child(2) .tedit:nth-child(4)").click()
                index = index + 1
            else:
                self.log(f"当前序列采集完成。")
                await self.page_1.locator(".tablebar:nth-child(2) > h2 > input").fill(init_num_str)
                await asyncio.sleep(0.1)
                await self.page_1.press(".tablebar:nth-child(2) > h2 > input", "Enter")
                await asyncio.sleep(0.1)
                break

            if data == "":
                self.log(f"***获取题目数据出现异常，任务终止***")
                return ""

            self.input_dataset[sn] = data
            self._ordered_sns.append(sn)

        return 1

    async def _get_current_sn(self):
        try:
            return await self.page_1.locator("td:nth-child(2) > a:nth-child(2)").first.inner_text()
        except Exception:
            return ""

    # 单页数据获取
    async def collect_onepage_data(self):
        if self.page_1 == None:
            self.log(f"页面未定位，非法操作。")
            return ("", "")

        if await self.page_1.locator("input#SStatus_3").is_visible() == False:
            self.log(f"非目标页面，请重连。")
            return ("", "")

        if self.page_1.is_closed():
            self.log(f"***※目标页面已关闭※***")
            return ("", "")
        
        if await self.page_1.locator("div#_messsage").is_visible():
            await self.page_1.locator("div#_messsage").click()

        sn = await self._get_current_sn()
        if not sn:
            self.log("***※未能获取SN※***")
            return ("", "")

        self.log(f"当前题目SN: {sn}")
        self.log(".../正在获取题目信息")
        problem_text = await self.copy_problem()

        choices_img = await self.choices_screenshot()
        if choices_img != None:
            self.log(f"../正在对题目选项进行OCR...")
            choices_text = await self.problem_ocr(self.pic2base64(choices_img))
            problem_alltext = problem_text + choices_text
        else:
            problem_alltext = problem_text

        keypoints = await self.copy_keypoint()
        answer = await self.copy_answer()
        analysis = await self.copy_analysis()
        discuss = await self.copy_discuss()

        self.log(f"✔️本页题目信息获取完成")
        return (sn, {"problem": problem_alltext, "answer": answer, "keypoints": keypoints, "analysis": analysis, "discuss": discuss})
    
    async def choices_screenshot(self):
        '''截图题目，返回截图地址'''

        if not self.page_1:
            self.log("目标页面未找到")
            return None

        problem_sn = ""
        save_path_choices = None
        script_path = os.path.dirname(os.path.abspath(__file__))

        try:
            problem_sn = await self.page_1.locator("td:nth-child(2) > a:nth-child(2)").first.inner_text()
        except Exception as e:
            self.log(f"***※未能找到题目SN※***: {e}")
            self.stop.set()

        if problem_sn:
            try:
                choices_locator = self.page_1.locator("table.qanwser")
                if await choices_locator.count() > 0:
                    save_path_choices = script_path + f"{problem_sn}_problem_choices.png"
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
                    await clone_handle.screenshot(path=save_path_choices)
                    await clone_handle.evaluate("el => el.remove()")
                else:
                    self.log("※非选择题※")
            except Exception as e:
                self.log(f"***※选项截图失败※***: {e}")
                self.stop.set()

        return save_path_choices if problem_sn else None
    
    def pic2base64(self, picpath) -> list:
        choices_path = picpath
        content_payload = []
        
        try:
            with open(choices_path, "rb") as f:
                choices_base64 = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            self.log(f"文件读取错误: {e}")

        content_payload.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{choices_base64}"}})
        # 删除截图
        try:
            if os.path.exists(choices_path):
                os.remove(choices_path)
        except Exception as e:
            self.log(f"清理截图文件失败: {e}")

        return content_payload    

    # 强制基于qwenVL的ocr
    async def problem_ocr(self, base64pic_contentpayload) -> str:
        if os.getenv("QWEN_API_KEY") == '1':
            self.log(f"请引入QwenAPI以至少进行图像识别。")
            return ""
        else:
            choice_text = await self.analyser.call_analyser(base64pic_contentpayload, '99')
        # 调试输出文本
        return choice_text

    async def execute(self):
        if self.page_1 is None:
            self.log("页面未定位，非法操作。")
            return

        if await self.page_1.locator("input#SStatus_3").is_visible() == 0:
            self.log("非目标页面，请重连。")
            return

        if self.page_1.is_closed():
            self.log("***※目标页面已关闭※***")
            return

        pagenum_lowerlimit_str = await self.page_1.locator(".tablebar:nth-child(2) > h2 > input").input_value()
        pagenum_lowerlimit = int(pagenum_lowerlimit_str)
        pagenum_outer_truelimit = int(await self.page_1.locator(".tablebar:nth-child(2) span").inner_text())
        pagenum_upperlimit = min(pagenum_outer_truelimit, pagenum_lowerlimit + self.taskcounts - 1)

        time_origin = time.perf_counter()
        info_gathered_flag = await self.gather_alldata(self.taskcounts)
        if info_gathered_flag != 1:
            self.log("***采集信息失败***")
            return

        info_processed_flag = await self.total_analyse()
        if info_processed_flag != 1:
            self.log("***处理信息失败***")
            return
        time_ender = time.perf_counter()
        self.log(f"本批次处理耗时：{time_ender - time_origin:.2f}")

        previous_sn = ""
        tobefilled: dict = {}
        while not self.stop.is_set():
            if self.stop.is_set():
                self.log("***※已终止※***")
                return

            current_sn = await self._get_current_sn()

            # 检查页码范围
            current_pagenum = int(await self.page_1.locator(".tablebar:nth-child(2) > h2 > input").input_value())
            if current_pagenum < pagenum_lowerlimit or current_pagenum > pagenum_upperlimit:
                self.result("当前页面超范围")
                previous_sn = current_sn
                await asyncio.sleep(0.1)
                continue

            if current_sn in self.output_dataset:
                output_data = self.output_dataset[current_sn]
                input_data = self.input_dataset[current_sn]

                output: str = ""
                output = output + f"当前SN：{current_sn} \n"
                if output_data == "本题略过。":
                    output = output + output_data
                else:
                    if output_data["problem_status"] == '0':
                        output = output + "### 题目建议修改：\n"
                        output = output + "```" + output_data["problem_suggestion"] + "```\n"
                    else:
                        output = output + "### 题目合适。\n"

                    output = output + "难度推荐设置为：" + output_data["difficulty"] + "\n"

                    if output_data["keypoint_status"] == '0':
                        output = output + "### 考点建议修改：\n"
                        output = output + "```" + str(output_data["keypoint_suggestion"]) + "```\n"
                    elif output_data["keypoint_status"] == '1':
                        output = output + "### 考点合适。\n"
                    else:
                        output = output + "### 无考点：\n"
                        output = output + output_data["keypoint_suggestion"] + "\n"

                    if output_data["answer_status"] == '0':
                        output = output + "### 解答建议修改：\n"
                        output = output + "```" + output_data["answer_suggestion"] + "```\n"
                        output = output + "#### 理由：\n" + output_data["answer_anchor"] + "\n"
                    else:
                        output = output + "### 解答合适。\n"

                    if output_data["analysis_status"] == '0':
                        output = output + "### 分析建议修改：\n"
                        output = output + "### 分析：\n" + "```"+ output_data["analysis"] + "```\n"
                    else:
                        output = output + "### 分析合适。\n"
                    
                    if output_data["discuss_status"] == '0':
                        output = output + "### 点评建议修改：\n"
                        output = output + "### 点评：\n" + "```"+ output_data["discuss"] + "```\n"
                    else:
                        output = output + "### 点评合适。\n"

                    output = output + "### 原始题目数据：\n"
                    output = output + str(input_data)

                    tobefilled = {
                        "analysis_status": output_data["analysis_status"],
                        "analysis": output_data["analysis"],
                        "discuss_status": output_data["discuss_status"],
                        "discuss": output_data["discuss"],
                        "difficulty": output_data["difficulty"],
                        "answer": output_data["answer_suggestion"],
                        "answer_status": output_data["answer_status"],
                        "keypoint": output_data["keypoint_suggestion"],
                        "keypoint_status": output_data["keypoint_status"]
                    }
                self.result(output)
            else:
                self.result("当前题目不在本批次中")

            is_filled = False
            previous_sn = current_sn
            while tobefilled != {} and current_sn == previous_sn:
                if self._auto_fill_enabled and tobefilled:
                    if not is_filled:
                        await self.fill_forms(tobefilled)
                        is_filled = True

                if self._fill_requested.is_set():
                    self._fill_requested.clear()
                    if not is_filled and tobefilled:
                        async with self._fill_lock:
                            await self.fill_forms(tobefilled)
                            is_filled = True
                    elif is_filled:
                        self.log("内容已填入。")

                if self._save_composite_requested.is_set():
                    self._save_composite_requested.clear()
                    async with self._save_composite_lock:
                        for save_related_func in self._save_func:
                            await save_related_func
                        await asyncio.sleep(1)

                        if await self.page_1.locator("div#_messsage").is_visible(timeout=1000):
                            await self.page_1.locator("div#_messsage").click()
                        if await self.page_1.locator("div#_messsage").is_visible(timeout=1000):
                            await self.page_1.locator("div#_messsage").click()
                
                await asyncio.sleep(0.5)
                current_sn = await self._get_current_sn()
                continue
            await asyncio.sleep(0.2)

    
    # def _formatize_ai_output2json(self, ai_output: str) -> str:
    #     text = ai_output
    #     text = text.replace("```", "")
    #     text = text.replace("json\n", "")
    #     text = text.replace("\\", "\\\\")
    #     text = text.replace(" ", "")
    #     text = text.replace("【", "")
    #     text = text.replace("】", "")
    #     text = text.replace(">", "＞")
    #     text = text.replace("<", "＜")
    #     return text

    def formatize_ai_output2json(self, ai_output: str):
        text = ai_output
        # 去除 markdown 代码块标记
        text = re.sub(r'```(?:json)?\s*\n?', '', text)
        # 提取最外层 JSON 对象
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and start < end:
            text = text[start:end + 1]
        return self._repair_json(text)

    def _repair_json(self, text: str) -> str:
        # 移除不可见字符
        text = re.sub(r'[​‌‍﻿ ]', '', text)
        # 保护尖括号（避免被误认为 HTML）
        text = text.replace(">", "＞").replace("<", "＜")

        # 转义 JSON 字符串值内的反斜杠，防止 LaTeX 命令被 json.loads 误解
        text = self._escape_string_backslashes(text)

        # 统计并补齐缺失的闭合括号
        missing_braces = text.count('{') - text.count('}')
        missing_brackets = text.count('[') - text.count(']')
        if missing_braces > 0 or missing_brackets > 0:
            text = text + ']' * max(0, missing_brackets) + '}' * max(0, missing_braces)

        # 修复缺失的逗号（在转义内部引号之前做，避免误判）
        text = self._fix_missing_commas(text)

        # 修复字符串值内部的未转义双引号
        text = self._escape_inner_quotes(text)

        # 修复字符串值内部的未转义换行/制表符
        text = self._escape_control_chars_in_strings(text)

        # 迭代式修复（多余逗号、非法转义等）
        text = self._iterative_json_repair(text)

        return text

    def _fix_missing_commas(self, text: str) -> str:
        """用正则修复明显缺失的逗号：相邻字符串值之间、值结束后接新键等。"""
        # "..." 后紧跟 "..."（跨行或同行）
        text = re.sub(r'"\s*\n\s*"', '",\n"', text)
        # } 或 ] 后紧跟 "key"
        text = re.sub(r'([}\]])\s*\n\s*"', r'\1,\n"', text)
        # "value" 后紧跟 {（嵌套对象）
        text = re.sub(r'"\s*\n\s*\{', '",\n{', text)
        return text

    def _escape_string_backslashes(self, text: str) -> str:
        """将 JSON 字符串值内的单反斜杠加倍，防止 LaTeX 命令被 json.loads 误解。
        结构性转义 \\\\、\\"、\\/ 保持不变；
        LaTeX 命令如 \\frac、\\sqrt 等的反斜杠会被加倍为 \\\\frac。"""
        result = []
        in_string = False
        i = 0
        n = len(text)
        while i < n:
            c = text[i]
            if c == '"' and (i == 0 or text[i - 1] != '\\'):
                in_string = not in_string
                result.append(c)
            elif in_string and c == '\\':
                if i > 0 and text[i - 1] == '\\':
                    result.append(c)
                elif i + 1 < n and text[i + 1] in '"/\\':
                    result.append(c)
                else:
                    result.append('\\\\')
            else:
                result.append(c)
            i += 1
        return ''.join(result)

    def _escape_inner_quotes(self, text: str) -> str:
        """将 JSON 字符串值内部出现的未转义双引号进行转义。
        通过判断引号前后的非空白字符来确定该引号是结构性的还是内容性的。"""
        result = []
        i = 0
        n = len(text)
        while i < n:
            c = text[i]
            if c == '"':
                # 跳过已转义的引号
                if i > 0 and text[i - 1] == '\\':
                    result.append(c)
                    i += 1
                    continue
                # 向后找到下一个非空白字符
                j = i + 1
                while j < n and text[j] in ' \t\n\r':
                    j += 1
                next_char = text[j] if j < n else ''
                # 向前找到上一个非空白字符
                k = i - 1
                while k >= 0 and text[k] in ' \t\n\r':
                    k -= 1
                prev_char = text[k] if k >= 0 else ''
                # 结构性引号：前面是 { [ , :  或  后面是 : , } ] 或 位于末尾
                is_structural = (
                    prev_char in '{[,:"' or
                    prev_char == '' or
                    next_char in ':},]"' or
                    next_char == ''
                )
                if is_structural:
                    result.append(c)
                else:
                    result.append('\\')
                    result.append(c)
            else:
                result.append(c)
            i += 1
        return ''.join(result)

    def _escape_control_chars_in_strings(self, text: str) -> str:
        """将 JSON 字符串值中的字面换行符和制表符转义。"""
        result = []
        in_string = False
        i = 0
        n = len(text)
        while i < n:
            c = text[i]
            if c == '"' and (i == 0 or text[i - 1] != '\\'):
                in_string = not in_string
                result.append(c)
            elif in_string:
                if c == '\n':
                    result.append('\\n')
                elif c == '\r':
                    result.append('\\r')
                elif c == '\t':
                    result.append('\\t')
                else:
                    result.append(c)
            else:
                result.append(c)
            i += 1
        return ''.join(result)

    def _iterative_json_repair(self, text: str) -> str:
        """基于 json.JSONDecodeError 迭代修复 JSON 结构问题。"""
        max_attempts = 30
        for _ in range(max_attempts):
            try:
                json.loads(text)
                return text
            except json.JSONDecodeError as e:
                pos = e.pos
                msg = e.msg

                if pos >= len(text):
                    missing_braces = text.count('{') - text.count('}')
                    missing_brackets = text.count('[') - text.count(']')
                    text = text + ']' * max(0, missing_brackets) + '}' * max(0, missing_braces)
                    continue

                char = text[pos] if pos < len(text) else ''

                if "Expecting ',' delimiter" in msg:
                    if char == '"':
                        text = text[:pos] + ',' + text[pos:]
                    elif char in 'tfn':  # true/false/null 可能被截断
                        text = text[:pos] + ',' + text[pos:]
                    continue

                if "Expecting value" in msg:
                    if char in ',}]':
                        continue
                    if char == '"':
                        text = text[:pos] + '""' + text[pos:]
                        continue
                    text = text[:pos] + '""' + text[pos:]
                    continue

                if "Expecting property name" in msg or "trailing comma" in msg:
                    if char == '}':
                        comma_pos = text.rfind(',', 0, pos)
                        if comma_pos != -1:
                            text = text[:comma_pos] + text[comma_pos + 1:]
                        continue
                    if char == ',':
                        text = text[:pos] + text[pos + 1:]
                        continue
                    break

                if "Expecting ':' delimiter" in msg:
                    text = text[:pos] + ':' + text[pos:]
                    continue

                if 'Invalid control character' in msg:
                    text = text[:pos] + ' ' + text[pos + 1:]
                    continue

                if 'Unterminated string' in msg:
                    text = text[:pos] + '"' + text[pos:]
                    continue

                if "Invalid \\escape" in msg:
                    escape_pos = text.rfind('\\', 0, pos + 1)
                    if escape_pos != -1:
                        text = text[:escape_pos] + '\\\\' + text[escape_pos + 1:]
                    continue

                if "Extra data" in msg:
                    text = text[:pos]
                    continue

                if "Expecting property name enclosed in double quotes" in msg:
                    if char == "'":
                        text = text[:pos] + '"' + text[pos + 1:]
                        continue
                    break

                # 其他未知错误：尝试在出错位置转义字符
                if char == '"':
                    text = text[:pos] + '\\' + text[pos:]
                    continue

                break

        return text

    async def copy_problem(self):
        problem_sn = await self.page_1.locator("td:nth-child(2) > a:nth-child(2)").first.inner_text()
        
        try:
            # 按页面元素交互逻辑复制
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
    async def copy_answer(self):
        problem_sn = await self.page_1.locator("td:nth-child(2) > a:nth-child(2)").first.inner_text()
        
        try:
            # 按页面元素交互逻辑复制解答
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
        
    # 不对已经填写的分析和点评进行审阅
    # 但需关于分析或点评是否已经填写的标识
    async def copy_discuss(self):
        problem_sn = await self.page_1.locator("td:nth-child(2) > a:nth-child(2)").first.inner_text()
        
        try:
            # 直接获取文本
            content = await self.page_1.locator("div#Discuss_" + problem_sn).first.inner_text()
            return content
        
        except Exception as e:
            self.log(f"搜索复制失败: {e}")
            self.stop.set()
            return ""
        
    async def copy_analysis(self):
        problem_sn = await self.page_1.locator("td:nth-child(2) > a:nth-child(2)").first.inner_text()
        
        try:
            # 直接获取文本
            content = await self.page_1.locator("div#Analyse_" + problem_sn).first.inner_text()
            return content
        
        except Exception as e:
            self.log(f"搜索复制失败: {e}")
            self.stop.set()
            return ""
        
    async def copy_keypoint(self):
        unformatted = await self.page_1.locator("tbody:nth-child(2) > tr:nth-child(3) > td:nth-child(2)").first.inner_text()
        formatted = re.sub(r'\d+：','',unformatted).strip()
        formatted = re.sub(r'\n+',',',formatted)
        return formatted
    
    def fill_formatted(self, ai_output: str) -> str:
        text = ai_output
        text = text.replace("。", "。\n")
        text = text.replace("\\\\", "\\")
        text = text.replace(" ", "")
        text = text.replace("【", "")
        text = text.replace("】", "")
        text = text.replace(">", "＞")
        text = text.replace("<", "＜")
        return text

    async def fill_forms(self, data: dict):
        problem_sn = await self.page_1.locator("td:nth-child(2) > a:nth-child(2)").first.inner_text()

        try:
            if "keypoint" in self._selected_forms and "keypoint_plus" in self._selected_forms and data["keypoint_status"] == '0': 
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

            # 填写分析
            if "analysis" in self._selected_forms and data["analysis_status"] == '0':
                analysis_text = self.fill_formatted(data["analysis"])
                await self.page_1.locator("div#Analyse_" + problem_sn).click()
                await self.page_1.wait_for_timeout(200)
                await self.page_1.locator("input.code").click()
                await self.page_1.wait_for_timeout(200)
                iframe = self.page_1.frame_locator("#htmlSourceFrame")
                textarea = iframe.locator("textarea#htmlSource")
                await textarea.fill(analysis_text)
                await iframe.locator("div:nth-child(3) > input:nth-child(3)").click()
                await self.page_1.wait_for_timeout(200)

            # 填写点评与难度
            if "discuss" in self._selected_forms and data["discuss_status"] == '0':
                discuss_text = self.fill_formatted(data["discuss"])
                await self.page_1.locator("div#Discuss_" + problem_sn).fill(discuss_text)
                await self.page_1.wait_for_timeout(200)
            
            if "difficulty" in self._selected_forms:
                await self.page_1.locator("input#Degree_" + problem_sn + "_" + str(data["difficulty"])).click()

            # 填写解答
            if "answer" in self._selected_forms and data["answer_status"] == '0':
                answer_text = self.fill_formatted(data["answer"])
                await self.page_1.locator("div#Method_" + problem_sn).click()
                await self.page_1.wait_for_timeout(200)
                await self.page_1.locator("input.code").click()
                await self.page_1.wait_for_timeout(200)
                iframe = self.page_1.frame_locator("#htmlSourceFrame")
                textarea = iframe.locator("textarea#htmlSource")
                await textarea.fill(answer_text)
                await iframe.locator("div:nth-child(3) > input:nth-child(3)").click()
                await self.page_1.wait_for_timeout(200)

            self.log(f"{problem_sn}")
            self.log(f"填写完成。")

        except Exception as e:
            self.log(f"***※填表异常※***")
            print(e)
            self.stop.set()
            return
            
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