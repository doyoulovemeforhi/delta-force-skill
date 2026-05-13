import base64
import os
from dataclasses import dataclass
from io import BytesIO
from typing import Optional, Tuple

from PIL import Image


@dataclass
class GUIAgentResult:
    """多模态调用结果：仅返回模型自然语言输出，不使用 function / computer_use。"""

    success: bool
    content: Optional[str] = None
    error: Optional[str] = None
    # 上传前会按比例缩小整图（不裁剪）；若与原始一致则二者相同
    original_image_size: Optional[Tuple[int, int]] = None
    sent_image_size: Optional[Tuple[int, int]] = None


class AliyunGUIAgent:
    """阿里云 GUI-Plus（OpenAI 兼容）：用于游戏截图的识别与理解。"""

    DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    DEFAULT_MODEL = "gui-plus"
    #: 720p 等效：最长边 1280；超过则整图等比例缩小后再上传（不裁剪）
    MAX_LONG_EDGE_FOR_API = 1280

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY")
        self.base_url = base_url or self.DEFAULT_BASE_URL
        self.model = model or self.DEFAULT_MODEL
        self._client = None

    def _client_instance(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    @classmethod
    def _prepare_image_for_api(cls, image: Image.Image) -> Tuple[Image.Image, Tuple[int, int], Tuple[int, int]]:
        """整图等比例缩小最长边至 MAX_LONG_EDGE_FOR_API；已更小则不放大。不裁剪。"""
        rgb = image.convert("RGB")
        w, h = rgb.size
        orig = (w, h)
        limit = cls.MAX_LONG_EDGE_FOR_API
        long_edge = max(w, h)
        if long_edge <= limit:
            return rgb, orig, orig
        scale = limit / float(long_edge)
        nw = max(1, int(round(w * scale)))
        nh = max(1, int(round(h * scale)))
        resized = rgb.resize((nw, nh), Image.Resampling.LANCZOS)
        return resized, orig, (nw, nh)

    @staticmethod
    def _image_to_data_url(image: Image.Image) -> str:
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{encoded}"

    @staticmethod
    def _system_prompt(width: int, height: int) -> str:
        return f"""你是《三角洲行动》界面的视觉分析助手，只做画面识别与理解，不假装能操作鼠标或键盘。

规则：
- 当前提供给你的图像分辨率为 {width}×{height} 像素（可能已由原始截图整图等比例缩小，仅为了传输；画面内容未被裁剪）。
- 坐标原点在左上角，x 向右、y 向下，范围 x∈[0,{width - 1}]、y∈[0,{height - 1}]。
- 客观描述你看到的 UI：所在界面（如大厅、仓库、特勤处、制造详情等）、主要区域、按钮/标签文字、数值、状态提示；不确定的请明确说「不确定」，不要编造。
- 若用户追问具体坐标，仅在确有把握时给出像素坐标（相对于当前这张 {width}×{height} 的图）；否则说明原因。
- 回答使用简体中文，简洁有条理。"""

    def analyze(self, screenshot: Image.Image, instruction: str) -> GUIAgentResult:
        if not self.api_key:
            return GUIAgentResult(False, error="缺少 API Key：请在 config.json 的 gui_agent.api_key 或环境变量 DASHSCOPE_API_KEY / .env 中配置")

        text = (instruction or "").strip()
        if not text:
            return GUIAgentResult(False, error="instruction 为空")

        try:
            sent, orig_wh, sent_wh = self._prepare_image_for_api(screenshot)
            sw, sh = sent_wh
            client = self._client_instance()
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._system_prompt(sw, sh)},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": self._image_to_data_url(sent)}},
                            {"type": "text", "text": text},
                        ],
                    },
                ],
                temperature=0,
                max_tokens=2048,
            )
            message = response.choices[0].message
            content = (message.content or "").strip()
            if not content:
                return GUIAgentResult(
                    False,
                    error="模型返回内容为空",
                    original_image_size=orig_wh,
                    sent_image_size=sent_wh,
                )
            return GUIAgentResult(
                True,
                content=content,
                original_image_size=orig_wh,
                sent_image_size=sent_wh,
            )
        except Exception as exc:
            return GUIAgentResult(False, error=str(exc))
