from __future__ import annotations

import json
from pathlib import Path


class JobFolder:
    def __init__(self, root: Path):
        self.root = Path(root)

    @classmethod
    def create(cls, jobs_dir: Path, date: str, slug: str) -> "JobFolder":
        root = Path(jobs_dir) / f"{date}-{slug}"
        jf = cls(root)
        jf.audio_dir.mkdir(parents=True, exist_ok=True)
        jf.video_dir.mkdir(parents=True, exist_ok=True)
        return jf

    @property
    def job_id(self) -> str:
        return self.root.name

    @property
    def story_json(self) -> Path:
        return self.root / "story.json"

    @property
    def compliance_json(self) -> Path:
        return self.root / "compliance.json"

    @property
    def audio_dir(self) -> Path:
        return self.root / "audio"

    @property
    def video_dir(self) -> Path:
        return self.root / "video"

    def script_path(self, lang: str) -> Path:
        return self.root / f"script_{lang}.md"

    def metadata_path(self, lang: str) -> Path:
        return self.root / f"metadata_{lang}.json"

    def write_json(self, path: Path, obj) -> None:
        path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

    def read_json(self, path: Path):
        return json.loads(path.read_text(encoding="utf-8"))
