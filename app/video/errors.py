"""视频接口的错误类型与识别。

ZenMux 有两条调用通道（vertex 兼容 / native），各自只支持一部分模型：
模型在当前通道不可用时返回 404 model_not_supported / invalid_model 等，
识别出来后 service 会自动换另一条通道重试。
"""


class ModelNotSupported(RuntimeError):
    """模型在当前接口通道不可用。"""


def is_model_not_supported(status_code: int, body: str) -> bool:
    markers = ("model_not_supported", "invalid_model", "model_not_found",
               "not supported", "does not support")
    low = (body or "").lower()
    return status_code == 404 or any(m in low for m in markers)
