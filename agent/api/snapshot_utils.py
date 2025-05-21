import os
import json
import boto3


class FSMSnapshotSaver:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FSMSnapshotSaver, cls).__new__(cls)
        return cls._instance

    @property
    def bucket_name(self) -> str:
        return os.getenv("SNAPSHOT_BUCKET", "fsm_snapshots")

    def save_snapshot(self, trace_id: str, key: str, data: object):
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
