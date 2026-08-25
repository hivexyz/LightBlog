import threading
import time
from collections import defaultdict
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Post
from app.config import settings


class ViewCounter:
    """浏览量内存缓冲，定时批量写入数据库，避免 SQLite 写锁瓶颈"""

    def __init__(self):
        self._counts: dict[int, int] = defaultdict(int)
        self._lock = threading.Lock()
        self._last_flush = time.time()
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def increment(self, post_id: int):
        """浏览量 +1，达到阈值时触发刷盘（不在持锁时执行 DB 写入）"""
        should_flush = False
        with self._lock:
            self._counts[post_id] += 1
            total = sum(self._counts.values())
            if total >= settings.VIEW_FLUSH_THRESHOLD:
                should_flush = True
        if should_flush:
            self.flush()

    def flush(self):
        """将缓冲区的浏览量批量写入数据库"""
        with self._lock:
            if not self._counts:
                return
            counts = dict(self._counts)
            self._counts.clear()

        db: Session = SessionLocal()
        try:
            for post_id, count in counts.items():
                db.query(Post).filter(Post.id == post_id).update(
                    {Post.views: Post.views + count}
                )
            db.commit()
        except Exception:
            db.rollback()
            # 写失败时把计数放回缓冲区
            with self._lock:
                for post_id, count in counts.items():
                    self._counts[post_id] += count
        finally:
            db.close()

    def _flush_loop(self):
        """定时刷盘，避免计数长时间停留在内存中"""
        while True:
            time.sleep(settings.VIEW_FLUSH_INTERVAL)
            self.flush()


view_counter = ViewCounter()
