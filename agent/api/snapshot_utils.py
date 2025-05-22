import ujson as json
import boto3
from log import get_logger
from api.config import CONFIG
import os


logger = get_logger(__name__)


class FSMSnapshotSaver:
    def __init__(self):
        self.bucket_name = CONFIG.snapshot_bucket or ""

        if os.path.exists(self.bucket_name) and os.path.isdir(self.bucket_name):
            self.is_local = True
            self.is_available = True
        else:
            self.is_local = False
            self.is_available = self.check_bucket_available()

    def check_bucket_available(self) -> bool:
        if not self.bucket_name:
            logger.info("Saving snapshots disabled. No bucket name provided.")
            return False

        try:
            boto3.resource('s3').meta.client.head_bucket(Bucket=self.bucket_name)
            logger.info("Saving snapshots enabled.")
            return True
        except Exception as e:
            logger.info(f"Saving snapshots disabled {e}")
            return False

    def save_local(self, trace_id: str, key: str, data: object):
        with open(os.path.join(self.bucket_name, f"{trace_id}-{key}.json"), "w") as f:
            json.dump(data, f)

    def save_snapshot(self, trace_id: str, key: str, data: object):
        if not self.is_available:
            return

        match self.is_local:
            case True:
                self.save_local(trace_id, key, data)
            case False:
                self.save_s3(trace_id, key, data)

    def save_s3(self, trace_id: str, key: str, data: object):
        logger.info(f"Storing snapshot for trace: {trace_id}/{key}")
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
