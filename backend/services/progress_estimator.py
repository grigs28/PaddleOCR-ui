"""基于历史处理数据估算进度"""

import logging
from sqlalchemy import select, func

from backend.database import async_session
from backend.models.task import Task

logger = logging.getLogger(__name__)

# 至少需要多少条历史记录才启用估算
MIN_HISTORY = 3


class ProgressEstimator:
    """根据已完成任务的平均速度，估算当前任务进度"""

    def __init__(self):
        self._avg_speed: float | None = None  # bytes/second，缓存

    async def _load_avg_speed(self) -> float | None:
        """从已完成任务计算平均处理速度 (bytes/sec)"""
        async with async_session() as s:
            result = await s.execute(
                select(
                    func.avg(Task.input_file_size),
                    func.avg(Task.processing_time),
                    func.count(Task.id),
                ).where(
                    Task.status == "completed",
                    Task.processing_time > 0,
                    Task.input_file_size > 0,
                )
            )
            avg_size, avg_time, count = result.one()

        if count < MIN_HISTORY or not avg_time or not avg_size:
            return None
        return float(avg_size) / float(avg_time)

    async def estimate(self, file_size: int, elapsed: float) -> int:
        """
        估算进度百分比

        Args:
            file_size: 文件大小 (bytes)
            elapsed: 已处理时间 (秒)
        Returns:
            0-95 的进度百分比
        """
        if self._avg_speed is None:
            self._avg_speed = await self._load_avg_speed()

        if self._avg_speed and self._avg_speed > 0:
            estimated_total = file_size / self._avg_speed
            if estimated_total > 0:
                progress = int(elapsed / estimated_total * 100)
            else:
                progress = 50
        else:
            # 无历史数据：粗略估算，图片 ~5秒，PDF ~每MB 20秒
            default_total = max(10, file_size / 1024 / 1024 * 20)
            progress = int(elapsed / default_total * 100)

        return min(max(progress, 0), 95)


# 单例
progress_estimator = ProgressEstimator()
