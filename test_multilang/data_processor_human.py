"""
真实人类编写的数据处理器 — Python
特点：dataclass值对象、类型标注、生成器、上下文管理器、结构化日志、单一职责
这是一个有经验的 Python 工程师写的代码
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Iterator, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

os.environ.setdefault("DB_CONNECTION", "postgresql://localhost:5432/data")


@dataclass
class DataRecord:
    id: str
    payload: dict
    processed: bool = False


class DataValidator:
    REQUIRED_FIELDS = {"id", "timestamp", "value"}
    
    @staticmethod
    def validate(record: dict) -> bool:
        return DataValidator.REQUIRED_FIELDS.issubset(record.keys())


class DataTransformer:
    @staticmethod
    def normalize(record: dict) -> dict:
        return {k: v for k, v in record.items() if not k.startswith("_")}


class DataProcessor:
    """数据处理器 — 编排验证、转换、持久化（CC ≈ 4）"""
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def process_batch(self, records: list[dict]) -> Iterator[DataRecord]:
        valid_count = 0
        for record in records:
            if not DataValidator.validate(record):
                logger.warning("Skipping invalid record: %s", record.get("id", "unknown"))
                continue
            
            normalized = DataTransformer.normalize(record)
            data_record = DataRecord(id=normalized["id"], payload=normalized)
            
            self._persist(data_record)
            valid_count += 1
            yield data_record
        
        logger.info("Processed %d/%d records successfully", valid_count, len(records))
    
    def _persist(self, record: DataRecord) -> None:
        output_file = self.output_dir / f"{record.id}.json"
        with open(output_file, "w") as f:
            json.dump(record.payload, f, indent=2, default=str)
