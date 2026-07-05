import os
from dotenv import load_dotenv
from openai import AsyncOpenAI
from google import genai
import asyncio
import httpx

load_dotenv(override = True)  # 从 .env 文件加载环境变量

class AsyncAnalyser:
    def __init__(self,max_concurrent_calls = 502):

        # httpx 层面强制超时：总超时180s，连接10s，防止 TCP 层面卡死导致 asyncio.wait_for 无法取消
        _httpx_client = httpx.AsyncClient(
            timeout=httpx.Timeout(180.0, connect=10.0),
            limits=httpx.Limits(max_connections=500, max_keepalive_connections=100),
        )

        self.deepseek_model = AsyncOpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
            http_client=_httpx_client,
            max_retries=0
            )

        self.doubao_model = AsyncOpenAI(
            api_key=os.getenv("DOUBAO_API_KEY"),
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            http_client=_httpx_client,
            max_retries=0
            )

        self.gemini_model = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

        self.qwen_model = AsyncOpenAI(
            api_key=os.getenv("QWEN_API_KEY"),
            base_url="https://ws-d6f3io2jewpkyjuw.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            http_client=_httpx_client,
            max_retries=0
            )

        self.github_model = AsyncOpenAI(
            api_key=os.getenv("GITHUB_API_KEY"),
            base_url="https://models.github.ai/inference",
            http_client=_httpx_client,
            max_retries=0
            )
        
        self.semaphore = asyncio.Semaphore(max_concurrent_calls)
        self.model_map = {
            "1": ("deepSeek-v4-flash", self._call_deepseek_flash),
            "2": ("deepSeek-v4-flash(thinking-high)", self._call_deepseek_flash_think_high),
            "3": ("deepSeek-v4-flash(thinking-max)", self._call_deepseek_flash_think_max),
            "4": ("deepSeek-v4-pro", self._call_deepseek_pro),
            "5": ("deepSeek-v4-pro(thinking)", self._call_deepseek_pro_think),
            "6": ("doubao-seed-2-0-lite-260215", self._call_doubao_lite),
            "7": ("doubao-seed-2-0-lite-260215(thinking)", self._call_doubao_lite_think),
            "8": ("doubao-seed-2-0-pro-260215", self._call_doubao_pro),
            "9": ("doubao-seed-2-0-pro-260215(thinking)", self._call_doubao_pro_think),
            "10": ("Google Gemini(flash-latest)", self._call_google_flash),
            "11": ("Google Gemini(pro-latest)", self._call_google_pro),
            "12": ("Qwen3.6-plus", self._call_qwen_flash),
            "13": ("Qwen3.7-plus", self._call_qwen_plus),
            "14": ("ChatGPT(github-4.1mini)", self._call_github_1),
            "99": ("QwenV", self._call_qwenvl)
        }
            
    async def call_analyser(self, content: any, num: str, sys_instruct: str = "") -> str:
        _, call_func = self.model_map.get(num, ("Google Gemini", self._call_google_flash))
        max_retries = 3
        last_error = ""
        for attempt in range(max_retries):
            try:
                async with self.semaphore:
                    result = await asyncio.wait_for(call_func(content, sys_instruct), timeout=100)
                if result:
                    print(result)
                    return result
                last_error = "empty_response"
            except asyncio.TimeoutError:
                last_error = "timeout(100s)"
            except Exception as e:
                last_error = str(e)
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"API 调用失败[{num}](attempt {attempt+1}): {last_error}, {wait}s后重试...")
                await asyncio.sleep(wait)
        print(f"API 调用最终失败[{num}]: {last_error}")
        return ""

    async def _call_deepseek_flash(self, content: str, sys_instruct: str = ""):
        messages = []
        if sys_instruct:
            messages.append({"role": "system", "content": sys_instruct})
        messages.append({"role": "user", "content": content})
        response = await self.deepseek_model.chat.completions.create(
            model="deepseek-v4-flash",
            messages=messages,
            stream = False,
            extra_body={"thinking": {"type": "disabled"}}
        )
        return response.choices[0].message.content
    
    async def _call_deepseek_flash_think_high(self, content: str, sys_instruct: str = ""):
        messages = []
        if sys_instruct:
            messages.append({"role": "system", "content": sys_instruct})
        messages.append({"role": "user", "content": content})
        response = await self.deepseek_model.chat.completions.create(
            model="deepseek-v4-flash",
            messages=messages,
            stream = False,
        )
        return response.choices[0].message.content

    async def _call_deepseek_flash_think_max(self, content: str, sys_instruct: str = ""):
        messages = []
        if sys_instruct:
            messages.append({"role": "system", "content": sys_instruct})
        messages.append({"role": "user", "content": content})
        response = await self.deepseek_model.chat.completions.create(
            model="deepseek-v4-flash",
            messages=messages,
            stream = False,
            extra_body={"reasoning_effort": "max"}
        )
        return response.choices[0].message.content

    async def _call_deepseek_pro(self, content: str, sys_instruct: str = ""):
        messages = []
        if sys_instruct:
            messages.append({"role": "system", "content": sys_instruct})
        messages.append({"role": "user", "content": content})
        response = await self.deepseek_model.chat.completions.create(
            model="deepseek-v4-pro",
            messages=messages,
            stream = False,
            extra_body={"thinking": {"type": "disabled"}}
        )
        return response.choices[0].message.content
    
    async def _call_deepseek_pro_think(self, content: str, sys_instruct: str = ""):
        messages = []
        if sys_instruct:
            messages.append({"role": "system", "content": sys_instruct})
        messages.append({"role": "user", "content": content})
        response = await self.deepseek_model.chat.completions.create(
            model="deepseek-v4-pro",
            messages=messages,
            stream = False,
        )
        return response.choices[0].message.content

    async def _call_doubao_lite(self, content: str, sys_instruct: str = ""):
        messages = []
        if sys_instruct:
            messages.append({"role": "system", "content": sys_instruct})
        messages.append({"role": "user", "content": content})
        kwargs = {
            "model": "doubao-seed-2-0-lite-260215",
            "input": messages,
            "reasoning": {"effort": "minimal"}
        }
        response = await self.doubao_model.responses.create(**kwargs)
        return response.output_text

    async def _call_doubao_lite_think(self, content: str, sys_instruct: str = ""):
        messages = []
        if sys_instruct:
            messages.append({"role": "system", "content": sys_instruct})
        messages.append({"role": "user", "content": content})
        kwargs = {
            "model": "doubao-seed-2-0-lite-260215",
            "input": messages,
            "reasoning": {"effort": "high"}
        }
        response = await self.doubao_model.responses.create(**kwargs)
        return response.output_text

    async def _call_doubao_pro(self, content: str, sys_instruct: str = ""):
        kwargs = {
            "model": "doubao-seed-2-0-pro-260215",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": content
                        }
                    ],
                }
            ],
            "reasoning": {"effort": "minimal"}
        }
        if sys_instruct:
            kwargs["instructions"] = sys_instruct
        response = await self.doubao_model.responses.create(**kwargs)
        return response.output_text
    
    async def _call_doubao_pro_think(self, content: str, sys_instruct: str = ""):
        kwargs = {
            "model": "doubao-seed-2-0-pro-260215",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": content
                        }
                    ],
                }
            ],
            "reasoning": {"effort": "high"}
        }
        if sys_instruct:
            kwargs["instructions"] = sys_instruct
        response = await self.doubao_model.responses.create(**kwargs)
        return response.output_text
        
    async def _call_google_flash(self, content: str, sys_instruct: str = ""):
        kwargs = {
            "model": "gemini-flash-latest",
            "contents": content
        }
        if sys_instruct:
            kwargs["config"] = {"system_instruction": sys_instruct}
        response = await self.gemini_model.aio.models.generate_content(**kwargs)
        return response.text

    async def _call_google_pro(self, content: str, sys_instruct: str = ""):
        kwargs = {
            "model": "gemini-pro-latest",
            "contents": content
        }
        if sys_instruct:
            kwargs["config"] = {"system_instruction": sys_instruct}
        response = await self.gemini_model.aio.models.generate_content(**kwargs)
        return response.text
        
    async def _call_qwen_flash(self, content: str, sys_instruct: str = ""):
        messages = []
        if sys_instruct:
            messages.append({"role": "system", "content": sys_instruct})
        messages.append({"role": "user", "content": content})
        response = await self.qwen_model.chat.completions.create(
            model="qwen3.6-plus",
            messages=messages,
            stream=False,
        )
        return(response.choices[0].message.content)

    async def _call_qwen_plus(self, content: str, sys_instruct: str = ""):
        messages = []
        if sys_instruct:
            messages.append({"role": "system", "content": sys_instruct})
        messages.append({"role": "user", "content": content})
        response = await self.qwen_model.chat.completions.create(
            model="qwen3.7-plus",
            messages=messages,
            stream=False,
        )
        return(response.choices[0].message.content)
        
    async def _call_github_1(self, content: str, sys_instruct: str = ""):
        messages = []
        if sys_instruct:
            messages.append({"role": "system", "content": sys_instruct})
        else:
            messages.append({"role": "system", "content": "You are a helpful assistant."})
        messages.append({"role": "user", "content": content})
        response = await self.github_model.chat.completions.create(
            messages=messages,
            temperature=1,
            top_p=1,
            model="openai/gpt-4o-mini"
        )
        return response.choices[0].message.content

    async def _call_qwenvl(self, content, sys_instruct: str = ""):
        messages=[]
        mercy = '#Task：根据所给出的题目的部分截图，按照格式要求仅输出识别内容。#OutputFormat(JSON)：{"OCR_Result":""} #InputData：'
        messages.append({"role": "user", "content": mercy})
        messages.append({"role": "user", "content": content})
        response = await self.qwen_model.chat.completions.create(
        model="qwen3.6-flash",
        messages = messages,
        stream=False,
        response_format={"type": "json_object"}
        )
        return(response.choices[0].message.content)
