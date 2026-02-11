import bz2
import os
import xml.etree.ElementTree as ET

from tqdm import tqdm


class ProgressReader:
    def __init__(self, raw, pbar):
        self.raw = raw
        self.pbar = pbar

    def read(self, size=-1):
        data = self.raw.read(size)
        if data:
            self.pbar.update(len(data))
        return data


def iter_pages(dump_filepath: str, max_pages: int = 0):
    total_bytes = os.path.getsize(dump_filepath)
    pbar = tqdm(
        total=total_bytes, unit="B", unit_scale=True, desc="Reading dump"
    )

    count = 0
    with open(dump_filepath, "rb") as raw:
        wrapped = ProgressReader(raw, pbar)
        with bz2.open(wrapped, "rb") as f:
            for _, elem in ET.iterparse(f, events=("end",)):
                if not elem.tag.endswith("page"):
                    continue

                ns = elem.findtext(".//{*}ns")
                title = elem.findtext(".//{*}title") or ""
                text = elem.findtext(".//{*}text") or ""

                yield ns, title, text

                count += 1
                elem.clear()

                if max_pages and count >= max_pages:
                    break

    pbar.close()
