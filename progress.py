from datetime import datetime
from collections import deque
import logging

logger = logging.getLogger(__name__)


class ProgressTracker:
    def __init__(self):
        self.current_task = None
        self.total_items = 0
        self.processed_items = 0
        self.status = "idle"
        self.logs = deque(maxlen=100)
        self.start_time = None
        self.errors = []

    def start_task(self, task_name, total=0):
        self.current_task = task_name
        self.total_items = total
        self.processed_items = 0
        self.status = "running"
        self.start_time = datetime.utcnow()
        self.errors = []
        log_msg = f"开始任务: {task_name}"
        if total > 0:
            log_msg += f" (共 {total} 项)"
        self.add_log(log_msg)
        logger.info(log_msg)

    def update_progress(self, processed=None, message=None):
        if processed is not None:
            self.processed_items = processed
        if message:
            self.add_log(message)
            logger.info(f"[{self.current_task}] {message}")

    def add_error(self, error_msg):
        self.errors.append(error_msg)
        self.add_log(f"错误: {error_msg}")
        logger.error(f"[{self.current_task}] {error_msg}")

    def complete_task(self):
        duration = (datetime.utcnow() - self.start_time).total_seconds() if self.start_time else 0
        log_msg = f"任务完成: {self.current_task} (耗时 {duration:.1f}秒)"
        if self.errors:
            log_msg += f", {len(self.errors)} 个错误"
        self.add_log(log_msg)
        logger.info(log_msg)
        self.status = "idle"
        self.current_task = None

    def add_log(self, message):
        self.logs.append({
            "time": datetime.utcnow().isoformat(),
            "message": message
        })

    def get_status(self):
        return {
            "status": self.status,
            "current_task": self.current_task,
            "total_items": self.total_items,
            "processed_items": self.processed_items,
            "progress_percent": (self.processed_items / self.total_items * 100) if self.total_items > 0 else 0,
            "errors": len(self.errors),
            "logs": list(self.logs)
        }


progress_tracker = ProgressTracker()
