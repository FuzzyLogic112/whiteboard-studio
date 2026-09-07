"""用智谱 GLM 给分镜挑关键词和简笔画。

一次请求把整篇文稿的所有分镜都标注完：模型能看到上下文，才知道哪个词是全篇
的主题、哪一镜该换张图。逐句调用既慢又拿不到这个信息。

比本地启发式强在两点：
1. 关键词是「读懂这句话之后」挑的，不是按词性和词频打分挑的；
2. 简笔画从概念表里**按语义**选，不依赖触发词命中——本地版命不中就只能画
   兜底涂鸦，而概念表再长也不可能穷举所有说法。

接口是 OpenAI 兼容的 `/chat/completions`，配 `response_format: json_object`。

鉴权有两种方式：配 `WBS_GLM_API_KEY`，或者干脆不配——在 Claude Code 的云环境
里，把 key 存成环境的 API credential 之后，代理会在请求离开沙箱后自动补上
Authorization 头，key 不进本进程。所以这里的 api_key 是可选的。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List, Sequence

from ..sketch import known_concepts
from .base import AnnotationError, SceneAnnotation

logger = logging.getLogger(__name__)

MAX_KEYWORD_LEN = 4
MAX_IMAGE_PROMPT_LEN = 40

_COMMON = """\
你是白板动画的分镜助手。用户会给你一篇中文口播稿切分好的分镜列表，
你要为每一镜挑一个写在白板上的关键词。

关键词要求：
- 2 到 4 个汉字，必须是一个完整的词，不能是从词中间截断的碎片
- 优先选这一镜真正在讲的那个具体事物或动作，不要选「需要」「进行」这类虚词
- 相邻两镜不要用同一个词
"""

# 内置简笔画模式：从固定的概念表里挑一张图
SYSTEM_PROMPT_CONCEPT = _COMMON + """
concept 要求：
- **必须逐字复制用户消息里 concepts 列表中的某一项**，一个字都不能改
- 不许自己发明新名字
- 按语义选最贴切的；实在没有贴切的就填 doodle
- 相邻两镜尽量不要用同一个，但「选得对」比「不重复」更重要

只输出 JSON，格式为：
{"scenes": [{"index": 0, "keyword": "关键词", "concept": "concept名"}]}
每一镜都要有一条，index 从 0 开始，不要遗漏也不要多给。"""

# AI 生图模式：写一个具体可画的物体，交给生图模型
SYSTEM_PROMPT_VISUAL = _COMMON + """
image_prompt 要求（这一条最容易做错，请仔细看）：
- 写**一件具体的、单独的静物**，用来隐喻这一镜的意思
- 10 个字以内，只写画什么，不要写画风（画风由程序统一加）
- **绝对不能是抽象词**。「天赋」「修改」「结构」这类词没有形状，
  必须翻译成实物：
    天赋 → 一颗星星
    修改 → 一支铅笔
    结构 → 一座积木塔
    手艺 → 一把锤子
    成本 → 一个天平
    时间 → 一个沙漏
- **只能是一个物体，不能是场景、动作或人物**。写成「一双手在雕刻木头」
  「一个人坐在桌前」这类带人物和动作的句子，生图模型会当成照片来画，
  出来是实拍照片而不是线稿，后续完全没法用。物体越单一越好。

只输出 JSON，格式为：
{"scenes": [{"index": 0, "keyword": "关键词", "image_prompt": "一颗星星"}]}
每一镜都要有一条，index 从 0 开始，不要遗漏也不要多给。"""


class GlmAnnotator:
    name = "glm"

    def __init__(self, endpoint: str, model: str, api_key: str = "", timeout: int = 60,
                 visual: bool = False):
        """visual=True 时问视觉隐喻，否则问内置概念。

        不一次问两个，是因为小模型同时应付「从 33 项枚举里逐字复制」和
        「自由写一个物体」会串味——实测 glm-4-flash 会照着 image_prompt 编出
        hammer / tower / pencil 这种不存在的 concept，四镜里错三镜。
        每次只问真正会被用到的那一个，准确率就回来了。
        """
        if not endpoint:
            raise AnnotationError("glm 标注器需要配置 WBS_GLM_ENDPOINT")
        if not model:
            raise AnnotationError("glm 标注器需要配置 WBS_GLM_MODEL")
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.visual = visual

    def annotate(self, sentences: Sequence[str]) -> List[SceneAnnotation]:
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system",
                 "content": SYSTEM_PROMPT_VISUAL if self.visual else SYSTEM_PROMPT_CONCEPT},
                {"role": "user", "content": self._build_user_message(sentences)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }, ensure_ascii=False).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        # 云环境里 key 由代理注入，这里可以不带
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = urllib.request.Request(
            f"{self.endpoint}/chat/completions", data=payload, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:400].decode("utf-8", "replace")
            raise AnnotationError(f"GLM 返回 {exc.code}：{detail}") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise AnnotationError(f"连接 GLM 失败（{self.endpoint}）：{exc}") from exc
        except json.JSONDecodeError as exc:
            raise AnnotationError(f"GLM 响应不是合法 JSON：{exc}") from exc

        return self._parse(body, len(sentences))

    def _build_user_message(self, sentences: Sequence[str]) -> str:
        scenes = [{"index": i, "text": t} for i, t in enumerate(sentences)]
        # 视觉隐喻模式下不发概念表：模型看不到那张表，就不会照着它编名字
        payload = {"scenes": scenes}
        if not self.visual:
            payload = {"concepts": known_concepts(), **payload}
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _parse(body: Dict[str, Any], expected: int) -> List[SceneAnnotation]:
        """解析并逐项校验。

        模型输出是不可信的：可能少给几镜、发明不存在的 concept、把关键词写成
        一整句话。这里只做校验和归一化，拿不准的位置留空，由调用方用本地结果补齐
        ——直接整批失败太脆了，模型八成是对的。
        """
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AnnotationError(f"GLM 响应结构异常：{body}") from exc

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AnnotationError(f"GLM 输出不是合法 JSON：{content[:200]}") from exc

        rows = parsed.get("scenes") if isinstance(parsed, dict) else None
        if not isinstance(rows, list):
            raise AnnotationError(f"GLM 输出缺少 scenes 数组：{content[:200]}")

        allowed = set(known_concepts())
        result: List[SceneAnnotation] = [SceneAnnotation("", "") for _ in range(expected)]
        for row in rows:
            if not isinstance(row, dict):
                continue
            index = row.get("index")
            if not isinstance(index, int) or not 0 <= index < expected:
                continue

            keyword = str(row.get("keyword") or "").strip()[:MAX_KEYWORD_LEN]
            concept = str(row.get("concept") or "").strip()
            result[index] = SceneAnnotation(
                keyword=keyword,
                # 编造出来的 concept 一律丢弃，留空交给本地结果补
                concept=concept if concept in allowed else "",
                image_prompt=str(row.get("image_prompt") or "").strip()[:MAX_IMAGE_PROMPT_LEN],
            )
        return result
