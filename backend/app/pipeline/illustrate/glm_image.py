"""用智谱的生图模型画配图，再矢量化成可绘制的笔迹。

位图本身没法做「一笔一笔画出来」的动画，所以生成之后必须过一遍
`vectorize`：取中心线骨架，得到笔尖真正要走的轨迹。

提示词是调出来的，不是随便写的。实测教训：
- 不写死「禁止阴影/立体感」，模型会给简笔画加投影，双线轮廓细化后会碎成
  一段段弧，笔顺就乱了；
- 不写死「主体居中、四周留白」，主体容易顶边，归一化之后构图很挤。

生成一张图要几秒到几十秒，而且按张收费，所以结果按提示词哈希缓存到工作目录。
同一个关键词重渲不会再花钱。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List

from ..vectorize import vectorize_report
from .base import IllustrationError

logger = logging.getLogger(__name__)


class _TransientError(IllustrationError):
    """可以退避重试的故障：限流、网关错误、超时。"""

# 逐镜连续生图很容易撞账号级的速率限制（智谱返回 429 / code 1302），
# 上游偶尔也会 502。这些都是瞬时故障，退避重试就能过去——不重试的话
# 一篇二十镜的稿子基本上必然有几镜掉进兜底。
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
BACKOFF_SECONDS = (4, 12, 30)

# 质量闸门。生图模型经常无视「线稿」约束，直接输出照片、实心色块或带纹理的
# 3D 渲染——这些东西中心线法表示不了，硬转出来是一团乱线，还不如退回内置
# 简笔画。阈值是照着实测数据定的：
#   干净线稿   墨迹 0.01~0.05，骨架/墨迹 0.30~0.45
#   实心五角星 墨迹 0.048，骨架/墨迹 0.08
#   实拍照片   墨迹 0.28~0.39，骨架/墨迹 0.04~0.15
MAX_INK_RATIO = 0.15
MIN_SKELETON_RATIO = 0.20

# 风格约束放在最前面：写在句尾时模型经常只顾着实现主体描述，
# 把「线稿」当成可选项，直接输出照片或 3D 渲染。
PROMPT_TEMPLATE = (
    "黑白线稿简笔画，不是照片，不是3D渲染，不是彩色插画。"
    "画面内容：{subject}。"
    "纯白背景，只用一种粗细均匀的纯黑细线勾勒轮廓，线条闭合干净，"
    "主体单一且居中，四周留出大片空白，"
    "禁止颜色、阴影、投影、立体感、渐变、灰度、填充色块和纹理，"
    "画面里不许出现任何文字、汉字、字母或数字。"
)


class GlmImageIllustrator:
    name = "glm_image"

    def __init__(self, endpoint: str, model: str, size: str, cache_dir: Path,
                 api_key: str = "", watermark: bool = True, timeout: int = 180,
                 backoff: tuple = BACKOFF_SECONDS,
                 max_ink_ratio: float = MAX_INK_RATIO,
                 min_skeleton_ratio: float = MIN_SKELETON_RATIO):
        if not endpoint:
            raise IllustrationError("glm_image 需要配置 WBS_IMAGE_ENDPOINT")
        if not model:
            raise IllustrationError("glm_image 需要配置 WBS_IMAGE_MODEL")
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.size = size
        self.cache_dir = cache_dir
        self.api_key = api_key
        self.watermark = watermark
        self.timeout = timeout
        self.backoff = backoff
        self.max_ink_ratio = max_ink_ratio
        self.min_skeleton_ratio = min_skeleton_ratio

    # -- 缓存 ---------------------------------------------------------------

    def _cache_key(self, prompt: str) -> str:
        seed = f"{self.model}|{self.size}|{self.watermark}|{prompt}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

    def _cached(self, key: str) -> List[str] | None:
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))["paths"]
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def _store(self, key: str, prompt: str, paths: List[str]) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / f"{key}.json").write_text(
            json.dumps({"prompt": prompt, "paths": paths}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # -- 生成 ---------------------------------------------------------------

    def paths_for(self, keyword: str, sentence: str, concept: str,
                  image_prompt: str = "") -> List[str]:
        # 抽象关键词直接丢给生图模型是画不出来的——「天赋」会变成手写单词、
        # 「修改」会变成人脸。有视觉隐喻就用隐喻，没有才退回关键词。
        prompt = PROMPT_TEMPLATE.format(subject=image_prompt or keyword)
        key = self._cache_key(prompt)

        cached = self._cached(key)
        if cached is not None:
            logger.info("配图命中缓存：%s", keyword)
            return cached

        image_path = self.cache_dir / f"{key}.png"
        self._download(self._generate(prompt), image_path)

        # 没关水印时切掉底部：显式水印固定在右下角，不切会被当成笔迹描出来
        report = vectorize_report(image_path, crop_bottom=0.10 if self.watermark else 0.0)
        self._reject_unusable(keyword, report)

        self._store(key, prompt, report.paths)
        return report.paths

    def _reject_unusable(self, keyword: str, report) -> None:
        """生成结果不适合走中心线时直接判失败，交给上层退回内置简笔画。

        硬把照片或实心色块转成笔迹，出来是一团认不出的乱线——那比画一个规规矩矩
        的内置图形差得多。
        """
        if report.ink_ratio == 0:
            raise IllustrationError(f"「{keyword}」的生成结果是一张空白图")
        # 先报具体原因再报「没笔迹」：照片和实心块细化后本来就可能一笔不剩，
        # 那时候说「没有任何笔迹」是对的但没用，说清楚是照片才好排查
        if report.ink_ratio > self.max_ink_ratio:
            raise IllustrationError(
                f"「{keyword}」的生成结果墨迹占比 {report.ink_ratio:.2f}，"
                f"超过 {self.max_ink_ratio}，多半是照片或大面积填充，不是线稿")
        if report.skeleton_ratio < self.min_skeleton_ratio:
            raise IllustrationError(
                f"「{keyword}」的生成结果骨架/墨迹比 {report.skeleton_ratio:.2f}，"
                f"低于 {self.min_skeleton_ratio}，是实心色块——中心线法只会把它"
                "削成一条脊线")
        if not report.paths:
            raise IllustrationError(f"「{keyword}」的生成结果矢量化后没有任何笔迹")

    def _generate(self, prompt: str) -> str:
        """请求生成，遇到瞬时故障退避重试。"""
        last_error: IllustrationError | None = None
        for attempt in range(len(self.backoff) + 1):
            try:
                return self._request_once(prompt)
            except _TransientError as exc:
                last_error = IllustrationError(str(exc))
                if attempt == len(self.backoff):
                    break
                delay = self.backoff[attempt]
                logger.warning("%s；%d 秒后重试（第 %d/%d 次）",
                               exc, delay, attempt + 1, len(self.backoff))
                time.sleep(delay)
        assert last_error is not None
        raise last_error

    def _request_once(self, prompt: str) -> str:
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "size": self.size,
            "watermark_enabled": self.watermark,
        }, ensure_ascii=False).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = urllib.request.Request(
            f"{self.endpoint}/images/generations", data=payload,
            headers=headers, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:400].decode("utf-8", "replace")
            message = f"生图接口返回 {exc.code}：{detail}"
            if exc.code in RETRYABLE_STATUS:
                raise _TransientError(message) from exc
            raise IllustrationError(message) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            # 超时和连接中断也当瞬时故障：hd 出图慢，偶尔会卡在网关上
            raise _TransientError(f"连接生图接口失败（{self.endpoint}）：{exc}") from exc
        except json.JSONDecodeError as exc:
            raise IllustrationError(f"生图接口响应不是合法 JSON：{exc}") from exc

        try:
            return body["data"][0]["url"]
        except (KeyError, IndexError, TypeError) as exc:
            raise IllustrationError(f"生图接口响应里没有图片地址：{body}") from exc

    def _download(self, url: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                data = response.read()
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            # 图片放在对象存储上，和 API 不是同一个域名——这里失败多半是
            # 那个域名没被网络策略放行，报错要说清楚，不然很难查
            raise IllustrationError(
                f"下载生成的图片失败（{url.split('?')[0]}）：{exc}。"
                "图片托管在与 API 不同的域名上，请确认该域名也在网络白名单里。"
            ) from exc
        if not data:
            raise IllustrationError("下载到的图片是空的")
        destination.write_bytes(data)
