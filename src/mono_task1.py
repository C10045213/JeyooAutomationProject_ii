import AI_analyse_V1 as analyser
import regex_formatting as refmt
import os,time,json
import pyperclip
import base64
import threading
from playwright.async_api import Page


class MonoQualityCheckStep1():
    """单发审题逻辑"""

    def __init__(self, log_callback, result_callback, input_num_for_AI: str, stop_signal: threading.Event):
        self.log = log_callback
        self.result = result_callback
        self.stop = stop_signal
        self.analyser = analyser.AsyncAnalyser(stop_event=self.stop)
        self._user_input = input_num_for_AI
        self.page_1: Page = None
        self.page_2: Page = None

    def sys_instruct_AI(self):
        with open("prompts/task1_sys_instruct_mono.txt", 'r', encoding='utf-8') as f:
            return f.read().strip()

    async def locate_pages(self, pages):
        for page in pages:
            try:
                if await page.locator("div.box-wrapper").is_visible(timeout=100):
                    self.page_1 = page
                    self.log(f"已锁定题目页面: {await page.title()}")
                elif await page.locator("label:nth-child(34)").is_visible(timeout=100):
                    self.page_2 = page
                    self.log(f"已锁定搜索页面: {await page.title()}")
            except Exception as e:
                self.log(f"页面定位异常。")
                self.log({e})

        if not self.page_1:
            self.log("!!! 警告: 未找到题目页面。")
        if not self.page_2:
            self.log("!!! 警告: 未找到搜索页面。")

    async def execute(self):
        if self.page_1 is None or self.page_2 is None:
            self.log("页面未定位，非法操作。")
            return

        if not await self.page_1.locator("div.box-wrapper").is_visible(timeout=100) or \
           not await self.page_2.locator("label:nth-child(34)").is_visible(timeout=100):
            self.log("非目标页面，请重连。")
            return

        if self.page_1.is_closed() or self.page_2.is_closed():
            self.log("***※目标页面已关闭※***")
            return

        if self.stop.is_set():
            self.log("***※已终止※***")
            return

        self.log("\n>>> 开始执行单发任务...")
        start_time = time.perf_counter()

        # 1. 截图
        self.log("1. 正在截图题目...")
        imgs = await self._problem_screenshot()
        if imgs is None:
            self.log("！！！截图失败！！！")
            return

        self.log("2. 正在获取答案...")
        answer0 = await self._jump_and_search_copy_and_return()
        answer = refmt.process_text(answer0)

        # 2. OCR
        self.log("3. 调用多模态LLM进行 OCR...")
        content_payload = self._pic2base64(imgs)
        if content_payload is None:
            return

        problem_alltext = await self._problem_ocr(content_payload)
        if problem_alltext == '' or type(json.loads(problem_alltext)) == list:
            self.log("请求超时(300s)，或识图失败。")
            problem_alltext = '{"OCR_Result": ""}'
        problem_alltext = json.loads(problem_alltext)["OCR_Result"]

        # 3. 审核
        self.log("4. 提交与 AI 审核...")
        ai_output = await self._analyze_answer(problem_alltext, answer)

        if ai_output != '':
            self.result(ai_output)
        else:
            self.stop.set()
            self.log("请求返回response超时(300s)")

        end_time = time.perf_counter()

        self.log(f"本次单发任务已完成。耗时{end_time - start_time:.2f}秒")
        self.log('=' * 30)

    # ── helpers ──

    async def _problem_screenshot(self):
        script_path = os.path.dirname(os.path.abspath(__file__))
        try:
            problem_sn_locator = self.page_1.locator("td > a:nth-child(2)")
            await problem_sn_locator.wait_for(state="visible", timeout=10000)
            problem_sn = await problem_sn_locator.inner_text()
            self.log(f"当前题目SN: {problem_sn}")
        except Exception as e:
            self.log(f"***※未能找到题目SN※***: {e}")
            return None

        save_path_choices = ""
        save_path_problem = ""
        try:
            choices_locator = self.page_1.locator("table.ques").first
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

        try:
            problem_locator = self.page_1.locator("div#Mark_Content_" + problem_sn)
            await problem_locator.wait_for(state="visible", timeout=10000)
            save_path_problem = script_path + f"{problem_sn}_problem.png"
            clone_handle = await problem_locator.evaluate_handle("""original => {
                const clone = original.cloneNode(true);
                Object.assign(clone.style, {
                    position: 'absolute', top: '0', left: '0', width: 'auto',
                    height: 'auto', maxHeight: 'none', overflow: 'visible',
                    zIndex: '2147483647', backgroundColor: '#ffffff', padding: '20px'
                });
                document.body.appendChild(clone);
                return clone;
            }""")
            await clone_handle.screenshot(path=save_path_problem)
            await clone_handle.evaluate("el => el.remove()")
        except Exception as e:
            self.log(f"题目截图错误: {e}")

        return (save_path_choices, save_path_problem)

    async def _jump_and_search_copy_and_return(self):
        if not self.page_2:
            return "无法获取第二页面"
        problem_sn = await self.page_1.locator("td > a:nth-child(2)").first.inner_text()
        try:
            await self.page_2.bring_to_front()
            await self.page_2.locator("input#SName").fill(problem_sn)
            await self.page_2.wait_for_timeout(300)
            await self.page_2.locator("input#SSearch").click()
            await self.page_2.locator("div#Method_" + problem_sn).click()
            await self.page_2.locator("input.code").click()
            iframe = self.page_2.frame_locator("#htmlSourceFrame")
            textarea = iframe.locator("textarea#htmlSource")
            await textarea.click()
            await self.page_2.wait_for_timeout(300)
            await self.page_2.keyboard.press("Control+A")
            await self.page_2.keyboard.press("Control+C")
            answer = pyperclip.paste()
            await self.page_2.locator("input.hclose:nth-child(2)").click()
            await self.page_1.bring_to_front()
            return answer
        except Exception as e:
            self.log(f"搜索复制失败: {e}")
            await self.page_1.bring_to_front()
            return ""

    def _pic2base64(self, picpath: tuple) -> list:
        choices_path, problem_path = picpath
        content_payload = []
        try:
            with open(problem_path, "rb") as f:
                problem_base64 = base64.b64encode(f.read()).decode("utf-8")
            if choices_path:
                with open(choices_path, "rb") as f:
                    choices_base64 = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            self.log(f"文件读取错误: {e}")
            return None

        # content_payload.append({"type": "text", "text": '#Task：根据所给出的题目的部分截图，按照格式要求仅输出识别内容。#OutputFormat(JSON)：{"OCR_Result":""} #InputData：'})
        content_payload.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{problem_base64}"}})
        if choices_path:
            content_payload.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{choices_base64}"}})

        try:
            if os.path.exists(problem_path):
                os.remove(problem_path)
            if choices_path and os.path.exists(choices_path):
                os.remove(choices_path)
        except Exception as e:
            self.log(f"清理截图文件失败: {e}")

        return content_payload

    async def _problem_ocr(self, base64pic_contentpayload) -> str:
        if os.getenv("QWEN_API_KEY") == '1':
            self.log("请引入QwenAPI。")
            return ""
        text = await self.analyser.call_analyser(base64pic_contentpayload, '99')
        print(text)
        return text

    async def _analyze_answer(self, problem_text: str, answer_text: str) -> str:
        self.log("正在调用 AI API...")
        combined = f"题目内容(可能有误):\n{problem_text}\n\n参考答案:\n{answer_text}\n\n"
        return await self.analyser.call_analyser(combined, self._user_input, self.sys_instruct_AI())
