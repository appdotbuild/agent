import os
import json
import boto3
from log import get_logger


logger = get_logger(__name__)


class FSMSnapshotSaver:
    def __init__(self):
        self.bucket_name = os.getenv("SNAPSHOT_BUCKET", "fsm_snapshots")
        self.is_available = self.check_bucket_available()

    def check_bucket_available(self) -> bool:
        try:
            boto3.resource('s3').meta.client.head_bucket(Bucket=self.bucket_name)
            logger.info("Saving snapshots enabled.")
            return True
        except Exception as e:
            logger.info(f"Saving snapshots disabled {e}")
            return False

    def save_snapshot(self, trace_id: str, key: str, data: object):
        if not self.is_available:
            return
        file_key = f"{trace_id}/{key}.json"
        boto3.resource('s3').Bucket(self.bucket_name).put_object(Key=file_key, Body=json.dumps(data))

snapshot_saver = FSMSnapshotSaver()


if __name__ == "__main__":
    data = {"random": "data"}
    snapshot_saver.save_snapshot(
        trace_id="12345678",
        key="fsm_enter",
        data=data
    )
