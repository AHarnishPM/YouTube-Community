"""Fetch an attributed MIT OCW pilot from public caption tracks; no video download."""
import argparse
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import random
import re
import subprocess
from urllib.parse import urljoin, urlparse
from .evaluation import digest, write_jsonl
from .prepare import windows


class Tracks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.captions = []
        self.videos = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "track" and attrs.get("srclang") == "en":
            self.captions.append(attrs["src"])
        if tag == "iframe":
            match = re.search(r'youtube.com/embed/([\w-]{11})', attrs.get("src", ""))
            if match:
                self.videos.add(match[1])


def seconds(value):
    if not re.fullmatch(r'(?:\d{2,}:)?\d{2}:\d{2}\.\d{3}', value):
        raise ValueError(f"invalid VTT timestamp: {value}")
    parts = value.split(":")
    if float(parts[-1]) >= 60 or int(parts[-2]) >= 60:
        raise ValueError("invalid VTT minute/second field")
    return sum(float(v)*60**i for i,v in enumerate(reversed(parts)))


def parse_vtt(text):
    text = text.lstrip("\ufeff").replace("\r\n", "\n")
    if not text.startswith("WEBVTT"):
        raise ValueError("expected a WEBVTT caption file")
    result = []
    for block in re.split(r'\n\s*\n', text):
        lines = block.splitlines()
        if not lines or lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        index = next((i for i,line in enumerate(lines) if " --> " in line), None)
        if index is None:
            raise ValueError("unrecognized VTT cue")
        start, end = lines[index].split(" --> ")
        content = unescape(re.sub(r'<[^>]*>', '', ' '.join(lines[index+1:])))
        if content.strip():
            result.append({"start":seconds(start), "end":seconds(end.split()[0]), "text":content.strip()})
    if not result:
        raise ValueError("no caption cues")
    return result


def fetch(url):
    if urlparse(url).scheme != "https" or urlparse(url).hostname != "ocw.mit.edu":
        raise ValueError("pilot importer accepts only official HTTPS MIT OCW URLs")
    # System curl uses the host trust store; TLS verification remains enabled.
    return subprocess.run(["curl", "--fail", "--location", "--proto", "=https",
                           "--max-time", "45", "--silent", "--show-error", url],
                          check=True, capture_output=True).stdout


def build(sources, output, per_video=20, seed=4701):
    if per_video < 1:
        raise ValueError("per-video sample size must be positive")
    output.mkdir(parents=True, exist_ok=False)
    all_rows, pilot, manifest = [], [], []
    for entry in sources:
        page = fetch(entry["page"])
        parser = Tracks()
        parser.feed(page.decode())
        if len(parser.videos) != 1 or len(set(parser.captions)) != 1:
            raise ValueError("expected exactly one video and English track")
        video = next(iter(parser.videos))
        track = urljoin(entry["page"], parser.captions[0])
        raw = fetch(track)
        (output / f"{video}.vtt").write_bytes(raw)
        document = {"video_id":video,"category":"lecture","captions":parse_vtt(raw.decode()),
                    "source_url":entry["page"],"caption_source":track,"language":"en","synthetic":False}
        rows = windows(document)
        for row in rows:
            row.update(subject=entry["subject"], title=entry["title"],
                       license="CC BY-NC-SA 4.0", attribution="MIT OpenCourseWare; "+entry["speaker"],
                       dataset_role="annotation_pilot", label=None)
        # Uniform sample across each lecture; no model-score selection or gold labels.
        indices = sorted(random.Random(f"{seed}:{video}").sample(range(len(rows)), min(per_video,len(rows))))
        pilot.extend(rows[i] for i in indices)
        all_rows.extend(rows)
        manifest.append({**entry,"video_id":video,"youtube_url":f"https://www.youtube.com/watch?v={video}",
                         "caption_url":track,"caption_sha256":digest(raw),"page_sha256":digest(page),
                         "cues":len(document["captions"]),"windows":len(rows),"sampled":len(indices),
                         "license_url":"https://creativecommons.org/licenses/by-nc-sa/4.0/"})
    write_jsonl(output/"all-windows.jsonl",all_rows)
    write_jsonl(output/"pilot-unlabeled.jsonl",pilot)
    metadata={"created_at":datetime.now(timezone.utc).isoformat(),"seed":seed,"sources":manifest,
              "windows":len(all_rows),"pilot_windows":len(pilot),
              "limitation":"Lecture-only annotation pilot. No held-out split or human labels. Keep all pilot videos out of future confirmatory test data."}
    (output/"manifest.json").write_text(json.dumps(metadata,indent=2)+"\n")
    return metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--per-video",type=int,default=20)
    args=parser.parse_args()
    try:
        print(json.dumps(build(json.loads(args.sources.read_text()),args.output,args.per_video),indent=2))
    except (ValueError,KeyError,TypeError,OSError,subprocess.CalledProcessError) as exc:
        parser.exit(2,f"error: {exc}\n")


if __name__ == "__main__":
    main()
